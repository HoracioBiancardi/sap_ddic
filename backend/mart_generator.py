"""Translates an arbitrary graph of table "boxes" (canvas nodes) plus their
join wiring into a denormalized dbt "mart" model (a fact or dimension) — the
SQL JOIN, its model-level YAML doc, and a separate human-readable Markdown
document (Mermaid diagram of the whole graph + per-table summary + the SQL
itself).

A box's ``node_id`` (see :class:`backend.schemas.MartTableNode`) is what
identifies it in the graph and becomes its SQL alias — not its
``table_name`` — because the *same* SAP table can legitimately appear as two
independent boxes with two independent roles. This isn't a hypothetical:
BSEG references KNA1 twice (``KUNNR`` sold-to and ``VPTNR`` payer) and MARA
references itself five times (``BMATN``/``GENNR``/``PMATA``/``RMATP``/
``SATNR``, all generic-material variants). Node IDs let the caller (the
frontend's visual builder) represent that as two distinct boxes joined to
the same root, each with its own alias and its own prefixed output columns,
instead of forcing one conflated join condition.

Unlike a star schema built purely from one table's own declared DD08L
foreign keys, the join graph here is caller-supplied: some edges may be
auto-detected real foreign keys, but SAP document-flow-style relationships
(e.g. VBFA's generic document-link table, or ``VGBEL``/``VGPOS``
"reference document" fields on LIPS/VBRP) are frequently *not* modeled as
formal DD08L check-table relationships at all, so a caller needs to be able
to hand-wire those edges explicitly, with an optional field/value filter
(e.g. VBFA's ``VBTYP_N = 'J'``).

Reuses the exact same per-column type-mapping/macro/alias logic as
:mod:`backend.dbt_generator` (``_col_to_macro``, ``_map_column_type``,
``_quote_if_needed``, ``_build_alias_map``, ``_esc``) so a column renders
identically whether it ends up in a single-table staging model or a
multi-table mart.

Scope, deliberately: always a full ``materialized="table"`` rebuild (no
incremental variant — a mart's grain/dedup story is different enough from a
single-table stream that folding it into the same FULL/INCREMENTAL
heuristic would be guessing), and every column of every joined box is
brought across, prefixed by its node ID (no attempt to guess which fields
are "the descriptive ones") — callers are warned (see ``warnings``) when a
joined box is wide enough that trimming columns afterward is probably worth
it.
"""

from collections import deque
from dataclasses import dataclass

from backend.dbt_generator import _build_alias_map, _col_to_macro, _esc, _map_column_type, _quote_if_needed
from backend.schemas import JoinFilter, MartArtifacts, MartJoinSpec, TableContract

# A joined box this wide probably shouldn't have every column brought across
# uncurated — the caller gets a warning, not a hard limit, since guessing
# which columns matter would be worse than a wide default.
_WIDE_TABLE_COLUMN_THRESHOLD = 25


@dataclass
class _ResolvedJoin:
    """A single box reached while walking the join graph outward from the
    root: its node ID, its contract, the MartJoinSpec that reached it, and
    whether that spec's ``left_node`` (True) or ``right_node`` (False) is the
    side already resolved when this join fires."""

    node_id: str
    contract: TableContract
    join_spec: MartJoinSpec
    forward: bool


def suggest_mart_type(root_contract: TableContract) -> str:
    """Suggests ``"FCT"`` for a Transactional root table, ``"DIM"`` otherwise.

    Mirrors the same Master Data / Transactional split already computed by
    :meth:`backend.heuristics.TableClassifier.classify_table_type` — a
    document/movement table is fact-shaped, everything else (master data,
    configuration, unknown) is dimension-shaped.
    """
    return "FCT" if root_contract.table_type == "Transactional" else "DIM"


