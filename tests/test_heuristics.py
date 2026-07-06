"""Unit tests for backend.heuristics.TableClassifier.

Fixtures are drawn from real SAP tables verified against the actual
Datasphere replica during implementation (MARA, MARC, VBAP, VBAK) plus
synthetic CONTFLAG edge cases (configuration, temporary/system).
"""

from backend.heuristics import TableClassifier


class TestClassifyTableType:
    """Tests for TableClassifier.classify_table_type."""

    def test_single_key_master_data(self) -> None:
        """MARA (MANDT+MATNR, CONTFLAG=A) is single-key Master Data."""
        result = TableClassifier.classify_table_type("A", ["MANDT", "MATNR"])
        assert result == "Master Data"

    def test_segmented_master_data_not_transactional(self) -> None:
        """MARC (MANDT+MATNR+WERKS) stays Master Data despite 2 keys."""
        result = TableClassifier.classify_table_type("A", ["MANDT", "MATNR", "WERKS"])
        assert result == "Master Data"

    def test_document_item_is_transactional(self) -> None:
        """VBAP (MANDT+VBELN+POSNR) is Transactional: item-level document key."""
        result = TableClassifier.classify_table_type("A", ["MANDT", "VBELN", "POSNR"])
        assert result == "Transactional"

    def test_single_key_document_is_transactional(self) -> None:
        """VBAK (MANDT+VBELN) is Transactional even with a single non-MANDT key."""
        result = TableClassifier.classify_table_type("A", ["MANDT", "VBELN"])
        assert result == "Transactional"

    def test_configuration_contflag_c(self) -> None:
        """CONTFLAG=C (cross-client Customizing) is Configuration."""
        result = TableClassifier.classify_table_type("C", ["MANDT", "SPRAS"])
        assert result == "Configuration"

    def test_configuration_contflag_g_and_e(self) -> None:
        """CONTFLAG=G and E are also Configuration."""
        assert TableClassifier.classify_table_type("G", ["KEY1"]) == "Configuration"
        assert TableClassifier.classify_table_type("E", ["KEY1"]) == "Configuration"

    def test_temporary_local_is_unknown(self) -> None:
        """CONTFLAG=L (temp/non-transported work table) is Unknown, not business data."""
        result = TableClassifier.classify_table_type("L", ["KEY1"])
        assert result == "Unknown"

    def test_system_tables_are_unknown(self) -> None:
        """CONTFLAG=S/W (system tables) are Unknown."""
        assert TableClassifier.classify_table_type("S", ["KEY1"]) == "Unknown"
        assert TableClassifier.classify_table_type("W", ["KEY1"]) == "Unknown"


class TestClassifyHierarchyType:
    """Tests for TableClassifier.classify_hierarchy_type."""

    def test_item_child_by_position_key(self) -> None:
        """VBAP (VBELN+POSNR, Transactional) is Item/Filha."""
        result = TableClassifier.classify_hierarchy_type("Transactional", ["MANDT", "VBELN", "POSNR"])
        assert result == "Item / Filha"

    def test_standalone_master_single_key(self) -> None:
        """MARA (Master Data, single key) is Standalone/Mestre."""
        result = TableClassifier.classify_hierarchy_type("Master Data", ["MANDT", "MATNR"])
        assert result == "Standalone / Mestre"

    def test_header_for_single_key_document(self) -> None:
        """VBAK (Transactional, single document key) is Header/Cabeçalho."""
        result = TableClassifier.classify_hierarchy_type("Transactional", ["MANDT", "VBELN"])
        assert result == "Header / Cabeçalho"

    def test_segmented_master_data_is_standalone(self) -> None:
        """MARC (Master Data, MATNR+WERKS) is Standalone/Mestre: still master data,
        not a document header, despite the segmentation key."""
        result = TableClassifier.classify_hierarchy_type("Master Data", ["MANDT", "MATNR", "WERKS"])
        assert result == "Standalone / Mestre"

    def test_header_with_document_number_as_second_key(self) -> None:
        """BKPF (BUKRS+BELNR+GJAHR) is Header/Cabeçalho, not Item/Filha: BELNR
        identifies *which* document, not a line within it — unlike BSEG's BUZEI."""
        result = TableClassifier.classify_hierarchy_type(
            "Transactional", ["MANDT", "BUKRS", "BELNR", "GJAHR"]
        )
        assert result == "Header / Cabeçalho"

    def test_item_by_line_position_after_document_number(self) -> None:
        """BSEG (BUKRS+BELNR+GJAHR+BUZEI) is Item/Filha: BUZEI is the line
        position within the accounting document identified by BELNR."""
        result = TableClassifier.classify_hierarchy_type(
            "Transactional", ["MANDT", "BUKRS", "BELNR", "GJAHR", "BUZEI"]
        )
        assert result == "Item / Filha"


