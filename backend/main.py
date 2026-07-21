"""FastAPI application entrypoint for the SAP Metadata Discovery Web App.

Exposes ``GET /api/search``/``GET /api/table/{table_name}`` for the DDIC
table dictionary and ``GET /api/tcode/search``/``GET /api/tcode/{tcode}``
for transaction codes, all validated through
:class:`backend.security.InputValidator`, and serves the static vanilla-JS
frontend from ``frontend/`` at ``/``. Serving both from the same FastAPI
process means the browser never crosses origins, so no CORS configuration
is needed.
"""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from backend.cache import MetadataCache
from backend.config import Settings, get_settings
from backend.connection import DatasphereConnector
from backend.ddic_repository import DDICRepository
from backend.dbt_generator import generate_dbt_artifacts
from backend.heuristics import TableClassifier
from backend.mart_generator import generate_mart_artifacts
from backend.schemas import (
    DbtArtifacts,
    DbtGenerateRequest,
    MartArtifacts,
    MartGenerateRequest,
    SearchResult,
    TableContract,
    TableCountStats,
    TransactionContract,
    TransactionSearchResult,
)
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


@app.get("/api/tcode/search", response_model=list[TransactionSearchResult])
def search_tcodes(
    q: str = Depends(InputValidator.validate_search_term),
    service: MetadataService = Depends(_get_service),
) -> list[dict[str, str]]:
    """Searches for SAP transaction codes by technical code prefix or description.

    Args:
        q: Validated, LIKE-escaped search term.
        service: Injected metadata service.

    Returns:
        Up to 15 matching transaction codes, technical-code prefix matches first.
    """
    return service.search_tcodes(q)


@app.get("/api/tcode/{tcode}", response_model=TransactionContract)
def get_tcode(
    tcode: str = Depends(InputValidator.validate_tcode),
    service: MetadataService = Depends(_get_service),
) -> dict:
    """Returns the full contract for a single SAP transaction code.

    Args:
        tcode: Validated, normalized transaction code.
        service: Injected metadata service.

    Returns:
        The transaction's contract (program, package, standard/custom
        classification), served from cache when still fresh.
    """
    return service.get_transaction_contract(tcode)


@app.get("/api/stats", response_model=TableCountStats)
def stats(service: MetadataService = Depends(_get_service)) -> dict:
    """Returns the total number of tables discoverable in the DDIC schema.

    Args:
        service: Injected metadata service.

    Returns:
        The total table count.
    """
    return {"total_tables": service.get_table_count()}


@app.get("/api/table/{table_name:path}", response_model=TableContract)
def get_table(
    table_name: str = Depends(InputValidator.validate_table_name),
    service: MetadataService = Depends(_get_service),
) -> dict:
    """Returns the full metadata contract for a single SAP table.

    ``table_name`` uses the ``:path`` converter (not the default
    single-segment matcher) because a namespaced SAP object name (e.g.
    ``/BIC/AZCUSTOMER``) contains its own ``/`` characters. The browser
    sends those percent-encoded (``%2F``), but ASGI servers decode the
    request path before Starlette's router ever sees it, so a
    single-segment route 404s before this handler — or even
    :func:`InputValidator.validate_table_name` — ever runs.

    Args:
        table_name: Validated, normalized technical table name.
        service: Injected metadata service.

    Returns:
        The table's metadata contract, served from cache when still fresh.
    """
    return service.get_table_contract(table_name)


@app.post("/api/table/{table_name:path}/dbt", response_model=DbtArtifacts)
def get_table_dbt_artifacts(
    request: DbtGenerateRequest,
    table_name: str = Depends(InputValidator.validate_table_name),
    service: MetadataService = Depends(_get_service),
    settings: Settings = Depends(get_settings),
) -> DbtArtifacts:
    """Generates the dbt staging SQL model and sources YAML for a single table.

    Args:
        request: The dbt generation parameters (load type, templates, etc.).
        table_name: Validated, normalized technical table name.
        service: Injected metadata service.
        settings: Injected application settings.

    Returns:
        The generated SQL/YML plus the resolved load type, watermark and any
        warnings.
    """
    contract = TableContract.model_validate(service.get_table_contract(table_name))
    resolved_schema = request.dbt_schema or settings.dbt_schema
    return generate_dbt_artifacts(
        contract,
        load_type=request.load_type,
        watermark_column=request.watermark_column,
        source_name=request.source_name or resolved_schema,
        database=request.database or settings.dbt_database,
        schema=resolved_schema,
        use_macros=request.use_macros,
        sql_template=request.sql_template,
        yml_template=request.yml_template,
        plain_sql=request.plain_sql,
        use_business_alias=request.use_business_alias,
    )


@app.post("/api/mart/generate", response_model=MartArtifacts)
def generate_mart(
    request: MartGenerateRequest,
    service: MetadataService = Depends(_get_service),
    settings: Settings = Depends(get_settings),
) -> MartArtifacts:
    """Generates a fact/dimension dbt mart model from an arbitrary graph of
    tables and their join wiring — the visual builder's "Gerar" action.

    Unlike a star schema built purely from one table's own declared DD08L
    foreign keys, ``request.joins`` may include hand-drawn edges for
    relationships DDIC doesn't model as a formal FK (e.g. SAP document-flow
    chains through VBFA, or ``VGBEL``/``VGPOS`` reference fields).

    Args:
        request: The table graph (every table, the join wiring between
            them, and which one anchors the ``FROM`` clause) plus optional
            FCT/DIM/source/schema overrides.
        service: Injected metadata service.
        settings: Injected application settings.

    Returns:
        The generated SQL/YML/documentation plus the resolved mart type and
        any warnings.

    Raises:
        HTTPException: With status 400 if any node ID/table name is invalid,
            if a ``node_id`` repeats, if ``root_node`` isn't one of
            ``tables``, if a join references a node ID outside ``tables``,
            or if any box isn't connected to the root by the given joins.
    """
    table_name_by_node = InputValidator.validate_mart_nodes(request.tables)
    root_node = InputValidator.validate_table_name_value(request.root_node)
    if root_node not in table_name_by_node:
        raise HTTPException(status_code=400, detail=f"root_node {root_node!r} não está em tables.")

    # Fetch each distinct SAP table once even if it backs multiple nodes
    # (e.g. KNA1 as both "sold-to" and "payer" — see mart_generator's module
    # docstring), then fan each contract back out to every node built on it.
    distinct_table_names = set(table_name_by_node.values())
    contract_by_table_name = {
        name: TableContract.model_validate(service.get_table_contract(name)) for name in distinct_table_names
    }
    nodes = {node_id: contract_by_table_name[table_name] for node_id, table_name in table_name_by_node.items()}
    resolved_schema = request.dbt_schema or settings.dbt_schema

    try:
        return generate_mart_artifacts(
            nodes,
            request.joins,
            root_node,
            mart_type=request.mart_type,
            source_name=request.source_name or resolved_schema,
            database=request.database or settings.dbt_database,
            schema=resolved_schema,
            use_macros=request.use_macros,
            sql_template=request.sql_template,
            yml_template=request.yml_template,
            use_business_alias=request.use_business_alias,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


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
