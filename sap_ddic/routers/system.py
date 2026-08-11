"""Health check and live log console endpoints for the dashboard's system panel."""

import time

from fastapi import APIRouter, Query

from sap_ddic.config import get_settings
from sap_ddic.logger import get_log_buffer

router = APIRouter(prefix="/api/system", tags=["system"])

_START_TIME = time.time()


@router.get("/health")
def health_check() -> dict:
    """Reports process liveness and uptime for the topbar connection badge.

    Returns:
        A status payload with the current uptime in seconds.
    """
    return {"status": "ok", "uptime_seconds": round(time.time() - _START_TIME, 2)}


@router.get("/metrics")
def get_metrics() -> dict:
    """Reports non-sensitive operational settings alongside process uptime.

    Returns:
        A payload with uptime, the target DDIC schema/language and the
        configured log level — never the HANA host or credentials.
    """
    settings = get_settings()
    return {
        "uptime_seconds": round(time.time() - _START_TIME, 2),
        "app_name": "SAP Metadata Discovery API",
        "ddic_schema": settings.ddic_schema,
        "ddic_language": settings.ddic_language,
        "log_level": settings.log_level,
    }


@router.get("/logs")
def get_system_logs(
    limit: int = Query(100, ge=1, le=500),
    level: str | None = None,
    search: str | None = None,
) -> dict:
    """Returns recent entries from the in-memory log ring buffer.

    Args:
        limit: Maximum number of entries to return.
        level: If given, only entries at this exact log level.
        search: If given, only entries whose message or source matches.

    Returns:
        A payload with the matching log entries, oldest first.
    """
    return {"logs": get_log_buffer().get_logs(limit=limit, level=level, search=search)}


@router.post("/logs/clear")
def clear_system_logs() -> dict:
    """Empties the in-memory log ring buffer.

    Returns:
        A confirmation status payload.
    """
    get_log_buffer().clear()
    return {"status": "ok"}
