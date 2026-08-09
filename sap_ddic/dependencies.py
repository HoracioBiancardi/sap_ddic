"""Shared FastAPI dependencies used across ``sap_ddic.routers``."""

from fastapi import Request

from sap_ddic.service import MetadataService


def get_service(request: Request) -> MetadataService:
    """Returns the process-wide :class:`MetadataService` built at startup.

    Args:
        request: The current request, used to reach ``app.state`` — routers
            live in separate modules from :mod:`sap_ddic.main`, so they
            can't close over the ``app`` variable directly.

    Returns:
        The :class:`MetadataService` instance created in ``main._lifespan``.
    """
    return request.app.state.service
