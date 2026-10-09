"""Windows notification-area controls for the packaged backend."""

from __future__ import annotations

import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any


class TrayIcon:
    """Run a small notification-area menu alongside the web server."""

    def __init__(self, web_url: str, request_shutdown: Callable[[], None]) -> None:
        self.web_url = web_url
        self.request_shutdown = request_shutdown
        self._icon: Any = None

    def start(self) -> None:
        """Create the icon and start its Windows message loop."""
        import pystray
        from PIL import Image

        logo_path = Path(__file__).with_name("static") / "tray-icon.ico"
        with Image.open(logo_path) as source:
            image = source.convert("RGBA")

        menu = pystray.Menu(
            pystray.MenuItem("Open WebUI", self._open_webui, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit BT Apokalypse", self._exit_application),
        )
        icon = pystray.Icon("bt_apokalypse", image, "BT Apokalypse", menu)
        self._icon = icon
        icon.run_detached()

    def stop(self) -> None:
        """Remove the icon and stop its message loop."""
        icon = self._icon
        if icon is not None:
            icon.stop()

    def _open_webui(self, _icon: Any = None, _item: Any = None) -> None:
        webbrowser.open(self.web_url)

    def _exit_application(self, icon: Any, _item: Any = None) -> None:
        self.request_shutdown()
        icon.stop()
