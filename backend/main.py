"""FastAPI application entrypoint for the SAP Metadata Discovery Web App.

Exposes ``GET /api/search`` and ``GET /api/table/{table_name}``, both
validated through :class:`backend.security.InputValidator`, and serves the
static vanilla-JS frontend from ``frontend/`` at ``/``. Serving both from the
same FastAPI process means the browser never crosses origins, so no CORS
configuration is needed.
"""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from backend.cache import MetadataCache
from backend.config import get_settings
from backend.connection import DatasphereConnector
from backend.ddic_repository import DDICRepository
from backend.heuristics import TableClassifier
from backend.schemas import SearchResult, TableContract
from backend.security import InputValidator
from backend.service import MetadataService

_CACHE_DIR = Path("cache")


def _build_service() -> MetadataService:
    """Wires up a MetadataService from application settings.

    Returns:
        A ready-to-use :class:`MetadataService` instance backed by a live
        HANA connection, the DDIC repository, the heuristics classifier and
        the local JSON cache.
    """
    settings = get_settings()
    connector = DatasphereConnector(settings)
    repository = DDICRepository(connector, settings.ddic_schema, settings.ddic_language)
    return MetadataService(repository, TableClassifier(), MetadataCache(_CACHE_DIR))


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initializes the MetadataService once at startup, failing fast on bad config.

    Args:
        app: The FastAPI application instance.

    Yields:
        Control back to FastAPI once the service is ready.
    """
    app.state.service = _build_service()
    yield


app = FastAPI(title="SAP Metadata Discovery API", lifespan=_lifespan)


def _get_service() -> MetadataService:
    """FastAPI dependency returning the process-wide MetadataService.

    Returns:
        The :class:`MetadataService` instance created at startup.
    """
    return app.state.service


@app.get("/api/search", response_model=list[SearchResult])
def search(
    q: str = Depends(InputValidator.validate_search_term),
    service: MetadataService = Depends(_get_service),
) -> list[dict[str, str]]:
    """Searches for SAP tables by technical name prefix or description.

    Args:
        q: Validated, LIKE-escaped search term.
        service: Injected metadata service.

    Returns:
        Up to 15 matching tables, technical-name prefix matches first.
    """
    return service.search_tables(q)


@app.get("/api/table/{table_name}", response_model=TableContract)
def get_table(
    table_name: str = Depends(InputValidator.validate_table_name),
    service: MetadataService = Depends(_get_service),
) -> dict:
    """Returns the full metadata contract for a single SAP table.

    Args:
        table_name: Validated, normalized technical table name.
        service: Injected metadata service.

    Returns:
        The table's metadata contract, served from cache when still fresh.
    """
    return service.get_table_contract(table_name)


app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")


def run() -> None:
    """Launches the development server (entrypoint for ``uv run ddic``).

    Binds to ``127.0.0.1:8000`` with auto-reload enabled, equivalent to
    running ``uvicorn backend.main:app --reload`` directly.
    """
    import uvicorn

    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    run()
