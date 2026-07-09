"""Translates a TableContract into dbt staging artifacts (SQL model + sources YAML).

Ports the type-mapping, load-type and watermark rules from the sibling
``datasphere_generator_dbt`` project's ``ingestor/translator.py`` and
``dbt_generator/generator.py`` modules, adapted to read directly from the
``TableContract`` that :class:`backend.service.MetadataService` already
assembles — no separate DDIC re-extraction step is needed here.

The generated SQL always relies on the bronze layer's own ``dt_ingestao``/
``hash_pk`` audit columns for its incremental filtering (exactly like the
sibling project); ``watermark_column`` is informational only, surfaced so it
can be copied into that table's bronze ingestion config (e.g. this repo's
sibling ``config.py`` pattern) — it does not change the SQL/YML content.
"""

import re

from backend.schemas import Column, DbtArtifacts, TableContract

_STRING_TYPES = {"CLNT", "CHAR", "NUMC", "TIMS", "UNIT", "CUKY", "LANG", "ACCP"}
_DATE_TYPES = {"DATS"}
_DECIMAL_TYPES = {"CURR", "QUAN", "DEC"}
_INT_TYPES = {"INT1", "INT2", "INT4", "INT8"}

_DATE_CANDIDATE_TYPES = {"CHAR", "NUMC"}
_DATE_KEYWORDS = {"DATA", "DT", "DATUM", "TIMESTAMP", "CRIADO", "MODIFICADO", "DATE"}

# Priority-ordered list of standard SAP modification/creation date fields.
_SAP_WATERMARK_CANDIDATES = ["AEDAT", "ERDAT", "CPUDT", "UDATE", "BUDAT", "UPDDT"]


def _is_hidden_date(column: Column) -> bool:
    """Returns True if a CHAR/NUMC column (8-10 chars) appears to encode a date."""
    if column.data_type not in _DATE_CANDIDATE_TYPES:
        return False
    if not (8 <= column.length <= 10):
        return False
    combined = f"{column.domain_name} {column.business_description}".upper()
    return any(keyword in combined for keyword in _DATE_KEYWORDS)


def _sap_alias(field_name: str) -> str:
    """Converts a SAP field name into a valid SQL/YAML identifier.

    Handles namespaced fields like ``/BEV1/LULDEGRP`` -> ``bev1_luldegrp``.
    """
    return field_name.lstrip("/").replace("/", "_").lower()


def _quote_if_needed(field_name: str) -> str:
    """Wraps a field name in SQL double quotes if it has non-standard identifier
    characters (e.g. a namespaced custom field like ``/BEV1/LULEINH``).

    The target dbt macros (``nullif_empty``, ``to_date``, ...) substitute
    ``{{ column_name }}`` straight into the SQL with no quoting of their own
    (ported as-is from the sibling ``datasphere_generator_dbt`` project's
    macros), so an unquoted ``/BEV1/LULEINH`` would render as a bare,
    unparsable token. Matches that sibling project's own
    ``ingestor/translator.py::_quote_if_needed``.
    """
    if re.search(r"[^A-Za-z0-9_]", field_name):
        return f'"{field_name}"'
    return field_name


def _map_column_type(column: Column) -> str:
    """Returns the dbt target type for a column (``STRING``, ``DATE``, ``DECIMAL(l,d)`` or ``INTEGER``)."""
    if _is_hidden_date(column) or column.data_type in _DATE_TYPES:
        return "DATE"
    if column.data_type in _STRING_TYPES:
        return "STRING"
    if column.data_type in _DECIMAL_TYPES:
        return f"DECIMAL({column.length}, {column.decimals})"
    if column.data_type in _INT_TYPES:
        return "INTEGER"
    return "STRING"


