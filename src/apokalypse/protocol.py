from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .config import default_data_dir

MAGNET_KEY = r"Software\Classes\magnet"
BACKUP_FILE = "magnet-handler-backup.json"


def _pythonw_path() -> Path:
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return candidate if candidate.exists() else Path(sys.executable)


def handler_command() -> str:
    return f'"{_pythonw_path()}" -m apokalypse.main --magnet "%1"'


def _read_registry_value(subkey: str, name: str = "") -> str:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey) as key:
            value, _ = winreg.QueryValueEx(key, name)
            return str(value)
    except FileNotFoundError:
        return ""


def magnet_handler_status() -> dict[str, Any]:
    if os.name != "nt":
        return {"supported": False, "registered": False, "command": ""}
    command = _read_registry_value(MAGNET_KEY + r"\shell\open\command")
    expected = handler_command()
    return {
        "supported": True,
        "registered": command.casefold() == expected.casefold(),
        "command": command,
    }


def register_magnet_handler() -> dict[str, Any]:
    if os.name != "nt":
        raise RuntimeError("OS-level magnet registration is currently supported on Windows only")
    import winreg

    current = magnet_handler_status()["command"]
    expected = handler_command()
    backup_path = default_data_dir() / BACKUP_FILE
    if current and current.casefold() != expected.casefold() and not backup_path.exists():
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_text(json.dumps({"command": current}, indent=2), encoding="utf-8")

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, MAGNET_KEY) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:Magnet Protocol")
        winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, MAGNET_KEY + r"\DefaultIcon") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'"{_pythonw_path()}"')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, MAGNET_KEY + r"\shell\open\command") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, expected)
    return magnet_handler_status()


def _delete_registry_tree(root: Any, subkey: str) -> None:
    import winreg

    try:
        with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
            while True:
                try:
                    child = winreg.EnumKey(key, 0)
                except OSError:
                    break
                _delete_registry_tree(root, subkey + "\\" + child)
        winreg.DeleteKey(root, subkey)
    except FileNotFoundError:
        pass


def unregister_magnet_handler() -> dict[str, Any]:
    if os.name != "nt":
        raise RuntimeError("OS-level magnet registration is currently supported on Windows only")
    import winreg

    if magnet_handler_status()["registered"]:
        _delete_registry_tree(winreg.HKEY_CURRENT_USER, MAGNET_KEY)

    backup_path = default_data_dir() / BACKUP_FILE
    if backup_path.exists():
        try:
            previous = json.loads(backup_path.read_text(encoding="utf-8")).get("command", "")
            if previous:
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, MAGNET_KEY) as key:
                    winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:Magnet Protocol")
                    winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, MAGNET_KEY + r"\shell\open\command") as key:
                    winreg.SetValueEx(key, "", 0, winreg.REG_SZ, previous)
        finally:
            backup_path.unlink(missing_ok=True)
    return magnet_handler_status()


def _post_magnet(magnet: str, api_url: str) -> None:
    body = json.dumps({"magnet": magnet}).encode("utf-8")
    request = urllib.request.Request(
        api_url.rstrip("/") + "/api/torrents/magnet",
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "BT-Apokalypse-Magnet-Handler/0.1"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        if response.status not in {200, 201}:
            raise RuntimeError(f"BT Apokalypse returned HTTP {response.status}")


def submit_magnet(magnet: str, api_url: str = "http://127.0.0.1:8080") -> None:
    if not magnet.lower().startswith("magnet:?"):
        raise ValueError("A valid magnet URI is required")
    try:
        _post_magnet(magnet, api_url)
        return
    except urllib.error.HTTPError as exc:
        if 400 <= exc.code < 500:
            return
        raise RuntimeError(f"BT Apokalypse returned HTTP {exc.code}") from exc
    except (OSError, urllib.error.URLError):
        pass

    pythonw = _pythonw_path()
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        [str(pythonw), "-m", "apokalypse.main"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creation_flags,
    )
    last_error: Exception | None = None
    for _ in range(30):
        time.sleep(0.5)
        try:
            _post_magnet(magnet, api_url)
            return
        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 500:
                return
            raise RuntimeError(f"BT Apokalypse returned HTTP {exc.code}") from exc
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
    raise RuntimeError("BT Apokalypse did not start in time") from last_error


def write_handler_error(exc: Exception) -> None:
    try:
        data_dir = default_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        with (data_dir / "magnet-handler.log").open("a", encoding="utf-8") as log:
            log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {type(exc).__name__}: {exc}\n")
    except OSError:
        pass
