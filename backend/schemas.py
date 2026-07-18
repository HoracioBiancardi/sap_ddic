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
        creation_date_candidate_fields: Field names recognized as common SAP
            "created on" timestamps (e.g. ``ERDAT``, ``ERSDA``). Better
            suited than a "last changed" field as the cutoff for the very
            first (full) load, since old or never-updated records commonly
            have their change-date field zero-filled (``"00000000"``) while
            the creation-date field is always populated.
    """

    field_count: int
    record_length_bytes: int
    key_length_bytes: int
    data_class: str
    size_category: str
    incremental_candidate_fields: list[str]
    supports_incremental_load: bool
    creation_date_candidate_fields: list[str] = []


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

class DbtGenerateRequest(BaseModel):
    """Request body for POST /api/table/{table_name}/dbt.

    Allows overriding staging generation properties and custom templates.

    Attributes:
        plain_sql: If True, skip the dbt scaffolding entirely (no
            ``config()`` block, no Jinja ``source()`` macro, no pipeline
            audit columns) and return a plain ``SELECT ... FROM
            {schema}.{table}`` a user can paste straight into a SQL client.
        use_business_alias: If True, every column's ``AS`` alias is a short
            slug of its business description (e.g. ``numero_material``)
            instead of the raw SAP field name lowercased.
    """

    load_type: str | None = None
    watermark_column: str | None = None
    source_name: str | None = None
    database: str | None = None
    dbt_schema: str | None = None
    use_macros: bool = True
    sql_template: str | None = None
    yml_template: str | None = None
    plain_sql: bool = False
    use_business_alias: bool = False


class DbtArtifacts(BaseModel):
    """Generated dbt staging artifacts for a single SAP table.

    Attributes:
        sql: The ``stg_<table>.sql`` model content. dbt macros (``to_date``,
            ``nullif_empty``, etc.) are left un-rendered, for the target dbt
            project's own macro definitions to expand.
        yml: The ``stg_<table>.yml`` ``sources:`` block content.
        load_type: The resolved load strategy actually used to build the SQL
            (``"FULL"`` or ``"INCREMENTAL"``), either auto-suggested or overridden.
        watermark_column: The suggested (or overridden) SAP field to use as
            the ingestion watermark for this table upstream, in the bronze
            layer. Informational only — it does not affect the SQL/YML
            content, which always relies on the bronze ``dt_ingestao``/
            ``hash_pk`` audit columns for its own incremental filtering.
        warnings: Human-readable warnings surfaced during generation (e.g. no
            watermark candidate found for an incremental table).
        source_name: The dbt source name actually used (echoed back so the
            frontend can pre-fill its inputs on the first, override-free call).
        database: The database actually used in the generated ``sources.yml``.
        dbt_schema: The schema actually used in the generated ``sources.yml``
            (named ``dbt_schema`` rather than ``schema`` to avoid shadowing
            ``BaseModel``'s own attribute of that name).
    """

    sql: str
    yml: str
    load_type: Literal["FULL", "INCREMENTAL"]
    watermark_column: str | None
    warnings: list[str]
    source_name: str
    database: str
    dbt_schema: str


class JoinFieldPair(BaseModel):
    """A single ``left.field = right.field`` equality within a join's ON clause."""

    left_field: str
    right_field: str


class JoinFilter(BaseModel):
    """A single extra ``field <op> 'value'`` condition ANDed into a join's ON
    clause, scoped to one side's own fields — e.g. VBFA's document-flow
    edges need ``VBTYP_N = 'J'`` to select only delivery-type successor
    documents. Structured (not a raw SQL string) so the backend can qualify
    ``field`` with the correct resolved table alias itself, and so the
    frontend can build it from a plain field/operator/value form."""

    field: str
    operator: Literal["=", "!=", "<>"] = "="
    value: str


class MartTableNode(BaseModel):
    """One box on the visual builder's canvas.

    ``node_id`` and ``table_name`` are almost always the same string — but
    they're kept distinct so the *same* SAP table can appear as two
    independent boxes with two independent roles, e.g. KNA1 once as
    "sold-to customer" (joined via ``KUNNR``) and once as "payer" (joined
    via ``VPTNR``) — a real shape in live BSEG data, not a hypothetical.
    Node IDs disambiguate boxes; ``table_name`` says which real DDIC table
    to fetch and to reference in the generated ``source(...)`` calls.

    Attributes:
        node_id: Unique identifier for this box within the request (also
            used as its SQL alias, lowercased). Free-form, chosen by the
            caller (e.g. ``"KNA1_PAYER"``).
        table_name: The real SAP table this box represents.
    """

    node_id: str
    table_name: str


class MartJoinSpec(BaseModel):
    """One join between two boxes in a mart's table graph — either
    auto-detected from a real DD08L foreign key, or hand-drawn by the user
    in the visual builder for relationships DDIC doesn't declare as a formal
    FK (e.g. SAP document-flow chains like VBFA, or ``VGBEL``/``VGPOS``
    "reference document" fields).

    Attributes:
        left_node: ``node_id`` of one side of the join. Must be one of the
            request's ``tables``.
        right_node: ``node_id`` of the other side. Must be one of the
            request's ``tables``, different from ``left_node``.
        fields: Equality conditions ANDed together in the ON clause. At
            least one pair is required.
        left_filter: Optional extra condition on ``left_node``'s own fields.
        right_filter: Optional extra condition on ``right_node``'s own fields.
        auto_detected: Whether this join was suggested from a real DD08L
            foreign key (informational — shown in the generated
            documentation) as opposed to hand-drawn by the user.
    """

    left_node: str
    right_node: str
    fields: list[JoinFieldPair]
    left_filter: JoinFilter | None = None
    right_filter: JoinFilter | None = None
    auto_detected: bool = False


class MartGenerateRequest(BaseModel):
    """Request body for ``POST /api/mart/generate``: an arbitrary graph of
    table boxes (not just one root table's own declared parents) plus every
    join wiring it together.

    Attributes:
        tables: Every box on the canvas.
        root_node: ``node_id`` of the box that anchors the SQL's ``FROM``
            clause. Every other box must be reachable from it by following
            ``joins`` (in either direction) — see
            :mod:`backend.mart_generator`.
        joins: Every edge connecting the boxes, auto-detected or manual.
        mart_type: Overrides the auto-suggested ``FCT``/``DIM`` role
            (defaults to the root table's own ``table_type``).
        source_name: Optional override for the dbt source name (see
            :func:`backend.main.get_table_dbt_artifacts` for why it defaults
            to the resolved schema rather than a fixed name).
        database: Optional override for the documentation's database.
        dbt_schema: Optional override for the yml/SQL schema.
        use_business_alias: If True, every column's output alias is a short
            slug of its business description instead of the raw SAP field
            name (see :class:`DbtGenerateRequest.use_business_alias`).
    """

    tables: list[MartTableNode]
    root_node: str
    joins: list[MartJoinSpec]
    mart_type: Literal["FCT", "DIM"] | None = None
    source_name: str | None = None
    database: str | None = None
    dbt_schema: str | None = None
    use_macros: bool = True
    sql_template: str | None = None
    yml_template: str | None = None
    use_business_alias: bool = False


class MartArtifacts(BaseModel):
    """Generated dbt "mart" artifacts for a fact or dimension model joining a
    root table to an arbitrary graph of related tables — not necessarily
    just the root's own declared parents (see :class:`MartGenerateRequest`).

    Attributes:
        sql: The ``<mart_type>_<table>.sql`` model content — a single SELECT
            with one LEFT JOIN per non-root table (in join-graph traversal
            order), all columns from every table in the graph (the root's
            unprefixed, every other table's prefixed by its join alias).
            Always a full ``materialized="table"`` rebuild — no incremental
            variant, see :mod:`backend.mart_generator`.
        yml: The model-level ``models:`` YAML block documenting every output
            column (as opposed to :class:`DbtArtifacts.yml`, which documents
            a raw ``sources:`` table).
        documentation: A standalone Markdown document — a Mermaid diagram of
            the whole table graph, a table summarizing every table involved
            (role, description, join keys, auto-detected vs. hand-drawn) and
            the generated SQL itself — meant for humans, not for the dbt
            project.
        mart_type: ``"FCT"`` or ``"DIM"``, either auto-suggested from the
            root table's ``table_type`` or overridden by the caller.
        model_name: The resolved model name (``<mart_type>_<table>``,
            lowercase), used as both the SQL file's alias and the yml's
            model name.
        base_table: The root box's ``node_id`` (usually equal to its table
            name — see :class:`MartTableNode`).
        joined_tables: Every other box's ``node_id`` actually joined in, in
            the order they appear in the SQL.
        warnings: Human-readable warnings (e.g. a joined table is wide
            enough that trimming columns afterward is probably worth it).
        source_name: The dbt source name actually used in ``source('name',
            'table')`` calls.
        database: The database actually referenced (informational; the mart
            SQL itself only references sources by name, not database).
        dbt_schema: The schema actually used (informational, for parity with
            :class:`DbtArtifacts`; the mart SQL only references sources by
            name).
    """

    sql: str
    yml: str
    documentation: str
    mart_type: Literal["FCT", "DIM"]
    model_name: str
    base_table: str
    joined_tables: list[str]
    warnings: list[str]
    source_name: str
    database: str
    dbt_schema: str


class SearchResult(BaseModel):
    """A single row returned by ``GET /api/search``.

    Attributes:
        table_name: Technical table name.
        description: Business-friendly table description.
    """

    table_name: str
    description: str