class TestFindAssociatedTextTable:
    """Tests for TableClassifier.find_associated_text_table."""

    def test_finds_existing_text_table(self) -> None:
        """T134T exists among candidates, so it is returned for T134."""
        result = TableClassifier.find_associated_text_table("T134", {"T134T", "OTHER"})
        assert result == "T134T"

    def test_returns_none_when_absent(self) -> None:
        """No candidate matches {table}T, so None is returned."""
        result = TableClassifier.find_associated_text_table("MARA", {"T134", "T137"})
        assert result is None


class TestClassifyRelationshipImportance:
    """Tests for TableClassifier.classify_relationship_importance."""

    def test_business_parent_is_high_importance_regardless_of_size(self) -> None:
        """A business-data parent (e.g. LFA1, MARA) is Alta even if tiny (e.g. MGEF, cat. 0)."""
        assert TableClassifier.classify_relationship_importance("A", "0") == "Alta"
        assert TableClassifier.classify_relationship_importance("A", "4") == "Alta"

    def test_substantial_configuration_parent_is_medium_importance(self) -> None:
        """A Configuration-class parent with a substantial size category (e.g. J_1BTANP,
        cat. 4, same as MARA itself) is Média, not Baixa."""
        assert TableClassifier.classify_relationship_importance("C", "4") == "Média"

    def test_tiny_configuration_parent_is_low_importance(self) -> None:
        """Small Configuration-class check tables (e.g. T006, T134 at cat. 0-1) are Baixa."""
        assert TableClassifier.classify_relationship_importance("C", "0") == "Baixa"
        assert TableClassifier.classify_relationship_importance("G", "1") == "Baixa"

    def test_unknown_parent_is_low_importance(self) -> None:
        """A blank/unrecognized CONTFLAG and size default to Baixa, not an error."""
        assert TableClassifier.classify_relationship_importance("") == "Baixa"


class TestBuildParentTables:
    """Tests for TableClassifier.build_parent_tables."""

    def test_groups_fields_by_checktable(self) -> None:
        """Fields referencing the same check table are grouped into one parent entry."""
        rows = [
            {"checktable": "T134", "child_field": "MTART", "parent_field": "MTART"},
            {"checktable": "T137", "child_field": "MBRSH", "parent_field": "MBRSH"},
        ]
        result = TableClassifier.build_parent_tables(rows)
        parent_names = {p["parent_table_name"] for p in result}
        assert parent_names == {"T134", "T137"}
        assert all(p["relationship_type"] == "Check Table" for p in result)

    def test_preserves_diverging_field_names(self) -> None:
        """MARA.BMATN checks MARA.MATNR: child and parent field names differ."""
        rows = [
            {"checktable": "MARA", "child_field": "MANDT", "parent_field": "MANDT"},
            {"checktable": "MARA", "child_field": "BMATN", "parent_field": "MATNR"},
        ]
        result = TableClassifier.build_parent_tables(rows, {"MARA": {"contflag": "A", "size_category": "4"}})
        assert result == [
            {
                "parent_table_name": "MARA",
                "relationship_type": "Check Table",
                "importance": "Alta",
                "foreign_key_fields": [
                    {"child_field": "MANDT", "parent_field": "MANDT"},
                    {"child_field": "BMATN", "parent_field": "MATNR"},
                ],
            }
        ]

    def test_defaults_to_low_importance_when_contflag_missing(self) -> None:
        """A parent table absent from the contflag mapping defaults to Baixa."""
        rows = [{"checktable": "T134", "child_field": "MTART", "parent_field": "MTART"}]
        result = TableClassifier.build_parent_tables(rows)
        assert result[0]["importance"] == "Baixa"

    def test_empty_when_no_foreign_keys(self) -> None:
        """No parent tables are produced when there are no foreign key rows."""
        assert TableClassifier.build_parent_tables([]) == []


class TestComputeRecordFootprint:
    """Tests for TableClassifier.compute_record_footprint."""

    def test_sums_lengths_and_counts_fields(self) -> None:
        """Record length sums all fields; key length sums only primary key fields."""
        columns = [
            {"length": 3, "is_primary_key": True},
            {"length": 18, "is_primary_key": True},
            {"length": 40, "is_primary_key": False},
        ]
        result = TableClassifier.compute_record_footprint(columns)
        assert result == {"field_count": 3, "record_length_bytes": 61, "key_length_bytes": 21}

    def test_empty_columns(self) -> None:
        """A table with no columns has an all-zero footprint."""
        result = TableClassifier.compute_record_footprint([])
        assert result == {"field_count": 0, "record_length_bytes": 0, "key_length_bytes": 0}


class TestFindIncrementalCandidateFields:
    """Tests for TableClassifier.find_incremental_candidate_fields."""

    def test_finds_known_change_date_fields(self) -> None:
        """AEDAT and LAEDA are recognized as incremental-load candidates."""
        result = TableClassifier.find_incremental_candidate_fields(
            ["MANDT", "MATNR", "AEDAT", "LAEDA", "ERSDA"]
        )
        assert result == ["AEDAT", "LAEDA"]

    def test_empty_when_no_candidates(self) -> None:
        """A table with no recognized change-date field returns an empty list."""
        result = TableClassifier.find_incremental_candidate_fields(["MANDT", "MATNR"])
        assert result == []
