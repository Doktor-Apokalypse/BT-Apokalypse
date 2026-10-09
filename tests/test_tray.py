from __future__ import annotations

from apokalypse import tray


class FakeIcon:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


def test_tray_actions_open_webui_and_request_clean_shutdown(monkeypatch) -> None:
    opened: list[str] = []
    shutdown_requested: list[bool] = []
    icon = FakeIcon()
    tray_icon = tray.TrayIcon("http://127.0.0.1:8080", lambda: shutdown_requested.append(True))
    monkeypatch.setattr(tray.webbrowser, "open", opened.append)

    tray_icon._open_webui()
    tray_icon._exit_application(icon)

    assert opened == ["http://127.0.0.1:8080"]
    assert shutdown_requested == [True]
    assert icon.stopped is True


def test_tray_starts_supported_detached_message_loop(monkeypatch) -> None:
    import pystray

    calls: list[str] = []

    class FakeRuntimeIcon:
        def __init__(self) -> None:
            self.calls = calls

        def run_detached(self) -> None:
            self.calls.append("started")

        def stop(self) -> None:
            self.calls.append("stopped")

    monkeypatch.setattr(pystray, "Icon", lambda *_args, **_kwargs: FakeRuntimeIcon())
    tray_icon = tray.TrayIcon("http://127.0.0.1:8080", lambda: None)

    tray_icon.start()
    tray_icon.stop()

    assert calls == ["started", "stopped"]
