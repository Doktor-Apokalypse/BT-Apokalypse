from __future__ import annotations

import ipaddress
import logging
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import libtorrent as lt

from .blocklist import BlockRule, parse_blocklist
from .config import JsonStore

log = logging.getLogger(__name__)


def _hash_string(handle: lt.torrent_handle) -> str:
    hashes = handle.info_hashes()
    v1 = str(hashes.v1)
    return v1 if v1 and v1 != "0000000000000000000000000000000000000000" else str(hashes.v2)


def _state_name(status: lt.torrent_status) -> str:
    if status.errc and status.errc.value():
        return "error"
    if status.paused:
        return "paused"
    if status.is_seeding:
        return "seeding"
    if status.is_finished:
        return "completed"
    names = {
        lt.torrent_status.states.checking_files: "checking",
        lt.torrent_status.states.downloading_metadata: "metadata",
        lt.torrent_status.states.downloading: "downloading",
        lt.torrent_status.states.finished: "completed",
        lt.torrent_status.states.seeding: "seeding",
        lt.torrent_status.states.checking_resume_data: "checking",
    }
    return names.get(status.state, "queued")


class TorrentEngine:
    """Thread-safe facade around one libtorrent session."""

    def __init__(self, store: JsonStore | None = None, start_worker: bool = True) -> None:
        self.store = store or JsonStore()
        self.settings = self.store.load_settings()
        self.records = self.store.load_records()
        self.block_rules = [BlockRule(**rule) for rule in self.store.load_block_rules()]
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._handles: dict[str, lt.torrent_handle] = {}
        self.session = self._make_session()
        self._apply_blocklist()
        self._restore_torrents()
        self._worker: threading.Thread | None = None
        if start_worker:
            worker = threading.Thread(target=self._run, name="torrent-engine", daemon=True)
            self._worker = worker
            worker.start()

    def _make_session(self) -> lt.session:
        settings = {
            "user_agent": "BT Apokalypse/0.1 libtorrent/" + lt.__version__,
            "listen_interfaces": f"0.0.0.0:{self.settings.listen_port},[::]:{self.settings.listen_port}",
            "enable_dht": self.settings.enable_dht,
            "enable_lsd": self.settings.enable_lsd,
            "enable_upnp": self.settings.enable_upnp,
            "enable_natpmp": self.settings.enable_natpmp,
            "download_rate_limit": self.settings.download_limit_kib * 1024,
            "upload_rate_limit": self.settings.upload_limit_kib * 1024,
            "connections_limit": self.settings.max_connections,
            "active_downloads": self.settings.max_active_downloads,
            "active_seeds": self.settings.max_active_seeds,
            "active_limit": self.settings.max_active_downloads + self.settings.max_active_seeds,
            "dont_count_slow_torrents": False,
            "alert_mask": int(lt.alert.category_t.all_categories),
        }
        return lt.session(settings)

    def _restore_torrents(self) -> None:
        for torrent_id, record in list(self.records.items()):
            try:
                resume_path = self.store.resume_dir / f"{torrent_id}.fastresume"
                if resume_path.exists():
                    params = lt.read_resume_data(resume_path.read_bytes())
                elif record.get("metadata_file"):
                    params = lt.load_torrent_file(record["metadata_file"])
                elif record.get("magnet"):
                    params = lt.parse_magnet_uri(record["magnet"])
                else:
                    continue
                params.save_path = record.get("save_path") or self.settings.download_dir
                self._apply_torrent_features(params)
                handle = self.session.add_torrent(params)
                handle.set_sequential_download(bool(record.get("sequential")))
                if not record.get("started", self.settings.auto_start):
                    handle.pause()
                self._handles[_hash_string(handle)] = handle
            except Exception as exc:  # corrupt resume data must not prevent startup
                log.warning("Could not restore torrent %s: %s", torrent_id, exc)

    def _persist_records(self) -> None:
        self.store.save_records(self.records)

    def _run(self) -> None:
        next_resume = time.monotonic() + 30
        while not self._stop.wait(0.5):
            self._process_alerts()
            if time.monotonic() >= next_resume:
                self.save_resume_data()
                next_resume = time.monotonic() + 30

    def _process_alerts(self) -> set[str]:
        resume_finished: set[str] = set()
        with self._lock:
            for alert in self.session.pop_alerts():
                if isinstance(alert, lt.save_resume_data_alert):
                    torrent_id = _hash_string(alert.handle)
                    path = self.store.resume_dir / f"{torrent_id}.fastresume"
                    path.write_bytes(bytes(lt.write_resume_data_buf(alert.params)))
                    resume_finished.add(torrent_id)
                elif isinstance(alert, lt.save_resume_data_failed_alert):
                    resume_finished.add(_hash_string(alert.handle))
                elif isinstance(alert, lt.torrent_finished_alert):
                    self._on_finished(alert.handle)
                elif isinstance(alert, lt.metadata_received_alert):
                    torrent_id = _hash_string(alert.handle)
                    if torrent_id in self.records:
                        self.records[torrent_id]["name"] = alert.handle.name()
                        alert.handle.save_resume_data(lt.save_resume_flags_t.save_info_dict)
                        self._persist_records()
                elif isinstance(alert, lt.storage_moved_alert):
                    torrent_id = _hash_string(alert.handle)
                    if torrent_id in self.records:
                        self.records[torrent_id]["save_path"] = alert.path
                        self._persist_records()
                elif isinstance(alert, lt.torrent_error_alert):
                    log.warning("Torrent error: %s", alert.message())
        return resume_finished

    def _on_finished(self, handle: lt.torrent_handle) -> None:
        torrent_id = _hash_string(handle)
        record = self.records.get(torrent_id, {})
        completed_path = record.get("completed_path")
        if record.get("move_completed") and completed_path:
            Path(completed_path).mkdir(parents=True, exist_ok=True)
            handle.move_storage(completed_path, lt.move_flags_t.always_replace_files)
        handle.save_resume_data(lt.save_resume_flags_t.save_info_dict)

    def _apply_torrent_features(self, params: lt.add_torrent_params) -> None:
        if self.settings.enable_pex:
            params.flags &= ~lt.torrent_flags.disable_pex
        else:
            params.flags |= lt.torrent_flags.disable_pex

    def save_resume_data(self) -> None:
        with self._lock:
            for handle in list(self._handles.values()):
                if handle.is_valid():
                    try:
                        handle.save_resume_data(lt.save_resume_flags_t.save_info_dict)
                    except RuntimeError:
                        pass

    def close(self) -> None:
        self._stop.set()
        pending = {torrent_id for torrent_id, handle in self._handles.items() if handle.is_valid()}
        self.save_resume_data()
        deadline = time.monotonic() + 3
        while pending and time.monotonic() < deadline:
            pending.difference_update(self._process_alerts())
            time.sleep(0.05)
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=1)

    def add_magnet(
        self,
        magnet: str,
        save_path: str | None = None,
        completed_path: str | None = None,
        sequential: bool = False,
        paused: bool = False,
    ) -> dict[str, Any]:
        if not magnet.lower().startswith("magnet:?"):
            raise ValueError("A valid magnet URI is required")
        params = lt.parse_magnet_uri(magnet)
        return self._add(params, save_path, completed_path, sequential, paused, magnet=magnet)

    def add_torrent_bytes(
        self,
        contents: bytes,
        save_path: str | None = None,
        completed_path: str | None = None,
        sequential: bool = False,
        paused: bool = False,
    ) -> dict[str, Any]:
        if len(contents) > 20 * 1024 * 1024:
            raise ValueError("Torrent files may not exceed 20 MiB")
        params = lt.load_torrent_buffer(contents)
        result = self._add(params, save_path, completed_path, sequential, paused)
        metadata_file = self.store.metadata_dir / f"{result['id']}.torrent"
        metadata_file.write_bytes(contents)
        self.records[result["id"]]["metadata_file"] = str(metadata_file)
        self._persist_records()
        return result

    def _add(
        self,
        params: lt.add_torrent_params,
        save_path: str | None,
        completed_path: str | None,
        sequential: bool,
        paused: bool,
        magnet: str = "",
    ) -> dict[str, Any]:
        target = Path(save_path or self.settings.download_dir).expanduser().resolve()
        target.mkdir(parents=True, exist_ok=True)
        params.save_path = str(target)
        self._apply_torrent_features(params)
        with self._lock:
            handle = self.session.add_torrent(params)
            torrent_id = _hash_string(handle)
            if torrent_id in self._handles:
                raise ValueError("This torrent is already in the client")
            handle.set_sequential_download(sequential)
            if paused or not self.settings.auto_start:
                handle.pause()
            self._handles[torrent_id] = handle
            done_path = completed_path if completed_path is not None else self.settings.completed_dir
            should_move = bool(done_path) if completed_path is not None else bool(done_path and self.settings.move_completed)
            self.records[torrent_id] = {
                "name": handle.name(),
                "save_path": str(target),
                "completed_path": str(Path(done_path).expanduser().resolve()) if done_path else "",
                "move_completed": should_move,
                "sequential": sequential,
                "started": not paused,
                "magnet": magnet,
                "added_at": int(time.time()),
            }
            self._persist_records()
            return self.get_torrent(torrent_id)

    def _handle(self, torrent_id: str) -> lt.torrent_handle:
        handle = self._handles.get(torrent_id)
        if not handle or not handle.is_valid():
            raise KeyError(torrent_id)
        return handle

    def list_torrents(self) -> list[dict[str, Any]]:
        with self._lock:
            items = [self._serialize(torrent_id, handle) for torrent_id, handle in self._handles.items()]
        return sorted(items, key=lambda item: item["added_at"], reverse=True)

    def get_torrent(self, torrent_id: str) -> dict[str, Any]:
        with self._lock:
            return self._serialize(torrent_id, self._handle(torrent_id))

    def _serialize(self, torrent_id: str, handle: lt.torrent_handle) -> dict[str, Any]:
        status = handle.status()
        record = self.records.get(torrent_id, {})
        return {
            "id": torrent_id,
            "name": status.name or record.get("name") or torrent_id,
            "state": _state_name(status),
            "error": status.errc.message() if status.errc and status.errc.value() else "",
            "progress": round(status.progress * 100, 2),
            "download_rate": status.download_rate,
            "upload_rate": status.upload_rate,
            "downloaded": status.total_done,
            "uploaded": status.all_time_upload,
            "total_size": status.total_wanted,
            "wanted_done": status.total_wanted_done,
            "peers": status.num_peers,
            "seeds": status.num_seeds,
            "eta": int((status.total_wanted - status.total_wanted_done) / status.download_rate)
            if status.download_rate > 0
            else None,
            "ratio": round(status.all_time_upload / max(1, status.all_time_download), 3),
            "save_path": status.save_path,
            "completed_path": record.get("completed_path", ""),
            "move_completed": record.get("move_completed", False),
            "sequential": record.get("sequential", False),
            "added_at": record.get("added_at", 0),
            "queue_position": handle.queue_position(),
            "has_metadata": handle.has_metadata(),
        }

    def action(self, torrent_id: str, action: str) -> dict[str, Any]:
        with self._lock:
            handle = self._handle(torrent_id)
            actions = {
                "pause": handle.pause,
                "resume": handle.resume,
                "recheck": handle.force_recheck,
                "reannounce": handle.force_reannounce,
                "queue_top": handle.queue_position_top,
                "queue_up": handle.queue_position_up,
                "queue_down": handle.queue_position_down,
                "queue_bottom": handle.queue_position_bottom,
            }
            if action not in actions:
                raise ValueError(f"Unknown action: {action}")
            actions[action]()
            if torrent_id in self.records and action in {"pause", "resume"}:
                self.records[torrent_id]["started"] = action == "resume"
                self._persist_records()
            return self._serialize(torrent_id, handle)

    def update_torrent(self, torrent_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            handle = self._handle(torrent_id)
            record = self.records[torrent_id]
            if "sequential" in changes:
                value = bool(changes["sequential"])
                handle.set_sequential_download(value)
                record["sequential"] = value
            if "download_limit_kib" in changes:
                handle.set_download_limit(max(0, int(changes["download_limit_kib"])) * 1024)
            if "upload_limit_kib" in changes:
                handle.set_upload_limit(max(0, int(changes["upload_limit_kib"])) * 1024)
            if "max_connections" in changes:
                handle.set_max_connections(max(2, int(changes["max_connections"])))
            if "completed_path" in changes:
                path = changes["completed_path"]
                record["completed_path"] = str(Path(path).expanduser().resolve()) if path else ""
            if "move_completed" in changes:
                record["move_completed"] = bool(changes["move_completed"])
            if record.get("move_completed") and record.get("completed_path") and handle.is_finished():
                Path(record["completed_path"]).mkdir(parents=True, exist_ok=True)
                handle.move_storage(record["completed_path"], lt.move_flags_t.always_replace_files)
            self._persist_records()
            return self._serialize(torrent_id, handle)

    def remove(self, torrent_id: str, delete_files: bool = False) -> None:
        with self._lock:
            handle = self._handle(torrent_id)
            options = lt.session.delete_files if delete_files else 0
            self.session.remove_torrent(handle, options)
            self._handles.pop(torrent_id, None)
            record = self.records.pop(torrent_id, {})
            self._persist_records()
            resume_path = self.store.resume_dir / f"{torrent_id}.fastresume"
            if resume_path.is_file():
                resume_path.unlink()
            metadata_file = record.get("metadata_file")
            if metadata_file:
                metadata_path = Path(metadata_file)
                if metadata_path.is_file():
                    metadata_path.unlink()

    def files(self, torrent_id: str) -> list[dict[str, Any]]:
        with self._lock:
            handle = self._handle(torrent_id)
            if not handle.has_metadata():
                return []
            info = handle.torrent_file()
            if info is None:
                return []
            storage = info.files()
            progress = handle.file_progress()
            priorities = handle.file_priorities()
            return [
                {
                    "index": index,
                    "path": storage.file_path(index),
                    "size": storage.file_size(index),
                    "downloaded": progress[index] if index < len(progress) else 0,
                    "progress": round(100 * progress[index] / max(1, storage.file_size(index)), 2),
                    "priority": int(priorities[index]) if index < len(priorities) else 4,
                }
                for index in range(storage.num_files())
            ]

    def set_file_priorities(self, torrent_id: str, priorities: dict[int, int]) -> list[dict[str, Any]]:
        with self._lock:
            handle = self._handle(torrent_id)
            current = [int(value) for value in handle.file_priorities()]
            for index, priority in priorities.items():
                if 0 <= index < len(current):
                    current[index] = min(7, max(0, int(priority)))
            handle.prioritize_files(current)
        return self.files(torrent_id)

    def peers(self, torrent_id: str) -> list[dict[str, Any]]:
        with self._lock:
            peers = self._handle(torrent_id).get_peer_info()
            return [
                {
                    "ip": str(peer.ip[0]),
                    "port": peer.ip[1],
                    "client": peer.client,
                    "progress": round(peer.progress * 100, 1),
                    "download_rate": peer.down_speed,
                    "upload_rate": peer.up_speed,
                    "country": getattr(peer, "country", ""),
                }
                for peer in peers
            ]

    def trackers(self, torrent_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "url": tracker["url"],
                    "tier": tracker.get("tier", 0),
                    "verified": tracker.get("verified", False),
                }
                for tracker in self._handle(torrent_id).trackers()
            ]

    def add_tracker(self, torrent_id: str, url: str, tier: int = 0) -> list[dict[str, Any]]:
        if not url.startswith(("http://", "https://", "udp://", "ws://", "wss://")):
            raise ValueError("Unsupported tracker URL")
        with self._lock:
            self._handle(torrent_id).add_tracker({"url": url, "tier": max(0, tier)})
        return self.trackers(torrent_id)

    def session_status(self) -> dict[str, Any]:
        torrents = self.list_torrents()
        status = self.session.status()
        return {
            "download_rate": sum(item["download_rate"] for item in torrents),
            "upload_rate": sum(item["upload_rate"] for item in torrents),
            "downloaded": sum(item["downloaded"] for item in torrents),
            "uploaded": sum(item["uploaded"] for item in torrents),
            "torrents": len(torrents),
            "connections": self.session.num_connections(),
            "dht_nodes": status.dht_nodes,
            "dht_running": self.session.is_dht_running(),
            "listening": self.session.is_listening(),
            "listen_port": self.session.listen_port() if self.session.is_listening() else 0,
            "libtorrent_version": lt.__version__,
        }

    def update_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        allowed = set(asdict(self.settings))
        for key, value in changes.items():
            if key in allowed:
                setattr(self.settings, key, value)
        self.settings.normalized()
        Path(self.settings.download_dir).mkdir(parents=True, exist_ok=True)
        if self.settings.completed_dir:
            Path(self.settings.completed_dir).mkdir(parents=True, exist_ok=True)
        self.store.save_settings(self.settings)
        self.session.apply_settings(
            {
                "listen_interfaces": f"0.0.0.0:{self.settings.listen_port},[::]:{self.settings.listen_port}",
                "enable_dht": self.settings.enable_dht,
                "enable_lsd": self.settings.enable_lsd,
                "enable_upnp": self.settings.enable_upnp,
                "enable_natpmp": self.settings.enable_natpmp,
                "download_rate_limit": self.settings.download_limit_kib * 1024,
                "upload_rate_limit": self.settings.upload_limit_kib * 1024,
                "connections_limit": self.settings.max_connections,
                "active_downloads": self.settings.max_active_downloads,
                "active_seeds": self.settings.max_active_seeds,
                "active_limit": self.settings.max_active_downloads + self.settings.max_active_seeds,
                "dont_count_slow_torrents": False,
            }
        )
        for handle in self._handles.values():
            if self.settings.enable_pex:
                handle.unset_flags(lt.torrent_flags.disable_pex)
            else:
                handle.set_flags(lt.torrent_flags.disable_pex)
        return asdict(self.settings)

    def get_settings(self) -> dict[str, Any]:
        return asdict(self.settings)

    def _apply_blocklist(self) -> None:
        ip_filter = lt.ip_filter()
        for rule in self.block_rules:
            ip_filter.add_rule(rule.first, rule.last, 1)
        self.session.set_ip_filter(ip_filter)

    def add_blocklist(self, text: str) -> dict[str, int]:
        parsed = parse_blocklist(text)
        existing = {(rule.first, rule.last) for rule in self.block_rules}
        added = [rule for rule in parsed if (rule.first, rule.last) not in existing]
        self.block_rules.extend(added)
        self.store.save_block_rules([rule.as_dict() for rule in self.block_rules])
        self._apply_blocklist()
        return {"added": len(added), "total": len(self.block_rules)}

    def ban_ip(self, address: str) -> dict[str, int]:
        ip = str(ipaddress.IPv4Address(address))
        return self.add_blocklist(ip)

    def clear_blocklist(self) -> None:
        self.block_rules.clear()
        self.store.save_block_rules([])
        self._apply_blocklist()

    def blocklist_status(self) -> dict[str, Any]:
        return {
            "count": len(self.block_rules),
            "rules": [rule.as_dict() for rule in self.block_rules[-200:]],
        }
