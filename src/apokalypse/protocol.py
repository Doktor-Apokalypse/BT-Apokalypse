from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from .config import default_data_dir

MAGNET_KEY = r"Software\Classes\magnet"
TORRENT_EXTENSION_KEY = r"Software\Classes\.torrent"
MAGNET_PROG_ID = "BT.Apokalypse.Magnet"
TORRENT_PROG_ID = "BT.Apokalypse.Torrent"
MAGNET_PROG_ID_KEY = rf"Software\Classes\{MAGNET_PROG_ID}"
TORRENT_PROG_ID_KEY = rf"Software\Classes\{TORRENT_PROG_ID}"
APPLICATION_KEY = r"Software\BT Apokalypse"
REGISTERED_APPLICATIONS_KEY = r"Software\RegisteredApplications"
MAGNET_USER_CHOICE_KEY = (
    r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\magnet\UserChoice"
)
TORRENT_USER_CHOICE_KEY = (
    r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.torrent\UserChoice"
)
BACKUP_FILE = "magnet-handler-backup.json"


def _pythonw_path() -> Path:
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return candidate if candidate.exists() else Path(sys.executable)


def _packaged_executable() -> Path | None:
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    candidate = Path(__file__).resolve().parents[2] / "dist" / "BT Apokalypse" / "BT Apokalypse.exe"
    return candidate if candidate.is_file() else None


def handler_command(kind: str = "magnet") -> str:
    packaged_executable = _packaged_executable()
    option = "--torrent" if kind == "torrent" else "--magnet"
    if packaged_executable:
        return f'"{packaged_executable}" {option} "%1"'
    return f'"{_pythonw_path()}" -m apokalypse.main {option} "%1"'


def _application_executable() -> Path:
    return _packaged_executable() or _pythonw_path()


def _notify_association_changed() -> None:
    try:
        import ctypes

        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
    except (AttributeError, OSError):
        pass


def open_default_apps() -> None:
    if os.name == "nt":
        os.startfile("ms-settings:defaultapps?registeredAppUser=BT%20Apokalypse")  # type: ignore[attr-defined]


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
        return {
            "supported": False,
            "registered": False,
            "magnet_registered": False,
            "torrent_registered": False,
            "command": "",
        }
    magnet_command = _read_registry_value(MAGNET_KEY + r"\shell\open\command")
    magnet_prog_id_command = _read_registry_value(MAGNET_PROG_ID_KEY + r"\shell\open\command")
    torrent_prog_id_command = _read_registry_value(TORRENT_PROG_ID_KEY + r"\shell\open\command")
    torrent_default = _read_registry_value(TORRENT_EXTENSION_KEY)
    magnet_user_choice = _read_registry_value(MAGNET_USER_CHOICE_KEY, "ProgId")
    torrent_user_choice = _read_registry_value(TORRENT_USER_CHOICE_KEY, "ProgId")
    registered_capabilities = _read_registry_value(REGISTERED_APPLICATIONS_KEY, "BT Apokalypse")
    expected_magnet = handler_command("magnet")
    expected_torrent = handler_command("torrent")
    magnet_registered = (
        magnet_command.casefold() == expected_magnet.casefold()
        and magnet_prog_id_command.casefold() == expected_magnet.casefold()
        and (
            not magnet_user_choice
            or magnet_user_choice.casefold() == MAGNET_PROG_ID.casefold()
        )
    )
    torrent_registered = (
        torrent_default.casefold() == TORRENT_PROG_ID.casefold()
        and torrent_prog_id_command.casefold() == expected_torrent.casefold()
        and (
            not torrent_user_choice
            or torrent_user_choice.casefold() == TORRENT_PROG_ID.casefold()
        )
    )
    return {
        "supported": True,
        "registered": (
            magnet_registered
            and torrent_registered
            and registered_capabilities.casefold()
            == (APPLICATION_KEY + r"\Capabilities").casefold()
        ),
        "magnet_registered": magnet_registered,
        "torrent_registered": torrent_registered,
        "windows_confirmation_required": bool(
            (magnet_user_choice and magnet_user_choice.casefold() != MAGNET_PROG_ID.casefold())
            or (torrent_user_choice and torrent_user_choice.casefold() != TORRENT_PROG_ID.casefold())
        ),
        "command": magnet_command,
    }


