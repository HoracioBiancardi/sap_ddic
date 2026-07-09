"""Unit tests for backend.mart_generator.

Fixtures are the real cached contracts in cache/*.json. BSEG (Transactional)
has both LFA1 and MARA as real DD08L "Alta"-importance foreign keys (all
three cached), giving a realistic root + two auto-detected joins scenario.

BSEG also references KNA1 twice in real data (KUNNR sold-to, VPTNR payer),
and MARA references itself five times (BMATN/GENNR/PMATA/RMATP/SATNR, all
generic-material variants) — both exercise the node_id-vs-table_name split:
the same table_name backing two independent, separately-aliased nodes.
"""

import json
from pathlib import Path

import pytest

from backend.mart_generator import generate_mart_artifacts, suggest_mart_type
from backend.schemas import Column, JoinFieldPair, JoinFilter, MartJoinSpec, TableContract, TechnicalStats

_CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"


def _load_contract(table_name: str) -> TableContract:
    data = json.loads((_CACHE_DIR / f"{table_name}.json").read_text())
    return TableContract.model_validate(data["payload"])


def _column(name: str, data_type: str = "CHAR", length: int = 10, decimals: int = 0, **overrides) -> Column:
    defaults = dict(
        column_name=name,
        is_primary_key=False,
        data_type=data_type,
        length=length,
        decimals=decimals,
        business_description="",
        domain_name="",
        has_fixed_values=False,
    )
    defaults.update(overrides)
    return Column(**defaults)


def _synthetic_contract(table_name: str, table_type: str, columns: list[Column]) -> TableContract:
    return TableContract(
        table_name=table_name,
        business_description=f"Tabela sintética {table_name}",
        technical_class="TRANSP",
        table_type=table_type,
        hierarchy_type="Standalone / Mestre",
        associated_text_table=None,
        parent_tables=[],
        columns=columns,
        technical_stats=TechnicalStats(
            field_count=len(columns),
            record_length_bytes=sum(c.length for c in columns),
            key_length_bytes=0,
            data_class="APPL1",
            size_category="4",
            incremental_candidate_fields=[],
            supports_incremental_load=False,
        ),
    )


def _mandt_join(left_node: str, right_node: str, left_field: str, right_field: str, **overrides) -> MartJoinSpec:
    return MartJoinSpec(
        left_node=left_node,
        right_node=right_node,
        fields=[
            JoinFieldPair(left_field="MANDT", right_field="MANDT"),
            JoinFieldPair(left_field=left_field, right_field=right_field),
        ],
        auto_detected=True,
        **overrides,
    )


class TestSuggestMartType:
    """Tests for suggest_mart_type."""

    def test_transactional_root_is_fct(self) -> None:
        assert suggest_mart_type(_load_contract("BSEG")) == "FCT"

    def test_master_data_root_is_dim(self) -> None:
        assert suggest_mart_type(_load_contract("MARA")) == "DIM"


