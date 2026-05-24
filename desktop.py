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


def deny_media_permissions() -> None:
    """Deny camera/microphone/photo permission requests from WKWebView."""
    if sys.platform != "darwin":
        return
    try:
        import objc
        from Foundation import NSObject

        WKUIDelegate = objc.protocolNamed("WKUIDelegate")

        class _NoMediaDelegate(NSObject, protocols=[WKUIDelegate]):
            @objc.python_method
            def webView_requestMediaCapturePermissionForOrigin_initiatedByFrame_type_decisionHandler_(
                self, webView, origin, frame, type_, handler
            ):
                # 1 = WKPermissionDecisionDeny
                handler(1)

        _deny_delegate = _NoMediaDelegate.alloc().init()

        # Patch pywebview's window creation to install this delegate after the
        # WKWebView is instantiated. We monkey-patch the private _webview attr
        # once the main window is created.
        def _install(wv_window):
            try:
                wv = wv_window._browser.webview  # pywebview cocoa backend
                wv.setUIDelegate_(_deny_delegate)
                _deny_delegate.retain()
            except Exception:
                pass

        import webview as _wv
        _orig_create = _wv.create_window

        def _patched_create(*a, **kw):
            win = _orig_create(*a, **kw)
            # defer until webview.start() has initialised the window
            def _later():
                import time; time.sleep(0.5)
                _install(win)
            threading.Thread(target=_later, daemon=True).start()
            return win

        _wv.create_window = _patched_create
    except Exception:
        pass


def main() -> None:
    os.environ.setdefault("MINDINGUFLAC_DESKTOP", "1")
    import app

    server = app.create_server("127.0.0.1", 0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, name="mindinguflac-http", daemon=True)
    thread.start()

    icon_path = resource_path("static/assets/app_icon.png")
    url = f"http://127.0.0.1:{port}/"
    force_dark_appearance()
    deny_media_permissions()

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
