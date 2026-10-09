from fastapi.testclient import TestClient

from apokalypse.web import app


def test_webui_and_core_api_start(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APOKALYPSE_DATA_DIR", str(tmp_path / "app-data"))
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "BT Apokalypse" in page.text
        assert "BT APOKALYPSE" in page.text
        assert '/static/logo.png' in page.text
        assert '/static/favicon-32.ico' in page.text
        assert '/static/favicon-64.ico' in page.text
        assert client.get("/static/logo.png").headers["content-type"] == "image/png"

        status = client.get("/api/status").json()
        assert status["torrents"] == 0
        assert "libtorrent_version" in status

        settings = client.get("/api/settings").json()
        assert settings["enable_dht"] is True

        imported = client.post("/api/blocklist/text", json={"text": "203.0.113.1"}).json()
        assert imported == {"added": 1, "total": 1}
