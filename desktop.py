from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import webview


APP_NAME = "Mindinguflac"
DARK_BACKGROUND = "#090b10"


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


def force_dark_appearance() -> None:
    if sys.platform != "darwin":
        return
    try:
        from AppKit import NSAppearance, NSApplication

        appearance = NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua")
        if appearance:
            NSApplication.sharedApplication().setAppearance_(appearance)
    except Exception:
        pass


def main() -> None:
    os.environ.setdefault("MINDINGUFLAC_DESKTOP", "1")
    import app

    server = app.create_server("127.0.0.1", 0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, name="mindinguflac-http", daemon=True)
    thread.start()

    icon_path = resource_path("static/assets/mindinguflac_icon.png")
    url = f"http://127.0.0.1:{port}/"
    force_dark_appearance()

    try:
        webview.create_window(
            APP_NAME,
            url,
            width=1280,
            height=820,
            min_size=(960, 640),
            background_color=DARK_BACKGROUND,
        )
        webview.start(icon=str(icon_path) if icon_path.exists() else None)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
