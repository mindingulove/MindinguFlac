"""Thin CORS-bypass proxy for DuckDuckGo's duck.ai chat endpoints.

This module implements a direct bypass of the DuckDuckGo anti-bot layer
using static known-good headers and challenge solutions, eliminating the need
for the frontend to solve JS challenges.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

_STATUS_URL = "https://duckduckgo.com/duckchat/v1/status"
_CHAT_URL = "https://duckduckgo.com/duckchat/v1/chat"

# Hardcoded headers that match the expected browser fingerprint
_HEADERS = {
    "Accept": "text/event-stream",
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

# Static bypass payloads
_STATIC_HASH_1 = "eyJzZXJ2ZXJfaGFzaGVzIjpbImRQSlJJTWczZnFYQXIvaStaa3c2cEpFVzEwckdTdmxJVlVkNlFsOVRGWXc9IiwiMUN3Qzg3N0Q3WXE1dzlEeTc4UjhBVi9qZVZWaUlYbmV0Q0xvckx3c01QZz0iLCJQSzc3TGc2L25weDdWQ2J2UWxsTEhBR3cyenJIVmEvQUFBRFBhQTl1ekVRPSJdLCJjbGllbnRfaGFzaGVzIjpbImxWblI0MStCMVFWZ0o4d0hhMUdBNmdxR0JoSjlWdjN5K0dISkdGekJmTGM9IiwiVS9RRUc2RE1qdEU4V2hHU1FxOUU1Z0VGNmw1SWJrNk9NVlBuY01DU1licz0iLCJ6SURsYUNvZG9JUjNwbTNSVTlWOUJXaUJkZDJqenRMODAyN0VYTHhkWll3PSJdLCJzaWduYWxzIjp7fSwibWV0YSI6eyJ2IjoiNCIsImNoYWxsZW5nZV9pZCI6ImM4M2Q0ZTc5NTU2MjJmZjU3Mzc0ZDUzOTk2ZjliMmJhZGE2ZDQxZTMzNDM1ZjVlNzMyYjFmNmZjNmQ0ZTE1NzVoOGpidCIsInRpbWVzdGFtcCI6IjE3NTIxNTU3Nzc4NjYiLCJvcmlnaW4iOiJodHRwczovL2R1Y2tkdWNrZ28uY29tIiwic3RhY2siOiJFcnJvclxuYXQgRSAoaHR0cHM6Ly9kdWNrZHVja2dvLmNvbS9kaXN0L3dwbS5jaGF0LjcwZWFjYTZhZWEyOTQ4YjBiYjYwLmpzOjE6MTQ4MjUpXG5hdCBhc3luYyBodHRwczovL2R1Y2tkdWNrZ28uY29tIiwic3RhY2siOiJvdGhlcnMvY29yZS9sb2dvLnBuZyIsImR1cmF0aW9uIjoiNTgifX0="
_STATIC_SIGNALS = "eyJzdGFydCI6MTc1MjE1NTc3NzQ4MCwiZXZlbnRzIjpbeyJuYW1lIjoic3RhcnROZXdDaGF0IiwiZGVsdGEiOjc1fSx7Im5hbWUiOiJyZWNlbnRDaGF0c0xpc3RJbXByZXNzaW9uIiwiZGVsdGEiOjEyNH1dLCJlbmQiOjQzNDN9"
_STATIC_VERSION = "serp_20250710_090702_ET-70eaca6aea2948b0bb60"


def fetch_status(user_agent: str = "") -> dict:
    """GET the initial vqd. We don't need JS evaluation anymore."""
    headers = dict(_HEADERS)
    headers["x-vqd-accept"] = "1"
    headers["Accept"] = "*/*"

    req = urllib.request.Request(_STATUS_URL, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            # The dynamic VQD is actually returned in the x-vqd-hash-1 header in the /status response
            vqd4 = resp.headers.get("x-vqd-hash-1", "")
            return {"vqd_hash_1": vqd4, "error": ""}
    except urllib.error.HTTPError as exc:
        return {"vqd_hash_1": "", "error": f"HTTP {exc.code}"}
    except Exception as exc:  # noqa: BLE001
        return {"vqd_hash_1": "", "error": str(exc)}


def _parse_sse(raw: str) -> str:
    """DuckDuckGo streams the answer as Server-Sent Events."""
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            obj = json.loads(data)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(obj, dict) and isinstance(obj.get("message"), str):
            out.append(obj["message"])
    return "".join(out)


def send_chat(token: str, messages: list, model: str = "gpt-5-mini") -> dict:
    """POST a chat turn. `token` here is the x-vqd-4 string we got from fetch_status."""
    if not token:
        return {"ok": False, "error": "missing x-vqd-4 token"}

    headers = dict(_HEADERS)
    headers["x-vqd-4"] = token
    headers["x-vqd-hash-1"] = _STATIC_HASH_1
    headers["x-fe-signals"] = _STATIC_SIGNALS
    headers["x-fe-version"] = _STATIC_VERSION
    headers["Content-Type"] = "application/json"

    payload = json.dumps({"model": model, "messages": messages}).encode("utf-8")
    req = urllib.request.Request(_CHAT_URL, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "replace")
            # The new VQD for the next request is in the x-vqd-4 header
            next_token = resp.headers.get("x-vqd-4", "") or ""
            return {"ok": True, "text": _parse_sse(raw), "vqd_hash_1": next_token, "status": 200, "error": ""}
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace")[:600]
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "status": exc.code, "error": f"HTTP {exc.code}", "body": body,
                "vqd_hash_1": exc.headers.get("x-vqd-4", "") or ""}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}

def save_bypass(data):
    pass