def _build_join_order(
    nodes: dict[str, TableContract], joins: list[MartJoinSpec], root_node: str
) -> list[_ResolvedJoin]:
    """Walks the join graph breadth-first from ``root_node``.

    Args:
        nodes: Every box in the canvas, keyed by ``node_id``.
        joins: Every edge wiring them together (referencing ``node_id``s).
        root_node: Which box anchors the ``FROM`` clause.

    Returns:
        Every other box, in traversal/emission order.

    Raises:
        ValueError: If ``root_node`` isn't in ``nodes``, a join references a
            node ID outside ``nodes``, a join has no field pairs, or any
            node isn't reachable from ``root_node`` by following ``joins``.
    """
    if root_node not in nodes:
        raise ValueError(f"root_node {root_node!r} não está na lista de tabelas.")

    adjacency: dict[str, list[tuple[MartJoinSpec, bool]]] = {node_id: [] for node_id in nodes}
    for spec in joins:
        if spec.left_node not in nodes or spec.right_node not in nodes:
            raise ValueError(f"O join {spec.left_node} <-> {spec.right_node} referencia uma tabela fora da lista.")
        if not spec.fields:
            raise ValueError(f"O join {spec.left_node} <-> {spec.right_node} não tem nenhum par de campos.")
        adjacency[spec.left_node].append((spec, True))
        adjacency[spec.right_node].append((spec, False))

    visited = {root_node}
    queue: deque[str] = deque([root_node])
    ordered_joins: list[_ResolvedJoin] = []

    while queue:
        current = queue.popleft()
        for spec, forward in adjacency[current]:
            other = spec.right_node if forward else spec.left_node
            if other in visited:
                continue
            visited.add(other)
            ordered_joins.append(_ResolvedJoin(node_id=other, contract=nodes[other], join_spec=spec, forward=forward))
            queue.append(other)

    unreachable = sorted(set(nodes) - visited)
    if unreachable:
        raise ValueError(
            f"As tabelas {unreachable} não estão conectadas a {root_node} por nenhum join — "
            "adicione um join ligando-as ao restante do grafo ou remova-as."
        )

    return ordered_joins


def _render_filter(alias: str, filter_: JoinFilter) -> str:
    escaped_value = filter_.value.replace("'", "''")
    return f"{alias}.{_quote_if_needed(filter_.field)} {filter_.operator} '{escaped_value}'"


def _join_condition(join: _ResolvedJoin) -> str:
    spec = join.join_spec
    left_alias = spec.left_node.lower()
    right_alias = spec.right_node.lower()

    conditions = [
        f"{left_alias}.{_quote_if_needed(pair.left_field)} = {right_alias}.{_quote_if_needed(pair.right_field)}"
        for pair in spec.fields
    ]
    if spec.left_filter:
        conditions.append(_render_filter(left_alias, spec.left_filter))
    if spec.right_filter:
        conditions.append(_render_filter(right_alias, spec.right_filter))

    return " AND ".join(conditions)


def _build_sql(
    root_node: str,
    root_contract: TableContract,
    joins: list[_ResolvedJoin],
    model_name: str,
    source_name: str,
    alias_maps: dict[str, dict[str, str]],
    use_macros: bool = True,
    sql_template: str | None = None,
) -> str:
    root_alias = root_node.lower()

    root_alias_map = alias_maps[root_node]
    col_lines = [
        f"    {_col_to_macro(column, _map_column_type(column), root_alias, use_macros=use_macros)} AS "
        f"{root_alias_map[column.column_name]}"
        for column in root_contract.columns
    ]
    for join in joins:
        alias = join.node_id.lower()
        join_alias_map = alias_maps[join.node_id]
        col_lines += [
            f"    {_col_to_macro(column, _map_column_type(column), alias, use_macros=use_macros)} AS "
            f"{alias}_{join_alias_map[column.column_name]}"
            for column in join.contract.columns
        ]

    if use_macros:
        timestamp_expr = f"{{{{ to_timestamp('{root_alias}.dt_ingestao') }}}}"
    else:
        timestamp_expr = f"CAST({root_alias}.dt_ingestao AS TIMESTAMP)"

    audit_block = (
        ",\n"
        "\n"
        "    -- Metadados de Auditoria da Pipeline (da tabela raiz)\n"
        f"    {timestamp_expr} AS dt_ingestao,\n"
        f"    {root_alias}.hash_pk AS hash_pk,\n"
        f"    {root_alias}.source AS source"
    )

    columns_str = ",\n".join(col_lines) + audit_block
    source_relation = f"{{{{ source('{source_name}', '{root_contract.table_name.lower()}') }}}} AS {root_alias}"

    join_statements = []
    for join in joins:
        alias = join.node_id.lower()
        table_lower = join.contract.table_name.lower()
        condition = _join_condition(join)
        join_statements.append(f"LEFT JOIN {{{{ source('{source_name}', '{table_lower}') }}}} AS {alias}\n    ON {condition}")
    joins_str = "\n".join(join_statements)

    if sql_template:
        rendered = sql_template.replace("{model_name}", model_name)\
                               .replace("{source_name}", source_name)\
                               .replace("{columns}", columns_str)\
                               .replace("{source_relation}", source_relation)\
                               .replace("{joins}", joins_str)
        return rendered

    lines = [
        "{{",
        "    config(",
        f"        tags=['{source_name}', 'gold'],",
        f"        alias='{model_name}',",
        "        materialized='table',",
        "    )",
        "}}",
        "",
        "SELECT",
    ]
    lines.append(columns_str)
    lines.append("")
    lines.append(f"FROM {source_relation}")

    for stmt in join_statements:
        lines.append(stmt)

    return "\n".join(lines) + "\n"


