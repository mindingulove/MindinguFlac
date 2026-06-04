"""Thin CORS-bypass proxy for DuckDuckGo's duck.ai chat endpoints.

This module follows the reverse-engineered logic from benoitpetit/duckduckgo-chat-cli
to bypass anti-bot measures (418/429 errors) without a headless browser.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
import time

_STATUS_URL = "https://duckduckgo.com/duckchat/v1/status"
_CHAT_URL = "https://duckduckgo.com/duckchat/v1/chat"

# Static headers and tokens as per the reverse engineering documentation
_BROWSER_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "fr-FR,fr;q=0.6",
    "Cache-Control": "no-store",
    "DNT": "1",
    "Priority": "u=1, i",
    "Referer": "https://duckduckgo.com/",
    "Sec-CH-UA": '"Not)A;Brand";v="8", "Chromium";v="138", "Brave";v="138"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Sec-GPC": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    "Cookie": "5=1; dcm=3; dcs=1",
}

# The "Breakthrough" Static Proofs
_STATIC_VQD_HASH_1 = "eyJzZXJ2ZXJfaGFzaGVzIjpbImRQSlJJTWczZnFYQXIvaStaa3c2cEpFVzEwckdTdmxJVlVkNlFsOVRGWXc9IiwiMUN3Qzg3N0Q3WXE1dzlEeTc4UjhBVi9qZVZWaUlYbmV0Q0xvckx3c01QZz0iLCJQSzc3TGc2L25weDdWQ2J2UWxsTEhBR3cyenJIVmEvQUFBRFBhQTl1ekVRPSJdLCJjbGllbnRfaGFzaGVzIjpbImxWblI0MStCMVFWZ0o4d0hhMUdBNmdxR0JoSjlWdjN5K0dISkdGekJmTGM9IiwiVS9RRUc2RE1qdEU4V2hHU1FxOUU1Z0VGNmw1SWJrNk9NVlBuY01DU1licz0iLCJ6SURsYUNvZG9JUjNwbTNSVTlWOUJXaUJkZDJqenRMODAyN0VYTHhkWll3PSJdLCJzaWduYWxzIjp7fSwibWV0YSI6eyJ2IjoiNCIsImNoYWxsZW5nZV9pZCI6ImM4M2Q0ZTc5NTU2MjJmZjU3Mzc0ZDUzOTk2ZjliMmJhZGE2ZDQxZTMzNDM1ZjVlNzMyYjFmNmZjNmQ0ZTE1NzVoOGpidCIsInRpbWVzdGFtcCI6IjE3NTIxNTU3Nzc4NjYiLCJvcmlnaW4iOiJodHRwczovL2R1Y2tkdWNrZ28uY29tIiwic3RhY2siOiJFcnJvclxuYXQgRSAoaHR0cHM6Ly9kdWNrZHVja2dvLmNvbS9kaXN0L3dwbS5jaGF0LjcwZWFjYTZhZWEyOTQ4YjBiYjYwLmpzOjE6MTQ4MjUpXG5hdCBhc3luYyBodHRwczovL2R1Y2tkdWNrZ28uY29tIiwic3RhY2siOiJvdGhlcnMvY29yZS9sb2dvLnBuZyIsImR1cmF0aW9uIjoiNTgifX0="
_STATIC_FE_SIGNALS = "eyJzdGFydCI6MTc1MjE1NTc3NzQ4MCwiZXZlbnRzIjpbeyJuYW1lIjoic3RhcnROZXdDaGF0IiwiZGVsdGEiOjc1fSx7Im5hbWUiOiJyZWNlbnRDaGF0c0xpc3RJbXByZXNzaW9uIiwiZGVsdGEiOjEyNH1dLCJlbmQiOjQzNDN9"
_STATIC_FE_VERSION = "serp_20250710_090702_ET-70eaca6aea2948b0bb60"


def fetch_status(user_agent: str = "") -> dict:
    """GET request to /status to obtain the dynamic x-vqd-4 header."""
    headers = dict(_BROWSER_HEADERS)
    headers["x-vqd-accept"] = "1"
    
    req = urllib.request.Request(_STATUS_URL, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            # The VQD header for chat requests is returned as x-vqd-hash-1 in /status
            vqd = resp.headers.get("x-vqd-hash-1", "")
            return {"vqd_hash_1": vqd, "error": ""}
    except urllib.error.HTTPError as exc:
        return {"vqd_hash_1": "", "error": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"vqd_hash_1": "", "error": str(exc)}


def _parse_sse(raw: str) -> str:
    """Parse DuckDuckGo streaming response."""
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


import os

_BYPASS_FILE = os.path.join("data", "duck_bypass.json")

def _load_bypass() -> dict:
    if os.path.exists(_BYPASS_FILE):
        try:
            with open(_BYPASS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {}

def save_bypass(data: dict):
    """Save a fresh browser proof harvested from the frontend."""
    os.makedirs("data", exist_ok=True)
    with open(_BYPASS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# Fallback headers if no bypass is harvested yet
_DEFAULT_HEADERS = {
    "Accept": "text/event-stream",
    "Accept-Language": "en-GB,en;q=0.9",
    "Cache-Control": "no-store",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
}

def send_chat(vqd_4: str, messages: list, model: str = "gpt-5-mini", **kwargs) -> dict:
    """POST request to /chat using harvested or default proofs."""
    if not vqd_4:
        return {"ok": False, "error": "missing x-vqd-4 token"}

    bypass = _load_bypass()
    
    # Use harvested headers/proofs if available, else use best-effort defaults
    headers = bypass.get("headers", dict(_DEFAULT_HEADERS))
    headers["x-vqd-4"] = vqd_4
    headers["x-vqd-hash-1"] = bypass.get("vqd_hash_1", _STATIC_VQD_HASH_1)
    headers["x-fe-signals"] = bypass.get("x_fe_signals", _STATIC_FE_SIGNALS)
    headers["x-fe-version"] = bypass.get("x_fe_version", _STATIC_FE_VERSION)
    headers["Content-Type"] = "application/json"
    headers["Accept"] = "text/event-stream"

    payload = json.dumps({
        "model": model,
        "messages": messages
    }).encode("utf-8")

    req = urllib.request.Request(_CHAT_URL, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "replace")
            # The next token for turn-based chat is returned in the x-vqd-4 header
            next_token = resp.headers.get("x-vqd-4", "")
            return {
                "ok": True,
                "text": _parse_sse(raw),
                "vqd_hash_1": next_token, # Keep naming consistent for frontend
                "status": 200,
                "error": ""
            }
    except urllib.error.HTTPError as exc:
        body = ""
        try: body = exc.read().decode("utf-8", "replace")[:500]
        except: pass
        return {
            "ok": False,
            "status": exc.code,
            "error": f"HTTP {exc.code}",
            "body": body,
            "vqd_hash_1": exc.headers.get("x-vqd-4", "") or ""
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
