from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import subprocess
import traceback
import webbrowser
from pathlib import Path


APP_NAME = "Mindinguflac"
DARK_BACKGROUND = "#090b10"
_app_quitting = False
_np_info: dict = {}
_macos_now_playing_proc: subprocess.Popen[str] | None = None
_macos_now_playing_stdin = None
_macos_now_playing_lock = threading.Lock()
_macos_dock_state: dict[str, object] = {
    "handler": None,
    "shuffle": False,
    "repeat": False,
    "playing": False,
}
webview = None


def get_runtime_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME / "runtime"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_NAME / "runtime"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME / "runtime"


_log_path = None

def setup_desktop_logging() -> Path:
    global _log_path
    log_dir = get_runtime_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    _log_path = log_dir / "desktop.log"
    with _log_path.open("a", encoding="utf-8") as log_file:
        log_file.write("\n--- Mindinguflac desktop start ---\n")
        log_file.write(f"platform={sys.platform} frozen={getattr(sys, 'frozen', False)} exe={sys.executable}\n")

    def _log_exception(exc_type, exc, tb):
        import traceback
        lines = traceback.format_exception(exc_type, exc, tb)
        with _log_path.open("a", encoding="utf-8") as lf:
            lf.write("".join(lines) + "\n")
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _log_exception
    return _log_path

def log_step(message: str) -> None:
    print(f"[desktop] {message}", flush=True)
    if _log_path:
        try:
            with _log_path.open("a", encoding="utf-8") as lf:
                lf.write(f"[desktop] {message}\n")
        except Exception:
            pass


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
    cert_runtime_dir = get_runtime_dir()
    cert_runtime_dir.mkdir(parents=True, exist_ok=True)
    stable_cert = cert_runtime_dir / "cacert.pem"
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


def _macos_now_playing_helper_path() -> Path | None:
    bundle_root = Path(sys.executable).resolve().parent.parent if getattr(sys, "frozen", False) else None
    candidates = [
        resource_path("MindinguflacNowPlayingHelper"),
        resource_path("Resources/MindinguflacNowPlayingHelper"),
        resource_path("Frameworks/MindinguflacNowPlayingHelper"),
        resource_path("build/macos/MindinguflacNowPlayingHelper"),
        bundle_root / "Resources" / "MindinguflacNowPlayingHelper" if bundle_root else None,
        bundle_root / "Frameworks" / "MindinguflacNowPlayingHelper" if bundle_root else None,
        Path(__file__).resolve().parent / "build" / "macos" / "MindinguflacNowPlayingHelper",
    ]
    for candidate in candidates:
        if candidate and candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def _stop_macos_now_playing_helper() -> None:
    global _macos_now_playing_proc, _macos_now_playing_stdin
    with _macos_now_playing_lock:
        if _macos_now_playing_stdin is not None:
            try:
                _macos_now_playing_stdin.close()
            except Exception:
                pass
            _macos_now_playing_stdin = None
        if _macos_now_playing_proc is not None and _macos_now_playing_proc.poll() is None:
            try:
                _macos_now_playing_proc.terminate()
                _macos_now_playing_proc.wait(timeout=2)
            except Exception:
                try:
                    _macos_now_playing_proc.kill()
                except Exception:
                    pass
        _macos_now_playing_proc = None


def _send_macos_now_playing_message(message: dict) -> None:
    with _macos_now_playing_lock:
        if _macos_now_playing_stdin is None or _macos_now_playing_proc is None:
            return
        if _macos_now_playing_proc.poll() is not None:
            return
        try:
            _macos_now_playing_stdin.write(json.dumps(message, ensure_ascii=True) + "\n")
            _macos_now_playing_stdin.flush()
        except Exception:
            _stop_macos_now_playing_helper()