def _build_yml(
    root_node: str,
    root_contract: TableContract,
    joins: list[_ResolvedJoin],
    mart_type: str,
    model_name: str,
    alias_maps: dict[str, dict[str, str]],
    yml_template: str | None = None,
) -> str:
    root_alias_map = alias_maps[root_node]
    out_cols = []
    for column in root_contract.columns:
        out_cols.append(f"      - name: {root_alias_map[column.column_name]}")
        if column.business_description:
            out_cols.append(f'        description: "{_esc(column.business_description)}"')

    for join in joins:
        alias = join.node_id.lower()
        join_alias_map = alias_maps[join.node_id]
        for column in join.contract.columns:
            out_cols.append(f"      - name: {alias}_{join_alias_map[column.column_name]}")
            desc = f"[{join.node_id}] {column.business_description}".strip()
            out_cols.append(f'        description: "{_esc(desc)}"')

    out_cols += [
        "      - name: dt_ingestao",
        '        description: "Data e hora da ingestão na bronze (tabela raiz)"',
        "      - name: hash_pk",
        '        description: "Chave primária MD5 gerada artificialmente para identificação única do registro (tabela raiz)"',
        "      - name: source",
        '        description: "Identificador da fonte dos dados (tabela raiz)"',
    ]
    columns_str = "\n".join(out_cols)

    if yml_template:
        role_label = "Fato" if mart_type == "FCT" else "Dimensão"
        joined_names = ", ".join(join.node_id for join in joins)
        description = (
            f"[{role_label}] {root_contract.business_description} — junta {joined_names}."
            if joins
            else f"[{role_label}] {root_contract.business_description}"
        )
        rendered = yml_template.replace("{model_name}", model_name)\
                               .replace("{description}", description)\
                               .replace("{columns}", columns_str)
        return rendered

    role_label = "Fato" if mart_type == "FCT" else "Dimensão"
    joined_names = ", ".join(join.node_id for join in joins)
    description = (
        f"[{role_label}] {root_contract.business_description} — junta {joined_names}."
        if joins
        else f"[{role_label}] {root_contract.business_description}"
    )

    out = [
        "version: 2",
        "",
        "models:",
        f"  - name: {model_name}",
        f'    description: "{_esc(description)}"',
        "    columns:",
    ]
    out += out_cols
    return "\n".join(out) + "\n"