class TestGenerateMartArtifacts:
    """Tests for generate_mart_artifacts against real BSEG/LFA1/MARA/KNA1
    fixtures plus synthetic graphs for shapes the real fixtures don't cover."""

    def test_auto_suggests_fct_for_transactional_root(self) -> None:
        artifacts = generate_mart_artifacts(
            {"BSEG": _load_contract("BSEG"), "LFA1": _load_contract("LFA1")},
            [_mandt_join("BSEG", "LFA1", "LIFNR", "LIFNR")],
            "BSEG",
        )
        assert artifacts.mart_type == "FCT"
        assert artifacts.model_name == "fct_bseg"

    def test_mart_type_override_is_honored(self) -> None:
        artifacts = generate_mart_artifacts({"BSEG": _load_contract("BSEG")}, [], "BSEG", mart_type="DIM")
        assert artifacts.mart_type == "DIM"
        assert artifacts.model_name == "dim_bseg"

    def test_invalid_mart_type_raises(self) -> None:
        with pytest.raises(ValueError):
            generate_mart_artifacts({"BSEG": _load_contract("BSEG")}, [], "BSEG", mart_type="WRONG")

    def test_root_node_not_in_nodes_raises(self) -> None:
        with pytest.raises(ValueError):
            generate_mart_artifacts({"BSEG": _load_contract("BSEG")}, [], "MARA")

    def test_join_referencing_node_outside_graph_raises(self) -> None:
        with pytest.raises(ValueError):
            generate_mart_artifacts(
                {"BSEG": _load_contract("BSEG")},
                [_mandt_join("BSEG", "LFA1", "LIFNR", "LIFNR")],
                "BSEG",
            )

    def test_disconnected_node_raises(self) -> None:
        """A box present in the graph but with no join reaching it from the
        root must be rejected, not silently dropped."""
        with pytest.raises(ValueError, match="MARA"):
            generate_mart_artifacts(
                {"BSEG": _load_contract("BSEG"), "LFA1": _load_contract("LFA1"), "MARA": _load_contract("MARA")},
                [_mandt_join("BSEG", "LFA1", "LIFNR", "LIFNR")],
                "BSEG",
            )

    def test_join_with_no_fields_raises(self) -> None:
        with pytest.raises(ValueError):
            generate_mart_artifacts(
                {"BSEG": _load_contract("BSEG"), "LFA1": _load_contract("LFA1")},
                [MartJoinSpec(left_node="BSEG", right_node="LFA1", fields=[])],
                "BSEG",
            )

    def test_two_tables_join_on_their_own_composite_keys(self) -> None:
        artifacts = generate_mart_artifacts(
            {"BSEG": _load_contract("BSEG"), "LFA1": _load_contract("LFA1"), "MARA": _load_contract("MARA")},
            [
                _mandt_join("BSEG", "LFA1", "LIFNR", "LIFNR"),
                _mandt_join("BSEG", "MARA", "MATNR", "MATNR"),
            ],
            "BSEG",
        )

        assert artifacts.joined_tables == ["LFA1", "MARA"]
        assert "FROM {{ source('sap', 'bseg') }} AS bseg" in artifacts.sql
        assert "LEFT JOIN {{ source('sap', 'lfa1') }} AS lfa1" in artifacts.sql
        assert "ON bseg.MANDT = lfa1.MANDT AND bseg.LIFNR = lfa1.LIFNR" in artifacts.sql
        assert "LEFT JOIN {{ source('sap', 'mara') }} AS mara" in artifacts.sql
        assert "ON bseg.MANDT = mara.MANDT AND bseg.MATNR = mara.MATNR" in artifacts.sql

    def test_columns_are_prefixed_and_all_included(self) -> None:
        artifacts = generate_mart_artifacts(
            {"BSEG": _load_contract("BSEG"), "LFA1": _load_contract("LFA1")},
            [_mandt_join("BSEG", "LFA1", "LIFNR", "LIFNR")],
            "BSEG",
        )
        assert "AS lfa1_lifnr" in artifacts.sql

    def test_root_audit_columns_are_qualified_by_root_alias(self) -> None:
        artifacts = generate_mart_artifacts(
            {"BSEG": _load_contract("BSEG"), "LFA1": _load_contract("LFA1")},
            [_mandt_join("BSEG", "LFA1", "LIFNR", "LIFNR")],
            "BSEG",
        )
        assert "{{ to_timestamp('bseg.dt_ingestao') }} AS dt_ingestao" in artifacts.sql
        assert "bseg.hash_pk AS hash_pk" in artifacts.sql
        assert "bseg.source AS source" in artifacts.sql

    def test_same_table_twice_under_different_node_ids(self) -> None:
        """BSEG references KNA1 twice in real data: KUNNR (sold-to) and
        VPTNR (payer). Modeled as two distinct nodes sharing one table_name,
        each gets its own alias, its own source() reference and its own
        prefixed columns — no conflated AND-together condition."""
        bseg = _load_contract("BSEG")
        kna1 = _load_contract("KNA1")
        artifacts = generate_mart_artifacts(
            {"BSEG": bseg, "KNA1_SOLDTO": kna1, "KNA1_PAYER": kna1},
            [
                _mandt_join("BSEG", "KNA1_SOLDTO", "KUNNR", "KUNNR"),
                _mandt_join("BSEG", "KNA1_PAYER", "VPTNR", "KUNNR"),
            ],
            "BSEG",
        )

        assert sorted(artifacts.joined_tables) == ["KNA1_PAYER", "KNA1_SOLDTO"]
        assert "LEFT JOIN {{ source('sap', 'kna1') }} AS kna1_soldto" in artifacts.sql
        assert "ON bseg.MANDT = kna1_soldto.MANDT AND bseg.KUNNR = kna1_soldto.KUNNR" in artifacts.sql
        assert "LEFT JOIN {{ source('sap', 'kna1') }} AS kna1_payer" in artifacts.sql
        assert "ON bseg.MANDT = kna1_payer.MANDT AND bseg.VPTNR = kna1_payer.KUNNR" in artifacts.sql
        assert "AS kna1_soldto_name1" in artifacts.sql or "kna1_soldto_" in artifacts.sql
        assert "AS kna1_payer_name1" in artifacts.sql or "kna1_payer_" in artifacts.sql

    def test_self_referencing_table_as_five_independent_nodes(self) -> None:
        """MARA -> MARA has five independent 2-field FKs in real DD08L data
        (BMATN/GENNR/PMATA/RMATP/SATNR, each -> MATNR). Modeled as five
        separate nodes all backed by the MARA contract, each its own alias."""
        mara = _load_contract("MARA")
        artifacts = generate_mart_artifacts(
            {"MARA": mara, "MARA_GENERIC": mara},
            [_mandt_join("MARA", "MARA_GENERIC", "BMATN", "MATNR")],
            "MARA",
        )
        assert "LEFT JOIN {{ source('sap', 'mara') }} AS mara_generic" in artifacts.sql
        assert "ON mara.MANDT = mara_generic.MANDT AND mara.BMATN = mara_generic.MATNR" in artifacts.sql

    def test_no_joins_produces_plain_single_table_select(self) -> None:
        artifacts = generate_mart_artifacts({"MARA": _load_contract("MARA")}, [], "MARA")

        assert artifacts.joined_tables == []
        assert "LEFT JOIN" not in artifacts.sql
        assert artifacts.warnings == []

    def test_wide_table_produces_warning(self) -> None:
        """LFA1 (142 fields) and MARA (229 fields) both exceed the wide-table
        threshold and should each get their own warning."""
        artifacts = generate_mart_artifacts(
            {"BSEG": _load_contract("BSEG"), "LFA1": _load_contract("LFA1"), "MARA": _load_contract("MARA")},
            [
                _mandt_join("BSEG", "LFA1", "LIFNR", "LIFNR"),
                _mandt_join("BSEG", "MARA", "MATNR", "MATNR"),
            ],
            "BSEG",
        )
        assert len(artifacts.warnings) == 2
        assert any("LFA1" in w for w in artifacts.warnings)
        assert any("MARA" in w for w in artifacts.warnings)

    def test_narrow_synthetic_table_produces_no_warning(self) -> None:
        root = _synthetic_contract(
            "ZFACT", "Transactional", [_column("MANDT"), _column("ZKEY", is_primary_key=True), _column("ZDIMKEY")]
        )
        dim = _synthetic_contract("ZDIM", "Master Data", [_column("ZDIMKEY", is_primary_key=True), _column("ZDESC")])

        artifacts = generate_mart_artifacts(
            {"ZFACT": root, "ZDIM": dim},
            [
                MartJoinSpec(
                    left_node="ZFACT", right_node="ZDIM", fields=[JoinFieldPair(left_field="ZDIMKEY", right_field="ZDIMKEY")]
                )
            ],
            "ZFACT",
        )
        assert artifacts.warnings == []

    def test_manual_join_with_filter_is_rendered_in_on_clause(self) -> None:
        """Mirrors a VBFA-style document-flow join: no real DD08L FK, wired
        by hand with an extra filter on the right side (e.g. VBTYP_N)."""
        order = _synthetic_contract(
            "ZORDER", "Transactional", [_column("MANDT"), _column("VBELN", is_primary_key=True)]
        )
        flow = _synthetic_contract(
            "ZFLOW",
            "Transactional",
            [_column("MANDT"), _column("VBELV"), _column("VBELN"), _column("VBTYP_N")],
        )

        artifacts = generate_mart_artifacts(
            {"ZORDER": order, "ZFLOW": flow},
            [
                MartJoinSpec(
                    left_node="ZORDER",
                    right_node="ZFLOW",
                    fields=[JoinFieldPair(left_field="VBELN", right_field="VBELV")],
                    right_filter=JoinFilter(field="VBTYP_N", operator="=", value="J"),
                    auto_detected=False,
                )
            ],
            "ZORDER",
        )
        assert "ON zorder.VBELN = zflow.VBELV AND zflow.VBTYP_N = 'J'" in artifacts.sql
        assert "Manual" in artifacts.documentation

    def test_yml_documents_root_and_joined_columns(self) -> None:
        artifacts = generate_mart_artifacts(
            {"BSEG": _load_contract("BSEG"), "LFA1": _load_contract("LFA1")},
            [_mandt_join("BSEG", "LFA1", "LIFNR", "LIFNR")],
            "BSEG",
        )
        assert "models:" in artifacts.yml
        assert "name: fct_bseg" in artifacts.yml
        assert "- name: lifnr" in artifacts.yml
        assert "- name: lfa1_lifnr" in artifacts.yml

    def test_documentation_contains_mermaid_table_and_sql(self) -> None:
        artifacts = generate_mart_artifacts(
            {"BSEG": _load_contract("BSEG"), "LFA1": _load_contract("LFA1")},
            [_mandt_join("BSEG", "LFA1", "LIFNR", "LIFNR")],
            "BSEG",
        )
        assert "```mermaid" in artifacts.documentation
        assert "flowchart LR" in artifacts.documentation
        assert "| LFA1 | LFA1 | Relacionada |" in artifacts.documentation
        assert "FK automática (DD08L)" in artifacts.documentation
        assert "```sql" in artifacts.documentation
        assert artifacts.sql.strip() in artifacts.documentation
