from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from typing import Any


def is_enabled() -> bool:
    provider = _provider()
    if provider == "openai":
        return bool(os.environ.get("MINDINGUFLAC_AI_RERANK_URL"))
    if provider in {"duck", "duck_chat", "duckai"}:
        return _duck_available()
    return False


def _provider() -> str:
    explicit = os.environ.get("MINDINGUFLAC_AI_RERANK_PROVIDER", "").strip().lower()
    if explicit:
        return explicit
    if os.environ.get("MINDINGUFLAC_AI_RERANK_URL"):
        return "openai"
    return "duck_chat"


def _timeout() -> float:
    try:
        return max(1.0, min(20.0, float(os.environ.get("MINDINGUFLAC_AI_RERANK_TIMEOUT", "8"))))
    except Exception:
        return 8.0


def _model() -> str:
    return os.environ.get("MINDINGUFLAC_AI_RERANK_MODEL", "gpt-4o-mini")


def _duck_available() -> bool:
    try:
        import duck_proxy  # noqa: F401
        return True
    except Exception:
        return False


def _parse_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass

    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _openai_compatible_request(prompt: str) -> dict[str, Any]:
    url = os.environ.get("MINDINGUFLAC_AI_RERANK_URL", "").strip()
    if not url:
        return {}
    payload = {
        "model": _model(),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ.get('MINDINGUFLAC_AI_RERANK_KEY', '')}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_timeout()) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return {}
    text = ""
    try:
        text = data["choices"][0]["message"]["content"]
    except Exception:
        text = data.get("text", "") if isinstance(data, dict) else ""
    return _parse_json_object(text)


def _duck_model_key(override: str) -> str:
    value = override or os.environ.get("MINDINGUFLAC_DUCKCHAT_MODEL", "").strip()
    if value in {"1", "2", "3", "4", "5"}:
        return value
    return "1"


def _duck_request(prompt: str, duck_model: str) -> dict[str, Any]:
    import duck_proxy

    # We need to prepend system instructions since we are passing a single prompt
    messages = [
        {
            "role": "user",
            "content": (
                "You rank clean music candidates. Return only JSON. "
                "Never promote adult, restricted, or unrelated candidates.\n\n"
                f"{prompt}"
            ),
        }
    ]

    status = duck_proxy.fetch_status()
    vqd = status.get("vqd_hash_1", "")
    if not vqd:
        return {}

    # Map the environment variable model to the actual model strings (June 2026)
    model_key = _duck_model_key(duck_model)
    models = {
        "1": "gpt-5-mini",
        "2": "claude-4.5-haiku",
        "3": "meta-llama/Llama-4-Scout",
        "4": "mistralai/Mistral-Small-4",
    }
    model = models.get(model_key, "gpt-5-mini")

    res = duck_proxy.send_chat(token=vqd, messages=messages, model=model)
    if res.get("ok"):
        return _parse_json_object(res.get("text", ""))
    return {}


def _request(prompt: str, duck_model: str) -> dict[str, Any]:
    provider = _provider()
    if provider == "openai":
        return _openai_compatible_request(prompt)
    if provider in {"duck", "duck_chat", "duckai"}:
        return _duck_request(prompt, duck_model)
    return {}


import urllib.parse


def _parse_magnet(uri: str) -> dict[str, Any]:
    """Extract useful signals from a magnet URI for the AI to analyze."""
    if not uri or not uri.startswith("magnet:?"):
        return {}
    try:
        parsed = urllib.parse.parse_qs(uri[8:])
        return {
            "dn": (parsed.get("dn") or [""])[0],
            "trackers": [urllib.parse.urlparse(t).netloc for t in parsed.get("tr", []) if t],
            "is_multipass": len(parsed.get("tr", [])) > 5
        }
    except Exception:
        return {}


def rank_candidates(target: dict[str, str], candidates: list[dict[str, Any]], duck_model: str = "1") -> list[int]:
    if not is_enabled() or not candidates:
        return []
    
    is_youtube = any("youtube" in str(c.get("query", "")).lower() or "youtube" in str(c.get("source", "")).lower() for c in candidates)
    
    compact_candidates = []
    for item in candidates[:20]:
        if is_youtube:
            compact_candidates.append({
                "id": int(item.get("id", 0)),
                "title": str(item.get("title") or "")[:160],
                "channel": str(item.get("source") or "YouTube")[:60],
                "local_score": int(float(item.get("score") or 0)),
            })
        else:
            magnet_data = _parse_magnet(item.get("magnet") or "")
            compact_candidates.append({
                "id": int(item.get("id", 0)),
                "title": str(item.get("title") or "")[:160],
                "seeders": int(item.get("seeders") or 0),
                "local_score": int(float(item.get("score") or 0)),
                "magnet_dn": magnet_data.get("dn", "")[:120],
                "trackers": magnet_data.get("trackers", [])[:6],
            })

    if is_youtube:
        task_desc = (
            "Rank YouTube candidate IDs for the requested music. "
            "PRIORITIZE: Official Artist Channels and '- Topic' channels. "
            "IDENTIFY: High-fidelity metadata (Remastered, Official Audio). "
            "AVOID: Music videos with long intros/outros, live performances (unless requested), and covers. "
            "Return {\"ranked_ids\":[...]} in order of highest confidence audio match."
        )
    else:
        task_desc = (
            "Rank candidate IDs for the requested music. Use metadata AND technical signals "
            "(Trackers/DN) to prioritize high-fidelity, healthy music swarms. "
            "Prioritize specialized trackers and FLAC/Lossless release group tags. "
            "Return {\"ranked_ids\":[...]} using only IDs that are plausible music matches."
        )

    prompt = json.dumps({
        "task": task_desc,
        "target": {
            "artist": target.get("artist", ""),
            "title": target.get("title", ""),
            "album": target.get("album", ""),
        },
        "candidates": compact_candidates,
    }, ensure_ascii=True)
    result = _request(prompt, duck_model)
    ranked = result.get("ranked_ids") if isinstance(result, dict) else None
    if not isinstance(ranked, list):
        return []
    valid_ids = {int(item["id"]) for item in compact_candidates}
    out: list[int] = []
    for value in ranked:
        try:
            candidate_id = int(value)
        except Exception:
            continue
        if candidate_id in valid_ids and candidate_id not in out:
            out.append(candidate_id)
    return out
