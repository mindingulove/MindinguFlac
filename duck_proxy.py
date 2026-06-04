"""Thin CORS-bypass proxy for DuckDuckGo's duck.ai chat endpoints.

This module implements the exact breakthrough bypass discovered by benoitpetit/duckduckgo-chat-cli
which uses a static browser-derived JSON VQD hash to eliminate 418 errors.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

_STATUS_URL = "https://duckduckgo.com/duckchat/v1/status"
_CHAT_URL = "https://duckduckgo.com/duckchat/v1/chat"

# Breakthrough Headers - 100% Match with benoitpetit repo breakthrough
_HEADERS = {
    "Accept": "text/event-stream",
    "Accept-Language": "fr-FR,fr;q=0.7",
    "Content-Type": "application/json",
    "DNT": "1",
    "Origin": "https://duckduckgo.com",
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

# The Breakthrough Static Proof (Hardcoded as per repo commit 3fa5c14)
_STATIC_HASH_1 = "eyJzZXJ2ZXJfaGFzaGVzIjpbIjR0Ui9HdVdKV0UyTzBzV2x4V0ZiNU5PbmV0SkdoUFNGTDdwSlpEUTJvTlE9IiwiK2ZaZnphZmdiZGtTUm53WEFaOW03bVZTSG5xRFZzVEhzYzgzZ3NKeXRSOD0iLCJTMVhmclNybnAyektUOGtKNE1pRDNSUk9ORzk1eFRwWGxLYko1ZUZXOGlrPSJdLCJjbGllbnRfaGFzaGVzIjpbImxWblI0MStCMVFWZ0o4d0hhMUdBNmdxR0JoSjlWdjN5K0dISkdGekJmTGM9IiwiTDROMTBxbVBnL0N1MWZzTlpMYm9CWkFTWjVGVEljNjUwNklHTzJEUVhMcz0iLCJrbFdNUTBlRDVDeUhhdXl5dnBia2hEZWs3UDZrYjF0aHlrMVNLRFlUWHRrPSJdLCJzaWduYWxzIjp7fSwibWV0YSI6eyJ2IjoiNCIsImNoYWxsZW5nZV9pZCI6IjA3ZjgxYTljZThiZmJjMzRiMWM3NGY5OTQwODkzZTA1ZWY2MmVhZjVhNTY5MTdmODRkYWZlYTExMGI1OTNjNThoOGpidCIsInRpbWVzdGFtcCI6IjE3NTIwODEyNDczOTQiLCJvcmlnaW4iOiJodHRwczovL2R1Y2tkdWNrZ28uY29tIiwic3RhY2siOiJFcnJvclxuYXQgdmUgKGh0dHBzOi8vZHVja2R1Y2tnby5jb20vZGlzdC93cG0uY2hhdC45NTFkMTYyZTJhODJmZmQ2OTBiZC5qczoxOjI3NjYwKVxuYXQgYXN5bmMgaHR0cHM6Ly9kdWNrZHVja2dvLmNvbS9kaXN0L3dwbS5jaGF0Ljk1MWQxNjJlMmE4MmZmZDY5MGJkLmpzOjE6Mjk4NDciLCJkdXJhdGlvbiI6Ijg4In19"
_STATIC_SIGNALS = "eyJzdGFydCI6MTc1MjE1NTc3NzQ4MCwiZXZlbnRzIjpbeyJuYW1lIjoic3RhcnROZXdDaGF0IiwiZGVsdGEiOjc1fSx7Im5hbWUiOiJyZWNlbnRDaGF0c0xpc3RJbXByZXNzaW9uIiwiZGVsdGEiOjEyNH1dLCJlbmQiOjQzNDN9"
_STATIC_VERSION = "serp_20250710_090702_ET-70eaca6aea2948b0bb60"


def fetch_status(user_agent: str = "") -> dict:
    """Step 1: GET /status to obtain the dynamic x-vqd-4 header."""
    headers = dict(_HEADERS)
    headers["x-vqd-accept"] = "1"
    headers["Accept"] = "*/*"

    req = urllib.request.Request(_STATUS_URL, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            # The dynamic token needed for chat is in the x-vqd-hash-1 header in status
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
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            obj = json.loads(data)
            if isinstance(obj, dict) and obj.get("message"):
                out.append(obj["message"])
        except:
            continue
    return "".join(out)


def send_chat(token: str, messages: list, model: str = "gpt-5-mini") -> dict:
    """Step 2: POST /chat with static proofs and dynamic VQD rotation."""
    if not token:
        return {"ok": False, "error": "missing x-vqd-4 token"}

    headers = dict(_HEADERS)
    headers["x-vqd-4"] = token
    headers["x-vqd-hash-1"] = _STATIC_HASH_1
    headers["x-fe-signals"] = _STATIC_SIGNALS
    headers["x-fe-version"] = _STATIC_VERSION

    payload = json.dumps({
        "model": model,
        "messages": messages,
        "canUseTools": True,
        "canUseApproxLocation": True
    }).encode("utf-8")

    req = urllib.request.Request(_CHAT_URL, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "replace")
            # Step 7: Next VQD is in x-vqd-4 header
            next_token = resp.headers.get("x-vqd-4", "") or ""
            return {"ok": True, "text": _parse_sse(raw), "vqd_hash_1": next_token, "status": 200, "error": ""}
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace")[:600]
        except:
            pass
        return {"ok": False, "status": exc.code, "error": f"HTTP {exc.code}", "body": body,
                "vqd_hash_1": exc.headers.get("x-vqd-4", "") or ""}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

def save_bypass(data):
    pass
