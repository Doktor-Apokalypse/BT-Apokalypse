from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from threading import RLock
from typing import Any


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
        allowed = {field.name for field in fields(AppSettings)}
        return AppSettings(**{key: value for key, value in raw.items() if key in allowed}).normalized()

    def save_settings(self, settings: AppSettings) -> None:
        self._write_json("settings.json", asdict(settings.normalized()))

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