def _md_cell(text: str) -> str:
    """Escapes text for use inside a Markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _describe_join(join: _ResolvedJoin) -> str:
    spec = join.join_spec
    pairs = ", ".join(f"{pair.left_field} = {pair.right_field}" for pair in spec.fields)
    filters = []
    if spec.left_filter:
        filters.append(f"{spec.left_node}.{spec.left_filter.field} {spec.left_filter.operator} '{spec.left_filter.value}'")
    if spec.right_filter:
        filters.append(f"{spec.right_node}.{spec.right_filter.field} {spec.right_filter.operator} '{spec.right_filter.value}'")
    desc = pairs
    if filters:
        desc += " (" + ", ".join(filters) + ")"
    return desc


def _build_documentation(
    root_node: str, root_contract: TableContract, joins: list[_ResolvedJoin], mart_type: str, model_name: str, sql: str
) -> str:
    role_label = "Fato" if mart_type == "FCT" else "Dimensão"
    grain_fields = ", ".join(c.column_name for c in root_contract.columns if c.is_primary_key)

    lines = [
        f"# {model_name}",
        "",
        f"**Tipo:** {role_label}  ",
        f"**Tabela raiz:** `{root_node}` ({root_contract.table_name}) — {_md_cell(root_contract.business_description)}  ",
        f"**Grão:** uma linha por `{grain_fields}` (chave primária de `{root_contract.table_name}`)  ",
        "",
        "## Linhagem",
        "",
        "```mermaid",
        "flowchart LR",
        f'    {root_node}["{root_node}\\n({role_label.lower()})"]',
    ]
    for join in joins:
        spec = join.join_spec
        origin = spec.left_node if join.forward else spec.right_node
        keys = ", ".join(f"{pair.left_field}={pair.right_field}" for pair in spec.fields)
        arrow = "-->|" if spec.auto_detected else "-.->|"
        lines.append(f'    {join.node_id}["{join.node_id}\\n({join.contract.table_name})"]')
        lines.append(f'    {origin} {arrow}"{keys}"| {join.node_id}')
    lines.append("```")
    lines.append("_Linhas tracejadas indicam joins definidos manualmente (sem FK declarada no DDIC)._")
    lines.append("")

    lines += [
        "## Tabelas envolvidas",
        "",
        "| Nó | Tabela | Papel | Descrição | Origem do join | Campos de join |",
        "|---|---|---|---|---|---|",
        f"| {root_node} | {root_contract.table_name} | {role_label} (raiz) | {_md_cell(root_contract.business_description)} | — | — |",
    ]
    for join in joins:
        origin_label = "FK automática (DD08L)" if join.join_spec.auto_detected else "Manual"
        lines.append(
            f"| {join.node_id} | {join.contract.table_name} | Relacionada | {_md_cell(join.contract.business_description)} "
            f"| {origin_label} | {_describe_join(join)} |"
        )
    lines.append("")

    lines += [
        "## Query gerada",
        "",
        "```sql",
        sql.rstrip("\n"),
        "```",
        "",
    ]

    return "\n".join(lines)


def generate_mart_artifacts(
    nodes: dict[str, TableContract],
    joins: list[MartJoinSpec],
    root_node: str,
    *,
    mart_type: str | None = None,
    source_name: str = "sap",
    database: str = "BRONZE",
    schema: str = "dataspherev2",
    use_macros: bool = True,
    sql_template: str | None = None,
    yml_template: str | None = None,
    use_business_alias: bool = False,
) -> MartArtifacts:
    """Builds a fact/dimension dbt mart model from an arbitrary graph of
    table boxes and their join wiring.

    Args:
        nodes: Every box in the canvas, keyed by ``node_id`` — full metadata
            contracts.
        joins: Every edge connecting the boxes (auto-detected or manual),
            referencing ``node_id``s.
        root_node: Which box anchors the SQL's ``FROM`` clause. Every other
            box in ``nodes`` must be reachable from it.
        mart_type: Overrides the auto-suggested ``FCT``/``DIM`` role.
        source_name: dbt source name used in ``source('name', 'table')``.
        database: Database referenced by the generated documentation.
        schema: Schema referenced by the generated documentation.
        use_macros: Whether to use dbt macros or standard ANSI SQL casts.
        sql_template: Optional custom mart SQL template.
        yml_template: Optional custom mart YML template.
        use_business_alias: If True, every column's output alias (both in
            the SQL and the yml column list) is a short slug of its business
            description instead of the raw SAP field name — see
            :func:`backend.dbt_generator._business_alias`. Each box (root or
            joined) gets its own collision-safe alias resolution, since
            joined-box columns are already disambiguated by their
            ``{node_id}_`` prefix.

    Returns:
        The generated SQL/YML/documentation.
    """
    root_contract = nodes.get(root_node)
    if root_contract is None:
        raise ValueError(f"root_node {root_node!r} não está na lista de tabelas.")

    resolved_mart_type = (mart_type or suggest_mart_type(root_contract)).upper()
    if resolved_mart_type not in ("FCT", "DIM"):
        raise ValueError(f"mart_type inválido: {resolved_mart_type!r} (use FCT ou DIM)")

    ordered_joins = _build_join_order(nodes, joins, root_node)

    model_name = f"{resolved_mart_type.lower()}_{root_node.lower()}"

    alias_maps = {root_node: _build_alias_map(root_contract.columns, use_business_alias, {"hash_pk", "dt_ingestao", "source"})}
    for join in ordered_joins:
        alias_maps[join.node_id] = _build_alias_map(join.contract.columns, use_business_alias)

    sql = _build_sql(root_node, root_contract, ordered_joins, model_name, source_name, alias_maps, use_macros, sql_template)
    yml = _build_yml(root_node, root_contract, ordered_joins, resolved_mart_type, model_name, alias_maps, yml_template)
    documentation = _build_documentation(root_node, root_contract, ordered_joins, resolved_mart_type, model_name, sql)

    warnings = [
        f"A tabela {join.node_id} ({join.contract.table_name}) tem {len(join.contract.columns)} campos — "
        "considere remover colunas não usadas do modelo gerado."
        for join in ordered_joins
        if len(join.contract.columns) > _WIDE_TABLE_COLUMN_THRESHOLD
    ]

    return MartArtifacts(
        sql=sql,
        yml=yml,
        documentation=documentation,
        mart_type=resolved_mart_type,
        model_name=model_name,
        base_table=root_node,
        joined_tables=[join.node_id for join in ordered_joins],
        warnings=warnings,
        source_name=source_name,
        database=database,
        dbt_schema=schema,
    )
