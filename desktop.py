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


def apply_macos_patches() -> None:
    """Apply various macOS-specific patches (media permissions, dock menu, etc)."""
    if sys.platform != "darwin":
        return
    try:
        import objc
        from AppKit import NSApplication, NSMenu, NSMenuItem
        from Foundation import NSObject

        # 1. Media permissions (WKUIDelegate)
        WKUIDelegate = objc.protocolNamed("WKUIDelegate")

        class _NoMediaDelegate(NSObject, protocols=[WKUIDelegate]):
            @objc.python_method
            def webView_requestMediaCapturePermissionForOrigin_initiatedByFrame_type_decisionHandler_(
                self, webView, origin, frame, type_, handler
            ):
                # 1 = WKPermissionDecisionDeny
                handler(1)

        _deny_delegate = _NoMediaDelegate.alloc().init()

        # 2. Dock Menu Handler
        class _DockMenuHandler(NSObject):
            @objc.python_method
            def initWithWindow_(self, window):
                self = objc.super(_DockMenuHandler, self).init()
                if self:
                    self.window = window
                return self

            def playPauseAction_(self, sender):
                self.window.evaluate_js('document.getElementById("playPause")?.click()')

            def nextAction_(self, sender):
                self.window.evaluate_js('document.getElementById("btnNext")?.click()')

            def prevAction_(self, sender):
                self.window.evaluate_js('document.getElementById("btnPrev")?.click()')

            def shuffleAction_(self, sender):
                self.window.evaluate_js('document.getElementById("btnShuffle")?.click()')

            def repeatAction_(self, sender):
                self.window.evaluate_js('document.getElementById("btnRepeat")?.click()')

        # 3. Patching logic
        def _install(wv_window):
            try:
                # Install media delegate
                wv = wv_window._browser.webview  # pywebview cocoa backend
                wv.setUIDelegate_(_deny_delegate)
                _deny_delegate.retain()

                # Install dock menu
                app = NSApplication.sharedApplication()
                delegate = app.delegate()
                if not delegate:
                    return

                handler = _DockMenuHandler.alloc().initWithWindow_(wv_window)
                handler.retain() # Keep alive

                dock_menu = NSMenu.alloc().initWithTitle_("Dock Menu")
                
                item_play = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Play / Pause", "playPauseAction:", "")
                item_play.setTarget_(handler)
                dock_menu.addItem_(item_play)
                
                item_next = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Next Track", "nextAction:", "")
                item_next.setTarget_(handler)
                dock_menu.addItem_(item_next)
                
                item_prev = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Previous Track", "prevAction:", "")
                item_prev.setTarget_(handler)
                dock_menu.addItem_(item_prev)
                
                dock_menu.addItem_(NSMenuItem.separatorItem())
                
                item_shuffle = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Shuffle", "shuffleAction:", "")
                item_shuffle.setTarget_(handler)
                dock_menu.addItem_(item_shuffle)
                
                item_repeat = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Repeat", "repeatAction:", "")
                item_repeat.setTarget_(handler)
                dock_menu.addItem_(item_repeat)

                def applicationDockMenu_(self, sender):
                    return dock_menu

                objc_method = objc.selector(applicationDockMenu_, selector=b"applicationDockMenu:", signature=b"@@:@")
                objc.classAddMethod(type(delegate), b"applicationDockMenu:", objc_method)
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
    apply_macos_patches()

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
