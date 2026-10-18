from __future__ import annotations

import pytest

from apokalypse import protocol


def test_submit_magnet_posts_to_configured_local_api(monkeypatch, tmp_path) -> None:
    calls: list[tuple[str, str]] = []
    magnet = "magnet:?xt=urn:btih:0123456789012345678901234567890123456789"
    monkeypatch.setenv("APOKALYPSE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(protocol, "_post_magnet", lambda value, url: calls.append((value, url)))

    protocol.submit_magnet(magnet)

    assert calls == [(magnet, "http://127.0.0.1:6969")]


def test_submit_magnet_rejects_other_protocols() -> None:
    with pytest.raises(ValueError, match="valid magnet"):
        protocol.submit_magnet("https://example.com/file.torrent")


def test_handler_command_passes_the_clicked_uri(monkeypatch) -> None:
    monkeypatch.setattr(protocol, "_packaged_executable", lambda: None)
    command = protocol.handler_command()
    assert "-m apokalypse.main --magnet" in command
    assert '"%1"' in command


def test_development_handler_prefers_branded_package(monkeypatch, tmp_path) -> None:
    executable = tmp_path / "BT Apokalypse.exe"
    executable.touch()
    monkeypatch.setattr(protocol, "_packaged_executable", lambda: executable)

    assert protocol.handler_command() == f'"{executable}" --magnet "%1"'


def test_frozen_handler_uses_the_packaged_executable(monkeypatch) -> None:
    monkeypatch.setattr(protocol.sys, "frozen", True, raising=False)
    monkeypatch.setattr(protocol.sys, "executable", r"C:\Program Files\BT Apokalypse\BT Apokalypse.exe")

    command = protocol.handler_command()

    assert command.startswith('"C:\\Program Files\\BT Apokalypse\\BT Apokalypse.exe"')
    assert '--magnet "%1"' in command
