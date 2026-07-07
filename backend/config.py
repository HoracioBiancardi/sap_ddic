"""Application configuration loaded from environment variables.

Defines the :class:`Settings` model used across the backend to access SAP
Datasphere connection parameters and logging configuration, plus a cached
accessor so the environment is parsed only once per process.
"""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed view over the ``.env`` configuration file.

    Attributes:
        hana_address: Hostname of the SAP Datasphere (HANA Cloud) instance.
        hana_port: TCP port used to reach the HANA instance (443 for Cloud).
        hana_user: Database user used to authenticate against HANA.
        hana_password: Database password, kept as a secret to avoid accidental
            leakage through logs or repr output.
        ddic_schema: Schema name where the replicated DDIC tables live.
        ddic_language: Two-letter SAP language key used to filter description
            texts (e.g. ``"P"`` for Portuguese, ``"E"`` for English).
        log_level: Minimum log level emitted by the application logger.
        log_to_json: Whether log records should be serialized as JSON.
        log_path: Filesystem path of the log file.
        dbt_source_name: Default dbt source name used in generated
            ``source('name', 'table')`` references (Dados Brutos dbt generator).
        dbt_database: Default database referenced by generated ``sources.yml``.
        dbt_schema: Default schema referenced by generated ``sources.yml``.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    hana_address: str
    hana_port: int
    hana_user: str
    hana_password: SecretStr
    ddic_schema: str
    ddic_language: str
    log_level: str = "INFO"
    log_to_json: bool = False
    log_path: str = "log/pipeline.json"
    dbt_source_name: str = "sap"
    dbt_database: str = "BRONZE"
    dbt_schema: str = "dataspherev2"


@lru_cache
def get_settings() -> Settings:
    """Returns the process-wide :class:`Settings` singleton.

    Returns:
        The parsed application settings, cached after the first call so the
        ``.env`` file is only read once per process.
    """
    return Settings()
