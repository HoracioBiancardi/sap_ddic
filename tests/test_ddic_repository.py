"""Unit tests for backend.ddic_repository.DDICRepository.

Exercises `count_tables` and the column-search tier of `search` (tier 4:
matches against DD03L.FIELDNAME or field business text via DD04T.DDTEXT)
against a fake connector, since these never touch the real HANA replica.
Fixtures use realistic SAP tables/fields (MARA/MATNR, MAKT/MAKTX).
"""

from backend.ddic_repository import DDICRepository


class _FakeConnector:
    """Routes canned rows to `run_query` based on which DDIC table a query touches.

    The real DatasphereConnector.run_query executes arbitrary parameterized
    SQL against HANA; this stand-in classifies each call into one of
    `search`'s four tiers (or `count_tables`) by a marker unique to that
    tier's SQL, so a test can assert both the returned rows and which tiers
    were actually queried (e.g. that tier 4 is skipped once `limit` is
    already filled by an earlier tier).
    """

    def __init__(self, rows_by_tier: dict[str, list[dict]] | None = None) -> None:
        self.rows_by_tier = rows_by_tier or {}
        self.calls: list[str] = []

    def _classify(self, sql: str) -> str:
        if "TADIR" in sql:
            return "tcode_header"
        if "TSTC" in sql and "LIKE :prefix" in sql:
            return "tcode_prefix"
        if "TSTCT" in sql and "UPPER(T.TTEXT)" in sql:
            return "tcode_description"
        if "TSTCT" in sql:
            return "tcode_text"
        if "DD03L" in sql:
            return "column"
        if "APPLCLASS" in sql:
            return "domain"
        if "LIKE :prefix" in sql:
            return "prefix"
        if "UPPER(DDTEXT)" in sql:
            return "description"
        if "COUNT(*)" in sql:
            return "count"
        raise AssertionError(f"Unrecognized query in test fake: {sql}")

    def run_query(self, sql: str, params: dict | None = None) -> list[dict]:
        tier = self._classify(sql)
        self.calls.append(tier)
        return self.rows_by_tier.get(tier, [])


def _repository(rows_by_tier: dict[str, list[dict]] | None = None) -> tuple[DDICRepository, _FakeConnector]:
    connector = _FakeConnector(rows_by_tier)
    repository = DDICRepository(connector, schema="DDIC", language="P")
    return repository, connector


class TestCountTables:
    """Tests for DDICRepository.count_tables."""

    def test_returns_total_from_count_row(self) -> None:
        """The COUNT(*) row's value round-trips through count_tables()."""
        repository, _ = _repository({"count": [{"total": 842}]})
        assert repository.count_tables() == 842


class TestSearchColumnTier:
    """Tests for the 4th (column-match) tier of DDICRepository.search."""

    def test_matches_only_field_name(self) -> None:
        """A term matching DD03L.FIELDNAME surfaces its owning table with matched_field set."""
        repository, connector = _repository(
            {"column": [{"fieldname": "MATNR", "tabname": "MARA", "ddtext": "Material Master"}]}
        )
        results = repository.search("MATNR")
        assert results == [{"table_name": "MARA", "description": "Material Master", "matched_field": "MATNR"}]
        assert connector.calls == ["prefix", "description", "column"]

    def test_matches_only_field_business_text(self) -> None:
        """A term matching only DD04T.DDTEXT (field text) surfaces the owning table via ROLLNAME."""
        repository, _ = _repository(
            {"column": [{"fieldname": "MAKTX", "tabname": "MAKT", "ddtext": "Textos breves de material"}]}
        )
        results = repository.search("MATERIAL")
        assert results == [
            {"table_name": "MAKT", "description": "Textos breves de material", "matched_field": "MAKTX"}
        ]

    def test_column_tier_skipped_once_limit_filled(self) -> None:
        """Tier 4 is not queried when tier 1 (name prefix) already fills the limit."""
        repository, connector = _repository(
            {"prefix": [{"tabname": "MARA", "ddtext": "Material Master"}]}
        )
        results = repository.search("MA", limit=1)
        assert results == [{"table_name": "MARA", "description": "Material Master"}]
        assert connector.calls == ["prefix"]
        assert "column" not in connector.calls

    def test_dedups_multiple_matching_fields_to_one_result_per_table(self) -> None:
        """A table with several matching fields yields exactly one result row for it."""
        repository, _ = _repository(
            {
                "column": [
                    {"fieldname": "MATNR", "tabname": "MARA", "ddtext": "Material Master"},
                    {"fieldname": "MTART", "tabname": "MARA", "ddtext": "Material Master"},
                ]
            }
        )
        results = repository.search("MAT")
        assert len(results) == 1
        assert results[0]["table_name"] == "MARA"
        assert results[0]["matched_field"] == "MATNR"

    def test_no_match_across_any_tier_returns_empty_list(self) -> None:
        """A term matching nothing in any of the 4 tiers returns []."""
        repository, _ = _repository()
        assert repository.search("ZZZNOMATCH") == []


