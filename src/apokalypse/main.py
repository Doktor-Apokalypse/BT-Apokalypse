"""Application and magnet protocol entry point."""

import argparse
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import webbrowser


def run() -> None:
    """Run the web application."""
    parser = argparse.ArgumentParser(prog="apokalypse")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--open-browser", action="store_true", help="open the WebUI after startup")
    parser.add_argument("--no-browser", action="store_true", help="do not open the WebUI after startup")
    parser.add_argument("--tray", action="store_true", help="show a Windows notification-area icon")
    parser.add_argument("--no-tray", action="store_true", help="do not show a notification-area icon")
    parser.add_argument("--magnet", help="submit a magnet URI to the local client")
    parser.add_argument("--register-magnet", action="store_true", help="register as the Windows magnet handler")
    parser.add_argument("--unregister-magnet", action="store_true", help="restore the previous magnet handler")
    parser.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    from apokalypse.protocol import (
        register_magnet_handler,
        submit_magnet,
        unregister_magnet_handler,
        write_handler_error,
    )

    if args.register_magnet:
        print(register_magnet_handler())
        return
    if args.unregister_magnet:
        print(unregister_magnet_handler())
        return
    if args.self_test:
        from pathlib import Path

        from apokalypse.config import JsonStore
        from apokalypse.engine import TorrentEngine
        from apokalypse.web import STATIC_DIR

        with tempfile.TemporaryDirectory(prefix="bt-apokalypse-") as temporary_dir:
            torrent_engine = TorrentEngine(JsonStore(Path(temporary_dir)), start_worker=False)
            try:
                status = torrent_engine.session_status()
                if not status["libtorrent_version"]:
                    raise RuntimeError("libtorrent failed to initialize")
                required_assets = ("logo.png", "favicon-32.ico", "favicon-64.ico", "tray-icon.ico")
                if not all(STATIC_DIR.joinpath(asset).is_file() for asset in required_assets):
                    raise RuntimeError("WebUI static assets are missing")
            finally:
                torrent_engine.close()
        return
    if args.magnet:
        try:
            submit_magnet(args.magnet, f"http://127.0.0.1:{args.port}")
        except Exception as exc:
            write_handler_error(exc)
            raise
        return

    import uvicorn
    from apokalypse.web import app

    web_url = f"http://127.0.0.1:{args.port}"
    try:
        with urllib.request.urlopen(web_url + "/api/status", timeout=0.5):
            if not args.no_browser:
                webbrowser.open(web_url)
            return
    except (OSError, urllib.error.URLError):
        pass

    should_open_browser = args.open_browser or (getattr(sys, "frozen", False) and not args.no_browser)
    if should_open_browser:
        browser_timer = threading.Timer(1.2, webbrowser.open, args=(web_url,))
        browser_timer.daemon = True
        browser_timer.start()

    config = uvicorn.Config(app, host=args.host, port=args.port, loop="asyncio", http="h11")
    server = uvicorn.Server(config)
    tray_icon = None
    should_show_tray = sys.platform == "win32" and not args.no_tray and (args.tray or getattr(sys, "frozen", False))
    if should_show_tray:
        try:
            from apokalypse.tray import TrayIcon

            tray_icon = TrayIcon(web_url, lambda: setattr(server, "should_exit", True))
            tray_icon.start()
        except Exception as exc:
            write_handler_error(RuntimeError(f"Could not start the task tray icon: {exc}"))

    try:
        server.run()
    finally:
        if tray_icon is not None:
            tray_icon.stop()


if __name__ == "__main__":
    run()
