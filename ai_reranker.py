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


def is_enabled(ai_provider: str = "") -> bool:
    provider = _selected_provider(ai_provider) if ai_provider else _provider()
    if provider == "openai":
        return bool(os.environ.get("MINDINGUFLAC_AI_RERANK_URL"))
    if provider in {"duck", "duck_chat", "duckai"}:
        return _duck_available()
    if provider == "gemini":
        return True # Handled via playwright worker
    return False


def _provider() -> str:
    explicit = os.environ.get("MINDINGUFLAC_AI_RERANK_PROVIDER", "").strip().lower()
    if explicit:
        return explicit
    if os.environ.get("MINDINGUFLAC_AI_RERANK_URL"):
        return "openai"
    # Default to duckai if nothing else specified
    return "duckai"


def _selected_provider(ai_provider: str) -> str:
    return (ai_provider or os.environ.get("MINDINGUFLAC_AI_RERANK_PROVIDER", "duckai")).strip().lower()


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
    """Robustly extract a JSON object from possibly-messy text."""
    raw = str(text or "").strip()
    if not raw:
        return {}

    # 1. Try markdown blocks
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL | re.IGNORECASE)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass

    # 2. Try strict brace finding
    start = raw.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(raw)):
            ch = raw[i]
            if in_str:
                if esc: esc = False
                elif ch == "\\": esc = True
                elif ch == '"': in_str = False
                continue
            if ch == '"': in_str = True
            elif ch == "{": depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(raw[start:i + 1])
                        if isinstance(parsed, dict): return parsed
                    except Exception: break
        start = raw.find("{", start + 1)
        
    # 3. LAZY PARSER: If Gemini returned prose like "Ranked IDs: [1, 2, 4]"
    m_list = re.search(r"ranked_ids\"?:\s*\[([0-9,\s]+)\]", raw, re.IGNORECASE)
    if m_list:
        try:
            ids = [int(x.strip()) for x in m_list.group(1).split(",") if x.strip()]
            return {"ranked_ids": ids}
        except Exception:
            pass

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


def _gemini_request(prompt: str, model: str = "gemini-1.5-flash") -> dict[str, Any]:
    print(f"[ai_reranker] Sending request to Gemini ({model})...")
    import gemini_proxy
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
    res = gemini_proxy.send_chat(prompt=prompt, messages=messages, ensure_model=model)
    if res.get("ok"):
        return _parse_json_object(res.get("text", ""))
    return {}


def _request(prompt: str, duck_model: str = "1", ai_provider: str = "duckai", gemini_model: str = "gemini-1.5-flash") -> dict[str, Any]:
    # Prefer the saved/app-selected provider. Environment override is only a fallback.
    provider = _selected_provider(ai_provider)
    
    if provider == "openai":
        return _openai_compatible_request(prompt)
    
    if provider in {"duck", "duck_chat", "duckai"}:
        res = _duck_request(prompt, duck_model)
        # Fallback to gemini if Duck.ai fails (e.g. rate limited)
        if not res or (isinstance(res, dict) and res.get("rate_limited")):
            print("[ai_reranker] Duck.ai limit reached or failed, falling back to Gemini")
            return _gemini_request(prompt, gemini_model)
        return res
        
    if provider == "gemini":
        return _gemini_request(prompt, gemini_model)
        
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


def _is_youtube_url(url: str) -> bool:
    return bool(url) and ("youtube.com/watch" in url or "youtu.be/" in url)


