"""SAP transaction code (tcode) search and contract retrieval."""

from fastapi import APIRouter, Depends

from sap_ddic.dependencies import get_service
from sap_ddic.schemas import TransactionContract, TransactionSearchResult
from sap_ddic.security import InputValidator
from sap_ddic.service import MetadataService

router = APIRouter(tags=["tcode"])


@router.get("/api/tcode/search", response_model=list[TransactionSearchResult])
def search_tcodes(
    q: str = Depends(InputValidator.validate_search_term),
    service: MetadataService = Depends(get_service),
) -> list[dict[str, str]]:
    """Searches for SAP transaction codes by technical code prefix or description.

    Args:
        q: Validated, LIKE-escaped search term.
        service: Injected metadata service.

    Returns:
        Up to 15 matching transaction codes, technical-code prefix matches first.
    """
    return service.search_tcodes(q)


@router.get("/api/tcode/{tcode}", response_model=TransactionContract)
def get_tcode(
    tcode: str = Depends(InputValidator.validate_tcode),
    service: MetadataService = Depends(get_service),
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