class TestFetchTcodeHeader:
    """Tests for DDICRepository.fetch_tcode_header."""

    def test_returns_none_when_tcode_not_found(self) -> None:
        """A tcode absent from TSTC yields None."""
        repository, _ = _repository({"tcode_header": []})
        assert repository.fetch_tcode_header("ZZZZ") is None

    def test_returns_program_and_package_when_tadir_matches(self) -> None:
        """A tcode with a matching TADIR row surfaces its package and creation date."""
        repository, _ = _repository(
            {
                "tcode_header": [
                    {"pgmna": "RM06BA00", "dypno": "0100", "devclass": "MEXX", "created_on": "20200115"}
                ]
            }
        )
        assert repository.fetch_tcode_header("ME5A") == {
            "pgmna": "RM06BA00",
            "dypno": "0100",
            "devclass": "MEXX",
            "created_on": "20200115",
        }

    def test_blanks_package_and_date_when_tadir_row_missing(self) -> None:
        """A LEFT JOIN miss on TADIR (NULL columns) defaults to blank strings, not None."""
        repository, _ = _repository(
            {"tcode_header": [{"pgmna": "SAPMZ001", "dypno": "1000", "devclass": None, "created_on": None}]}
        )
        assert repository.fetch_tcode_header("Z001") == {
            "pgmna": "SAPMZ001",
            "dypno": "1000",
            "devclass": "",
            "created_on": "",
        }


class TestFetchTcodeText:
    """Tests for DDICRepository.fetch_tcode_text."""

    def test_returns_text_when_found(self) -> None:
        """A tcode with a TSTCT row in the configured language returns its text."""
        repository, _ = _repository({"tcode_text": [{"ttext": "Lista de requisições de compra"}]})
        assert repository.fetch_tcode_text("ME5A") == "Lista de requisições de compra"

    def test_falls_back_to_tcode_when_no_text(self) -> None:
        """A tcode with no TSTCT text in the configured language falls back to itself."""
        repository, _ = _repository({"tcode_text": []})
        assert repository.fetch_tcode_text("ME5A") == "ME5A"


class TestSearchTcodes:
    """Tests for DDICRepository.search_tcodes."""

    def test_prefix_tier_matches_tcode(self) -> None:
        """A term matching TSTC.TCODE by prefix surfaces it via the first tier."""
        repository, connector = _repository(
            {"tcode_prefix": [{"tcode": "ME5A", "ttext": "Lista de requisições de compra"}]}
        )
        results = repository.search_tcodes("ME5")
        assert results == [{"tcode": "ME5A", "description": "Lista de requisições de compra"}]
        # Falls through to the description tier too, since the prefix tier
        # alone didn't fill the (default 15) limit — mirrors search()'s own
        # cascading behavior.
        assert connector.calls == ["tcode_prefix", "tcode_description"]

    def test_description_tier_used_as_fallback(self) -> None:
        """A term matching only TSTCT.TTEXT surfaces it once the prefix tier is exhausted."""
        repository, connector = _repository(
            {"tcode_description": [{"tcode": "ME5A", "ttext": "Lista de requisições de compra"}]}
        )
        results = repository.search_tcodes("REQUISI")
        assert results == [{"tcode": "ME5A", "description": "Lista de requisições de compra"}]
        assert connector.calls == ["tcode_prefix", "tcode_description"]

    def test_description_tier_skipped_once_limit_filled(self) -> None:
        """The fallback tier is not queried once the prefix tier already fills the limit."""
        repository, connector = _repository({"tcode_prefix": [{"tcode": "ME5A", "ttext": "..."}]})
        repository.search_tcodes("ME5", limit=1)
        assert connector.calls == ["tcode_prefix"]

    def test_no_match_returns_empty_list(self) -> None:
        """A term matching neither tier returns []."""
        repository, _ = _repository()
        assert repository.search_tcodes("ZZZNOMATCH") == []
