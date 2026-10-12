from __future__ import annotations

import json
import base64
import html
import os
import shutil
import sys
import threading
import subprocess
import traceback
import time
import webbrowser
import uuid
from pathlib import Path
from urllib.parse import urlparse


APP_NAME = "Mindinguflac"
DARK_BACKGROUND = "#090b10"
_app_quitting = False
_np_info: dict = {}
_macos_now_playing_proc: subprocess.Popen[str] | None = None
_macos_now_playing_stdin = None
_macos_now_playing_lock = threading.Lock()
_system_notification_delegate = None
_system_notification_permission_request = None
_macos_dock_state: dict[str, object] = {
    "handler": None,
    "shuffle": False,
    "repeat": False,
    "playing": False,
}
webview = None
_instance_lock_handle = None


def get_runtime_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME / "runtime"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_NAME / "runtime"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME / "runtime"


def acquire_single_instance_lock() -> bool:
    global _instance_lock_handle
    runtime_dir = get_runtime_dir()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    lock_path = runtime_dir / "app.lock"
    try:
        handle = lock_path.open("a+", encoding="utf-8")
    except OSError:
        return True
    try:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        _instance_lock_handle = handle
        return True
    except OSError:
        try:
            handle.close()
        except Exception:
            pass
        return False


def release_single_instance_lock() -> None:
    global _instance_lock_handle
    handle = _instance_lock_handle
    _instance_lock_handle = None
    if handle is None:
        return
    try:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        handle.close()
    except Exception:
        pass


_log_path = None
_startup_t0 = time.monotonic()

class SafeLogWriter:
    def __init__(self, path: Path):
        self.path = path

    def write(self, message: str) -> None:
        if not message:
            return
        try:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(message)
        except Exception:
            pass

    def flush(self) -> None:
        pass


def setup_desktop_logging() -> Path:
    global _log_path
    log_dir = get_runtime_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    _log_path = log_dir / "desktop.log"
    
    writer = SafeLogWriter(_log_path)
    sys.stdout = writer
    sys.stderr = writer

    writer.write(f"\n--- Mindinguflac desktop start ---\nplatform={sys.platform} frozen={getattr(sys, 'frozen', False)} exe={sys.executable}\n")

    def _log_exception(exc_type, exc, tb):
        import traceback
        lines = traceback.format_exception(exc_type, exc, tb)
        writer.write("".join(lines) + "\n")

    sys.excepthook = _log_exception
    return _log_path


def log_step(message: str) -> None:
    elapsed = time.monotonic() - _startup_t0
    print(f"[desktop +{elapsed:.2f}s] {message}", flush=True)


