from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from threading import RLock
from typing import Any

from .security import protect_secret, unprotect_secret

TRACKER_URL_PREFIXES = ("http://", "https://", "udp://", "ws://", "wss://")


def normalize_tracker_urls(value: Any, *, reject_invalid: bool = False) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        entries = value.splitlines()
    elif isinstance(value, (list, tuple)):
        entries = value
    else:
        if reject_invalid:
            raise ValueError("Tracker list must contain one URL per line")
        return []

    result: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        url = entry.strip() if isinstance(entry, str) else ""
        if not url:
            continue
        if not url.lower().startswith(TRACKER_URL_PREFIXES):
            if reject_invalid:
                raise ValueError(f"Unsupported tracker URL: {url}")
            continue
        if url not in seen:
            seen.add(url)
            result.append(url)
    return result


def default_data_dir() -> Path:
    configured = os.environ.get("APOKALYPSE_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    if os.name == "nt" and getattr(sys, "frozen", False):
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return (Path(local_app_data) / "BT Apokalypse").resolve()
    return (Path.cwd() / "data").resolve()


@dataclass(slots=True)
class AppSettings:
    download_dir: str = str((Path.home() / "Downloads").resolve())
    completed_dir: str = ""
    move_completed: bool = False
    listen_port: int = 6881
    randomize_listen_port: bool = False
    enable_dht: bool = True
    enable_pex: bool = True
    enable_lsd: bool = True
    enable_upnp: bool = True
    enable_natpmp: bool = True
    auto_start: bool = True
    download_limit_kib: int = 0
    upload_limit_kib: int = 0
    max_connections: int = 500
    max_active_downloads: int = 3
    max_active_seeds: int = 5
    add_trackers_to_new_torrents: bool = False
    tracker_list: list[str] = field(default_factory=list)
    encryption_mode: str = "prefer"
    anonymous_mode: bool = False
    bind_interface: str = ""
    bind_interface_name: str = ""
    proxy_type: str = "none"
    proxy_hostname: str = ""
    proxy_port: int = 1080
    proxy_username: str = ""
    proxy_password: str = ""
    webui_access: str = "local"
    webui_port: int = 6969
    webui_auth_enabled: bool = False
    webui_username: str = "admin"
    webui_password_hash: str = ""

    def normalized(self) -> "AppSettings":
        self.download_dir = str(Path(self.download_dir).expanduser().resolve())
        if self.completed_dir:
            self.completed_dir = str(Path(self.completed_dir).expanduser().resolve())
        self.listen_port = min(65535, max(1, int(self.listen_port)))
        self.download_limit_kib = max(0, int(self.download_limit_kib))
        self.upload_limit_kib = max(0, int(self.upload_limit_kib))
        self.max_connections = max(10, int(self.max_connections))
        self.max_active_downloads = min(1000, max(1, int(self.max_active_downloads)))
        self.max_active_seeds = min(1000, max(1, int(self.max_active_seeds)))
        self.tracker_list = normalize_tracker_urls(self.tracker_list)
        if self.encryption_mode not in {"prefer", "require", "disabled"}:
            self.encryption_mode = "prefer"
        if self.proxy_type not in {"none", "socks5", "socks5_password"}:
            self.proxy_type = "none"
        self.bind_interface = str(self.bind_interface or "").strip()
        self.bind_interface_name = str(self.bind_interface_name or "").strip()
        self.proxy_hostname = str(self.proxy_hostname or "").strip()
        self.proxy_port = min(65535, max(1, int(self.proxy_port)))
        self.proxy_username = str(self.proxy_username or "").strip()
        self.webui_username = str(self.webui_username or "admin").strip() or "admin"
        if self.webui_access not in {"local", "lan", "tailscale"}:
            self.webui_access = "local"
        self.webui_port = min(65535, max(1, int(self.webui_port)))
        return self


class JsonStore:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or default_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_dir = self.data_dir / "metadata"
        self.resume_dir = self.data_dir / "resume"
        self.metadata_dir.mkdir(exist_ok=True)
        self.resume_dir.mkdir(exist_ok=True)
        self._lock = RLock()

    def _read_json(self, name: str, fallback: Any) -> Any:
        path = self.data_dir / name
        with self._lock:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                return fallback

    def _write_json(self, name: str, value: Any) -> None:
        path = self.data_dir / name
        temporary = path.with_suffix(path.suffix + ".tmp")
        with self._lock:
            temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
            os.replace(temporary, path)

    def load_settings(self) -> AppSettings:
        raw = self._read_json("settings.json", {})
        if isinstance(raw, dict) and "proxy_password" in raw:
            raw["proxy_password"] = unprotect_secret(str(raw["proxy_password"]))
        allowed = {field.name for field in fields(AppSettings)}
        return AppSettings(**{key: value for key, value in raw.items() if key in allowed}).normalized()

    def save_settings(self, settings: AppSettings) -> None:
        raw = asdict(settings.normalized())
        raw["proxy_password"] = protect_secret(settings.proxy_password)
        self._write_json("settings.json", raw)

    def load_records(self) -> dict[str, dict[str, Any]]:
        value = self._read_json("torrents.json", {})
        return value if isinstance(value, dict) else {}

    def save_records(self, records: dict[str, dict[str, Any]]) -> None:
        self._write_json("torrents.json", records)

    def load_block_rules(self) -> list[dict[str, str]]:
        value = self._read_json("blocklist.json", [])
        return value if isinstance(value, list) else []

    def save_block_rules(self, rules: list[dict[str, str]]) -> None:
        self._write_json("blocklist.json", rules)