def _start_macos_now_playing_helper(base_url: str) -> None:
    global _macos_now_playing_proc, _macos_now_playing_stdin
    helper_path = _macos_now_playing_helper_path()
    if helper_path is None:
        print("macOS Now Playing helper not found", file=sys.stderr)
        return
    with _macos_now_playing_lock:
        if _macos_now_playing_proc is not None and _macos_now_playing_proc.poll() is None:
            return
        try:
            proc = subprocess.Popen(
                [str(helper_path), "--base-url", base_url],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
            _macos_now_playing_proc = proc
            _macos_now_playing_stdin = proc.stdin
        except Exception as exc:
            print(f"Unable to start macOS Now Playing helper: {exc}", file=sys.stderr)
            _macos_now_playing_proc = None
            _macos_now_playing_stdin = None


def install_now_playing(window: webview.Window, base_url: str) -> None:
    """Register MPNowPlayingInfoCenter and MPRemoteCommandCenter for Touch Bar."""
    if sys.platform != "darwin":
        return
    try:
        import app as _app
        from AppKit import NSApplicationDidBecomeActiveNotification, NSApplicationDidResignActiveNotification
        from Foundation import NSNotificationCenter, NSObject

        _start_macos_now_playing_helper(base_url)

        def set_now_playing(info: dict) -> None:
            try:
                payload = {"type": "set_now_playing"}
                payload.update({k: v for k, v in info.items() if k in {"title", "artist", "album", "duration", "position", "artwork_url"}})
                _send_macos_now_playing_message(payload)
            except Exception as exc:
                print(f"set_now_playing error: {exc}", file=sys.stderr)

        def set_playback_state(state_val: int) -> None:
            try:
                _send_macos_now_playing_message({"type": "set_playback_state", "state": int(state_val)})
            except Exception as exc:
                print(f"set_playback_state error: {exc}", file=sys.stderr)

        def clear_now_playing() -> None:
            try:
                _send_macos_now_playing_message({"type": "clear_now_playing"})
            except Exception as exc:
                print(f"clear_now_playing error: {exc}", file=sys.stderr)

        def send_app_active(active: bool) -> None:
            _send_macos_now_playing_message({"type": "app_active", "active": bool(active)})

        def handle_media_command(action: str) -> None:
            mapping = {
                "playPause": "document.getElementById('playPause')?.click()",
                "btnNext": "document.getElementById('btnNext')?.click()",
                "btnPrev": "document.getElementById('btnPrev')?.click()",
            }
            script = mapping.get(action)
            if not script:
                return
            threading.Thread(target=window.evaluate_js, args=(script,), daemon=True).start()

        _app._np_update_fn = set_now_playing
        _app._np_state_fn = set_playback_state
        _app._np_clear_fn = clear_now_playing
        _app._macos_media_command_fn = handle_media_command

        class _AppStateObserver(NSObject):
            def appStateChanged_(self, notification):
                try:
                    from AppKit import NSApplication

                    send_app_active(NSApplication.sharedApplication().isActive())
                except Exception as exc:
                    print(f"appStateChanged error: {exc}", file=sys.stderr)

        _observer = _AppStateObserver.alloc().init()
        nc = NSNotificationCenter.defaultCenter()
        nc.addObserver_selector_name_object_(_observer, "appStateChanged:", NSApplicationDidBecomeActiveNotification, None)
        nc.addObserver_selector_name_object_(_observer, "appStateChanged:", NSApplicationDidResignActiveNotification, None)
        from AppKit import NSApplication
        send_app_active(NSApplication.sharedApplication().isActive())

    except Exception as exc:
        print(f"Unable to install Now Playing: {exc}", file=sys.stderr)


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

            def applicationShouldTerminate_(self, sender):
                global _app_quitting
                _app_quitting = True
                return super().applicationShouldTerminate_(sender)

            def applicationShouldHandleReopen_hasVisibleWindows_(self, app, flag):
                if not flag:
                    try:
                        for bv in cocoa.BrowserView.instances.values():
                            bv.window.makeKeyAndOrderFront_(None)
                    except Exception:
                        pass
                return True

        # pywebview creates this delegate inside webview.start(), after this setup runs.
        cocoa.BrowserView.AppDelegate = _DockAppDelegate
    except Exception as exc:
        print(f"Unable to install macOS Dock menu: {exc}", file=sys.stderr)


import multiprocessing
import ctypes

def main() -> None:
    global webview
    log_path = setup_desktop_logging()
    os.environ.setdefault("MINDINGUFLAC_DESKTOP", "1")
    os.environ.setdefault("PYWEBVIEW_LOG", "DEBUG")
    
    if sys.platform == "win32":
        # Stability flags: disable features known to cause hangs in shared/restricted environments
        os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
            "--disable-dev-shm-usage --disable-features=ZstdContentEncoding"
        )
        
        # Set AUMID for proper taskbar grouping and notifications
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("com.mindinguflac.desktop")
        except Exception:
            pass

        # Use a consistent folder for WebView2 data
        runtime_dir = get_runtime_dir()
        wv2_data = runtime_dir / "WebView2Data"
        try:
            wv2_data.mkdir(parents=True, exist_ok=True)
            # Setting this variable ensures WebView2 loader picks it up immediately
            os.environ["WEBVIEW2_USER_DATA_FOLDER"] = str(wv2_data)
        except Exception:
            pass

    log_step(f"startup log: {log_path}")
    log_step("importing pywebview")
    import webview as _webview
    webview = _webview
    log_step(f"pywebview imported: {getattr(webview, '__version__', 'unknown')}")
    log_step("configuring TLS certificates")
    configure_tls_certificates()
    log_step("importing app")
    import app

    log_step("initializing recent items")
    app.initialize_dock_recent_items()
    log_step("creating local HTTP server")
    server = app.create_server("127.0.0.1", 0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, name="mindinguflac-http", daemon=True)
    thread.start()
    log_step(f"server started on port {port}")

    icon_path = resource_path("static/assets/app_icon.png")
    url = f"http://127.0.0.1:{port}/index.html"
    force_dark_appearance()

    try:
        log_step("creating pywebview window")
        window = webview.create_window(
            APP_NAME,
            url,
            width=1280,
            height=820,
            min_size=(960, 640),
            background_color=DARK_BACKGROUND,
        )
        log_step("pywebview window object created")
        install_macos_dock_menu(window, app.get_dock_recent_items)

        if sys.platform == "darwin":
            def _hide_on_close():
                if _app_quitting:
                    return True  # let it close so the app can terminate
                window.hide()
                return False  # returning False makes should_cancel=True → prevents close
            window.events.closing += _hide_on_close

        log_step("starting pywebview event loop")
        start_kwargs = {
            "icon": str(icon_path) if icon_path.exists() else None,
            "debug": True,
            "private_mode": False,  # Required for WebView2 in many bundled environments
        }
        if sys.platform == "win32":
            start_kwargs["gui"] = "edgechromium"
            # Prefer the environment variable we just set
            start_kwargs["storage_path"] = os.environ.get("WEBVIEW2_USER_DATA_FOLDER")
        
        def on_shown():
            # macOS-specific helper and Darwin Now Playing
            install_now_playing(window, url)

        window.events.shown += on_shown
        webview.start(**start_kwargs)
        log_step("pywebview event loop exited")
    finally:
        log_step("shutting down desktop server")
        _stop_macos_now_playing_helper()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