def register_magnet_handler() -> dict[str, Any]:
    if os.name != "nt":
        raise RuntimeError("OS-level torrent registration is currently supported on Windows only")
    import winreg

    current_magnet_command = _read_registry_value(MAGNET_KEY + r"\shell\open\command")
    current_torrent_default = _read_registry_value(TORRENT_EXTENSION_KEY)
    expected_magnet = handler_command("magnet")
    expected_torrent = handler_command("torrent")
    backup_path = default_data_dir() / BACKUP_FILE
    backup: dict[str, Any] = {}
    if backup_path.exists():
        try:
            backup = json.loads(backup_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            backup = {}
    backup.setdefault("magnet_command", backup.get("command", current_magnet_command))
    backup.setdefault("torrent_default", current_torrent_default)
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path.write_text(json.dumps(backup, indent=2), encoding="utf-8")

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, MAGNET_KEY) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:Magnet Protocol")
        winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, MAGNET_KEY + r"\DefaultIcon") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'"{_application_executable()}",0')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, MAGNET_KEY + r"\shell\open\command") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, expected_magnet)

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, MAGNET_PROG_ID_KEY) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "BT Apokalypse Magnet Link")
        winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, MAGNET_PROG_ID_KEY + r"\DefaultIcon") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'"{_application_executable()}",0')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, MAGNET_PROG_ID_KEY + r"\shell\open\command") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, expected_magnet)

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, TORRENT_EXTENSION_KEY) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, TORRENT_PROG_ID)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, TORRENT_EXTENSION_KEY + r"\OpenWithProgids") as key:
        winreg.SetValueEx(key, TORRENT_PROG_ID, 0, winreg.REG_NONE, b"")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, TORRENT_PROG_ID_KEY) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "BT Apokalypse Torrent File")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, TORRENT_PROG_ID_KEY + r"\DefaultIcon") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'"{_application_executable()}",0')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, TORRENT_PROG_ID_KEY + r"\shell\open\command") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, expected_torrent)

    capabilities_key = APPLICATION_KEY + r"\Capabilities"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, capabilities_key) as key:
        winreg.SetValueEx(key, "ApplicationName", 0, winreg.REG_SZ, "BT Apokalypse")
        winreg.SetValueEx(
            key,
            "ApplicationDescription",
            0,
            winreg.REG_SZ,
            "A self-hosted BitTorrent client with a browser interface",
        )
        winreg.SetValueEx(key, "ApplicationIcon", 0, winreg.REG_SZ, f'"{_application_executable()}",0')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, capabilities_key + r"\URLAssociations") as key:
        winreg.SetValueEx(key, "magnet", 0, winreg.REG_SZ, MAGNET_PROG_ID)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, capabilities_key + r"\FileAssociations") as key:
        winreg.SetValueEx(key, ".torrent", 0, winreg.REG_SZ, TORRENT_PROG_ID)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REGISTERED_APPLICATIONS_KEY) as key:
        winreg.SetValueEx(key, "BT Apokalypse", 0, winreg.REG_SZ, capabilities_key)
    _notify_association_changed()
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
        raise RuntimeError("OS-level torrent registration is currently supported on Windows only")
    import winreg

    active_command = _read_registry_value(MAGNET_KEY + r"\shell\open\command")
    if active_command.casefold() == handler_command("magnet").casefold():
        _delete_registry_tree(winreg.HKEY_CURRENT_USER, MAGNET_KEY)
    _delete_registry_tree(winreg.HKEY_CURRENT_USER, MAGNET_PROG_ID_KEY)
    _delete_registry_tree(winreg.HKEY_CURRENT_USER, TORRENT_PROG_ID_KEY)
    _delete_registry_tree(winreg.HKEY_CURRENT_USER, APPLICATION_KEY)
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            TORRENT_EXTENSION_KEY + r"\OpenWithProgids",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, TORRENT_PROG_ID)
    except FileNotFoundError:
        pass
    try:
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, REGISTERED_APPLICATIONS_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, "BT Apokalypse")
    except FileNotFoundError:
        pass

    backup_path = default_data_dir() / BACKUP_FILE
    if backup_path.exists():
        try:
            backup = json.loads(backup_path.read_text(encoding="utf-8"))
            previous_magnet = backup.get("magnet_command") or backup.get("command", "")
            previous_torrent = backup.get("torrent_default", "")
            if previous_magnet:
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, MAGNET_KEY) as key:
                    winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:Magnet Protocol")
                    winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, MAGNET_KEY + r"\shell\open\command") as key:
                    winreg.SetValueEx(key, "", 0, winreg.REG_SZ, previous_magnet)
            if _read_registry_value(TORRENT_EXTENSION_KEY).casefold() == TORRENT_PROG_ID.casefold():
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, TORRENT_EXTENSION_KEY) as key:
                    if previous_torrent:
                        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, previous_torrent)
                    else:
                        try:
                            winreg.DeleteValue(key, "")
                        except FileNotFoundError:
                            pass
        finally:
            backup_path.unlink(missing_ok=True)
    _notify_association_changed()
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