def suggest_load_type(contract: TableContract) -> str:
    """Suggests ``FULL`` or ``INCREMENTAL`` for the table, mirroring the sibling translator's rules.

    Structural types (VIEW/INTTAB) and master/config data (APPL0/APPL2) are
    always full snapshots; transactional data (APPL1) or unclassified large
    tables (``size_category >= 3``) use incremental loads.
    """
    stats = contract.technical_stats
    if contract.technical_class in ("VIEW", "INTTAB") or stats.data_class in ("APPL0", "APPL2"):
        return "FULL"
    try:
        size_category = int(stats.size_category)
    except ValueError:
        size_category = 0
    if stats.data_class == "APPL1" or size_category >= 3:
        return "INCREMENTAL"
    return "FULL"


def suggest_watermark(contract: TableContract) -> str | None:
    """Suggests the SAP field name best suited as an ingestion watermark, or None.

    Priority 1 is a well-known SAP change-date field (AEDAT, ERDAT, ...);
    priority 2 is the first field flagged by the hidden-date heuristic.
    """
    by_name = {column.column_name.upper(): column for column in contract.columns}
    for candidate in _SAP_WATERMARK_CANDIDATES:
        if candidate in by_name:
            return by_name[candidate].column_name
    for column in contract.columns:
        if _is_hidden_date(column):
            return column.column_name
    return None


def _col_to_macro(column: Column, target_type: str, alias: str | None = None, use_macros: bool = True) -> str:
    """Returns the dbt macro expression for a column based on its target type.

    Args:
        column: The column to render.
        target_type: Result of :func:`_map_column_type` for this column.
        alias: Optional table alias to qualify the field with.
        use_macros: Whether to use dbt macros or standard ANSI SQL casts.
    """
    raw_field = _quote_if_needed(column.column_name)
    field = f"{alias}.{raw_field}" if alias else raw_field
    if use_macros:
        if target_type == "DATE":
            return f"{{{{ to_date('{field}') }}}}"
        if target_type.startswith("DECIMAL"):
            return f"{{{{ to_decimal_nullif('{field}') }}}}"
        if target_type == "INTEGER":
            return f"{{{{ to_integer_nullif('{field}') }}}}"
        return f"{{{{ nullif_empty('{field}') }}}}"
    else:
        if target_type == "DATE":
            return f"CAST(NULLIF(TRIM({field}), '') AS DATE)"
        if target_type.startswith("DECIMAL"):
            return f"CAST(NULLIF(TRIM({field}), '') AS {target_type})"
        if target_type == "INTEGER":
            return f"CAST(NULLIF(TRIM({field}), '') AS INTEGER)"
        return f"NULLIF(TRIM({field}), '')"


