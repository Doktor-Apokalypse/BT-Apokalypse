from fastapi.testclient import TestClient

from apokalypse import web
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
        assert 'name="max_active_downloads"' in page.text
        assert 'name="max_active_seeds"' in page.text
        assert 'name="add_trackers_to_new_torrents"' in page.text
        assert 'name="tracker_list"' in page.text
        assert 'name="encryption_mode"' in page.text
        assert 'name="randomize_listen_port"' in page.text
        assert 'name="bind_interface"' in page.text
        assert 'name="webui_auth_enabled"' in page.text
        assert 'id="login-dialog"' in page.text
        assert 'data-remove-files="false"' in page.text
        assert 'data-remove-files="true"' in page.text
        assert 'id="remove-confirm-dialog"' in page.text
        assert client.get("/static/logo.png").headers["content-type"] == "image/png"
        script = client.get("/static/app.js")
        assert script.status_code == 200
        assert script.headers["cache-control"] == "no-cache, max-age=0, must-revalidate"
        assert 'if (state.filter === "completed") return isComplete(torrent);' in script.text
        assert 'class="danger tracker-remove"' in script.text

        status = client.get("/api/status").json()
        assert status["torrents"] == 0
        assert "libtorrent_version" in status

        settings = client.get("/api/settings").json()
        assert settings["enable_dht"] is True
        assert settings["max_active_downloads"] == 3
        assert settings["max_active_seeds"] == 5
        assert settings["add_trackers_to_new_torrents"] is False
        assert settings["tracker_list"] == []
        assert settings["webui_port"] == 6969
        assert "webui_password_hash" not in settings
        assert settings["proxy_password"] == ""

        imported = client.post("/api/blocklist/text", json={"text": "203.0.113.1"}).json()
        assert imported == {"added": 1, "total": 1}


def test_open_torrent_download_folder(tmp_path, monkeypatch) -> None:
    class FakeEngine:
        @staticmethod
        def get_torrent(_torrent_id: str) -> dict[str, str]:
            return {"save_path": str(tmp_path)}

    opened: list[object] = []
    monkeypatch.setattr(web, "engine", lambda _request: FakeEngine())
    monkeypatch.setattr(web, "open_in_file_manager", opened.append)
    with TestClient(app) as client:
        response = client.post("/api/torrents/example/open-folder")

    assert response.status_code == 200
    assert response.json() == {"path": str(tmp_path.resolve())}
    assert opened == [tmp_path.resolve()]


def test_tailscale_access_requires_login_but_localhost_bypasses_it(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APOKALYPSE_DATA_DIR", str(tmp_path / "app-data"))
    with TestClient(app) as client:
        configured = client.patch(
            "/api/settings",
            json={
                "webui_access": "tailscale",
                "webui_auth_enabled": True,
                "webui_username": "doktor",
                "webui_password": "apokalypse-test-password",
            },
        )
        assert configured.status_code == 200
        assert client.get("/api/settings").status_code == 200

        monkeypatch.setattr(web, "_client_address", lambda _request: "100.114.56.102")
        assert client.get("/api/auth/status").json()["required"] is True
        assert client.get("/api/settings").status_code == 401
        assert client.post(
            "/api/auth/login", json={"username": "doktor", "password": "wrong-password"}
        ).status_code == 401

        login = client.post(
            "/api/auth/login",
            json={"username": "doktor", "password": "apokalypse-test-password"},
        )
        assert login.status_code == 200
        settings = client.get("/api/settings")
        assert settings.status_code == 200
        assert "webui_password_hash" not in settings.json()


def test_network_access_rules() -> None:
    assert web.webui_client_allowed("local", "127.0.0.1") is True
    assert web.webui_client_allowed("tailscale", "100.114.56.102") is True
    assert web.webui_client_allowed("tailscale", "fd7a:115c:a1e0::123") is True
    assert web.webui_client_allowed("tailscale", "192.168.0.143") is False
