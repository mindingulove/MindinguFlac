"""Pinned-LAN pairing and incremental data sync for desktop and Android."""
from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import os
import secrets
import socket
import ssl
import threading
import time
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


DISCOVERY_PORT = 37643
PROTOCOL = 1
SHARED_SETTINGS = (
    "volume", "track_max_retries", "cache_cleanup_frequency",
    "strict_title_match", "demo_music_indexer", "tour_source",
    "tour_city", "tour_lat", "tour_lon", "tour_state", "tour_country",
)
_desktop: "DesktopPairingService | None" = None
_android: "AndroidPairingClient | None" = None


def _state_dir() -> Path:
    from config import app_data_dir
    return app_data_dir() / "device_sync"


def _load_json(path: Path, fallback: dict) -> dict:
    try:
        value = json.loads(path.read_text("utf-8"))
        return value if isinstance(value, dict) else dict(fallback)
    except Exception:
        return dict(fallback)


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2), encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    temp.replace(path)


def _local_snapshot(local_id: str, statistics_since: float = 0, desktop_cursor: float = 0) -> dict:
    """Export only portable preferences and user listening history."""
    import app
    import db
    import service_downloader

    settings = {key: getattr(app.app_config, key) for key in SHARED_SETTINGS}
    try:
        settings_revision = app.CONFIG_PATH.stat().st_mtime
    except OSError:
        settings_revision = 0
    manager = app.service_downloader
    jobs = []
    with manager._lock:
        for job in manager.jobs.values():
            if job.get("status") != "finished":
                continue
            sync_id = str(job.get("sync_id") or f"{local_id}:{job.get('id', '')}")
            jobs.append({
                "sync_id": sync_id,
                "title": str(job.get("title") or ""),
                "artist": str(job.get("artist") or ""),
                "album": str(job.get("album") or ""),
                "created_at": float(job.get("created_at") or 0),
                "artwork_url": str(job.get("artwork_url") or ""),
                "metadata": job.get("metadata") if isinstance(job.get("metadata"), dict) else {},
                "spotify_id": str(job.get("spotify_id") or ""),
                "isrc": str(job.get("isrc") or ""),
                "hidden_from_recent": bool(job.get("hidden_from_recent")),
            })
    jobs.sort(key=lambda item: item["created_at"], reverse=True)
    return {
        "schema": PROTOCOL,
        "device_id": local_id,
        "settings": settings,
        "settings_revision": settings_revision,
        "recent": jobs[:1000],
        "statistics": db.sync_export(statistics_since),
        "desktop_cursor": float(desktop_cursor or 0),
        "sent_at": time.time(),
    }


def _apply_snapshot(snapshot: dict, remote_id: str) -> dict:
    """Merge append-only listen events and recent rows; apply newer shared settings."""
    import app
    import db
    import service_downloader

    if int(snapshot.get("schema") or 0) != PROTOCOL:
        raise ValueError("Unsupported sync protocol")
    imported_events = db.sync_import(snapshot.get("statistics") or {})
    manager = app.service_downloader
    imported_recent = 0
    save_recent = False
    with manager._lock:
        for row in (snapshot.get("recent") or [])[:1000]:
            if not isinstance(row, dict):
                continue
            sync_id = str(row.get("sync_id") or "").strip()
            if not sync_id or len(sync_id) > 512:
                continue
            job_id = "sync-" + hashlib.sha256(sync_id.encode("utf-8")).hexdigest()[:32]
            if job_id in manager.jobs:
                if row.get("hidden_from_recent") and not manager.jobs[job_id].get("hidden_from_recent"):
                    manager.jobs[job_id]["hidden_from_recent"] = True
                    imported_recent += 1
                continue
            manager.jobs[job_id] = {
                "id": job_id,
                "sync_id": sync_id,
                "sync_remote_device": remote_id,
                "status": "finished",
                "mode": "stream",
                "title": str(row.get("title") or "")[:500],
                "artist": str(row.get("artist") or "")[:500],
                "album": str(row.get("album") or "")[:500],
                "created_at": float(row.get("created_at") or 0),
                "artwork_url": str(row.get("artwork_url") or "")[:2000],
                "metadata": row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
                "spotify_id": str(row.get("spotify_id") or ""),
                "isrc": str(row.get("isrc") or ""),
                "hidden_from_recent": bool(row.get("hidden_from_recent")),
                "library_path": "",
            }
            imported_recent += 1
            save_recent = True
    if save_recent:
        manager._save_jobs()

    incoming = snapshot.get("settings")
    if isinstance(incoming, dict):
        current_revision = app.CONFIG_PATH.stat().st_mtime if app.CONFIG_PATH.exists() else 0
        incoming_revision = float(snapshot.get("settings_revision") or 0)
        current = {key: getattr(app.app_config, key) for key in SHARED_SETTINGS}
        values = {key: incoming[key] for key in SHARED_SETTINGS if key in incoming}
        if incoming_revision > current_revision and values != current:
            config_values = app.app_config.public_dict()
            config_values.update(values)
            updated = app._sanitize_runtime_config(app.AppConfig.from_public_dict(config_values))
            with app.config_lock:
                app.app_config = updated
                app.save_config(app.CONFIG_PATH, updated)
                app.service_downloader.update_config(updated)
    return {"events": imported_events, "recent": imported_recent}


