"""SAP Datasphere (HANA) connection management.

Provides :class:`DatasphereConnector`, the single component responsible for
building the SQLAlchemy engine used to talk to the HANA Cloud replica and for
executing queries against it with retry and connection-pool resilience.
"""

from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Engine, URL
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy import create_engine
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from backend.config import Settings
from backend.logger import get_logger

logger = get_logger()


class DatasphereConnector:
    """Owns the lifecycle of the SQLAlchemy engine used to reach HANA.

    The connection URL is built with :func:`sqlalchemy.engine.URL.create`
    instead of manual string interpolation. SAP Datasphere technical users
    routinely contain characters such as ``#`` (e.g. ``DWCDBUSER#DATALAKE``)
    that are reserved in the URL fragment syntax; hand-built f-string DSNs
    silently truncate the connection string on such characters, which was a
    real bug observed in an earlier draft of this connector.

    Attributes:
        settings: The application settings used to configure the connection.
    """

    def __init__(self, settings: Settings) -> None:
        """Initializes the connector with the given settings.

        Args:
            settings: Parsed application configuration containing the HANA
                host, port, credentials and target schema.
        """
        self.settings = settings
        self._engine: Engine | None = None

    def _build_url(self) -> URL:
        """Builds the SQLAlchemy connection URL for the HANA dialect.

        Returns:
            A :class:`sqlalchemy.engine.URL` with credentials and connection
            options properly escaped, requesting an encrypted (TLS) session
            as required by HANA Cloud.
        """
        return URL.create(
            drivername="hana",
            username=self.settings.hana_user,
            password=self.settings.hana_password.get_secret_value(),
            host=self.settings.hana_address,
            port=self.settings.hana_port,
            query={"encrypt": "true", "sslValidateCertificate": "true"},
        )

    def get_engine(self) -> Engine:
        """Lazily creates and returns the shared SQLAlchemy engine.

        Returns:
            The SQLAlchemy :class:`Engine` instance, created on first call
            and reused for the lifetime of the process.
        """
        if self._engine is None:
            logger.info("Initializing Datasphere SQLAlchemy engine.")
            self._engine = create_engine(
                self._build_url(),
                echo=False,
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,
                pool_recycle=3600,
            )
        return self._engine

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((OperationalError, DBAPIError)),
        reraise=True,
    )
    def run_query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Executes a parameterized SQL query and returns the result rows.

        Args:
            sql: SQL statement with named bind parameters (``:name`` style).
                Callers must never interpolate user-supplied values directly
                into this string. Parameters whose value is a list or tuple
                (e.g. for an ``IN :names`` clause) are automatically bound
                as expanding parameters.
            params: Mapping of bind parameter names to values.

        Returns:
            The result rows as a list of plain dictionaries, one per row.

        Raises:
            OperationalError: If the connection to HANA fails after all
                retry attempts are exhausted.
            DBAPIError: If the database driver reports a transient error
                after all retry attempts are exhausted.
        """
        engine = self.get_engine()
        params = params or {}
        statement = text(sql)
        expanding_keys = [key for key, value in params.items() if isinstance(value, (list, tuple))]
        if expanding_keys:
            statement = statement.bindparams(
                *(bindparam(key, expanding=True) for key in expanding_keys)
            )
        with engine.connect() as connection:
            result = connection.execute(statement, params)
            return [dict(row) for row in result.mappings().all()]
