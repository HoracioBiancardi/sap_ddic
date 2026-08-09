"""Table contract retrieval and its dbt staging-model generation."""

from fastapi import APIRouter, Depends

from sap_ddic.config import Settings, get_settings
from sap_ddic.dbt_generator import generate_dbt_artifacts
from sap_ddic.dependencies import get_service
from sap_ddic.schemas import DbtArtifacts, DbtGenerateRequest, TableContract
from sap_ddic.security import InputValidator
from sap_ddic.service import MetadataService

router = APIRouter(tags=["tables"])


@router.get("/api/table/{table_name:path}", response_model=TableContract)
def get_table(
    table_name: str = Depends(InputValidator.validate_table_name),
    service: MetadataService = Depends(get_service),
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


@router.post("/api/table/{table_name:path}/dbt", response_model=DbtArtifacts)
def get_table_dbt_artifacts(
    request: DbtGenerateRequest,
    table_name: str = Depends(InputValidator.validate_table_name),
    service: MetadataService = Depends(get_service),
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