def _ensure_certificate(state_dir: Path) -> tuple[Path, Path, str]:
    cert_path, key_path = state_dir / "lan-cert.pem", state_dir / "lan-key.pem"
    state_dir.mkdir(parents=True, exist_ok=True)
    if not cert_path.exists() or not key_path.exists():
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        from datetime import datetime, timedelta, timezone

        key = ec.generate_private_key(ec.SECP256R1())
        now = datetime.now(timezone.utc)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Mindinguflac LAN pairing")])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256())
        )
        key_path.write_bytes(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        try:
            os.chmod(key_path, 0o600)
        except OSError:
            pass
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    fingerprint = cert.fingerprint(hashes.SHA256()).hex()
    return cert_path, key_path, fingerprint


class DesktopPairingService:
    def __init__(self):
        self.root = _state_dir()
        self.path = self.root / "desktop.json"
        self.state = _load_json(self.path, {"device_id": str(uuid.uuid4()), "devices": {}, "revoked": []})
        self.state.setdefault("device_id", str(uuid.uuid4()))
        self.state.setdefault("devices", {})
        self.state.setdefault("revoked", [])
        self.lock = threading.RLock()
        self.invitation: dict | None = None
        self.httpd: ThreadingHTTPServer | None = None
        self.port = 0
        self.fingerprint = ""
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        cert, key, self.fingerprint = _ensure_certificate(self.root)
        service = self

        class PairHandler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):
                pass

            def respond(self, payload: dict, status: int = 200):
                data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def read_body(self):
                size = min(int(self.headers.get("Content-Length", "0") or 0), 8 * 1024 * 1024)
                return json.loads(self.rfile.read(size).decode("utf-8")) if size else {}

            def do_POST(self):
                try:
                    body = self.read_body()
                    if self.path == "/pair/complete":
                        result = service.complete_pairing(body)
                        self.respond(result, 200)
                        return
                    device_id = str(self.headers.get("X-Mindinguflac-Device") or "")
                    secret = str(self.headers.get("X-Mindinguflac-Pair-Secret") or "")
                    with service.lock:
                        peer = service.state["devices"].get(device_id)
                        revoked = device_id in service.state["revoked"]
                    if revoked or peer is None:
                        self.respond({"desauth": True, "error": "This device pairing was removed"}, 410)
                        return
                    if not secrets.compare_digest(str(peer.get("secret") or ""), secret):
                        self.respond({"error": "Unauthorized paired device"}, 401)
                        return
                    if self.path == "/sync":
                        counts = _apply_snapshot(body, device_id)
                        with service.lock:
                            peer["last_seen"] = time.time()
                            peer["phone_cursor"] = float((body.get("statistics") or {}).get("cursor") or peer.get("phone_cursor") or 0)
                            service._save()
                        snapshot = _local_snapshot(service.state["device_id"], float(body.get("desktop_cursor") or 0))
                        self.respond({"ok": True, "counts": counts, "snapshot": snapshot})
                        return
                    if self.path == "/pair/remove":
                        service.remove_device(device_id)
                        self.respond({"ok": True, "desauth": True})
                        return
                    self.respond({"error": "Not found"}, 404)
                except Exception as exc:
                    self.respond({"error": str(exc)[:300]}, 400)

        self.httpd = ThreadingHTTPServer(("0.0.0.0", 0), PairHandler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(str(cert), str(key))
        self.httpd.socket = context.wrap_socket(self.httpd.socket, server_side=True)
        self.port = int(self.httpd.server_address[1])
        threading.Thread(target=self.httpd.serve_forever, daemon=True, name="mindinguflac-pairing-http").start()
        self._running = True
        threading.Thread(target=self._advertise, daemon=True, name="mindinguflac-pairing-discovery").start()

    def _save(self):
        _write_json(self.path, self.state)

    def _advertise(self):
        payload = json.dumps({
            "protocol": PROTOCOL,
            "device_id": self.state["device_id"],
            "name": socket.gethostname() or "Mindinguflac desktop",
            "port": self.port,
            "fingerprint": self.fingerprint,
        }, separators=(",", ":")).encode("utf-8")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            while self._running:
                try:
                    sock.sendto(payload, ("255.255.255.255", DISCOVERY_PORT))
                except OSError:
                    pass
                time.sleep(1.5)
        finally:
            sock.close()

    def make_invitation(self) -> dict:
        self.start()
        token = secrets.token_urlsafe(24)
        invitation = {
            "device_id": self.state["device_id"],
            "token": token,
            "fingerprint": self.fingerprint,
            "expires_at": time.time() + 180,
        }
        with self.lock:
            self.invitation = invitation
        query = urllib.parse.urlencode({key: invitation[key] for key in ("device_id", "token", "fingerprint")})
        uri = "mindinguflac://pair?" + query
        import qrcode
        import qrcode.image.svg
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=7, border=3)
        qr.add_data(uri)
        qr.make(fit=True)
        image = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
        return {"uri": uri, "qr_svg": image.to_string().decode("utf-8"), "expires_at": invitation["expires_at"]}

    def complete_pairing(self, body: dict) -> dict:
        now = time.time()
        device_id = str(body.get("device_id") or "")
        token = str(body.get("token") or "")
        fingerprint = str(body.get("fingerprint") or "")
        with self.lock:
            invitation = self.invitation
            if not invitation or float(invitation["expires_at"]) < now:
                raise ValueError("The pairing QR code expired. Create a new one on desktop.")
            if device_id != invitation["device_id"] or not secrets.compare_digest(token, invitation["token"]):
                raise ValueError("Pairing invitation does not match")
            if not secrets.compare_digest(fingerprint, self.fingerprint):
                raise ValueError("Desktop fingerprint changed. Scan the new QR code.")
            phone_id = str(body.get("phone_id") or "")
            if len(phone_id) < 12 or len(phone_id) > 128:
                raise ValueError("Invalid phone identity")
            shared = secrets.token_urlsafe(32)
            self.state["devices"][phone_id] = {
                "name": str(body.get("name") or "Android device")[:100],
                "secret": shared,
                "fingerprint": self.fingerprint,
                "paired_at": now,
                "last_seen": now,
            }
            self.state["revoked"] = [item for item in self.state["revoked"] if item != phone_id]
            self.invitation = None
            self._save()
        return {"ok": True, "device_id": device_id, "phone_id": phone_id, "secret": shared, "fingerprint": self.fingerprint, "name": socket.gethostname()}

    def remove_device(self, device_id: str) -> bool:
        with self.lock:
            peer = self.state["devices"].pop(str(device_id), None)
            found = peer is not None
            if device_id not in self.state["revoked"]:
                self.state["revoked"].append(str(device_id))
            self.state["revoked"] = self.state["revoked"][-100:]
            self._save()
        if peer:
            packet = json.dumps({
                "protocol": PROTOCOL,
                "kind": "desauth",
                "device_id": self.state["device_id"],
                "target_id": str(device_id),
                "proof": hmac.new(str(peer.get("secret") or "").encode(), f"desauth:{device_id}".encode(), hashlib.sha256).hexdigest(),
            }, separators=(",", ":")).encode("utf-8")
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                try:
                    sock.sendto(packet, ("255.255.255.255", DISCOVERY_PORT))
                except OSError:
                    pass
        return found

    def status(self) -> dict:
        self.start()
        with self.lock:
            devices = [{"device_id": key, **{k: v for k, v in value.items() if k != "secret"}}
                       for key, value in self.state["devices"].items()]
        return {"role": "desktop", "device_id": self.state["device_id"], "fingerprint": self.fingerprint, "devices": devices}


