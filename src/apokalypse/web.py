from __future__ import annotations

import ipaddress
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Annotated

from fastapi import Body, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .engine import TorrentEngine
from .protocol import magnet_handler_status, register_magnet_handler, unregister_magnet_handler
from .security import verify_password

STATIC_DIR = Path(__file__).with_name("static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = TorrentEngine()
    app.state.engine = engine
    app.state.auth_sessions = {}
    yield
    engine.close()


app = FastAPI(title="BT Apokalypse", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

TAILSCALE_V4 = ipaddress.ip_network("100.64.0.0/10")
TAILSCALE_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")
SESSION_SECONDS = 24 * 60 * 60
SESSION_COOKIE = "bt_apokalypse_session"


def _client_address(request: Request) -> str:
    return request.client.host if request.client else ""


def is_loopback(address: str) -> bool:
    if address == "testclient":
        return True
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


def webui_client_allowed(mode: str, address: str) -> bool:
    if is_loopback(address):
        return True
    if mode == "lan":
        return True
    if mode != "tailscale":
        return False
    try:
        client_ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return client_ip in (TAILSCALE_V4 if client_ip.version == 4 else TAILSCALE_V6)


def _authenticated(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE, "")
    expires = request.app.state.auth_sessions.get(token, 0)
    if expires <= time.time():
        request.app.state.auth_sessions.pop(token, None)
        return False
    return True


@app.middleware("http")
async def protect_webui(request: Request, call_next):
    settings = request.app.state.engine.settings
    address = _client_address(request)
    access_mode = os.environ.get("APOKALYPSE_WEBUI_ACCESS_OVERRIDE", settings.webui_access)
    if not webui_client_allowed(access_mode, address):
        return JSONResponse({"detail": "WebUI access is not allowed from this network"}, status_code=403)
    public_api = request.url.path in {"/api/auth/status", "/api/auth/login"}
    needs_login = settings.webui_auth_enabled and not is_loopback(address)
    if request.url.path.startswith("/api/") and needs_login and not public_api:
        if not _authenticated(request):
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
    return await call_next(request)


@app.middleware("http")
async def revalidate_webui_assets(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, max-age=0, must-revalidate"
    return response


def engine(request: Request) -> TorrentEngine:
    return request.app.state.engine


def api_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(404, "Torrent not found")
    if isinstance(exc, ValueError):
        return HTTPException(400, str(exc))
    return HTTPException(500, str(exc))


def open_in_file_manager(folder: Path) -> None:
    """Open a local folder using the operating system's file manager."""
    if os.name == "nt":
        os.startfile(str(folder))  # type: ignore[attr-defined]
        return
    command = ["open" if sys.platform == "darwin" else "xdg-open", str(folder)]
    subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )


def network_interfaces() -> list[dict[str, Any]]:
    """Return usable Windows adapters and their IPv4 addresses."""
    if os.name != "nt":
        return []
    script = (
        "$items = Get-NetAdapter -ErrorAction Stop | ForEach-Object { "
        "$ips = @(Get-NetIPAddress -InterfaceIndex $_.ifIndex -AddressFamily IPv4 "
        "-ErrorAction SilentlyContinue | Select-Object -ExpandProperty IPAddress); "
        "[PSCustomObject]@{Name=$_.Name; Description=$_.InterfaceDescription; "
        "Guid=$_.InterfaceGuid.ToString(); Status=$_.Status.ToString(); IPv4=$ips} }; "
        "$items | ConvertTo-Json -Depth 4 -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            check=True,
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        raw = json.loads(result.stdout or "[]")
        items = raw if isinstance(raw, list) else [raw]
        interfaces = []
        for item in items:
            guid = str(item.get("Guid") or "").strip("{}")
            addresses = item.get("IPv4") or []
            if isinstance(addresses, str):
                addresses = [addresses]
            interfaces.append(
                {
                    "name": str(item.get("Name") or ""),
                    "description": str(item.get("Description") or ""),
                    "id": "{" + guid + "}" if guid else "",
                    "status": str(item.get("Status") or "Unknown"),
                    "ipv4": addresses,
                }
            )
        return sorted(interfaces, key=lambda item: (item["status"] != "Up", item["name"].casefold()))
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return []


class MagnetInput(BaseModel):
    magnet: str
    save_path: str | None = None
    completed_path: str | None = None
    sequential: bool = False
    paused: bool = False


class ActionInput(BaseModel):
    action: str


class TorrentUpdate(BaseModel):
    sequential: bool | None = None
    download_limit_kib: int | None = Field(None, ge=0)
    upload_limit_kib: int | None = Field(None, ge=0)
    max_connections: int | None = Field(None, ge=2)
    completed_path: str | None = None
    move_completed: bool | None = None


class PriorityInput(BaseModel):
    priorities: dict[int, int]


class TrackerInput(BaseModel):
    url: str | None = None
    urls: list[str] = Field(default_factory=list)
    tier: int = Field(0, ge=0)


class BanInput(BaseModel):
    ip: str


class TextBlocklistInput(BaseModel):
    text: str


class UrlBlocklistInput(BaseModel):
    url: str


class LoginInput(BaseModel):
    username: str
    password: str


@app.get("/api/auth/status")
def auth_status(request: Request) -> dict[str, Any]:
    settings = engine(request).settings
    bypassed = is_loopback(_client_address(request))
    required = settings.webui_auth_enabled and not bypassed
    return {
        "required": required,
        "authenticated": not required or _authenticated(request),
        "local_bypass": bypassed,
        "username": settings.webui_username,
    }


@app.post("/api/auth/login")
def login(payload: LoginInput, request: Request):
    settings = engine(request).settings
    if is_loopback(_client_address(request)) or not settings.webui_auth_enabled:
        return {"authenticated": True}
    if payload.username != settings.webui_username or not verify_password(
            payload.password, settings.webui_password_hash
    ):
        raise HTTPException(401, "Invalid username or password")
    token = secrets.token_urlsafe(32)
    request.app.state.auth_sessions[token] = time.time() + SESSION_SECONDS
    response = JSONResponse({"authenticated": True})
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_SECONDS,
        httponly=True,
        samesite="strict",
    )
    return response


@app.delete("/api/auth/session")
def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE, "")
    request.app.state.auth_sessions.pop(token, None)
    response = JSONResponse({"authenticated": False})
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
def status(request: Request) -> dict[str, Any]:
    return engine(request).session_status()


@app.get("/api/torrents")
def torrents(request: Request) -> list[dict[str, Any]]:
    return engine(request).list_torrents()


@app.get("/api/torrents/{torrent_id}")
def torrent(torrent_id: str, request: Request) -> dict[str, Any]:
    try:
        return engine(request).get_torrent(torrent_id)
    except Exception as exc:
        raise api_error(exc) from exc


@app.post("/api/torrents/magnet", status_code=201)
def add_magnet(payload: MagnetInput, request: Request) -> dict[str, Any]:
    try:
        return engine(request).add_magnet(**payload.model_dump())
    except Exception as exc:
        raise api_error(exc) from exc


@app.post("/api/torrents/file", status_code=201)
async def add_torrent_file(
        request: Request,
        torrent: Annotated[UploadFile, File()],
        save_path: Annotated[str | None, Form()] = None,
        completed_path: Annotated[str | None, Form()] = None,
        sequential: Annotated[bool, Form()] = False,
        paused: Annotated[bool, Form()] = False,
) -> dict[str, Any]:
    try:
        return engine(request).add_torrent_bytes(
            await torrent.read(), save_path, completed_path, sequential, paused
        )
    except Exception as exc:
        raise api_error(exc) from exc


@app.post("/api/torrents/{torrent_id}/action")
def torrent_action(torrent_id: str, payload: ActionInput, request: Request) -> dict[str, Any]:
    try:
        return engine(request).action(torrent_id, payload.action)
    except Exception as exc:
        raise api_error(exc) from exc


@app.patch("/api/torrents/{torrent_id}")
def update_torrent(torrent_id: str, payload: TorrentUpdate, request: Request) -> dict[str, Any]:
    try:
        return engine(request).update_torrent(torrent_id, payload.model_dump(exclude_none=True))
    except Exception as exc:
        raise api_error(exc) from exc


@app.post("/api/torrents/{torrent_id}/open-folder")
def open_torrent_folder(torrent_id: str, request: Request) -> dict[str, str]:
    try:
        folder = Path(engine(request).get_torrent(torrent_id)["save_path"]).expanduser().resolve()
        if not folder.is_dir():
            raise ValueError("The torrent download folder does not exist")
        open_in_file_manager(folder)
        return {"path": str(folder)}
    except Exception as exc:
        raise api_error(exc) from exc


@app.delete("/api/torrents/{torrent_id}", status_code=204)
def remove_torrent(
        torrent_id: str, request: Request, delete_files: bool = Query(False)
) -> None:
    try:
        engine(request).remove(torrent_id, delete_files)
    except Exception as exc:
        raise api_error(exc) from exc


@app.get("/api/torrents/{torrent_id}/files")
def torrent_files(torrent_id: str, request: Request) -> list[dict[str, Any]]:
    try:
        return engine(request).files(torrent_id)
    except Exception as exc:
        raise api_error(exc) from exc


@app.patch("/api/torrents/{torrent_id}/files")
def set_priorities(torrent_id: str, payload: PriorityInput, request: Request) -> list[dict[str, Any]]:
    try:
        return engine(request).set_file_priorities(torrent_id, payload.priorities)
    except Exception as exc:
        raise api_error(exc) from exc


@app.get("/api/torrents/{torrent_id}/peers")
def torrent_peers(torrent_id: str, request: Request) -> list[dict[str, Any]]:
    try:
        return engine(request).peers(torrent_id)
    except Exception as exc:
        raise api_error(exc) from exc


@app.get("/api/torrents/{torrent_id}/trackers")
def torrent_trackers(torrent_id: str, request: Request) -> list[dict[str, Any]]:
    try:
        return engine(request).trackers(torrent_id)
    except Exception as exc:
        raise api_error(exc) from exc


@app.post("/api/torrents/{torrent_id}/trackers")
def add_tracker(torrent_id: str, payload: TrackerInput, request: Request) -> list[dict[str, Any]]:
    try:
        urls = [*payload.urls, *([payload.url] if payload.url else [])]
        return engine(request).add_trackers(torrent_id, urls, payload.tier)
    except Exception as exc:
        raise api_error(exc) from exc


@app.delete("/api/torrents/{torrent_id}/trackers/{tracker_index}")
def remove_tracker(torrent_id: str, tracker_index: int, request: Request) -> list[dict[str, Any]]:
    try:
        return engine(request).remove_tracker(torrent_id, tracker_index)
    except Exception as exc:
        raise api_error(exc) from exc


@app.get("/api/settings")
def get_settings(request: Request) -> dict[str, Any]:
    return engine(request).get_settings()


@app.patch("/api/settings")
def update_settings(request: Request, changes: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        auth_changed = bool(
            {"webui_auth_enabled", "webui_username", "webui_password"}.intersection(changes)
        )
        result = engine(request).update_settings(changes)
        if auth_changed:
            request.app.state.auth_sessions.clear()
        return result
    except Exception as exc:
        raise api_error(exc) from exc


@app.get("/api/network/interfaces")
def get_network_interfaces() -> list[dict[str, Any]]:
    return network_interfaces()


@app.get("/api/integration/magnet")
def magnet_integration_status() -> dict[str, Any]:
    return magnet_handler_status()


@app.post("/api/integration/magnet")
def register_magnet_integration() -> dict[str, Any]:
    try:
        return register_magnet_handler()
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/integration/magnet")
def unregister_magnet_integration() -> dict[str, Any]:
    try:
        return unregister_magnet_handler()
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/directories")
def directories(path: str | None = None) -> dict[str, Any]:
    try:
        if path:
            current = Path(path).expanduser().resolve()
        elif os.name == "nt":
            current = Path.home().resolve()
        else:
            current = Path("/")
        if not current.is_dir():
            raise ValueError("Directory does not exist")
        children = sorted(
            (entry for entry in current.iterdir() if entry.is_dir()),
            key=lambda entry: entry.name.casefold(),
        )
        roots = (
            [f"{letter}:\\" for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if Path(f"{letter}:\\").exists()]
            if os.name == "nt"
            else ["/"]
        )
        return {
            "path": str(current),
            "parent": str(current.parent) if current.parent != current else None,
            "roots": roots,
            "directories": [{"name": item.name, "path": str(item)} for item in children[:500]],
        }
    except (OSError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/blocklist")
def blocklist(request: Request) -> dict[str, Any]:
    return engine(request).blocklist_status()


@app.post("/api/blocklist/text")
def add_blocklist_text(payload: TextBlocklistInput, request: Request) -> dict[str, int]:
    return engine(request).add_blocklist(payload.text)


@app.post("/api/blocklist/file")
async def add_blocklist_file(request: Request, blocklist: Annotated[UploadFile, File()]) -> dict[str, int]:
    contents = await blocklist.read(50 * 1024 * 1024 + 1)
    if len(contents) > 50 * 1024 * 1024:
        raise HTTPException(413, "Blocklists may not exceed 50 MiB")
    return engine(request).add_blocklist(contents.decode("utf-8", errors="replace"))


@app.post("/api/blocklist/url")
def add_blocklist_url(payload: UrlBlocklistInput, request: Request) -> dict[str, int]:
    if not payload.url.startswith(("http://", "https://")):
        raise HTTPException(400, "Blocklist URL must use HTTP or HTTPS")
    try:
        request_headers = {"User-Agent": "BT-Apokalypse/0.1"}
        with urllib.request.urlopen(urllib.request.Request(payload.url, headers=request_headers),
                                    timeout=20) as response:
            contents = response.read(50 * 1024 * 1024 + 1)
        if len(contents) > 50 * 1024 * 1024:
            raise HTTPException(413, "Blocklists may not exceed 50 MiB")
        return engine(request).add_blocklist(contents.decode("utf-8", errors="replace"))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f"Could not download blocklist: {exc}") from exc


@app.post("/api/blocklist/ban")
def ban_ip(payload: BanInput, request: Request) -> dict[str, int]:
    try:
        return engine(request).ban_ip(payload.ip)
    except ValueError as exc:
        raise HTTPException(400, "A valid IPv4 address is required") from exc


@app.delete("/api/blocklist", status_code=204)
def clear_blocklist(request: Request) -> None:
    engine(request).clear_blocklist()
