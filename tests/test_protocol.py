from __future__ import annotations

import pytest

from apokalypse import protocol


def test_submit_magnet_posts_to_local_api(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    magnet = "magnet:?xt=urn:btih:0123456789012345678901234567890123456789"
    monkeypatch.setattr(protocol, "_post_magnet", lambda value, url: calls.append((value, url)))

    protocol.submit_magnet(magnet)

    assert calls == [(magnet, "http://127.0.0.1:8080")]


def test_submit_magnet_rejects_other_protocols() -> None:
    with pytest.raises(ValueError, match="valid magnet"):
        protocol.submit_magnet("https://example.com/file.torrent")


def test_handler_command_passes_the_clicked_uri() -> None:
    command = protocol.handler_command()
    assert "-m apokalypse.main --magnet" in command
    assert '"%1"' in command
