"""Application-wide logging configuration.

Provides a single cached logger factory so every module logs through the
same configured handler, honoring the ``LOG_LEVEL``/``LOG_TO_JSON``/
``LOG_PATH`` settings from :mod:`backend.config`.
"""

import json
import logging
from functools import lru_cache
from pathlib import Path


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

    Reads configuration lazily (rather than importing :mod:`backend.config`
    eagerly) to avoid a circular import, since ``config`` does not depend on
    ``logger`` and callers may want a logger before settings are validated.

    Returns:
        A configured :class:`logging.Logger` instance, memoized so handlers
        are only attached once per process.
    """
    from backend.config import get_settings

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
    logger.propagate = False
    return logger
