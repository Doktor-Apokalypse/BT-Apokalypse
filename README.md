# BT Apokalypse

BT Apokalypse is a self-hosted BitTorrent client with a browser interface. Its transfer engine is
[libtorrent](https://www.libtorrent.org/), with FastAPI serving a local WebUI.

## Features

- Add magnet links and `.torrent` files
- Mainline DHT, peer exchange (PEX), local peer discovery, UPnP, NAT-PMP, trackers, and web seeds through libtorrent
- Normal or sequential piece downloading
- Per-torrent file selection and priorities
- Pause, resume, recheck, reannounce, queue ordering, speed limits, and connection limits
- A separate download folder for each torrent
- Optional automatic moves to a completed folder while continuing to seed
- Persistent fast-resume data and automatic restoration after restarting
- Peer inspection and one-click persistent IP bans
- PeerGuardian, eMule, CIDR, IP-range, and single-IP blocklist imports from a file or URL
- Server-side folder browser, including Windows drive selection

## Run it

Python 3.11 or newer is required. From PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
apokalypse
```

Open <http://127.0.0.1:8080>. The WebUI listens on localhost by default. Torrent traffic listens on
port `6881` by default and can be changed in Settings.

The configured folders are paths on the computer running BT Apokalypse. The process must have read and
write access to them. Application state is stored in `./data`; set `APOKALYPSE_DATA_DIR` to place it
elsewhere.

For development dependencies and tests:

```powershell
python -m pip install -e ".[dev]"
pytest
```

## API

Interactive API documentation is available at <http://127.0.0.1:8080/docs>. The REST API exposes
torrents, files, peers, trackers, session settings, filesystem browsing, and blocklist management.

Use BitTorrent only for content you are legally allowed to download and share.