def rank_candidates(
    target: dict[str, str],
    candidates: list[dict[str, Any]],
    duck_model: str = "1",
    ai_provider: str = "duckai",
    gemini_model: str = "gemini-1.5-flash",
    include_urls: bool = False,
    video_mode: bool = False,
    video_clip_mode: bool = False,
) -> list[int] | dict[str, list[Any]]:
    if not is_enabled(ai_provider) or not candidates:
        return {"ranked_ids": [], "ranked_urls": []} if include_urls else []

    is_youtube = any("youtube" in str(c.get("query", "")).lower() or "youtube" in str(c.get("source", "")).lower() for c in candidates)

    compact_candidates = []
    for item in candidates[:20]:
        if is_youtube:
            compact_candidates.append({
                "id": int(item.get("id", 0)),
                "title": str(item.get("title") or "")[:160],
                "channel": str(item.get("source") or "YouTube")[:60],
                "local_score": int(float(item.get("score") or 0)),
                "url": str(item.get("url") or item.get("webpage_url") or "")[:300],
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

    if is_youtube and video_mode:
        task_desc = (
            "Find the official standalone MUSIC VIDEO (real filmed video content) on YouTube for the requested track. "
            "First, try to recall the exact VEVO YouTube URL (e.g. from ArtistNameVEVO channel) from your training data and return it as 'suggested_url' — this takes absolute priority over all candidates. "
            "If no VEVO URL is known, try the Official Artist Channel URL instead. "
            "Only leave 'suggested_url' empty if you have no confident knowledge of the official video URL. "
            "PRIORITIZE: VEVO channels, Official Artist Channels, actual standalone filmed music videos. "
            "STRICTLY AVOID: 'Official Audio' videos (just album art), lyric videos, visualizers, covers, tributes, fan-made, reactions, live performances, auto-generated Topic channel uploads, "
            "movie trailers, documentary clips, concert films, compilation albums, soundtracks, 'This Is It', or any video that is part of a movie/film project. "
            "Return {\"suggested_url\":\"<full youtube url or empty string>\",\"ranked_ids\":[...],\"ranked_urls\":[...]}."
        )
    elif is_youtube:
        task_desc = (
            "Rank YouTube candidate IDs for the requested music. "
            "PRIORITIZE: Official Artist Channels and '- Topic' channels. "
            "IDENTIFY: High-fidelity metadata (Remastered, Official Audio). "
            "AVOID: Music videos with long intros/outros, live performances (unless requested), and covers. "
            "Return {\"ranked_ids\":[...],\"ranked_urls\":[...]} in order of highest confidence audio match. "
            "Use only URLs from the provided candidate list."
        )
    elif video_clip_mode:
        task_desc = (
            "Rank these video torrent candidates for the best official music video clip. "
            "Prioritize: exact artist+title name match, official/VEVO music videos, "
            "reasonable file size (under 700 MB), healthy seed/leech count. "
            "REJECT: audio-only releases (FLAC/MP3/320kbps/lossless), full concerts, "
            "documentaries, TV episodes, adult content, or unrelated artists. "
            "Return {\"ranked_ids\":[...]} using only IDs for plausible music VIDEO clip matches, "
            "best match first."
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
    result = _request(prompt, duck_model, ai_provider, gemini_model)
    ranked = result.get("ranked_ids") if isinstance(result, dict) else None
    if not isinstance(ranked, list):
        return {"ranked_ids": [], "ranked_urls": [], "suggested_url": ""} if include_urls and is_youtube else []
    valid_ids = {int(item["id"]) for item in compact_candidates}
    out: list[int] = []
    for value in ranked:
        try:
            candidate_id = int(value)
        except Exception:
            continue
        if candidate_id in valid_ids and candidate_id not in out:
            out.append(candidate_id)

    if not (include_urls and is_youtube):
        return out

    id_to_url = {
        int(item["id"]): str(item.get("url") or "").strip()
        for item in compact_candidates
        if str(item.get("url") or "").strip()
    }
    ranked_urls = result.get("ranked_urls") if isinstance(result, dict) else None
    url_out: list[str] = []
    if isinstance(ranked_urls, list):
        valid_urls = set(id_to_url.values())
        for value in ranked_urls:
            url = str(value or "").strip()
            if url and url in valid_urls and url not in url_out:
                url_out.append(url)
    if not url_out:
        url_out = [id_to_url[candidate_id] for candidate_id in out if candidate_id in id_to_url]

    suggested_url = ""
    if video_mode and isinstance(result, dict):
        raw = str(result.get("suggested_url") or "").strip()
        if _is_youtube_url(raw):
            suggested_url = raw

    return {"ranked_ids": out, "ranked_urls": url_out, "suggested_url": suggested_url}
