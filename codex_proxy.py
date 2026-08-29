"""Codex advisor access through explicit, cached OAuth authentication.

The third-party ``codex-auth`` package normally monkey-patches every OpenAI SDK
client on import. Mindinguflac disables that global behavior and uses its
explicit client only, keeping Codex authentication isolated from other code.
"""
from __future__ import annotations

import os
import threading
from typing import Any

os.environ["CODEX_AUTH_NO_PATCH"] = "1"

from codex_auth import CodexClient  # noqa: E402
from codex_auth.auth import authenticate, refresh_access_token  # noqa: E402
from codex_auth.tokens import AuthTokens, TokenStore  # noqa: E402


DEFAULT_MODEL = "gpt-5.4-mini"
_lock = threading.Lock()


def _stored_tokens():
    """Load or refresh cached credentials without ever starting interactive login."""
    store = TokenStore()
    tokens = store.load()
    if not tokens or not tokens.access_token:
        return None
    if tokens.is_expired():
        if not tokens.refresh_token:
            return None
        try:
            raw = refresh_access_token(tokens.refresh_token)
            tokens = AuthTokens.from_response(
                raw,
                tokens.refresh_token,
                tokens.account_id,
            )
            store.save(tokens)
        except Exception:
            return None
    return tokens


def fetch_status() -> dict[str, Any]:
    """Return login state without opening a browser or exposing token data."""
    return {
        "ok": True,
        "authenticated": _stored_tokens() is not None,
        "model": DEFAULT_MODEL,
    }


def login() -> dict[str, Any]:
    """Authenticate if necessary; the package opens the system browser for PKCE."""
    try:
        with _lock:
            tokens = authenticate()
        return {"ok": bool(tokens.access_token), "authenticated": bool(tokens.access_token)}
    except Exception as exc:
        return {"ok": False, "authenticated": False, "error": str(exc)}


def send_chat(prompt: str, model: str = DEFAULT_MODEL) -> dict[str, Any]:
    """Send one advisor prompt without triggering an unexpected login popup."""
    if not str(prompt or "").strip():
        return {"ok": False, "error": "empty prompt"}
    tokens = _stored_tokens()
    if tokens is None:
        return {"ok": False, "error": "Codex login required"}

    try:
        with _lock:
            # Pass the already validated token so an advisor request can never
            # start a surprise interactive browser login.
            client = CodexClient(token=tokens.access_token, timeout=30.0)
            try:
                stream = client.responses.create(
                    model=model or DEFAULT_MODEL,
                    instructions=(
                        "You are an advisory music-matching component. Follow the requested "
                        "output format exactly and never promote unsafe or unrelated content."
                    ),
                    input=str(prompt),
                    stream=True,
                )
                # codex-auth 0.1.1's non-stream buffer loses output_text with
                # current Codex responses. Streaming deltas retain it reliably.
                text = "".join(
                    str(getattr(event, "delta", "") or "")
                    for event in stream
                    if getattr(event, "type", "") == "response.output_text.delta"
                )
            finally:
                client.close()
        return {"ok": bool(text), "text": text, "model": model or DEFAULT_MODEL}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