def _post_torrent_file(path: Path, contents: bytes, api_url: str) -> None:
    boundary = "----BTApokalypse" + uuid.uuid4().hex
    safe_name = path.name.replace('"', "_")
    prefix = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="torrent"; filename="{safe_name}"\r\n'
        "Content-Type: application/x-bittorrent\r\n\r\n"
    ).encode("utf-8")
    body = prefix + contents + f"\r\n--{boundary}--\r\n".encode("ascii")
    request = urllib.request.Request(
        api_url.rstrip("/") + "/api/torrents/file",
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "BT-Apokalypse-Torrent-Handler/0.1",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        if response.status not in {200, 201}:
            raise RuntimeError(f"BT Apokalypse returned HTTP {response.status}")


def _start_client() -> None:
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    command = (
        [sys.executable, "--no-browser"]
        if getattr(sys, "frozen", False)
        else [str(_pythonw_path()), "-m", "apokalypse.main", "--no-browser"]
    )
    subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creation_flags,
    )


def submit_magnet(magnet: str, api_url: str | None = None) -> None:
    if not magnet.lower().startswith("magnet:?"):
        raise ValueError("A valid magnet URI is required")
    if api_url is None:
        from .config import JsonStore

        api_url = f"http://127.0.0.1:{JsonStore().load_settings().webui_port}"
    try:
        _post_magnet(magnet, api_url)
        return
    except urllib.error.HTTPError as exc:
        if 400 <= exc.code < 500:
            return
        raise RuntimeError(f"BT Apokalypse returned HTTP {exc.code}") from exc
    except (OSError, urllib.error.URLError):
        pass

    _start_client()
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


def submit_torrent_file(torrent_path: str | Path, api_url: str | None = None) -> None:
    path = Path(torrent_path).expanduser().resolve()
    if path.suffix.casefold() != ".torrent" or not path.is_file():
        raise ValueError("A valid .torrent file is required")
    contents = path.read_bytes()
    if len(contents) > 20 * 1024 * 1024:
        raise ValueError("Torrent files may not exceed 20 MiB")
    if api_url is None:
        from .config import JsonStore

        api_url = f"http://127.0.0.1:{JsonStore().load_settings().webui_port}"
    try:
        _post_torrent_file(path, contents, api_url)
        return
    except urllib.error.HTTPError as exc:
        if 400 <= exc.code < 500:
            return
        raise RuntimeError(f"BT Apokalypse returned HTTP {exc.code}") from exc
    except (OSError, urllib.error.URLError):
        pass

    _start_client()
    last_error: Exception | None = None
    for _ in range(30):
        time.sleep(0.5)
        try:
            _post_torrent_file(path, contents, api_url)
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
