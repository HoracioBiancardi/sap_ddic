"""HTTP-level tests for sap_ddic.routers.system via TestClient.

Only exercises the system router (health/metrics/logs), which has no
dependency on a live HANA connection — DatasphereConnector.get_engine() is
lazy, so starting the app under TestClient never attempts a real network
call, but the other domain routers (search/tables/tcode/mart) do require a
working MetadataService and are out of scope for this module.
"""

from fastapi.testclient import TestClient

from sap_ddic.main import app

client = TestClient(app)


class TestSystemRouter:
    """Tests for the /api/system/* endpoints."""

    def test_health_check(self) -> None:
        """GET /api/system/health reports ok status and uptime."""
        response = client.get("/api/system/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "uptime_seconds" in data

    def test_metrics(self) -> None:
        """GET /api/system/metrics reports uptime and non-sensitive settings."""
        response = client.get("/api/system/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "uptime_seconds" in data
        assert "ddic_schema" in data
        assert "hana_password" not in data
        assert "hana_address" not in data

    def test_logs_and_clear(self) -> None:
        """GET /api/system/logs returns entries; POST /logs/clear empties the buffer."""
        client.get("/api/system/health")
        response = client.get("/api/system/logs")
        assert response.status_code == 200
        assert "logs" in response.json()

        clear_response = client.post("/api/system/logs/clear")
        assert clear_response.status_code == 200
        assert clear_response.json()["status"] == "ok"
