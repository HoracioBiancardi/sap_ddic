"""Orchestration layer wiring the repository, classifier and cache together.

:class:`MetadataService` is the only component :mod:`backend.main` talks to:
it resolves a table name into the full JSON contract, transparently
consulting and refreshing the local cache, and turns a search term into a
ranked list of table matches.
"""

from typing import Any

from fastapi import HTTPException

from backend.cache import MetadataCache
from backend.ddic_repository import DDICRepository
from backend.heuristics import TableClassifier


class MetadataService:
    """Builds table metadata contracts and search results for the API layer.

    Attributes:
        repository: Read-only access to the replicated DDIC tables.
        classifier: Pure business-classification heuristics.
        cache: Local JSON cache keyed by table name, invalidated by AS4DATE.
    """

    def __init__(
        self,
        repository: DDICRepository,
        classifier: TableClassifier,
        cache: MetadataCache,
    ) -> None:
        """Initializes the service with its collaborators.

        Args:
            repository: Read-only access to the replicated DDIC tables.
            classifier: Pure business-classification heuristics.
            cache: Local JSON cache keyed by table name.
        """
        self.repository = repository
        self.classifier = classifier
        self.cache = cache

    def search_tables(self, term: str) -> list[dict[str, str]]:
        """Searches for tables by technical name prefix or description.

        Args:
            term: Normalized, LIKE-escaped search term (see
                :class:`backend.security.InputValidator.validate_search_term`).

        Returns:
            A list of ``{"table_name": ..., "description": ...}`` dicts,
            ranked with technical-name prefix matches first, capped at 15.
        """
        return self.repository.search(term)

    def get_table_contract(self, table_name: str) -> dict[str, Any]:
        """Builds (or reuses from cache) the full metadata contract for a table.

        Args:
            table_name: Normalized technical table name (see
                :class:`backend.security.InputValidator.validate_table_name`).

        Returns:
            A dict matching the :class:`backend.schemas.TableContract` shape.

        Raises:
            HTTPException: With status 404 if the table does not exist in
                the replicated DD02L.
        """
        header = self.repository.fetch_header(table_name)
        if header is None:
            raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found.")

        cached = self.cache.read(table_name)
        if cached is not None and self.cache.is_valid(cached, header["as4date"]):
            return cached["payload"]

        contract = self._build_contract(table_name, header)
        self.cache.write(table_name, contract, header["as4date"])
        return contract

    def _build_contract(self, table_name: str, header: dict[str, Any]) -> dict[str, Any]:
        """Assembles the full contract from live DDIC data.

        Args:
            table_name: Normalized technical table name.
            header: Result of :meth:`DDICRepository.fetch_header`.

        Returns:
            A dict matching the :class:`backend.schemas.TableContract` shape.
        """
        raw_columns = self.repository.fetch_columns(table_name)
        key_fields = [c["column_name"] for c in raw_columns if c["is_primary_key"]]

        rollnames = sorted({c["rollname"] for c in raw_columns if c["rollname"]})
        field_texts = self.repository.fetch_field_texts(rollnames)

        domnames = sorted({c["domain_name"] for c in raw_columns if c["domain_name"]})
        fixed_values = self.repository.fetch_fixed_values(domnames)

        columns = [
            {
                "column_name": c["column_name"],
                "is_primary_key": c["is_primary_key"],
                "data_type": c["data_type"],
                "length": c["length"],
                "decimals": c["decimals"],
                "business_description": field_texts.get(c["rollname"], c["column_name"]),
                "domain_name": c["domain_name"],
                "has_fixed_values": c["domain_name"] in fixed_values,
                "fixed_values_map": fixed_values.get(c["domain_name"], {}),
            }
            for c in raw_columns
        ]

        foreign_key_rows = self.repository.fetch_foreign_keys(table_name)
        parent_table_names = sorted({row["checktable"] for row in foreign_key_rows if row["checktable"]})
        parent_classes = self.repository.fetch_table_classes(parent_table_names)
        parent_tables = self.classifier.build_parent_tables(foreign_key_rows, parent_classes)

        text_table_candidate = f"{table_name}T"
        candidate_names = (
            {text_table_candidate} if self.repository.table_exists(text_table_candidate) else set()
        )
        associated_text_table = self.classifier.find_associated_text_table(
            table_name, candidate_names
        )

        table_type = self.classifier.classify_table_type(header["contflag"], key_fields)
        hierarchy_type = self.classifier.classify_hierarchy_type(table_type, key_fields)

        business_description = self.repository.fetch_description(table_name)
        if self.classifier.bucket_contflag(header["contflag"]) == "temporary_local":
            business_description = f"[Tabela de Trabalho Temporária] {business_description}"
        elif self.classifier.bucket_contflag(header["contflag"]) == "system":
            business_description = f"[Tabela de Sistema] {business_description}"

        footprint = self.classifier.compute_record_footprint(raw_columns)
        incremental_candidates = self.classifier.find_incremental_candidate_fields(
            [c["column_name"] for c in raw_columns]
        )
        table_attributes = self.repository.fetch_table_attributes(table_name)
        technical_stats = {
            **footprint,
            **table_attributes,
            "incremental_candidate_fields": incremental_candidates,
            "supports_incremental_load": bool(incremental_candidates),
        }

        return {
            "table_name": table_name,
            "business_description": business_description,
            "technical_class": header["tabclass"],
            "table_type": table_type,
            "hierarchy_type": hierarchy_type,
            "associated_text_table": associated_text_table,
            "parent_tables": parent_tables,
            "columns": columns,
            "technical_stats": technical_stats,
        }