class AndroidPairingClient:
    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "device_sync" / "android.json"
        self.state = _load_json(self.path, {"phone_id": str(uuid.uuid4()), "pair": None})
        self.state.setdefault("phone_id", str(uuid.uuid4()))
        self.state.setdefault("pair", None)
        self.lock = threading.RLock()
        self.discovered: dict[str, dict] = {}
        self.last_sync = 0.0
        self.last_error = ""
        self.running = True
        threading.Thread(target=self._listen, daemon=True, name="mindinguflac-pairing-listener").start()
        threading.Thread(target=self._sync_loop, daemon=True, name="mindinguflac-data-sync").start()

    def _save(self):
        _write_json(self.path, self.state)

    def _listen(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", DISCOVERY_PORT))
            sock.settimeout(2)
            while self.running:
                try:
                    packet, address = sock.recvfrom(8192)
                    item = json.loads(packet.decode("utf-8"))
                    if item.get("kind") == "desauth":
                        with self.lock:
                            pair = self.state.get("pair") or {}
                            expected = hmac.new(str(pair.get("secret") or "").encode(), f"desauth:{self.state['phone_id']}".encode(), hashlib.sha256).hexdigest()
                            if (pair.get("device_id") == item.get("device_id")
                                    and item.get("target_id") == self.state["phone_id"]
                                    and secrets.compare_digest(expected, str(item.get("proof") or ""))):
                                self.state["pair"] = None
                                self._save()
                                self.last_error = "Desktop removed this device pairing"
                        continue
                    if item.get("protocol") != PROTOCOL or not item.get("device_id"):
                        continue
                    item["address"] = address[0]
                    with self.lock:
                        self.discovered[str(item["device_id"])] = item
                except socket.timeout:
                    continue
                except Exception:
                    continue
        except OSError as exc:
            self.last_error = f"LAN discovery unavailable: {exc}"
        finally:
            sock.close()

    def status(self) -> dict:
        with self.lock:
            pair = dict(self.state.get("pair") or {})
            pair.pop("secret", None)
            devices = list(self.discovered.values())
        return {
            "role": "android",
            "phone_id": self.state["phone_id"],
            "paired": bool(self.state.get("pair")),
            "pair": pair,
            "last_sync": self.last_sync,
            "last_error": self.last_error,
            "discovered": devices,
        }

    def _connect(self, device: dict, path: str, payload: dict, secret: str = "") -> dict:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        conn = http.client.HTTPSConnection(device["address"], int(device["port"]), context=context, timeout=5)
        conn.connect()
        cert = conn.sock.getpeercert(binary_form=True)
        fingerprint = hashlib.sha256(cert).hexdigest()
        if not secrets.compare_digest(fingerprint, str(device["fingerprint"])):
            conn.close()
            raise ValueError("Desktop certificate fingerprint does not match the scanned QR")
        headers = {"Content-Type": "application/json", "X-Mindinguflac-Device": str(payload.get("device_id") or "")}
        if secret:
            headers["X-Mindinguflac-Pair-Secret"] = secret
        conn.request("POST", path, body=json.dumps(payload).encode("utf-8"), headers=headers)
        response = conn.getresponse()
        raw = response.read(8 * 1024 * 1024)
        status = response.status
        conn.close()
        result = json.loads(raw.decode("utf-8") or "{}")
        if status not in (200, 410):
            raise RuntimeError(str(result.get("error") or f"Pairing request failed ({status})"))
        result["_status"] = status
        return result

    def pair(self, invitation: str) -> dict:
        parsed = urllib.parse.urlparse(invitation)
        if parsed.scheme == "mindinguflac":
            data = dict(urllib.parse.parse_qsl(parsed.query))
        else:
            try:
                data = json.loads(invitation)
            except Exception:
                raise ValueError("That QR code is not a Mindinguflac pairing invitation")
        target_id = str(data.get("device_id") or "")
        token = str(data.get("token") or "")
        fingerprint = str(data.get("fingerprint") or "")
        if not target_id or not token or len(fingerprint) != 64:
            raise ValueError("Pairing QR code is incomplete")
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            with self.lock:
                device = dict(self.discovered.get(target_id) or {})
            if device:
                break
            time.sleep(.25)
        else:
            raise TimeoutError("Could not find that desktop on this Wi-Fi network")
        if not secrets.compare_digest(fingerprint, str(device.get("fingerprint") or "")):
            raise ValueError("The desktop fingerprint advertised on Wi-Fi does not match the QR code")
        response = self._connect(device, "/pair/complete", {
            "device_id": target_id,
            "phone_id": self.state["phone_id"],
            "token": token,
            "fingerprint": fingerprint,
            "name": socket.gethostname() or "Android device",
        })
        pair = {
            "device_id": target_id,
            "phone_id": self.state["phone_id"],
            "secret": response["secret"],
            "fingerprint": fingerprint,
            "name": response.get("name") or device.get("name") or "Desktop",
        }
        with self.lock:
            self.state["pair"] = pair
            self._save()
            self.last_error = ""
        return {"ok": True, "name": pair["name"]}

    def _sync_once(self):
        with self.lock:
            pair = dict(self.state.get("pair") or {})
            device = dict(self.discovered.get(pair.get("device_id", "")) or {})
        if not pair:
            return
        if not device:
            raise TimeoutError("Waiting for the paired desktop to appear on Wi-Fi")
        if not secrets.compare_digest(str(pair.get("fingerprint") or ""), str(device.get("fingerprint") or "")):
            raise ValueError("Paired desktop fingerprint changed")
        outgoing = _local_snapshot(pair["phone_id"], float(pair.get("phone_cursor") or 0), float(pair.get("desktop_cursor") or 0))
        result = self._connect(device, "/sync", outgoing, pair["secret"])
        if result.get("desauth") or result.get("_status") == 410:
            with self.lock:
                self.state["pair"] = None
                self._save()
            raise RuntimeError("Desktop removed this device pairing")
        _apply_snapshot(result.get("snapshot") or {}, pair["device_id"])
        pair["desktop_cursor"] = float(((result.get("snapshot") or {}).get("statistics") or {}).get("cursor") or pair.get("desktop_cursor") or 0)
        pair["phone_cursor"] = float(outgoing["statistics"].get("cursor") or pair.get("phone_cursor") or 0)
        with self.lock:
            self.state["pair"] = pair
            self._save()
        self.last_sync = time.time()
        self.last_error = ""

    def _sync_loop(self):
        while self.running:
            try:
                self._sync_once()
            except Exception as exc:
                if self.state.get("pair"):
                    self.last_error = str(exc)[:240]
            time.sleep(5)

    def remove_pairing(self) -> dict:
        with self.lock:
            pair = dict(self.state.get("pair") or {})
            device = dict(self.discovered.get(pair.get("device_id", "")) or {})
        if not pair:
            return {"ok": True, "paired": False}
        if not device:
            raise TimeoutError("Connect to the paired desktop's Wi-Fi to send the removal message")
        result = self._connect(device, "/pair/remove", {"device_id": pair["device_id"]}, pair["secret"])
        if result.get("desauth"):
            with self.lock:
                self.state["pair"] = None
                self._save()
            return {"ok": True, "paired": False}
        raise RuntimeError("Desktop did not confirm pairing removal")

    def stop(self) -> None:
        self.running = False


def start_desktop_pairing() -> DesktopPairingService:
    global _desktop
    if _desktop is None:
        _desktop = DesktopPairingService()
    _desktop.start()
    return _desktop


def start_android_pairing(data_dir: str | Path) -> AndroidPairingClient:
    global _android
    if _android is None or not _android.running:
        _android = AndroidPairingClient(Path(data_dir))
    return _android


def status() -> dict:
    if os.environ.get("MINDINGUFLAC_ANDROID") == "1":
        return _android.status() if _android else {"role": "android", "paired": False, "discovered": []}
    return _desktop.status() if _desktop else {"role": "desktop", "devices": []}


def invitation() -> dict:
    if _desktop is None:
        raise RuntimeError("Desktop pairing service is not running")
    return _desktop.make_invitation()


def remove(device_id: str) -> dict:
    if os.environ.get("MINDINGUFLAC_ANDROID") == "1":
        if _android is None:
            raise RuntimeError("Android pairing service is not running")
        return _android.remove_pairing()
    if _desktop is None:
        raise RuntimeError("Desktop pairing service is not running")
    return {"ok": _desktop.remove_device(device_id)}


def pair(invitation_value: str) -> dict:
    if _android is None:
        raise RuntimeError("Android pairing service is not running")
    return _android.pair(invitation_value)


def stop_android_pairing() -> None:
    if _android is not None:
        _android.stop()

