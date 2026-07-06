"""Pydantic models for the SAP metadata JSON contract.

These models mirror the ``SAPTableMetadata`` JSON schema exactly and are used
both as FastAPI ``response_model``s (enforcing the contract on every
response) and as the return type of :class:`backend.service.MetadataService`.
"""

from typing import Literal

from pydantic import BaseModel


class ForeignKeyField(BaseModel):
    """A single child-to-parent field mapping within a foreign key.

    Attributes:
        child_field: Field name on the table being described.
        parent_field: Corresponding field name on the parent (check) table.
    """

    child_field: str
    parent_field: str


class ParentTable(BaseModel):
    """A parent table related to the described table via a foreign key.

    Attributes:
        parent_table_name: Technical name of the parent/check table.
        relationship_type: Human-readable relationship label (e.g.
            ``"Check Table"``).
        importance: ``"Alta"`` if the parent table is itself business data (a
            real entity relationship); otherwise ``"Média"`` or ``"Baixa"``
            depending on how substantial the Configuration-class
            domain/value-help lookup is (its own DD09L size category) — see
            :meth:`backend.heuristics.TableClassifier.classify_relationship_importance`.
        foreign_key_fields: Field-level mappings composing the relationship.
    """

    parent_table_name: str
    relationship_type: str
    importance: Literal["Alta", "Média", "Baixa"]
    foreign_key_fields: list[ForeignKeyField]


class Column(BaseModel):
    """A single column/field of the described table.

    Attributes:
        column_name: Technical field name.
        is_primary_key: Whether the field is part of the table's primary key.
        data_type: SAP ABAP data type (e.g. ``"CHAR"``, ``"NUMC"``).
        length: Field length in characters/digits.
        decimals: Number of decimal places (0 for non-numeric fields).
        business_description: Business-friendly field description.
        domain_name: Underlying DDIC domain name, if any.
        has_fixed_values: Whether the domain has a fixed value set (DD07T).
        fixed_values_map: Mapping of domain value to its business text,
            populated only when ``has_fixed_values`` is ``True``.
    """

    column_name: str
    is_primary_key: bool
    data_type: str
    length: int
    decimals: int
    business_description: str
    domain_name: str
    has_fixed_values: bool
    fixed_values_map: dict[str, str] = {}


class TechnicalStats(BaseModel):
    """DDIC-derived structural sizing and incremental-load signals.

    All values are computed purely from DDIC field metadata (DD03L), so they
    are available even for a table that exists only as a DDIC-defined view
    with no physical replicated data yet — unlike a live row count, which
    would require a runtime source.

    Attributes:
        field_count: Number of real fields (columns) on the table.
        record_length_bytes: Sum of all fields' lengths — the byte width of
            a single record.
        key_length_bytes: Sum of primary key fields' lengths.
        data_class: Raw DD09L ``TABART`` (e.g. ``"APPL0"`` for master data,
            ``"APPL1"`` for transaction data, ``"APPL2"`` for configuration/
            customizing — verified empirically: BSEG/EKPO/VBAP are all
            ``APPL1`` despite being item/line-level, not ``APPL2``); blank
            if none.
        size_category: Raw DD09L ``TABKAT``, SAP's coarse 0-9 expected-volume
            category set at table creation; ``"0"`` if none.
        incremental_candidate_fields: Field names recognized as common SAP
            "last changed" timestamps (e.g. ``AEDAT``, ``LAEDA``), suggesting
            the table's own data could support incremental/delta extraction.
        supports_incremental_load: Whether at least one candidate field was
            found. This is a structural heuristic, not confirmation that
            delta extraction is actually configured for this table.
    """

    field_count: int
    record_length_bytes: int
    key_length_bytes: int
    data_class: str
    size_category: str
    incremental_candidate_fields: list[str]
    supports_incremental_load: bool


class TableContract(BaseModel):
    """The full metadata contract returned by ``GET /api/table/{table_name}``.

    Attributes:
        table_name: Technical table name.
        business_description: Business-friendly table description.
        technical_class: DDIC table class (TABCLASS).
        table_type: Business classification inferred by
            :class:`backend.heuristics.TableClassifier`.
        hierarchy_type: Header/item/standalone classification inferred by
            the same classifier.
        associated_text_table: Technical name of the table's text table, if
            one was found.
        parent_tables: Related parent tables discovered via check-table
            references.
        columns: All fields of the table.
        technical_stats: DDIC-derived record size and incremental-load signals.
    """

    table_name: str
    business_description: str
    technical_class: Literal["TRANSP", "INTTAB", "CLUSTER", "VIEW"]
    table_type: Literal["Master Data", "Transactional", "Configuration", "Unknown"]
    hierarchy_type: Literal["Header / Cabeçalho", "Item / Filha", "Standalone / Mestre"]
    associated_text_table: str | None
    parent_tables: list[ParentTable]
    columns: list[Column]
    technical_stats: TechnicalStats


class SearchResult(BaseModel):
    """A single row returned by ``GET /api/search``.

    Attributes:
        table_name: Technical table name.
        description: Business-friendly table description.
    """

    table_name: str
    description: str
