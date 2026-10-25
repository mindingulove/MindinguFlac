"""Lifecycle of the embedded, authenticated Mornye REST service.

Only this module knows how to start upstream. Consumers use its versioned HTTP
contract; no downloader or metadata monkeypatches are installed.
"""
from __future__ import annotations

import atexit
import json
import os
import secrets
import shutil
import socket
import threading
import time
from pathlib import Path

import requests

_lock = threading.RLock()
_server = None
_thread = None
_base_url = ""
_token = ""
_session = requests.Session()
_session.trust_env = False  # Loopback must not use a user's external proxy.


def configure():
    from config import app_data_dir
    root = app_data_dir() / "mornye"
    for key, path in {
        "MORNYE_DATA_DIR": root,
        "MORNYE_CACHE_DIR": root / "cache",
        "MORNYE_EXT_DIR": root / "extensions",
        "MORNYE_DB_PATH": root / "mornye.db",
        "MORNYE_DOWNLOAD_DIR": root / "downloads",
    }.items():
        os.environ[key] = str(path)
    root.mkdir(parents=True, exist_ok=True)
    _adopt_installed_extensions(root)
    return root


def _adopt_installed_extensions(root):
    """Retain already installed providers without fetching a new registry.

    Never replace a configured Mindinguflac extension or alter the old install.
    A fresh device simply records an empty migration.
    """
    with _lock:
        marker = root / "legacy-extensions-imported.json"
        if marker.exists():
            return
        target = root / "extensions"
        target.mkdir(exist_ok=True)
        copied = []
        for source in (Path.home() / ".mornye/extensions", Path.home() / ".spotiflac/extensions"):
            if not source.is_dir() or source.is_symlink():
                continue
            for folder in source.iterdir():
                destination = target / folder.name
                if (folder.is_symlink() or not folder.is_dir()
                        or not (folder / "manifest.json").is_file() or destination.exists()):
                    continue
                if any(path.is_symlink() for path in folder.rglob("*")):
                    continue
                temporary = target / (".import-" + secrets.token_hex(8))
                try:
                    shutil.copytree(folder, temporary, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
                    temporary.rename(destination)
                    copied.append(folder.name)
                except OSError:
                    shutil.rmtree(temporary, ignore_errors=True)
        marker.write_text(json.dumps({"copied": copied}), encoding="utf-8")


def start():
    global _server, _thread, _base_url, _token
    with _lock:
        if _thread is not None and _thread.is_alive() and _server.started:
            return _base_url
        configure()
        import uvicorn
        from mornye.webapp import create_app

        token = secrets.token_urlsafe(32)
        application = create_app(token=token)
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        # Upstream's GUI lifespan checks/installers are unnecessary here: our
        # app owns startup, provider configuration and the download directory.
        server = uvicorn.Server(uvicorn.Config(
            application, host="127.0.0.1", port=port, loop="asyncio", http="h11",
            lifespan="off", ws="none", log_level="warning", access_log=False,
            # The native app owns logging and redirects stdout/stderr to a
            # file-like writer without terminal methods. Uvicorn's default
            # formatter calls isatty() and prevented the API from starting.
            log_config=None,
        ))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]},
                                  name="mindinguflac-mornye-api", daemon=True)
        _server, _thread = server, thread
        _base_url, _token = f"http://127.0.0.1:{port}/api/v1", token
        thread.start()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if not thread.is_alive():
                break
            try:
                response = _session.get(_base_url + "/info", cookies={"mornye_web_token": token}, timeout=0.5)
                if response.ok and response.json().get("api_version") == "v1":
                    return _base_url
            except (requests.RequestException, ValueError):
                pass
            time.sleep(0.05)
        stop()
        raise RuntimeError("Embedded Mornye API did not start")


def request(method, path, *, payload=None, params=None, timeout=90):
    base = start()
    if not path.startswith("/") or ".." in path:
        raise ValueError("Invalid Mornye API path")
    response = _session.request(method, base + path, json=payload, params=params,
                                cookies={"mornye_web_token": _token}, timeout=timeout)
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError("Mornye returned an invalid API response") from exc
    if not response.ok:
        message = data.get("error") or "Mornye API request failed"
        raise RuntimeError(str(message))
    return data


def stop():
    global _server, _thread, _base_url, _token
    with _lock:
        if _server is not None:
            _server.should_exit = True
        if _thread is not None and _thread is not threading.current_thread():
            _thread.join(timeout=5)
        if _thread is None or not _thread.is_alive():
            _server = _thread = None
            _base_url = _token = ""


atexit.register(stop)
