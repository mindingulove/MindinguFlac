"""Thin CORS-bypass proxy for DuckDuckGo's duck.ai chat endpoints.

This module implements a dynamic bypass that periodically 'harvests' fresh 
anti-bot proofs from the app's real browser environment.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
import os
import config

_STATUS_URL = "https://duck.ai/duckchat/v1/status"
_CHAT_URL = "https://duck.ai/duckchat/v1/chat"

def _bypass_path() -> str:
    return str(config.app_data_dir() / "duck_bypass.json")

def _load_bypass() -> dict:
    path = _bypass_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {}

def save_bypass(data: dict):
    """Save a fresh browser proof harvested from the frontend."""
    path = _bypass_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# Fallback headers (Mac/Safari June 4, 2026)
_DEFAULT_HEADERS = {
    "Accept": "text/event-stream",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "en-GB,en;q=0.9",
    "Cache-Control": "no-store",
    "Origin": "https://duck.ai",
    "Referer": "https://duck.ai/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.5 Safari/605.1.15",
    "x-ddg-journey-id": "9cc6bed97b1bf9ae5c398c7fef8c5a49"
}

def fetch_status(user_agent: str = "") -> dict:
    """GET the dynamic VQD for the current turn."""
    bypass = _load_bypass()
    headers = bypass.get("headers", dict(_DEFAULT_HEADERS))
    headers["x-vqd-accept"] = "1"
    headers["Accept"] = "*/*"
    
    req = urllib.request.Request(_STATUS_URL, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            vqd = resp.headers.get("x-vqd-hash-1", "")
            return {"vqd_hash_1": vqd, "error": ""}
    except urllib.error.HTTPError as exc:
        return {"vqd_hash_1": "", "error": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"vqd_hash_1": "", "error": str(exc)}

def _parse_sse(raw: str) -> str:
    """Parse Duck.ai streaming response."""
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data:"): continue
        data = line[5:].strip()
        if data == "[DONE]": break
        try:
            obj = json.loads(data)
            if isinstance(obj, dict) and obj.get("message"):
                out.append(obj["message"])
        except: continue
    return "".join(out)

def send_chat(vqd_4: str, messages: list, model: str = "gpt-5-mini", **kwargs) -> dict:
    """POST request to /chat using the latest harvested proof."""
    if not vqd_4:
        return {"ok": False, "error": "missing x-vqd-4 token"}

    bypass = _load_bypass()
    headers = bypass.get("headers", dict(_DEFAULT_HEADERS))
    
    headers["x-vqd-4"] = vqd_4
    headers["x-vqd-hash-1"] = bypass.get("vqd_hash_1", "")
    headers["x-fe-signals"] = bypass.get("x_fe_signals", "")
    headers["x-fe-version"] = bypass.get("x_fe_version", "")
    headers["Content-Type"] = "application/json"
    headers["Accept"] = "text/event-stream"

    payload = json.dumps({"model": model, "messages": messages}).encode("utf-8")
    req = urllib.request.Request(_CHAT_URL, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "replace")
            next_vqd = resp.headers.get("x-vqd-4", "")
            return {
                "ok": True,
                "text": _parse_sse(raw),
                "vqd_hash_1": next_vqd,
                "status": 200,
                "error": ""
            }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:600]
        return {
            "ok": False,
            "status": exc.code,
            "error": f"HTTP {exc.code}",
            "body": body,
            "vqd_hash_1": exc.headers.get("x-vqd-4", "") or ""
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
