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
_np_info: dict = {}
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


def install_now_playing(window: webview.Window) -> None:
    """Register MPNowPlayingInfoCenter and MPRemoteCommandCenter for Touch Bar."""
    if sys.platform != "darwin":
        return
    try:
        import ctypes
        import objc
        from Foundation import NSBundle, NSURL
        from AppKit import NSImage

        mp_bundle = NSBundle.bundleWithPath_("/System/Library/Frameworks/MediaPlayer.framework")
        mp_bundle.load()

        MPNowPlayingInfoCenter = objc.lookUpClass("MPNowPlayingInfoCenter")
        MPRemoteCommandCenter = objc.lookUpClass("MPRemoteCommandCenter")
        MPMediaItemArtwork = objc.lookUpClass("MPMediaItemArtwork")

        center = MPNowPlayingInfoCenter.defaultCenter()
        cmd_center = MPRemoteCommandCenter.sharedCommandCenter()

        mascot_path = resource_path("static/assets/mindinguflac_icon_bcp.png")
        _fallback_image = None
        if mascot_path.is_file():
            _fallback_image = NSImage.alloc().initWithContentsOfFile_(str(mascot_path))

        _blocks: list = []
        try:
            def _make_handler(elem_id: str):
                @objc.block(restype=ctypes.c_long, argtypes=[objc.objc_id])
                def _blk(event):
                    threading.Thread(
                        target=window.evaluate_js,
                        args=(f'document.getElementById("{elem_id}")?.click()',),
                        daemon=True,
                    ).start()
                    return 0
                return _blk

            for cmd, eid in (
                (cmd_center.playCommand(), "playPause"),
                (cmd_center.pauseCommand(), "playPause"),
                (cmd_center.togglePlayPauseCommand(), "playPause"),
                (cmd_center.nextTrackCommand(), "btnNext"),
                (cmd_center.previousTrackCommand(), "btnPrev"),
            ):
                blk = _make_handler(eid)
                _blocks.append(blk)
                cmd.setEnabled_(True)
                cmd.addTargetWithHandler_(blk)
        except Exception as cmd_exc:
            print(f"Now Playing remote commands unavailable: {cmd_exc}", file=sys.stderr)
            for cmd in (
                cmd_center.playCommand(),
                cmd_center.pauseCommand(),
                cmd_center.togglePlayPauseCommand(),
                cmd_center.nextTrackCommand(),
                cmd_center.previousTrackCommand(),
            ):
                try:
                    cmd.setEnabled_(True)
                except Exception:
                    pass

        def set_now_playing(info: dict) -> None:
            try:
                updates: dict = {}
                if "title" in info:
                    updates["title"] = str(info["title"])
                if "artist" in info:
                    updates["artist"] = str(info["artist"])
                if "album" in info:
                    updates["albumTitle"] = str(info["album"])
                if "duration" in info:
                    d = float(info["duration"] or 0)
                    if d > 0:
                        updates["playbackDuration"] = d
                if "position" in info:
                    updates["MPNowPlayingInfoPropertyElapsedPlaybackTime"] = float(info["position"] or 0)
                if "playing" in info:
                    updates["MPNowPlayingInfoPropertyPlaybackRate"] = 1.0 if info["playing"] else 0.0

                if "artwork_url" in info:
                    artwork = None
                    artwork_url = str(info["artwork_url"] or "")
                    if artwork_url:
                        try:
                            ns_url = NSURL.URLWithString_(artwork_url)
                            img = NSImage.alloc().initWithContentsOfURL_(ns_url)
                            if img:
                                artwork = MPMediaItemArtwork.alloc().initWithImage_(img)
                        except Exception:
                            pass
                    if artwork is None and _fallback_image is not None:
                        try:
                            artwork = MPMediaItemArtwork.alloc().initWithImage_(_fallback_image)
                        except Exception:
                            pass
                    if artwork is not None:
                        updates["artwork"] = artwork

                if updates:
                    _np_info.update(updates)
                    center.setNowPlayingInfo_(_np_info)
            except Exception as exc:
                print(f"set_now_playing error: {exc}", file=sys.stderr)

        def set_playback_state(state_val: int) -> None:
            try:
                sv = int(state_val)
                _np_info["MPNowPlayingInfoPropertyPlaybackRate"] = 1.0 if sv == 1 else 0.0
                if _np_info:
                    center.setNowPlayingInfo_(_np_info)
                center.setPlaybackState_(sv)
            except Exception as exc:
                print(f"set_playback_state error: {exc}", file=sys.stderr)

        window.expose(set_now_playing)
        window.expose(set_playback_state)

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
        install_now_playing(window)
        install_macos_dock_menu(window, app.get_dock_recent_items)
        webview.start(icon=str(icon_path) if icon_path.exists() else None)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
