"""Application-wide logging configuration.

Provides a single cached logger factory so every module logs through the
same configured handler, honoring the ``LOG_LEVEL``/``LOG_TO_JSON``/
``LOG_PATH`` settings from :mod:`sap_ddic.config`.
"""

import json
import logging
import time
from collections import deque
from functools import lru_cache
from pathlib import Path
from typing import Any


class BufferHandler(logging.Handler):
    """Keeps the last ``maxlen`` log records in memory for live viewing.

    Attached alongside the file/stream handler in :func:`get_logger`, so
    every ``logger.info/warning/error`` call already made throughout the
    app (``cache.py``, ``service.py``, ``ddic_repository.py``,
    ``connection.py``, etc.) feeds this buffer automatically — the system
    dashboard's log panel needs no separate instrumentation.
    """

    def __init__(self, maxlen: int = 500) -> None:
        super().__init__()
        self._buffer: deque[dict[str, Any]] = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        """Appends a formatted entry for ``record`` to the ring buffer.

        Args:
            record: The log record emitted by the logging framework.
        """
        self._buffer.append(
            {
                "timestamp": record.created,
                "time_str": time.strftime("%H:%M:%S", time.localtime(record.created)),
                "level": record.levelname,
                "source": record.name,
                "message": record.getMessage(),
            }
        )

    def get_logs(self, limit: int = 100, level: str | None = None, search: str | None = None) -> list[dict[str, Any]]:
        """Returns the most recent buffered entries, optionally filtered.

        Args:
            limit: Maximum number of entries to return (most recent last).
            level: If given, only entries with this exact level name (case-insensitive).
            search: If given, only entries whose message or source contains this substring (case-insensitive).

        Returns:
            Up to ``limit`` log entries, oldest first.
        """
        entries = list(self._buffer)
        if level:
            level_upper = level.upper()
            entries = [entry for entry in entries if entry["level"] == level_upper]
        if search:
            needle = search.lower()
            entries = [
                entry for entry in entries if needle in entry["message"].lower() or needle in entry["source"].lower()
            ]
        return entries[-limit:]

    def clear(self) -> None:
        """Empties the ring buffer."""
        self._buffer.clear()


class _JsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        """Serializes a log record to a JSON string.

        Args:
            record: The log record emitted by the logging framework.

        Returns:
            A JSON-encoded string representing the record's level, logger
            name, message and timestamp.
        """
        payload = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        return json.dumps(payload, ensure_ascii=False)


@lru_cache
def get_logger() -> logging.Logger:
    """Returns the process-wide application logger.

    Reads configuration lazily (rather than importing :mod:`sap_ddic.config`
    eagerly) to avoid a circular import, since ``config`` does not depend on
    ``logger`` and callers may want a logger before settings are validated.

    Returns:
        A configured :class:`logging.Logger` instance, memoized so handlers
        are only attached once per process.
    """
    from sap_ddic.config import get_settings

    settings = get_settings()
    logger = logging.getLogger("sap_ddic")
    logger.setLevel(settings.log_level.upper())

    log_path = Path(settings.log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    handler: logging.Handler
    if settings.log_to_json:
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(_JsonFormatter())
    else:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))

    logger.addHandler(handler)
    logger.addHandler(get_log_buffer())
    logger.propagate = False
    return logger


@lru_cache
def get_log_buffer() -> BufferHandler:
    """Returns the process-wide in-memory log ring buffer.

    Memoized separately from :func:`get_logger` (though attached to it as a
    handler) so :mod:`sap_ddic.routers.system` can read/clear it without
    reaching into the logger's handler list.

    Returns:
        The shared :class:`BufferHandler` instance.
    """
    return BufferHandler()
