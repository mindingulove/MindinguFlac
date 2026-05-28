from __future__ import annotations

import json
import os
import shutil
import sys
import threading
from pathlib import Path

import webview


APP_NAME = "Mindinguflac"
DARK_BACKGROUND = "#090b10"
_macos_dock_state: dict[str, object] = {
    "handler": None,
    "shuffle": False,
    "repeat": False,
    "playing": False,
}


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


def configure_tls_certificates() -> None:
    """Keep TLS verification usable while a new desktop bundle is installed."""
    bundled_cert = resource_path("certifi/cacert.pem")
    if not bundled_cert.is_file():
        try:
            import certifi

            bundled_cert = Path(certifi.where())
        except Exception:
            return
    if sys.platform == "darwin":
        runtime_dir = Path.home() / "Library" / "Application Support" / APP_NAME / "runtime"
    elif sys.platform == "win32":
        runtime_dir = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_NAME / "runtime"
    else:
        runtime_dir = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    stable_cert = runtime_dir / "cacert.pem"
    shutil.copy2(bundled_cert, stable_cert)
    for name in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        os.environ[name] = str(stable_cert)


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


def install_macos_dock_menu(window: webview.Window, recent_items_provider) -> None:
    """Install native playback controls in the macOS Dock context menu."""
    if sys.platform != "darwin":
        return
    try:
        import objc
        from AppKit import NSControlStateValueOff, NSControlStateValueOn, NSMenu, NSMenuItem
        from Foundation import NSObject
        import webview.platforms.cocoa as cocoa

        class _DockMenuHandler(NSObject):
            def initWithWindow_(self, window):
                self = objc.super(_DockMenuHandler, self).init()
                if self:
                    self.window = window
                return self

            @objc.python_method
            def run_js_script(self, script):
                threading.Thread(
                    target=self.window.evaluate_js,
                    args=(script,),
                    daemon=True,
                ).start()

            @objc.python_method
            def run_button_action(self, element_id):
                self.run_js_script(f'document.getElementById("{element_id}")?.click()')

            def playPauseAction_(self, sender):
                self.run_button_action("playPause")

            def nextAction_(self, sender):
                self.run_button_action("btnNext")

            def prevAction_(self, sender):
                self.run_button_action("btnPrev")

            def shuffleAction_(self, sender):
                _macos_dock_state["shuffle"] = not _macos_dock_state["shuffle"]
                self.run_button_action("btnShuffle")

            def repeatAction_(self, sender):
                _macos_dock_state["repeat"] = not _macos_dock_state["repeat"]
                self.run_button_action("btnRepeat")

            def recentAction_(self, sender):
                entries = recent_items_provider()
                index = sender.tag()
                if 0 <= index < len(entries):
                    entry_json = json.dumps(entries[index], ensure_ascii=True)
                    self.run_js_script(f"window.openDockRecentItem({entry_json})")

        handler = _DockMenuHandler.alloc().initWithWindow_(window)
        _macos_dock_state["handler"] = handler

        def build_dock_menu():
            dock_menu = NSMenu.alloc().initWithTitle_("Dock Menu")
            for title, action in (
                ("Pause" if _macos_dock_state["playing"] else "Play", "playPauseAction:"),
                ("Next", "nextAction:"),
                ("Previous", "prevAction:"),
            ):
                item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
                item.setTarget_(handler)
                dock_menu.addItem_(item)

            dock_menu.addItem_(NSMenuItem.separatorItem())

            for title, action, state_key in (
                ("Shuffle", "shuffleAction:", "shuffle"),
                ("Repeat", "repeatAction:", "repeat"),
            ):
                item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
                item.setTarget_(handler)
                item.setState_(NSControlStateValueOn if _macos_dock_state[state_key] else NSControlStateValueOff)
                dock_menu.addItem_(item)

            recent_items = recent_items_provider()
            if recent_items:
                dock_menu.addItem_(NSMenuItem.separatorItem())
                heading = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Recently Played", None, "")
                heading.setEnabled_(False)
                dock_menu.addItem_(heading)
                for index, entry in enumerate(recent_items):
                    item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                        entry["title"], "recentAction:", ""
                    )
                    item.setTarget_(handler)
                    item.setTag_(index)
                    dock_menu.addItem_(item)
            return dock_menu

        class _DockAppDelegate(cocoa.BrowserView.AppDelegate):
            def applicationDockMenu_(self, sender):
                return build_dock_menu()

        # pywebview creates this delegate inside webview.start(), after this setup runs.
        cocoa.BrowserView.AppDelegate = _DockAppDelegate
    except Exception as exc:
        print(f"Unable to install macOS Dock menu: {exc}", file=sys.stderr)


def main() -> None:
    os.environ.setdefault("MINDINGUFLAC_DESKTOP", "1")
    configure_tls_certificates()
    import app

    app.initialize_dock_recent_items()
    server = app.create_server("127.0.0.1", 0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, name="mindinguflac-http", daemon=True)
    thread.start()

    icon_path = resource_path("static/assets/app_icon.png")
    url = f"http://127.0.0.1:{port}/"
    force_dark_appearance()

    try:
        window = webview.create_window(
            APP_NAME,
            url,
            width=1280,
            height=820,
            min_size=(960, 640),
            background_color=DARK_BACKGROUND,
        )
        install_macos_dock_menu(window, app.get_dock_recent_items)
        webview.start(icon=str(icon_path) if icon_path.exists() else None)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
