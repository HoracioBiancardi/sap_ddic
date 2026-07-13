"""Local JSON cache for table metadata contracts.

Cache freshness is decided by comparing the SAP DDIC object's own
``AS4DATE`` (last-changed date, stored as a zero-padded ``YYYYMMDD`` string
and therefore directly comparable lexicographically) against the value
recorded when the cache entry was written, instead of a fixed wall-clock
TTL. This avoids serving a week-old cache for a table that changed today,
and avoids needless re-extraction for tables that never change.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class MetadataCache:
    """Reads and writes per-table JSON cache files with AS4DATE-based invalidation.

    Attributes:
        cache_dir: Directory where one JSON file per table is stored.
    """

    def __init__(self, cache_dir: Path) -> None:
        """Initializes the cache and ensures its directory exists.

        Args:
            cache_dir: Directory where cache files are stored, created if
                missing.
        """
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, table_name: str) -> Path:
        """Builds the cache file path for a table.

        Args:
            table_name: Technical table name, already validated upstream by
                :class:`backend.security.InputValidator` against a strict
                DDIC object-name regex before reaching this method.

        Returns:
            The path ``{cache_dir}/{table_name}.json``. A namespaced SAP
            object name (e.g. ``/BIC/AZCUSTOMER``) has its ``/`` replaced
            with ``_`` first: a leading ``/`` would otherwise make
            ``Path.__truediv__`` discard ``cache_dir`` entirely and treat
            the rest as an absolute path, and a mid-string ``/`` would
            silently nest the file in a subdirectory that was never created.
        """
        safe_name = table_name.replace("/", "_")
        return self.cache_dir / f"{safe_name}.json"

    def read(self, table_name: str) -> dict[str, Any] | None:
        """Reads a cache entry from disk, if present and well-formed.

        Args:
            table_name: Technical table name.

        Returns:
            The cache envelope (``{"as4date": ..., "cached_at": ..., "payload": ...}``)
            or ``None`` if the file does not exist or is corrupted.
        """
        path = self._path_for(table_name)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def is_valid(self, cached: dict[str, Any], current_as4date: str) -> bool:
        """Checks whether a cache entry is still fresh.

        Args:
            cached: The cache envelope previously returned by :meth:`read`.
            current_as4date: The table's current ``AS4DATE`` as read live
                from DD02L.

        Returns:
            ``True`` if the cached ``as4date`` matches the current one.
        """
        return cached.get("as4date") == current_as4date

    def write(self, table_name: str, contract: dict[str, Any], as4date: str) -> None:
        """Writes a cache entry atomically.

        Args:
            table_name: Technical table name.
            contract: The JSON-serializable contract payload to cache.
            as4date: The table's ``AS4DATE`` at the time of extraction, used
                for future freshness comparisons.
        """
        envelope = {
            "as4date": as4date,
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "payload": contract,
        }
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._path_for(table_name)
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, path)
