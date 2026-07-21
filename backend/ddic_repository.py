"""Read access to the replicated SAP DDIC tables in Datasphere/HANA.

The schema now exposes the classic DDIC catalog tables directly (DD02L,
DD02T, DD03L, DD04T, DD07T, DD05S, DD08L), as plain-named views over the
Replication Flow artifacts. DD05S (Foreign Key Fields) and DD08L (Foreign
Key: Definitions) give proper field-level foreign-key mappings, replacing
the earlier ``DD03L.CHECKTABLE``-only approximation.

DD05S only ever names the *local* (child) side of each key position
(``FORTABLE``/``FORKEY`` refer to the table being described itself, or to
``SYST`` for the client field) — it never names the check table's own field.
The check table's field at the same key position must be looked up
separately from its own DD03L key structure. For example, ``MARA.BMATN``
(old material number) has a DD08L check table of ``MARA`` itself, and DD05S
only tells us the local field is ``BMATN`` at key position 2 — the actual
parent field, ``MATNR``, only becomes known once MARA's own ordered primary
key (``MANDT``, ``MATNR``) is matched up position-by-position.

All SQL here is parameterized through
:meth:`backend.connection.DatasphereConnector.run_query` — no user-supplied
value is ever interpolated directly into a query string.
"""

from backend.connection import DatasphereConnector

_TABCLASS_ALIASES: dict[str, str] = {
    "POOL": "TRANSP",
    "APPEND": "INTTAB",
}

# Business-domain synonyms (Portuguese, plain-ASCII since the caller strips
# accents before this lookup). Each domain's "applclass_codes" are DD02L
# APPLCLASS values empirically confirmed against well-known "seed_tables" in
# this replica (e.g. BKPF/BSEG -> "FB", VBAK/VBAP -> "VA"). Lets a term like
# "financeiro" surface tables whose description never contains that word,
# since SAP's own DDTEXT is technical ("Documento contabil: Cabecalho"), not
# business-domain phrasing. "applclass_codes" can be left as [] for a domain
# whose APPLCLASS hasn't been empirically confirmed yet — the SQLAlchemy
# expanding bindparam treats an empty tuple as "matches nothing", so the
# seed_tables hits alone still surface reliably.
#
# "seed_tables" order is meaningful: it's the *display* order among domain
# hits (see the ORDER BY in `search`), so the first table listed is treated
# as the canonical/"main" table for that concept (e.g. VBAK before VBAP for
# "pedido") — it is not just an unordered membership set. Listing order is
# what lets a combined-concept domain like PEDIDOS (below) put its more
# generic reading (sales order) ahead of the narrower one (purchase order)
# regardless of the tables' own alphabetical order (EKKO would otherwise
# sort before VBAK by accident).
_BUSINESS_DOMAINS: list[dict] = [
    {
        "synonyms": {"FINANCEIRO", "CONTABIL", "CONTABILIDADE"},
        "applclass_codes": ["FB"],
        "seed_tables": ["BKPF", "BSEG", "BSIK", "BSAK", "BSID", "BSAD", "SKA1", "SKB1"],
    },
    {
        "synonyms": {
            "VENDAS", "COMERCIAL",
            "PEDIDO DE VENDA", "PEDIDOS DE VENDA", "ORDEM DE VENDA", "ORDENS DE VENDA",
        },
        "applclass_codes": ["VA", "VF"],
        "seed_tables": ["VBAK", "VBAP", "VBRK", "VBRP"],
    },
    {
        "synonyms": {"FATURAMENTO", "NOTA FISCAL", "NOTAS FISCAIS", "FATURA", "FATURAS"},
        "applclass_codes": ["VF"],
        "seed_tables": ["VBRK", "VBRP"],
    },
    {
        "synonyms": {
            "COMPRAS", "SUPRIMENTOS",
            "PEDIDO DE COMPRA", "PEDIDOS DE COMPRA", "ORDEM DE COMPRA", "ORDENS DE COMPRA",
        },
        "applclass_codes": ["ME"],
        "seed_tables": ["EKKO", "EKPO"],
    },
    {
        # Bare "pedido"/"pedidos" is ambiguous between sales and purchase
        # orders; per product decision, show both, sales-order tables first
        # (see the seed_tables-order note above). "Pedidos abertos" can't
        # filter by open status — this only browses DDIC metadata, not live
        # documents — so it's mapped to the same header/item tables.
        "synonyms": {"PEDIDO", "PEDIDOS", "PEDIDOS ABERTOS", "PEDIDO ABERTO", "PEDIDOS EM ABERTO"},
        "applclass_codes": ["VA", "ME"],
        "seed_tables": ["VBAK", "VBAP", "EKKO", "EKPO"],
    },
    {
        "synonyms": {"MATERIAIS", "MATERIAL", "ESTOQUE", "PRODUTO", "PRODUTOS"},
        "applclass_codes": ["MG"],
        "seed_tables": ["MARA", "MARC", "MARD", "MBEW"],
    },
    {
        "synonyms": {"PRODUCAO"},
        "applclass_codes": ["CO"],
        "seed_tables": ["AFKO", "AFPO"],
    },
    {
        "synonyms": {"CONTROLADORIA", "CUSTOS"},
        "applclass_codes": ["KA", "KS", "KSS"],
        "seed_tables": ["COEP", "CSKS", "CSKB"],
    },
    {
        "synonyms": {"CLIENTE", "CLIENTES"},
        "applclass_codes": [],
        "seed_tables": ["KNA1", "KNVV", "KNB1"],
    },
    {
        "synonyms": {"FORNECEDOR", "FORNECEDORES"},
        "applclass_codes": [],
        "seed_tables": ["LFA1", "LFB1", "LFM1"],
    },
    {
        "synonyms": {"ENTREGA", "ENTREGAS", "REMESSA", "REMESSAS"},
        "applclass_codes": [],
        "seed_tables": ["LIKP", "LIPS"],
    },
    {
        "synonyms": {
            "FUNCIONARIO", "FUNCIONARIOS", "COLABORADOR", "COLABORADORES", "RECURSOS HUMANOS",
        },
        "applclass_codes": [],
        "seed_tables": ["PA0000", "PA0001", "PA0002"],
    },
]