def _build_sql(contract: TableContract, load_type: str, source_name: str, use_macros: bool = True, sql_template: str | None = None) -> str:
    table_name = contract.table_name.lower()
    
    col_lines = [
        f"    {_col_to_macro(column, _map_column_type(column), use_macros=use_macros)} AS {_sap_alias(column.column_name)}"
        for column in contract.columns
    ]
    
    if use_macros:
        timestamp_expr = "{{ to_timestamp('dt_ingestao') }}"
    else:
        timestamp_expr = "CAST(dt_ingestao AS TIMESTAMP)"

    if sql_template:
        materialized = "incremental" if load_type == "INCREMENTAL" else "table"
        source_relation = f"{{{{ source('{source_name}', '{table_name}') }}}}"
        if load_type == "INCREMENTAL":
            source_relation += " AS silver"
            
        config_extra = ""
        if load_type == "INCREMENTAL":
            config_extra = '\n        incremental_strategy="delete+insert",\n        unique_key="hash_pk",'
        else:
            config_extra = '\n        unique_key="hash_pk",'
            
        incremental_header = ""
        if load_type == "INCREMENTAL":
            incremental_header = (
                "{% if is_incremental() %}\n"
                "    WITH novos_hashes AS (\n"
                "        SELECT s_tgt.hash_pk\n"
                f"        FROM {{{{ source('{source_name}', '{table_name}') }}}} AS s_tgt\n"
                "        WHERE TRY_CONVERT(DATETIME2, s_tgt.dt_ingestao) >= (\n"
                "                SELECT DATEADD(\n"
                "                    DAY, -1, MAX(s_src.dt_ingestao)\n"
                "                ) FROM {{ this }} AS s_src\n"
                "            )\n"
                "    )\n"
                "{% endif %}"
            )
            
        incremental_footer = ""
        if load_type == "INCREMENTAL":
            incremental_footer = (
                "\n    {% if is_incremental() %}\n"
                "        INNER JOIN novos_hashes AS nhashes ON silver.hash_pk = nhashes.hash_pk\n"
                "    {% endif %}"
            )
            
        if load_type == "INCREMENTAL":
            audit_cols = [
                f"    {timestamp_expr} AS dt_ingestao",
                "    silver.hash_pk",
                "    silver.source"
            ]
        else:
            audit_cols = [
                f"    {timestamp_expr} AS dt_ingestao",
                "    hash_pk",
                "    source"
            ]
        columns_str = ",\n".join(col_lines + audit_cols)
        
        rendered = sql_template.replace("{table_name}", table_name)\
                               .replace("{source_name}", source_name)\
                               .replace("{materialized}", materialized)\
                               .replace("{config_extra}", config_extra)\
                               .replace("{incremental_header}", incremental_header)\
                               .replace("{incremental_footer}", incremental_footer)\
                               .replace("{source_relation}", source_relation)\
                               .replace("{columns}", columns_str)
        return rendered

    lines: list[str] = []

    if load_type == "INCREMENTAL":
        lines += [
            "{{",
            "    config(",
            f'        tags=["{source_name}", "silver"],',
            f'        alias="{table_name}",',
            '        materialized="incremental",',
            '        incremental_strategy="delete+insert",',
            '        unique_key="hash_pk",',
            "    )",
            "}}",
            "{% if is_incremental() %}",
            "    WITH novos_hashes AS (",
            "        SELECT s_tgt.hash_pk",
            f"        FROM {{{{ source('{source_name}', '{table_name}') }}}} AS s_tgt",
            "        WHERE TRY_CONVERT(DATETIME2, s_tgt.dt_ingestao) >= (",
            "                SELECT DATEADD(",
            "                    DAY, -1, MAX(s_src.dt_ingestao)",
            "                ) FROM {{ this }} AS s_src",
            "            )",
            "    )",
            "{% endif %}",
        ]
    else:
        lines += [
            "{{",
            "    config(",
            f"        tags=['{source_name}', 'silver'],",
            f"        alias='{table_name}',",
            "        materialized='table',",
            "    )",
            "}}",
        ]

    lines.append("")
    lines.append("SELECT")

    if load_type == "INCREMENTAL":
        audit_block = f",\n    {timestamp_expr} AS dt_ingestao,\n    silver.hash_pk,\n    silver.source"
        lines.append(",\n".join(col_lines) + audit_block)
        lines += [
            f"FROM {{{{ source('{source_name}', '{table_name}') }}}} AS silver",
            "    {% if is_incremental() %}",
            "        INNER JOIN novos_hashes AS nhashes ON silver.hash_pk = nhashes.hash_pk",
            "    {% endif %}",
        ]
    else:
        audit_block = (
            ",\n"
            "\n"
            "    -- Metadados de Auditoria da Pipeline\n"
            f"    {timestamp_expr} AS dt_ingestao,\n"
            "    hash_pk,\n"
            "    source"
        )
        lines.append(",\n".join(col_lines) + audit_block)
        lines.append("")
        lines.append(f"FROM {{{{ source('{source_name}', '{table_name}') }}}}")

    return "\n".join(lines) + "\n"


