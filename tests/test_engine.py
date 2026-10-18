from __future__ import annotations

from pathlib import Path

import libtorrent as lt

from apokalypse.config import JsonStore
from apokalypse.engine import TorrentEngine, _is_complete


def test_paused_finished_torrent_is_complete() -> None:
    class PausedFinishedStatus:
        paused = True
        is_finished = True
        is_seeding = False

    assert _is_complete(PausedFinishedStatus()) is True


def make_torrent(folder: Path) -> bytes:
    source = folder / "sample.txt"
    source.write_text("BT Apokalypse test payload", encoding="utf-8")
    storage = lt.file_storage()
    lt.add_files(storage, str(source))
    creator = lt.create_torrent(storage)
    creator.add_tracker("udp://tracker.example:80/announce")
    lt.set_piece_hashes(creator, str(folder))
    return bytes(lt.bencode(creator.generate()))


def test_add_manage_and_remove_torrent(tmp_path: Path) -> None:
    engine = TorrentEngine(JsonStore(tmp_path / "state"), start_worker=False)
    try:
        result = engine.add_torrent_bytes(make_torrent(tmp_path), str(tmp_path / "downloads"), sequential=True)
        torrent_id = result["id"]

        assert result["sequential"] is True
        assert engine.list_torrents()[0]["id"] == torrent_id
        assert engine.files(torrent_id)[0]["path"].endswith("sample.txt")
        assert engine.trackers(torrent_id)[0]["url"].startswith("udp://")

        engine.action(torrent_id, "pause")
        engine.update_torrent(torrent_id, {"sequential": False, "download_limit_kib": 100})
        assert engine.get_torrent(torrent_id)["sequential"] is False

        settings = engine.update_settings({"max_active_downloads": 7, "max_active_seeds": 11})
        session_settings = engine.session.get_settings()
        assert settings["max_active_downloads"] == 7
        assert settings["max_active_seeds"] == 11
        assert session_settings["active_downloads"] == 7
        assert session_settings["active_seeds"] == 11
        assert session_settings["active_limit"] == 18
        assert session_settings["dont_count_slow_torrents"] is False

        engine.remove(torrent_id)
        assert engine.list_torrents() == []
    finally:
        engine.close()


def test_global_and_individual_tracker_lists(tmp_path: Path) -> None:
    store = JsonStore(tmp_path / "state")
    engine = TorrentEngine(store, start_worker=False)
    try:
        settings = engine.update_settings(
            {
                "add_trackers_to_new_torrents": True,
                "tracker_list": [
                    "udp://tracker.example:80/announce",
                    "https://tracker.two.example/announce",
                    "https://tracker.two.example/announce",
                ],
            }
        )
        assert settings["tracker_list"] == [
            "udp://tracker.example:80/announce",
            "https://tracker.two.example/announce",
        ]

        result = engine.add_torrent_bytes(make_torrent(tmp_path), str(tmp_path / "downloads"))
        torrent_id = result["id"]
        urls = [tracker["url"] for tracker in engine.trackers(torrent_id)]
        assert urls.count("udp://tracker.example:80/announce") == 1
        assert "https://tracker.two.example/announce" in urls

        trackers = engine.add_trackers(
            torrent_id,
            ["https://tracker.two.example/announce", "udp://tracker.manual.example:6969/announce"],
        )
        urls = [tracker["url"] for tracker in trackers]
        assert urls.count("https://tracker.two.example/announce") == 1
        assert "udp://tracker.manual.example:6969/announce" in urls

        manual_index = next(
            tracker["index"]
            for tracker in trackers
            if tracker["url"] == "udp://tracker.manual.example:6969/announce"
        )
        remaining = engine.remove_tracker(torrent_id, manual_index)
        assert "udp://tracker.manual.example:6969/announce" not in {
            tracker["url"] for tracker in remaining
        }
    finally:
        engine.close()

    saved = store.load_settings()
    assert saved.add_trackers_to_new_torrents is True
    assert saved.tracker_list == [
        "udp://tracker.example:80/announce",
        "https://tracker.two.example/announce",
    ]


def test_block_rules_are_persistent(tmp_path: Path) -> None:
    store = JsonStore(tmp_path / "state")
    engine = TorrentEngine(store, start_worker=False)
    try:
        assert engine.add_blocklist("203.0.113.0/24") == {"added": 1, "total": 1}
        assert engine.ban_ip("198.51.100.4") == {"added": 1, "total": 2}
    finally:
        engine.close()

    assert len(store.load_block_rules()) == 2