_SYNONYM_TO_DOMAIN: dict[str, dict] = {
    synonym: domain for domain in _BUSINESS_DOMAINS for synonym in domain["synonyms"]
}


class DDICRepository:
    """Fetches raw DDIC rows for a single table from the replicated schema.

    Attributes:
        connector: Connection wrapper used to run parameterized queries.
        schema: Name of the Datasphere schema holding the replicated tables.
        language: Two-letter SAP language key used to filter description texts.
    """

    def __init__(self, connector: DatasphereConnector, schema: str, language: str) -> None:
        """Initializes the repository.

        Args:
            connector: Connection wrapper used to run parameterized queries.
            schema: Name of the Datasphere schema holding the replicated tables.
            language: Two-letter SAP language key (e.g. ``"P"``) used to
                filter description texts.
        """
        self.connector = connector
        self.schema = schema
        self.language = language

    def _qualified(self, table_name: str) -> str:
        """Builds a double-quoted, schema-qualified identifier.

        Args:
            table_name: Physical table/view name.

        Returns:
            The identifier quoted as ``"schema"."table_name"``, safe to
            splice into SQL because it is only ever built from fixed,
            hardcoded table names in this module, never from user input.
        """
        return f'"{self.schema}"."{table_name}"'

    def fetch_header(self, table_name: str) -> dict | None:
        """Fetches DD02L header attributes for a table.

        Args:
            table_name: Technical table name, already validated upstream.

        Returns:
            A dict with ``tabname``, ``tabclass`` (normalized to the
            contract's fixed enum), ``contflag`` and ``as4date``, or
            ``None`` if the table does not exist in DD02L.
        """
        rows = self.connector.run_query(
            f"SELECT TABNAME, TABCLASS, CONTFLAG, AS4DATE "
            f"FROM {self._qualified('DD02L')} WHERE TABNAME = :table_name",
            {"table_name": table_name},
        )
        if not rows:
            return None

        row = rows[0]
        tabclass = row["tabclass"].strip().upper()
        return {
            "tabname": row["tabname"],
            "tabclass": _TABCLASS_ALIASES.get(tabclass, tabclass),
            "contflag": row["contflag"].strip().upper(),
            "as4date": row["as4date"].strip(),
        }

    def fetch_description(self, table_name: str) -> str:
        """Fetches the business description of a table for the configured language.

        Args:
            table_name: Technical table name.

        Returns:
            The description text, falling back to the table name itself if
            no text exists in the configured language.
        """
        rows = self.connector.run_query(
            f"SELECT DDTEXT FROM {self._qualified('DD02T')} "
            f"WHERE TABNAME = :table_name AND DDLANGUAGE = :language",
            {"table_name": table_name, "language": self.language},
        )
        return rows[0]["ddtext"].strip() if rows else table_name

    def fetch_columns(self, table_name: str) -> list[dict]:
        """Fetches all real fields of a table, ordered by DDIC position.

        Rows representing structural include markers (``FIELDNAME`` starting
        with ``.``, e.g. ``.INCLUDE``) are skipped since they are not
        addressable columns.

        Args:
            table_name: Technical table name.

        Returns:
            A list of dicts with ``column_name``, ``is_primary_key``,
            ``data_type``, ``length``, ``decimals`` and ``domain_name`` for
            every real field, ordered by ``POSITION``.
        """
        rows = self.connector.run_query(
            f"SELECT FIELDNAME, KEYFLAG, DATATYPE, LENG, DECIMALS, ROLLNAME, DOMNAME "
            f"FROM {self._qualified('DD03L')} "
            f"WHERE TABNAME = :table_name ORDER BY POSITION",
            {"table_name": table_name},
        )
        columns = []
        for row in rows:
            field_name = row["fieldname"].strip()
            if not field_name or field_name.startswith("."):
                continue
            columns.append(
                {
                    "column_name": field_name,
                    "is_primary_key": row["keyflag"].strip().upper() == "X",
                    "data_type": row["datatype"].strip(),
                    "length": int(row["leng"] or 0),
                    "decimals": int(row["decimals"] or 0),
                    "rollname": row["rollname"].strip(),
                    "domain_name": row["domname"].strip(),
                }
            )
        return columns

    def _fetch_ordered_key_fields(self, table_names: list[str]) -> dict[str, list[str]]:
        """Fetches the ordered primary-key field names for a batch of tables.

        Used to resolve the parent-side field name of a foreign key: DD05S
        never names it directly, but it occupies the same key position as
        the corresponding field in the check table's own primary key.

        Args:
            table_names: Distinct table names to look up.

        Returns:
            A mapping of table name to its primary key field names, ordered
            by DDIC ``POSITION``.
        """
        if not table_names:
            return {}
        rows = self.connector.run_query(
            f"SELECT TABNAME, FIELDNAME FROM {self._qualified('DD03L')} "
            f"WHERE TABNAME IN :table_names AND KEYFLAG = 'X' "
            f"ORDER BY TABNAME, POSITION",
            {"table_names": tuple(table_names)},
        )
        keys: dict[str, list[str]] = {}
        for row in rows:
            keys.setdefault(row["tabname"].strip(), []).append(row["fieldname"].strip())
        return keys

    def fetch_table_classes(self, table_names: list[str]) -> dict[str, dict[str, str]]:
        """Fetches the DD02L delivery class and DD09L size category for a batch of tables.

        Used to rank a parent table's relevance in the lineage graph: a
        check table that is itself business data (e.g. ``LFA1``, ``MARA``)
        represents a real entity relationship, while one that is
        Configuration-class (e.g. ``T006`` units of measure, ``T134``
        material types) is usually a small, static domain/value-help lookup
        — "usually", because some Configuration-class tables are
        substantial in their own right (e.g. ``J_1BTANP`` shares MARA's own
        size category, 4, while ``T006`` sits at 0), so the raw size
        category is kept alongside the delivery class rather than
        collapsing straight to a business/configuration binary — see
        :meth:`backend.heuristics.TableClassifier.classify_relationship_importance`.

        Args:
            table_names: Distinct table names to look up.

        Returns:
            A mapping of table name to ``{"contflag": ..., "size_category": ...}``.
            Tables not found in DD02L are simply absent; a DD02L match with
            no DD09L row defaults ``size_category`` to ``"0"``.
        """
        if not table_names:
            return {}
        rows = self.connector.run_query(
            f"SELECT L.TABNAME, L.CONTFLAG, COALESCE(D.TABKAT, '0') AS size_category "
            f"FROM {self._qualified('DD02L')} L "
            f"LEFT JOIN {self._qualified('DD09L')} D ON D.TABNAME = L.TABNAME "
            f"WHERE L.TABNAME IN :table_names",
            {"table_names": tuple(table_names)},
        )
        return {
            row["tabname"].strip(): {
                "contflag": row["contflag"].strip().upper(),
                "size_category": row["size_category"].strip(),
            }
            for row in rows
        }

    def fetch_foreign_keys(self, table_name: str) -> list[dict]:
        """Fetches field-level foreign key mappings for a table.

        Args:
            table_name: Technical table name.

        Returns:
            A list of dicts with ``checktable``, ``child_field`` and
            ``parent_field``, one row per matched key position of every
            foreign key defined on the table. Key positions where
            ``DD05S.FORKEY`` is blank are skipped: this happens when the
            check-table key position is compared against a fixed ABAP
            literal instead of a local field (``DD05S.FORTABLE`` holds
            something like ``'M'`` or ``*`` rather than ``SYST``/the table's
            own name in that case) — a conditional foreign key, not a real
            field-to-field join key, so keeping it would produce an
            unusable "join" with an empty column name.
        """
        fk_headers = self.connector.run_query(
            f"SELECT FIELDNAME, CHECKTABLE FROM {self._qualified('DD08L')} "
            f"WHERE TABNAME = :table_name",
            {"table_name": table_name},
        )
        if not fk_headers:
            return []
        checktable_by_field = {row["fieldname"].strip(): row["checktable"].strip() for row in fk_headers}

        fk_field_rows = self.connector.run_query(
            f"SELECT FIELDNAME, PRIMPOS, FORKEY FROM {self._qualified('DD05S')} "
            f"WHERE TABNAME = :table_name ORDER BY FIELDNAME, PRIMPOS",
            {"table_name": table_name},
        )
        child_fields_by_fk: dict[str, list[str]] = {}
        for row in fk_field_rows:
            fk_id = row["fieldname"].strip()
            child_fields_by_fk.setdefault(fk_id, []).append(row["forkey"].strip())

        parent_keys = self._fetch_ordered_key_fields(sorted(set(checktable_by_field.values())))

        results = []
        for fk_id, checktable in checktable_by_field.items():
            child_fields = child_fields_by_fk.get(fk_id, [])
            parent_fields = parent_keys.get(checktable, [])
            for child_field, parent_field in zip(child_fields, parent_fields):
                if not child_field:
                    continue
                results.append(
                    {"checktable": checktable, "child_field": child_field, "parent_field": parent_field}
                )
        return results

    def fetch_fixed_values(self, domnames: list[str]) -> dict[str, dict[str, str]]:
        """Fetches fixed-value maps for a batch of domains.

        Args:
            domnames: Distinct ``DOMNAME`` values to look up.

        Returns:
            A mapping of domain name to its ``{value: text}`` dict, in the
            configured language. Domains with no fixed values are absent.
        """
        if not domnames:
            return {}
        rows = self.connector.run_query(
            f"SELECT DOMNAME, DOMVALUE_L, DDTEXT FROM {self._qualified('DD07T')} "
            f"WHERE DDLANGUAGE = :language AND DOMNAME IN :domnames "
            f"ORDER BY DOMNAME, VALPOS",
            {"language": self.language, "domnames": tuple(domnames)},
        )
        result: dict[str, dict[str, str]] = {}
        for row in rows:
            domain = row["domname"].strip()
            result.setdefault(domain, {})[row["domvalue_l"].strip()] = row["ddtext"].strip()
        return result

    def fetch_field_texts(self, rollnames: list[str]) -> dict[str, str]:
        """Fetches business-friendly texts for a batch of data elements.

        Args:
            rollnames: Distinct ``ROLLNAME`` (data element) values to look up.

        Returns:
            A mapping of rollname to its description in the configured
            language. Rollnames with no matching text are simply absent.
        """
        if not rollnames:
            return {}
        rows = self.connector.run_query(
            f"SELECT ROLLNAME, DDTEXT FROM {self._qualified('DD04T')} "
            f"WHERE DDLANGUAGE = :language AND ROLLNAME IN :rollnames",
            {"language": self.language, "rollnames": tuple(rollnames)},
        )
        return {row["rollname"].strip(): row["ddtext"].strip() for row in rows}

    def table_exists(self, table_name: str) -> bool:
        """Checks whether a table name is a known DDIC object.

        Used to confirm a naming-convention candidate (e.g. ``{TABLE}T`` for
        a text table) actually exists before it is reported as related.

        Args:
            table_name: Candidate technical table name.

        Returns:
            ``True`` if the name exists in DD02L, ``False`` otherwise.
        """
        rows = self.connector.run_query(
            f"SELECT 1 AS found FROM {self._qualified('DD02L')} WHERE TABNAME = :table_name",
            {"table_name": table_name},
        )
        return bool(rows)

    def count_tables(self) -> int:
        """Counts distinct tables with a description text in the configured language.

        This is the same DD02T universe tiers (1) and (3) of `search` draw
        from, so it stays consistent with what search can actually surface.

        Returns:
            The total number of tables discoverable in the DDIC schema.
        """
        rows = self.connector.run_query(
            f"SELECT COUNT(*) AS total FROM {self._qualified('DD02T')} WHERE DDLANGUAGE = :language",
            {"language": self.language},
        )
        return int(rows[0]["total"]) if rows else 0

    def fetch_table_attributes(self, table_name: str) -> dict:
        """Fetches DD09L's data class and size category for a table.

        DD09L ("Further Attributes of a Table") is purely DDIC metadata, so
        — unlike a live row count from a runtime system view — it is
        available for any table this repository can describe, including one
        that exists only as a DDIC-defined view with no physical replicated
        data yet.

        Args:
            table_name: Technical table name.

        Returns:
            A dict with ``data_class`` (raw ``TABART``, e.g. ``"APPL0"`` for
            master data, ``"APPL1"`` for transaction data (header and item
            alike — BSEG/EKPO/VBAP are all APPL1), ``"APPL2"`` for
            configuration/customizing — blank if the table has none) and
            ``size_category`` (raw
            ``TABKAT``, SAP's coarse 0-9 expected-volume category set at
            table creation — ``"0"`` if absent). Both are defaulted via
            ``COALESCE`` rather than left null, since a missing DD09L row
            is routine for non-data-holding DDIC objects (structures,
            views) rather than an error condition.
        """
        rows = self.connector.run_query(
            f"SELECT COALESCE(D.TABART, '') AS data_class, COALESCE(D.TABKAT, '0') AS size_category "
            f"FROM {self._qualified('DD09L')} D WHERE D.TABNAME = :table_name",
            {"table_name": table_name},
        )
        if not rows:
            return {"data_class": "", "size_category": "0"}
        return {"data_class": rows[0]["data_class"].strip(), "size_category": rows[0]["size_category"].strip()}

    def search(self, term: str, limit: int = 15) -> list[dict]:
        """Searches tables by technical name prefix, business domain, description, or column.

        Four tiers, each only queried if the previous one didn't already
        fill the result limit: (1) prefix match on the technical name
        (index-friendly, ranked first), (2) business-domain synonym match
        against ``DD02L.APPLCLASS`` (see ``_BUSINESS_DOMAINS``) — this is what
        lets a term like "financeiro" surface ``BKPF``/``BSEG`` even though
        neither table's technical name nor DDTEXT contains that word, (3) a
        broad substring match on the description, as a last-resort fallback,
        (4) a match against a column's technical name (``DD03L.FIELDNAME``)
        or its business text (``DD04T.DDTEXT`` via ``ROLLNAME``), ranked
        lowest since a field-level hit is the most indirect signal — a
        table's own name/description is a stronger match than one of its
        columns coincidentally matching the term.

        Args:
            term: Normalized, already-escaped search term (see
                :class:`backend.security.InputValidator`).
            limit: Maximum number of results to return.

        Returns:
            A list of dicts with ``table_name`` and ``description``, ranked
            prefix-match first, capped at ``limit``. Results surfaced only
            via a column match also carry ``matched_field`` with the
            technical field name that matched.
        """
        prefix_rows = self.connector.run_query(
            f"SELECT TABNAME, DDTEXT FROM {self._qualified('DD02T')} "
            f"WHERE DDLANGUAGE = :language AND TABNAME LIKE :prefix ESCAPE '\\' "
            f"ORDER BY TABNAME LIMIT :limit",
            {"language": self.language, "prefix": f"{term}%", "limit": limit},
        )
        results = [{"table_name": r["tabname"], "description": r["ddtext"]} for r in prefix_rows]
        seen = {r["table_name"] for r in results}

        domain = _SYNONYM_TO_DOMAIN.get(term.upper())
        if domain and len(results) < limit:
            seed_tables = tuple(domain["seed_tables"])
            # Seed tables are ranked first, in the exact order they're
            # listed in seed_tables (the first one is the domain's "main"
            # table — see the note above _BUSINESS_DOMAINS), then
            # non-seed applclass hits fall back to shorter non-namespaced
            # names: classic SAP core tables (BKPF, BSEG, KNA1...) date back
            # to the original R/3 naming convention and are short, while
            # customer/partner namespaces ("/partner/...", "Y*", "Z*") and
            # add-on tables tend to be long and would otherwise crowd out
            # the tables actually meant to surface for a business-domain
            # search. seed_tables is always sourced from our own hardcoded
            # _BUSINESS_DOMAINS, never from user input, so splicing table
            # names into the CASE literal here is safe (same trust boundary
            # as `_qualified`'s schema/table interpolation).
            seed_rank_sql = " ".join(f"WHEN '{name}' THEN {index}" for index, name in enumerate(seed_tables))
            domain_rows = self.connector.run_query(
                f"SELECT L.TABNAME, T.DDTEXT "
                f"FROM {self._qualified('DD02L')} L "
                f"JOIN {self._qualified('DD02T')} T "
                f"  ON T.TABNAME = L.TABNAME AND T.DDLANGUAGE = :language "
                f"WHERE (L.TABNAME IN :seed_tables OR L.APPLCLASS IN :applclass_codes) "
                f"  AND L.TABNAME NOT LIKE '/%' "
                f"  AND L.TABNAME NOT LIKE 'Y%' "
                f"  AND L.TABNAME NOT LIKE 'Z%' "
                f"ORDER BY CASE L.TABNAME {seed_rank_sql} ELSE {len(seed_tables)} END, "
                f"  LENGTH(L.TABNAME) ASC, L.TABNAME ASC LIMIT :limit",
                {
                    "language": self.language,
                    "seed_tables": seed_tables,
                    "applclass_codes": tuple(domain["applclass_codes"]),
                    "limit": limit,
                },
            )
            for row in domain_rows:
                if row["tabname"] not in seen and len(results) < limit:
                    results.append({"table_name": row["tabname"], "description": row["ddtext"]})
                    seen.add(row["tabname"])

        contains = f"%{term.upper()}%"
        if len(results) < limit:
            fallback_rows = self.connector.run_query(
                f"SELECT TABNAME, DDTEXT FROM {self._qualified('DD02T')} "
                f"WHERE DDLANGUAGE = :language AND UPPER(DDTEXT) LIKE :contains ESCAPE '\\' "
                f"ORDER BY TABNAME LIMIT :limit",
                {"language": self.language, "contains": contains, "limit": limit},
            )
            for row in fallback_rows:
                if row["tabname"] not in seen and len(results) < limit:
                    results.append({"table_name": row["tabname"], "description": row["ddtext"]})
                    seen.add(row["tabname"])

        if len(results) < limit:
            # LEFT JOIN DD04T because not every field has a ROLLNAME/text —
            # a field can match purely on FIELDNAME with no business text at
            # all. Filtering out structural include markers (FIELDNAME
            # starting with '.') before the join matters here, unlike in
            # fetch_columns, since this scans all of DD03L rather than one
            # table's rows.
            column_rows = self.connector.run_query(
                f"SELECT F.FIELDNAME, L.TABNAME, T.DDTEXT "
                f"FROM {self._qualified('DD03L')} F "
                f"JOIN {self._qualified('DD02L')} L ON L.TABNAME = F.TABNAME "
                f"JOIN {self._qualified('DD02T')} T ON T.TABNAME = L.TABNAME AND T.DDLANGUAGE = :language "
                f"LEFT JOIN {self._qualified('DD04T')} E ON E.ROLLNAME = F.ROLLNAME AND E.DDLANGUAGE = :language "
                f"WHERE F.FIELDNAME NOT LIKE '.%' "
                f"  AND (F.FIELDNAME LIKE :contains ESCAPE '\\' OR UPPER(E.DDTEXT) LIKE :contains ESCAPE '\\') "
                f"ORDER BY L.TABNAME, F.FIELDNAME LIMIT :limit",
                {"language": self.language, "contains": contains, "limit": limit},
            )
            for row in column_rows:
                if row["tabname"] not in seen and len(results) < limit:
                    results.append(
                        {
                            "table_name": row["tabname"],
                            "description": row["ddtext"],
                            "matched_field": row["fieldname"],
                        }
                    )
                    seen.add(row["tabname"])

        return results

    def fetch_tcode_header(self, tcode: str) -> dict | None:
        """Fetches TSTC/TADIR header attributes for a transaction code.

        ``TADIR`` is joined with a fixed ``PGMID='R3TR' AND OBJECT='TRAN'``
        filter to isolate the object-directory entry for this specific tcode
        (as opposed to any other object sharing the same name in a different
        object type). The join is a LEFT JOIN because not every entry in
        ``TSTC`` has a matching ``TADIR`` row (e.g. some parameter
        transactions), in which case package/creation-date default to blank.

        Args:
            tcode: Technical transaction code, already validated upstream.

        Returns:
            A dict with ``pgmna``, ``dypno``, ``devclass`` and
            ``created_on`` (the latter two blank if no TADIR entry exists),
            or ``None`` if the tcode does not exist in TSTC. ``created_on``
            is used as this tcode's cache-freshness value, in place of
            DD02L's ``AS4DATE`` (TADIR has no AS4DATE/AS4TIME in this
            replica, unlike the standard SAP field set).
        """
        rows = self.connector.run_query(
            f"SELECT S.PGMNA, S.DYPNO, D.DEVCLASS, D.CREATED_ON "
            f"FROM {self._qualified('TSTC')} S "
            f"LEFT JOIN {self._qualified('TADIR')} D "
            f"  ON D.PGMID = 'R3TR' AND D.OBJECT = 'TRAN' AND D.OBJ_NAME = S.TCODE "
            f"WHERE S.TCODE = :tcode",
            {"tcode": tcode},
        )
        if not rows:
            return None

        row = rows[0]
        return {
            "pgmna": row["pgmna"].strip(),
            "dypno": row["dypno"].strip(),
            "devclass": (row["devclass"] or "").strip(),
            "created_on": (row["created_on"] or "").strip(),
        }

    def fetch_tcode_text(self, tcode: str) -> str:
        """Fetches the business description of a transaction code.

        Args:
            tcode: Technical transaction code.

        Returns:
            The description text for the configured language, falling back
            to the tcode itself if no text exists in that language.
        """
        rows = self.connector.run_query(
            f"SELECT TTEXT FROM {self._qualified('TSTCT')} "
            f"WHERE TCODE = :tcode AND SPRSL = :language",
            {"tcode": tcode, "language": self.language},
        )
        return rows[0]["ttext"].strip() if rows else tcode

    def search_tcodes(self, term: str, limit: int = 15) -> list[dict]:
        """Searches transaction codes by technical code prefix or description.

        Two tiers, mirroring :meth:`search`: (1) prefix match on the
        technical tcode (index-friendly, ranked first), (2) a substring
        match on the description text, as a fallback once the prefix tier
        is exhausted.

        Args:
            term: Normalized, already-escaped search term (see
                :class:`backend.security.InputValidator`).
            limit: Maximum number of results to return.

        Returns:
            A list of dicts with ``tcode`` and ``description``, ranked
            prefix-match first, capped at ``limit``.
        """
        prefix_rows = self.connector.run_query(
            f"SELECT S.TCODE, T.TTEXT "
            f"FROM {self._qualified('TSTC')} S "
            f"LEFT JOIN {self._qualified('TSTCT')} T ON T.TCODE = S.TCODE AND T.SPRSL = :language "
            f"WHERE S.TCODE LIKE :prefix ESCAPE '\\' "
            f"ORDER BY S.TCODE LIMIT :limit",
            {"language": self.language, "prefix": f"{term}%", "limit": limit},
        )
        results = [
            {"tcode": r["tcode"], "description": (r["ttext"] or r["tcode"]).strip()} for r in prefix_rows
        ]
        seen = {r["tcode"] for r in results}

        if len(results) < limit:
            contains = f"%{term.upper()}%"
            fallback_rows = self.connector.run_query(
                f"SELECT S.TCODE, T.TTEXT "
                f"FROM {self._qualified('TSTCT')} T "
                f"JOIN {self._qualified('TSTC')} S ON S.TCODE = T.TCODE "
                f"WHERE T.SPRSL = :language AND UPPER(T.TTEXT) LIKE :contains ESCAPE '\\' "
                f"ORDER BY S.TCODE LIMIT :limit",
                {"language": self.language, "contains": contains, "limit": limit},
            )
            for row in fallback_rows:
                if row["tcode"] not in seen and len(results) < limit:
                    results.append({"tcode": row["tcode"], "description": row["ttext"].strip()})
                    seen.add(row["tcode"])

        return results
