"""FastAPI application entrypoint for the SAP Metadata Discovery Web App.

Wires the :class:`~sap_ddic.service.MetadataService` up at startup and
mounts each domain's routes from :mod:`sap_ddic.routers` (search, tables,
tcode, mart, system), all validated through
:class:`sap_ddic.security.InputValidator` inside those routers, and serves
the static vanilla-JS frontend from ``sap_ddic/frontend/`` at ``/``. Serving
both from the same FastAPI process means the browser never crosses origins,
so no CORS configuration is needed.
"""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from sap_ddic.cache import MetadataCache
from sap_ddic.config import get_settings
from sap_ddic.connection import DatasphereConnector
from sap_ddic.ddic_repository import DDICRepository
from sap_ddic.heuristics import TableClassifier
from sap_ddic.routers import mart, search, system, tables, tcode
from sap_ddic.service import MetadataService

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

app.include_router(search.router)
app.include_router(tables.router)
app.include_router(tcode.router)
app.include_router(mart.router)
app.include_router(system.router)

_FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"

app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")


def run() -> None:
    """Launches the development server (entrypoint for ``uv run ddic``).

    Binds to ``127.0.0.1:8000`` with auto-reload enabled, equivalent to
    running ``uvicorn sap_ddic.main:app --reload`` directly.
    """
    import uvicorn

    uvicorn.run("sap_ddic.main:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    run()
