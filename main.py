"""
Entrypoint principal do sap_ddic.
Re-exporta a aplicação FastAPI de sap_ddic.main para padronização de inicialização.
"""
from sap_ddic.main import app

__all__ = ["app"]
