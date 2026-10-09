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
- Windows `magnet:` protocol integration for links clicked in Chrome, Edge, Firefox, and other browsers

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

On Windows, open **Settings → Browser integration** and enable the magnet handler. Browsers may show a
one-time confirmation before opening BT Apokalypse. If the client is not running when a magnet link is
clicked, the handler starts it in the background and then adds the torrent. The setting is reversible
and restores the previous per-user magnet handler when one was present. Fully restart browsers that
still show the name of an older torrent client, then choose BT Apokalypse once and allow future links.

The same integration can be managed from PowerShell:

```powershell
apokalypse --register-magnet
apokalypse --unregister-magnet
```

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

## Build the Windows application

The Windows release uses a PyInstaller one-folder bundle. This is more reliable for libtorrent's native
extension than unpacking a one-file executable on every launch. The optional installer uses Inno Setup 6.

```powershell
python -m pip install -e ".[dev]"
powershell -NoProfile -ExecutionPolicy Bypass -File .\build-windows.ps1
```

Build outputs:

- `dist\BT Apokalypse\BT Apokalypse.exe` — portable standalone application folder
- `release\BT-Apokalypse-Setup-0.1.0.exe` — installer, when Inno Setup 6 is installed

The installer installs per-user without administrator access, creates Start Menu shortcuts, offers a
desktop shortcut, and can register the `magnet:` protocol. Installed application data is kept in
`%LOCALAPPDATA%\BT Apokalypse`, separate from the program files. Run the build on Windows x64 to produce
the Windows x64 release.

Use BitTorrent only for content you are legally allowed to download and share.