def _esc(value: str) -> str:
    """Escapes a string for a double-quoted YAML scalar."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _build_yml(contract: TableContract, load_type: str, source_name: str, database: str, schema: str, yml_template: str | None = None) -> str:
    table_name = contract.table_name.lower()
    description = _esc(contract.business_description)
    materialized = "incremental" if load_type == "INCREMENTAL" else "table"

    pk_columns = [column for column in contract.columns if column.is_primary_key]
    non_pk_columns = [column for column in contract.columns if not column.is_primary_key]

    out_cols = []
    if pk_columns:
        out_cols.append("          # Chaves Primárias / Identificadores")
        for column in pk_columns:
            out_cols.append(f"          - name: {_sap_alias(column.column_name)}")
            if column.business_description:
                out_cols.append(f'            description: "{_esc(column.business_description)}"')

    for column in non_pk_columns:
        out_cols.append(f"          - name: {_sap_alias(column.column_name)}")
        if column.business_description:
            out_cols.append(f'            description: "{_esc(column.business_description)}"')

    out_cols += [
        "          # Metadados de Auditoria da Pipeline",
        '          - name: hash_pk',
        '            description: "Chave primária MD5 gerada artificialmente para identificação única do registro"',
        '          - name: dt_ingestao',
        '            description: "Data e hora da ingestão na bronze"',
        '          - name: source',
        '            description: "Identificador da fonte dos dados"',
    ]
    columns_str = "\n".join(out_cols)

    if yml_template:
        config_extra = ""
        if load_type == "INCREMENTAL":
            config_extra = 'incremental_strategy: "delete+insert"'

        rendered = yml_template.replace("{source_name}", source_name)\
                               .replace("{database}", database)\
                               .replace("{schema}", schema)\
                               .replace("{table_name}", table_name)\
                               .replace("{description}", description)\
                               .replace("{materialized}", materialized)\
                               .replace("{config_extra}", config_extra)\
                               .replace("{columns}", columns_str)
        return rendered

    out: list[str] = [
        "sources:",
        f"  - name: {source_name}",
        f"    database: {database}",
        f"    schema: {schema}",
        "    tables:",
        f"      - name: {table_name}",
        f'        description: "{description}"',
        "        config:",
        f"          materialized: {materialized}",
    ]
    if load_type == "INCREMENTAL":
        out.append('          incremental_strategy: "delete+insert"')
    out.append('          unique_key: "hash_pk"')
    out.append(f'          tags: ["{source_name}", "silver"]')
    out.append("")
    out.append("        columns:")

    out += out_cols
    return "\n".join(out) + "\n"


def generate_dbt_artifacts(
    contract: TableContract,
    *,
    load_type: str | None = None,
    watermark_column: str | None = None,
    source_name: str = "sap",
    database: str = "BRONZE",
    schema: str = "dataspherev2",
    use_macros: bool = True,
    sql_template: str | None = None,
    yml_template: str | None = None,
) -> DbtArtifacts:
    """Builds the dbt staging SQL model and sources YAML for a single table.

    Args:
        contract: The table's full metadata contract.
        load_type: Overrides the auto-suggested ``FULL``/``INCREMENTAL``
            strategy. Must be one of those two values if given.
        watermark_column: Overrides the auto-suggested watermark field.
        source_name: dbt source name used in ``source('name', 'table')``.
        database: Database referenced by the generated ``sources.yml``.
        schema: Schema referenced by the generated ``sources.yml``.
        use_macros: Whether to use dbt macros or standard ANSI SQL casts.
        sql_template: Optional custom staging SQL template.
        yml_template: Optional custom staging YML template.

    Returns:
        The generated SQL/YML plus the resolved load type, watermark and any
        warnings.
    """
    resolved_load_type = (load_type or suggest_load_type(contract)).upper()
    if resolved_load_type not in ("FULL", "INCREMENTAL"):
        raise ValueError(f"load_type inválido: {resolved_load_type!r} (use FULL ou INCREMENTAL)")

    resolved_watermark = watermark_column or (
        suggest_watermark(contract) if resolved_load_type == "INCREMENTAL" else None
    )

    warnings: list[str] = []
    if resolved_load_type == "INCREMENTAL" and not resolved_watermark:
        warnings.append(
            "Nenhuma coluna de watermark foi encontrada automaticamente para esta carga incremental."
        )

    return DbtArtifacts(
        sql=_build_sql(contract, resolved_load_type, source_name, use_macros, sql_template),
        yml=_build_yml(contract, resolved_load_type, source_name, database, schema, yml_template),
        load_type=resolved_load_type,
        watermark_column=resolved_watermark,
        warnings=warnings,
        source_name=source_name,
        database=database,
        dbt_schema=schema,
    )
