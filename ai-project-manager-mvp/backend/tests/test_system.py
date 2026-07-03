from fastapi.testclient import TestClient

from app.main import app


def test_clear_system_data_returns_downloadable_backup():
    client = TestClient(app)

    response = client.post("/system/clear")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "cleared"
    assert payload["backup_name"].endswith(".zip")
    assert payload["backup_url"].startswith("/api/system/backups/")

    download = client.get(payload["backup_url"].replace("/api", ""))
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/zip"
