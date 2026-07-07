"""Unit tests for backend.dbt_generator.

Fixtures are the real cached contracts in cache/MARA.json (TRANSP/APPL0 ->
FULL, no watermark needed) and cache/BSEG.json (CLUSTER/APPL1 -> INCREMENTAL,
no recognizable watermark field in this replica -> warning expected).
"""

import json
from pathlib import Path

from backend.dbt_generator import generate_dbt_artifacts, suggest_load_type, suggest_watermark
from backend.schemas import Column, TableContract, TechnicalStats

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


def _synthetic_contract(columns: list[Column]) -> TableContract:
    """Builds a minimal, otherwise-irrelevant TableContract around a given column list."""
    return TableContract(
        table_name="ZTEST",
        business_description="Tabela sintética de teste",
        technical_class="TRANSP",
        table_type="Transactional",
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


class TestSuggestLoadType:
    """Tests for suggest_load_type."""

    def test_master_data_is_full_even_with_high_size_category(self) -> None:
        """MARA (TRANSP/APPL0, size_category 4) is FULL: data_class wins over size."""
        contract = _load_contract("MARA")
        assert suggest_load_type(contract) == "FULL"

    def test_transactional_is_incremental(self) -> None:
        """BSEG (CLUSTER/APPL1) is INCREMENTAL."""
        contract = _load_contract("BSEG")
        assert suggest_load_type(contract) == "INCREMENTAL"


class TestSuggestWatermark:
    """Tests for suggest_watermark."""

    def test_priority_field_found_by_name(self) -> None:
        """AEDAT outranks ERDAT per the fixed SAP priority order."""
        contract = _synthetic_contract(
            [_column("ERDAT", "DATS", 8), _column("AEDAT", "DATS", 8), _column("OTHER")]
        )
        assert suggest_watermark(contract) == "AEDAT"

    def test_falls_back_to_hidden_date_heuristic(self) -> None:
        """No priority field present — falls back to a CHAR/NUMC field that looks like a date."""
        contract = _synthetic_contract(
            [
                _column("OTHER"),
                _column("DT_MODIFICACAO", "CHAR", length=8, business_description="Data de modificação"),
            ]
        )
        assert suggest_watermark(contract) == "DT_MODIFICACAO"

    def test_real_master_data_table_has_no_recognizable_watermark(self) -> None:
        """MARA has neither a priority field nor a hidden-date CHAR/NUMC field in this replica —
        documents the real (imperfect) heuristic behavior against live data."""
        contract = _load_contract("MARA")
        assert suggest_watermark(contract) is None

    def test_real_transactional_table_has_no_recognizable_watermark(self) -> None:
        """BSEG has neither a priority watermark field nor a hidden-date CHAR/NUMC field in this replica."""
        contract = _load_contract("BSEG")
        assert suggest_watermark(contract) is None


class TestGenerateDbtArtifacts:
    """Tests for generate_dbt_artifacts."""

    def test_full_table_uses_table_materialization(self) -> None:
        contract = _load_contract("MARA")
        artifacts = generate_dbt_artifacts(contract, source_name="sap", database="BRONZE", schema="dataspherev2")

        assert artifacts.load_type == "FULL"
        assert artifacts.watermark_column is None
        assert artifacts.warnings == []
        assert "materialized='table'" in artifacts.sql
        assert "is_incremental()" not in artifacts.sql
        assert "materialized: table" in artifacts.yml

    def test_full_table_maps_types_correctly(self) -> None:
        """MANDT/MATNR (PK) are plain nullif_empty; ERSDA (DATS) uses to_date; BRGEW (QUAN) uses to_decimal_nullif."""
        contract = _load_contract("MARA")
        artifacts = generate_dbt_artifacts(contract)

        assert "{{ nullif_empty('MANDT') }} AS mandt" in artifacts.sql
        assert "{{ to_date('ERSDA') }} AS ersda" in artifacts.sql
        assert "{{ to_decimal_nullif('BRGEW') }} AS brgew" in artifacts.sql

    def test_full_table_yml_lists_primary_keys_first(self) -> None:
        contract = _load_contract("MARA")
        artifacts = generate_dbt_artifacts(contract)

        pk_section = artifacts.yml.index("Chaves Primárias")
        mandt_pos = artifacts.yml.index("- name: mandt")
        matnr_pos = artifacts.yml.index("- name: matnr")
        ersda_pos = artifacts.yml.index("- name: ersda")
        assert pk_section < mandt_pos < ersda_pos
        assert pk_section < matnr_pos < ersda_pos

    def test_incremental_table_uses_incremental_materialization(self) -> None:
        contract = _load_contract("BSEG")
        artifacts = generate_dbt_artifacts(contract)

        assert artifacts.load_type == "INCREMENTAL"
        assert 'materialized="incremental"' in artifacts.sql
        assert "is_incremental()" in artifacts.sql
        assert "incremental_strategy: \"delete+insert\"" in artifacts.yml

    def test_incremental_table_without_watermark_warns(self) -> None:
        contract = _load_contract("BSEG")
        artifacts = generate_dbt_artifacts(contract)

        assert artifacts.watermark_column is None
        assert len(artifacts.warnings) == 1
        assert "watermark" in artifacts.warnings[0].lower()

    def test_incremental_table_maps_currency_and_integer_types(self) -> None:
        """DMBTR (CURR) uses to_decimal_nullif; PENDAYS (INT4) uses to_integer_nullif; AUGDT (DATS) uses to_date."""
        contract = _load_contract("BSEG")
        artifacts = generate_dbt_artifacts(contract)

        assert "{{ to_decimal_nullif('DMBTR') }} AS dmbtr" in artifacts.sql
        assert "{{ to_integer_nullif('PENDAYS') }} AS pendays" in artifacts.sql
        assert "{{ to_date('AUGDT') }} AS augdt" in artifacts.sql

    def test_overrides_take_precedence_over_heuristics(self) -> None:
        contract = _load_contract("MARA")
        artifacts = generate_dbt_artifacts(contract, load_type="INCREMENTAL", watermark_column="LAEDA")

        assert artifacts.load_type == "INCREMENTAL"
        assert artifacts.watermark_column == "LAEDA"
        assert artifacts.warnings == []

    def test_namespaced_field_is_aliased_without_slashes(self) -> None:
        """A /BEV1/-style namespaced field (real MARA data) is double-quoted as
        the macro's source argument (so the macro's raw {{ column_name }}
        substitution renders a valid quoted SQL identifier instead of a bare,
        unparsable `/BEV1/LULEINH` token) but is aliased as a valid,
        slash-free SQL identifier."""
        contract = _load_contract("MARA")
        artifacts = generate_dbt_artifacts(contract)

        assert """{{ nullif_empty('"/BEV1/LULEINH"') }} AS bev1_luleinh""" in artifacts.sql

    def test_custom_source_and_schema_appear_in_yml(self) -> None:
        contract = _load_contract("MARA")
        artifacts = generate_dbt_artifacts(contract, source_name="custom_src", database="MYDB", schema="my_schema")

        assert "name: custom_src" in artifacts.yml
        assert "database: MYDB" in artifacts.yml
        assert "schema: my_schema" in artifacts.yml
        assert "source('custom_src', 'mara')" in artifacts.sql
