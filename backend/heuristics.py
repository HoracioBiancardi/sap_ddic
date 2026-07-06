"""Business classification heuristics for SAP DDIC tables.

Every method in :class:`TableClassifier` is a pure function of its inputs —
no database access, no I/O — so the classification rules can be unit tested
with plain fixtures. The rules refine the naive "one primary key means
master data" approach with two corrections learned from real SAP tables:

* Tables with an organizational segmentation key (e.g. ``MARC`` keyed by
  ``MATNR`` + ``WERKS``) are still Master Data, not Transactional.
* A single-key table can still be a document (e.g. ``VBAK`` keyed only by
  ``VBELN``) and must be classified as Transactional despite having one key.
"""

import re

ORG_SEGMENT_FIELDS: frozenset[str] = frozenset(
    {
        "WERKS",
        "VKORG",
        "BUKRS",
        "VTWEG",
        "SPART",
        "KOKRS",
        "BWKEY",
        "LGORT",
        "VKBUR",
        "VKGRP",
        "EKORG",
        "WERKS_S",
    }
)

_DOC_KEY_SUFFIX_RE = re.compile(r"(POSNR|EBELP|ITEM\d*|ZEILE|BELNR|MBLNR|EBELN|VBELN|AUFNR|BUZEI)$")

# Narrower than _DOC_KEY_SUFFIX_RE: only true line/position-within-document
# indicators. BELNR/MBLNR/EBELN/VBELN/AUFNR identify *which* document a
# record belongs to (a header trait — e.g. BKPF is keyed by BUKRS+BELNR+GJAHR
# and is unambiguously a header, not an item) whereas POSNR/EBELP/ZEILE/BUZEI
# identify *which line* within that document (the genuine item trait — e.g.
# BSEG adds BUZEI on top of BELNR). Using the broader pattern for hierarchy
# classification mis-tagged header tables like BKPF as "Item / Filha" simply
# because their key includes a document-number field.
_ITEM_POSITION_RE = re.compile(r"(POSNR|EBELP|ITEM\d*|ZEILE|BUZEI)$")

_CONTFLAG_BUCKETS: dict[str, str] = {
    "C": "configuration",
    "G": "configuration",
    "E": "configuration",
    "A": "business",
    "L": "temporary_local",
    "S": "system",
    "W": "system",
}

# Well-known SAP "last changed" timestamp fields. Their presence is a
# structural (DDIC-only) signal that a table's own record-changed-on value
# could support incremental/delta extraction — as opposed to genuine
# operational proof that delta capture is configured in the replication
# tool, which this repository has no reliable per-table source for (see
# backend/ddic_repository.py module docstring). Deliberately conservative:
# a table with none of these fields is not necessarily full-load-only, it
# just has no field this heuristic recognizes.
_INCREMENTAL_CANDIDATE_FIELDS: frozenset[str] = frozenset({"AEDAT", "LAEDA", "UPDDA", "CPUDT"})


