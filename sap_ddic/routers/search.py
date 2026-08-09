"""Table search endpoints: by name/description, and the total count."""

from fastapi import APIRouter, Depends

from sap_ddic.dependencies import get_service
from sap_ddic.schemas import SearchResult, TableCountStats
from sap_ddic.security import InputValidator
from sap_ddic.service import MetadataService

router = APIRouter(tags=["search"])


@router.get("/api/search", response_model=list[SearchResult])
def search(
    q: str = Depends(InputValidator.validate_search_term),
    service: MetadataService = Depends(get_service),
) -> list[dict[str, str]]:
    """Searches for SAP tables by technical name prefix or description.

    Args:
        q: Validated, LIKE-escaped search term.
        service: Injected metadata service.

    Returns:
        Up to 15 matching tables, technical-name prefix matches first.
    """
    return service.search_tables(q)


@router.get("/api/stats", response_model=TableCountStats)
def stats(service: MetadataService = Depends(get_service)) -> dict:
    """Returns the total number of tables discoverable in the DDIC schema.

    Args:
        service: Injected metadata service.

    Returns:
        The total table count.
    """
    return {"total_tables": service.get_table_count()}