def write_startup_failure(exc: BaseException) -> None:
    try:
        log_dir = get_runtime_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / "desktop-fatal.log"
        path.write_text("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)), encoding="utf-8")
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            ctypes.windll.user32.MessageBoxW(
                None,
                f"Mindinguflac failed to start.\n\n{exc}\n\nCheck %LOCALAPPDATA%\\Mindinguflac\\runtime\\desktop-fatal.log",
                "Mindinguflac startup error",
                0x10,
            )
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
    try:
        shutil.copy2(bundled_cert, stable_cert)
    except (PermissionError, OSError) as e:
        log_step(f"Using existing certificate bundle (locked: {e})")

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

        try:
            from AppKit import NSApplicationDidBecomeActiveNotification, NSApplicationDidResignActiveNotification, NSApplication
            from Foundation import NSNotificationCenter, NSObject

            class _AppStateObserver(NSObject):
                def appStateChanged_(self, notification):
                    try:
                        send_app_active(NSApplication.sharedApplication().isActive())
                    except Exception as exc:
                        print(f"appStateChanged error: {exc}", file=sys.stderr)

            _observer = _AppStateObserver.alloc().init()
            nc = NSNotificationCenter.defaultCenter()
            nc.addObserver_selector_name_object_(_observer, "appStateChanged:", NSApplicationDidBecomeActiveNotification, None)
            nc.addObserver_selector_name_object_(_observer, "appStateChanged:", NSApplicationDidResignActiveNotification, None)
            
            send_app_active(NSApplication.sharedApplication().isActive())
        except ImportError:
            pass

    except Exception as exc:
        print(f"Unable to install Now Playing: {exc}", file=sys.stderr)


def install_macos_dock_menu(window: webview.Window, recent_items_provider) -> None:
    """Install native playback controls in the macOS Dock context menu."""
    if sys.platform != "darwin":
        return
    try:
        import app as _app
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

        def set_playing_state(playing: bool) -> None:
            _macos_dock_state["playing"] = bool(playing)

        # desktop.py is the PyInstaller entry point and therefore executes as
        # __main__.  Register a callback on the already-loaded app module;
        # importing `desktop` from app.py would create a second module with a
        # different Dock state dictionary.
        _app._dock_playing_state_fn = set_playing_state

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


def install_system_notifications(window: webview.Window) -> None:
    """Install clickable native notifications for actions that need attention."""
    global _system_notification_delegate, _system_notification_permission_request
    try:
        import app as _app

        if sys.platform == "darwin":
            import objc
            from Foundation import NSObject
            from UserNotifications import (
                UNAuthorizationOptionAlert,
                UNAuthorizationOptionSound,
                UNMutableNotificationContent,
                UNNotificationPresentationOptionBanner,
                UNNotificationPresentationOptionSound,
                UNNotificationRequest,
                UNUserNotificationCenter,
            )

            center = UNUserNotificationCenter.currentNotificationCenter()

            class _NotificationDelegate(NSObject):
                def userNotificationCenter_willPresentNotification_withCompletionHandler_(
                    self, center_value, notification, completion_handler
                ):
                    completion_handler(
                        UNNotificationPresentationOptionBanner |
                        UNNotificationPresentationOptionSound
                    )

                def userNotificationCenter_didReceiveNotificationResponse_withCompletionHandler_(
                    self, center_value, response, completion_handler
                ):
                    try:
                        info = response.notification().request().content().userInfo() or {}
                        target = str(info.get("url") or "")
                        if target:
                            if _app._youtube_login_fn:
                                threading.Thread(target=_app._youtube_login_fn, name="youtube-notification-login", daemon=True).start()
                            else:
                                webbrowser.open(target, new=2)
                    finally:
                        completion_handler()

            delegate = _NotificationDelegate.alloc().init()
            _system_notification_delegate = delegate
            center.setDelegate_(delegate)

            def request_permission() -> bool:
                def completed(granted, error):
                    if error is not None:
                        print(f"Notification permission request failed: {error}", file=sys.stderr)
                    elif not granted:
                        print("Notification permission was not granted; using in-app alerts", file=sys.stderr)

                center.requestAuthorizationWithOptions_completionHandler_(
                    UNAuthorizationOptionAlert | UNAuthorizationOptionSound,
                    completed,
                )
                return True

            _system_notification_permission_request = request_permission

            def show_notification(title: str, message: str, target: str) -> bool:
                def deliver(granted, error):
                    if not granted or error is not None:
                        return
                    content = UNMutableNotificationContent.alloc().init()
                    content.setTitle_(title)
                    content.setBody_(message)
                    content.setSound_(None)
                    content.setUserInfo_({"url": target})
                    request = UNNotificationRequest.requestWithIdentifier_content_trigger_(
                        f"youtube-login-{uuid.uuid4()}", content, None
                    )
                    center.addNotificationRequest_withCompletionHandler_(request, None)

                center.requestAuthorizationWithOptions_completionHandler_(
                    UNAuthorizationOptionAlert | UNAuthorizationOptionSound,
                    deliver,
                )
                return True

            _app._system_notification_fn = show_notification
            return

        if sys.platform == "win32":
            def show_notification(title: str, message: str, target: str) -> bool:
                toast_xml = (
                    f'<toast launch="{html.escape(target, quote=True)}" activationType="protocol">'
                    '<visual><binding template="ToastGeneric">'
                    f'<text>{html.escape(title)}</text><text>{html.escape(message)}</text>'
                    '</binding></visual></toast>'
                )
                script = (
                    "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument;"
                    f"$xml.LoadXml('{toast_xml.replace("'", "''")}');"
                    "$toast = New-Object Windows.UI.Notifications.ToastNotification $xml;"
                    "[Windows.UI.Notifications.ToastNotificationManager]::"
                    "CreateToastNotifier('Mindinguflac').Show($toast)"
                )
                encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
                subprocess.Popen(
                    ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                return True

            _app._system_notification_fn = show_notification
    except Exception as exc:
        print(f"Unable to install system notifications: {exc}", file=sys.stderr)


import multiprocessing
import ctypes

def clear_youtube_native_cookies(main_window) -> None:
    """Delete only YouTube/Google cookies in this app's native browser store."""
    finished = threading.Event()
    errors = []

    def allowed(domain):
        domain = str(domain).lstrip(".").lower()
        return any(domain == host or domain.endswith("." + host) for host in ("youtube.com", "google.com"))

    if sys.platform == "darwin":
        from PyObjCTools import AppHelper
        from webview.platforms.cocoa import BrowserView

        def begin():
            try:
                store = BrowserView.instances[main_window.uid].datastore.httpCookieStore()

                def received(cookies):
                    pending = [cookie for cookie in cookies if allowed(cookie.domain())]
                    if not pending:
                        finished.set()
                        return
                    remaining = [len(pending)]

                    def deleted():
                        remaining[0] -= 1
                        if remaining[0] == 0:
                            finished.set()

                    for cookie in pending:
                        store.deleteCookie_completionHandler_(cookie, deleted)

                store.getAllCookies_(received)
            except Exception as exc:
                errors.append(exc)
                finished.set()

        AppHelper.callAfter(begin)
    else:
        from webview.platforms.winforms import BrowserView
        from System import Action
        from System.Collections.Generic import List
        from System.Threading.Tasks import Task
        from Microsoft.Web.WebView2.Core import CoreWebView2Cookie
        browser = BrowserView.instances[main_window.uid].browser

        def begin():
            try:
                manager = browser.webview.CoreWebView2.CookieManager

                def received(task):
                    try:
                        for cookie in task.Result:
                            if allowed(cookie.Domain):
                                manager.DeleteCookies(cookie.Name, cookie.Domain, cookie.Path)
                    except Exception as exc:
                        errors.append(exc)
                    finally:
                        finished.set()

                manager.GetCookiesAsync("").ContinueWith(
                    Action[Task[List[CoreWebView2Cookie]]](received), browser.syncContextTaskScheduler,
                )
            except Exception as exc:
                errors.append(exc)
                finished.set()

        browser.webview.BeginInvoke(Action(begin))
    if not finished.wait(15) or errors:
        raise RuntimeError("Could not clear the app's YouTube session. Please try again.")


def install_youtube_login(main_window) -> None:
    """Read the app-owned WebView2/WKWebView session through its native API."""
    if sys.platform not in {"win32", "darwin"}:
        return
    import app
    import backend_ytpdl

    state = {"window": None, "stopped": None, "signing_out": False, "outcome": "idle"}
    lock = threading.Lock()

    def install_login_navigation(login):
        if sys.platform != "darwin":
            return
        from PyObjCTools import AppHelper
        from webview.platforms import cocoa

        # The default WKWebView UI delegate handles only link-click popups;
        # form submissions and script-created authentication windows are lost.
        # Keep trusted authentication popups in this window, with their original
        # NSURLRequest (including a form's POST body).
        if not hasattr(install_login_navigation, "delegate_class"):
            class MindinguflacYoutubeLoginDelegate(cocoa.BrowserView.BrowserDelegate):
                def webView_decidePolicyForNavigationAction_decisionHandler_(
                    self, native_view, action, handler
                ):
                    target = urlparse(str(action.request().URL().absoluteString()))
                    host = (target.hostname or "").lower()
                    trusted = any(host == domain or host.endswith("." + domain)
                                  for domain in ("google.com", "youtube.com"))
                    if target.scheme == "https" and trusted:
                        # WebKit's AllowWithoutTryingAppLink policy prevents a
                        # Safari-installed YouTube web app from taking over the
                        # redirect. It preserves normal HTTPS/cookie handling.
                        # Defined in WKNavigationDelegatePrivate.h as Allow + 2
                        # since macOS 10.11; scoped to this login view only.
                        handler(cocoa.WebKit.WKNavigationActionPolicyAllow + 2)
                        return
                    return super().webView_decidePolicyForNavigationAction_decisionHandler_(
                        native_view, action, handler
                    )

                def webView_createWebViewWithConfiguration_forNavigationAction_windowFeatures_(
                    self, native_view, configuration, action, features
                ):
                    target = urlparse(str(action.request().URL().absoluteString()))
                    host = (target.hostname or "").lower()
                    trusted = any(host == domain or host.endswith("." + domain)
                                  for domain in ("google.com", "youtube.com"))
                    if target.scheme == "https" and trusted:
                        log_step("YouTube sign-in continued an authentication request in the same window")
                        native_view.loadRequest_(action.request())
                        return None
                    return super().webView_createWebViewWithConfiguration_forNavigationAction_windowFeatures_(
                        native_view, configuration, action, features
                    )
            install_login_navigation.delegate_class = MindinguflacYoutubeLoginDelegate

        def install():
            instance = cocoa.BrowserView.instances.get(login.uid)
            if instance:
                instance._youtube_login_delegate = install_login_navigation.delegate_class.alloc().init()
                instance.webview.setUIDelegate_(instance._youtube_login_delegate)
                instance.webview.setNavigationDelegate_(instance._youtube_login_delegate)

        AppHelper.callAfter(install)

    def open_login():
        stopped = threading.Event()
        with lock:
            if state["signing_out"]:
                return False
            if state["window"] is not None:
                state["window"].show()
                return True
            login = webview.create_window(
                "Sign in to YouTube — Mindinguflac",
                "https://www.youtube.com/signin?app=desktop&next=https%3A%2F%2Fwww.youtube.com%2F", width=1000, height=760,
                min_size=(640, 480), background_color=DARK_BACKGROUND,
                js_api=None,
            )
            state["window"] = login
            state["stopped"] = stopped
            state["outcome"] = "pending"

        def on_closed():
            stopped.set()
            with lock:
                if state["window"] is login:
                    state["window"] = None
                    if state["outcome"] == "pending":
                        state["outcome"] = "cancelled"

        login.events.closed += on_closed
        login.events.shown += lambda: install_login_navigation(login)

        def on_loaded():
            # Keep authentication codes, query strings and account details out
            # of logs while recording which stage actually finished loading.
            current = urlparse(login.get_current_url() or "")
            log_step(f"YouTube sign-in page loaded: {current.hostname or 'unknown'}{current.path}")

        login.events.loaded += on_loaded

        def capture_session():
            # Native get_cookies includes HttpOnly cookies. Passwords and cookie
            # values are never evaluated in JS, logged, or sent to the frontend.
            while not stopped.wait(2):
                try:
                    url = urlparse(login.get_current_url() or "")
                    host = (url.hostname or "").lower()
                    if url.scheme != "https" or not (host == "youtube.com" or host.endswith(".youtube.com")):
                        continue
                    confirmed = login.evaluate_js("""(() => {
                        if (location.protocol !== 'https:' ||
                            !(location.hostname === 'youtube.com' || location.hostname.endsWith('.youtube.com')) ||
                            location.pathname.startsWith('/signin')) return false;
                        const cfg = window.ytcfg;
                        if (cfg && typeof cfg.get === 'function' && cfg.get('LOGGED_IN') === true) return true;
                        return window.ytInitialData?.responseContext?.mainAppWebResponseContext?.loggedOut === false;
                    })()""")
                    if confirmed is not True:
                        continue
                    cookies = login.get_cookies()
                    # Navigation can change while the native cookie API runs.
                    if login.get_current_url() != url.geturl():
                        continue
                    with lock:
                        if stopped.is_set():
                            return
                        saved = backend_ytpdl.import_youtube_webview_cookies(cookies)
                        if saved:
                            state["outcome"] = "completed"
                    if saved:
                        log_step("YouTube session saved from the app sign-in window")
                        login.destroy()
                        main_window.show()
                        return
                except Exception as exc:
                    log_step(f"YouTube sign-in capture unavailable ({type(exc).__name__})")

        threading.Thread(target=capture_session, name="youtube-sign-in", daemon=True).start()
        return True

    def sign_out():
        with lock:
            if state["signing_out"]:
                raise RuntimeError("YouTube sign-out is already in progress")
            state["signing_out"] = True
            login = state["window"]
            stopped = state["stopped"]
            if stopped:
                stopped.set()
        try:
            if login:
                login.destroy()
            clear_youtube_native_cookies(main_window)
            backend_ytpdl.clear_saved_youtube_session()
            with lock:
                state["outcome"] = "idle"
            log_step("Cleared the app-owned YouTube session")
            return True
        finally:
            with lock:
                state["signing_out"] = False

    app._youtube_login_fn = open_login
    app._youtube_login_active_fn = lambda: state["window"] is not None
    app._youtube_login_outcome_fn = lambda: state["outcome"]
    app._youtube_logout_fn = sign_out


def main() -> None:
    global webview
    # Set desktop mode immediately before any other imports
    os.environ["MINDINGUFLAC_DESKTOP"] = "1"
    if not acquire_single_instance_lock():
        return
    try:
        log_path = setup_desktop_logging()
        os.environ.setdefault("PYWEBVIEW_LOG", "INFO")
        
        if sys.platform == "win32":
            # pywebview's Windows backends set pythonnet to coreclr when needed.
            # Forcing netfx here makes the packaged app exit on systems where that
            # runtime is not available before a window can be shown.
            os.environ.pop("PYTHONNET_RUNTIME", None)
            
            # Stability flags: disable features known to cause hangs in shared/restricted environments
            os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
                "--disable-dev-shm-usage --disable-features=ZstdContentEncoding"
            )
            
            # Set AUMID for proper taskbar grouping and notifications
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("com.mindinguflac.desktop")
            except Exception:
                log_step("SetCurrentProcessExplicitAppUserModelID failed")

            # Use a consistent folder for WebView2 data
            runtime_dir = get_runtime_dir()
            wv2_data = runtime_dir / "WebView2Data"
            try:
                wv2_data.mkdir(parents=True, exist_ok=True)
                # Setting this variable ensures WebView2 loader picks it up immediately
                os.environ["WEBVIEW2_USER_DATA_FOLDER"] = str(wv2_data)
            except Exception as exc:
                log_step(f"Unable to prepare WebView2 data folder: {exc}")

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
        try:
            import device_sync
            device_sync.start_desktop_pairing()
            log_step("LAN device pairing service started")
        except Exception as exc:
            log_step(f"LAN device pairing service unavailable: {exc}")

        icon_path = resource_path("static/assets/app_icon.png")
        url = f"http://127.0.0.1:{port}/index.html"
        force_dark_appearance()

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
        install_youtube_login(window)
        install_system_notifications(window)
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
            "debug": bool(os.environ.get("MINDINGUFLAC_DEBUG")),
            "private_mode": False,  # Required for WebView2 in many bundled environments
        }
        if sys.platform == "win32":
            start_kwargs["gui"] = "edgechromium"
            start_kwargs["storage_path"] = os.environ.get("WEBVIEW2_USER_DATA_FOLDER")
            log_step(f"WebView2 User Data Folder: {start_kwargs.get('storage_path')}")
        elif sys.platform == "darwin":
            start_kwargs["icon"] = str(icon_path) if icon_path.exists() else None
        
        def on_shown():
            # macOS-specific helper and Darwin Now Playing
            install_now_playing(window, url)
            if _system_notification_permission_request:
                _system_notification_permission_request()

        window.events.shown += on_shown
        
        try:
            webview.start(**start_kwargs)
            log_step("pywebview event loop exited normally")
        except Exception as exc:
            log_step(f"CRITICAL: pywebview.start() failed: {exc}")
            import traceback
            log_step(traceback.format_exc())
            # Give time to read the log if running in console
            import time
            time.sleep(5)
    finally:
        try:
            if "_log_path" in globals() and _log_path is not None:
                log_step("shutting down desktop server")
        except Exception:
            pass
        try:
            _stop_macos_now_playing_helper()
        except Exception:
            pass
        try:
            if "app" in locals():
                app.apply_shutdown_cache_cleanup()
        except Exception as exc:
            log_step(f"cache shutdown cleanup failed: {exc}")
        try:
            if "server" in locals():
                server.shutdown()
                server.server_close()
        finally:
            release_single_instance_lock()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    # Re-entry point for the Duck.ai browser worker. In a frozen app sys.executable
    # is this binary (not python), so duck_proxy spawns us with --ddg-worker and we
    # run the worker instead of the GUI (prevents recursively launching the app).
    if "--ddg-worker" in sys.argv:
        import ddg_browser
        ddg_browser.main()
        sys.exit(0)
    if "--gemini-worker" in sys.argv:
        import gemini_browser
        gemini_browser.main()
        sys.exit(0)
    try:
        main()
    except Exception as exc:
        write_startup_failure(exc)
        traceback.print_exc()
        raise