class TableClassifier:
    """Infers business metadata for a DDIC table from its raw attributes.

    All methods are stateless and side-effect free, taking plain DDIC field
    data (dicts/lists as returned by :class:`backend.ddic_repository.DDICRepository`)
    and returning the classification strings used in the JSON contract.
    """

    @staticmethod
    def bucket_contflag(contflag: str) -> str:
        """Buckets a raw DD02L ``CONTFLAG`` (delivery class) value.

        Args:
            contflag: Raw one-letter delivery class from DD02L.

        Returns:
            One of ``"configuration"``, ``"business"``,
            ``"temporary_local"``, ``"system"`` or ``"unknown"``.
        """
        return _CONTFLAG_BUCKETS.get(contflag.strip().upper(), "unknown")

    @staticmethod
    def _is_document_key(field_name: str) -> bool:
        """Checks whether a field name looks like a document/position key.

        Args:
            field_name: Technical field name to test.

        Returns:
            ``True`` if the name matches a known document/position suffix
            pattern (e.g. ``VBELN``, ``POSNR``, ``EBELP``).
        """
        return bool(_DOC_KEY_SUFFIX_RE.search(field_name.strip().upper()))

    @staticmethod
    def _is_item_position_key(field_name: str) -> bool:
        """Checks whether a field name looks like a line/position indicator.

        Args:
            field_name: Technical field name to test.

        Returns:
            ``True`` if the name matches a genuine item/position pattern
            (e.g. ``POSNR``, ``BUZEI``) as opposed to a document-number
            field (e.g. ``BELNR``), which identifies the document itself,
            not a line within it.
        """
        return bool(_ITEM_POSITION_RE.search(field_name.strip().upper()))

    @classmethod
    def classify_table_type(cls, contflag: str, key_fields: list[str]) -> str:
        """Classifies a table as Master Data, Transactional or Configuration.

        Args:
            contflag: Raw DD02L delivery class (``CONTFLAG``).
            key_fields: Primary key field names, excluding ``MANDT``.

        Returns:
            One of ``"Configuration"``, ``"Master Data"``, ``"Transactional"``
            or ``"Unknown"``.
        """
        bucket = cls.bucket_contflag(contflag)
        if bucket == "configuration":
            return "Configuration"
        if bucket in ("temporary_local", "system", "unknown"):
            return "Unknown"

        non_mandt_keys = [f for f in key_fields if f.strip().upper() != "MANDT"]

        if len(non_mandt_keys) == 1:
            return "Transactional" if cls._is_document_key(non_mandt_keys[0]) else "Master Data"

        extra_keys = non_mandt_keys[1:]
        if extra_keys and all(k.strip().upper() in ORG_SEGMENT_FIELDS for k in extra_keys):
            return "Master Data"

        if any(cls._is_document_key(k) for k in non_mandt_keys):
            return "Transactional"

        return "Transactional"

    @classmethod
    def classify_hierarchy_type(cls, table_type: str, key_fields: list[str]) -> str:
        """Classifies a table's position in a header/item hierarchy.

        Uses the already-computed ``table_type`` rather than a generic
        "has any check-table reference" signal: virtually every master data
        table has at least one attribute-level foreign key (unit of
        measure, material type, currency...), so that signal cannot
        distinguish a true document header from a standalone master record.
        ``table_type`` (Master Data vs. Transactional) is a much cleaner
        proxy given the data actually available (see module docstring on
        DD05S/DD08L not being replicated).

        Args:
            table_type: Result of :meth:`classify_table_type` for this table.
            key_fields: Primary key field names, excluding ``MANDT``.

        Returns:
            One of ``"Item / Filha"``, ``"Standalone / Mestre"`` or
            ``"Header / Cabeçalho"``.
        """
        non_mandt_keys = [f for f in key_fields if f.strip().upper() != "MANDT"]

        if any(cls._is_item_position_key(k) for k in non_mandt_keys[1:]):
            return "Item / Filha"

        if table_type == "Master Data":
            return "Standalone / Mestre"

        return "Header / Cabeçalho"

    @staticmethod
    def compute_record_footprint(columns: list[dict]) -> dict:
        """Computes a table's structural size from its own DDIC field lengths.

        Purely DDIC-derived (sum of ``DD03L.LENG``), so it works for any
        table this repository can describe — including one that exists only
        as a DDIC-defined view and has no physical replicated data yet.
        This is a structural footprint (bytes per record), not a live row
        count: DDIC's own volume-estimate fields (``DD02L.DATMIN``/
        ``DATMAX``/``DATAVG``) are only populated for custom Z-tables whose
        developer set a size category at creation time — for standard
        SAP-delivered tables they are consistently blank in this system, so
        they cannot be relied on for an actual record count.

        Args:
            columns: Column dicts as returned by
                :meth:`backend.ddic_repository.DDICRepository.fetch_columns`.

        Returns:
            A dict with ``field_count``, ``record_length_bytes`` (sum of all
            fields' ``length``) and ``key_length_bytes`` (sum of primary key
            fields' ``length``).
        """
        return {
            "field_count": len(columns),
            "record_length_bytes": sum(c["length"] for c in columns),
            "key_length_bytes": sum(c["length"] for c in columns if c["is_primary_key"]),
        }

    @classmethod
    def find_incremental_candidate_fields(cls, column_names: list[str]) -> list[str]:
        """Finds fields that could support incremental/delta extraction.

        Args:
            column_names: All field names of the table.

        Returns:
            The subset of ``column_names`` matching a well-known "last
            changed" timestamp field (e.g. ``AEDAT``, ``LAEDA``), preserving
            input order. Empty if none are present — this means the
            heuristic found no candidate, not that the table is confirmed
            full-load-only.
        """
        return [c for c in column_names if c.strip().upper() in _INCREMENTAL_CANDIDATE_FIELDS]

    @staticmethod
    def find_associated_text_table(table_name: str, candidate_names: set[str]) -> str | None:
        """Finds the table's text table by naming convention.

        Args:
            table_name: Technical name of the table being described.
            candidate_names: Set of table names known to exist (typically
                the check tables referenced by this table's own fields, plus
                the ``{table_name}T`` naming candidate), used to confirm a
                candidate is a real DDIC object before claiming it.

        Returns:
            The text table's technical name if ``{table_name}T`` exists in
            ``candidate_names``, otherwise ``None``.
        """
        candidate = f"{table_name.strip().upper()}T"
        return candidate if candidate in candidate_names else None

    # A Configuration-class table with a DD09L size category at or above this
    # threshold (per the documented TABKAT ceilings — category 3 tops out at
    # ~650,000 rows, see frontend/js/render.js SIZE_CATEGORY_RANGES) is
    # substantial enough to rank as "Média" rather than "Baixa" — e.g.
    # J_1BTANP sits at category 4 (~2.5M rows ceiling), the same as MARA
    # itself, while a typical tiny lookup like T006 sits at 0 (~10,000 rows).
    _SUBSTANTIAL_SIZE_CATEGORY_THRESHOLD = 3

    @classmethod
    def classify_relationship_importance(cls, parent_contflag: str, parent_size_category: str = "0") -> str:
        """Ranks a parent-table relationship's relevance for the lineage graph.

        A check table that is itself business data (CONTFLAG ``A``, e.g.
        ``LFA1`` vendor master, or a table referencing itself like ``MARA``)
        represents a real entity relationship and always ranks ``"Alta"``.
        Otherwise the table is a domain/value-help lookup, but not all
        lookups are equally minor: one with a substantial DD09L size
        category ranks ``"Média"``, while a small/tiny one ranks ``"Baixa"``.

        Args:
            parent_contflag: Raw DD02L delivery class of the parent/check
                table (not the described table's own CONTFLAG).
            parent_size_category: Raw DD09L ``TABKAT`` of the parent table
                (``"0"`` if unknown).

        Returns:
            ``"Alta"``, ``"Média"`` or ``"Baixa"``.
        """
        if cls.bucket_contflag(parent_contflag) == "business":
            return "Alta"
        try:
            size = int(parent_size_category)
        except ValueError:
            size = 0
        return "Média" if size >= cls._SUBSTANTIAL_SIZE_CATEGORY_THRESHOLD else "Baixa"

    @classmethod
    def build_parent_tables(
        cls,
        foreign_key_rows: list[dict[str, str]],
        parent_classes: dict[str, dict[str, str]] | None = None,
    ) -> list[dict]:
        """Groups field-level foreign key rows into parent table entries.

        Args:
            foreign_key_rows: Rows shaped like
                ``{"checktable": ..., "child_field": ..., "parent_field": ...}``,
                as returned by
                :meth:`backend.ddic_repository.DDICRepository.fetch_foreign_keys`
                — one row per matched key position of every foreign key
                defined on the described table.
            parent_classes: Mapping of parent table name to
                ``{"contflag": ..., "size_category": ...}``, as returned by
                :meth:`backend.ddic_repository.DDICRepository.fetch_table_classes`,
                used to set ``importance``. Tables absent from this mapping
                default to ``"Baixa"``.

        Returns:
            A list of dicts shaped like the ``ParentTable`` schema, one per
            distinct check table referenced, each tagged with an
            ``importance`` of ``"Alta"``, ``"Média"`` or ``"Baixa"``.
        """
        parent_classes = parent_classes or {}
        grouped: dict[str, list[dict[str, str]]] = {}
        for row in foreign_key_rows:
            checktable = row["checktable"].strip().upper()
            if not checktable:
                continue
            grouped.setdefault(checktable, []).append(
                {"child_field": row["child_field"], "parent_field": row["parent_field"]}
            )

        return [
            {
                "parent_table_name": parent_table_name,
                "relationship_type": "Check Table",
                "importance": cls.classify_relationship_importance(
                    parent_classes.get(parent_table_name, {}).get("contflag", ""),
                    parent_classes.get(parent_table_name, {}).get("size_category", "0"),
                ),
                "foreign_key_fields": fk_fields,
            }
            for parent_table_name, fk_fields in grouped.items()
        ]
