from __future__ import annotations

import os
import subprocess
import sys
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Annotated

from fastapi import Body, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .engine import TorrentEngine
from .protocol import magnet_handler_status, register_magnet_handler, unregister_magnet_handler

STATIC_DIR = Path(__file__).with_name("static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = TorrentEngine()
    app.state.engine = engine
    yield
    engine.close()


app = FastAPI(title="BT Apokalypse", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


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
    url: str
    tier: int = Field(0, ge=0)


class BanInput(BaseModel):
    ip: str


class TextBlocklistInput(BaseModel):
    text: str


class UrlBlocklistInput(BaseModel):
    url: str


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
        return engine(request).add_tracker(torrent_id, payload.url, payload.tier)
    except Exception as exc:
        raise api_error(exc) from exc


@app.get("/api/settings")
def get_settings(request: Request) -> dict[str, Any]:
    return engine(request).get_settings()


@app.patch("/api/settings")
def update_settings(request: Request, changes: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return engine(request).update_settings(changes)
    except Exception as exc:
        raise api_error(exc) from exc


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
