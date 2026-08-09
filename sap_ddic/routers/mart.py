"""Fact/dimension dbt mart generation from an arbitrary graph of tables."""

from fastapi import APIRouter, Depends, HTTPException

from sap_ddic.config import Settings, get_settings
from sap_ddic.dependencies import get_service
from sap_ddic.mart_generator import generate_mart_artifacts
from sap_ddic.schemas import MartArtifacts, MartGenerateRequest, TableContract
from sap_ddic.security import InputValidator
from sap_ddic.service import MetadataService

router = APIRouter(tags=["mart"])


@router.post("/api/mart/generate", response_model=MartArtifacts)
def generate_mart(
    request: MartGenerateRequest,
    service: MetadataService = Depends(get_service),
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
