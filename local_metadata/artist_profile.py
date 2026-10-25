"""Artist profile implementation retained from SpotiFLAC 3.9.0 (MIT)."""
import asyncio
import logging
import re
logger = logging.getLogger(__name__)

async def fetch_artist_profile(artist_id: str, web_client) -> dict:
    payload = {
        "operationName": "queryArtistOverview",
        "variables": {"uri": f"spotify:artist:{artist_id}", "locale": ""},
        "extensions": {
            "persistedQuery": {
                "version": 1,
                "sha256Hash": "446130b4a0aa6522a686aafccddb0ae849165b5e0436fd802f96e0243617b5d8",
            },
        },
    }
    try:
        response = await asyncio.to_thread(web_client.query, payload)
        artist_data = response.get("data", {}).get("artistUnion", {})
        if not artist_data:
            return {}

        profile = artist_data.get("profile") or {}
        stats = artist_data.get("stats") or {}

        avatar_node = artist_data.get("visuals", {}).get("avatarImage", {})
        sources = avatar_node.get("sources", []) or (
            avatar_node.get("data") or {}
        ).get("sources", [])
        avatar_url = sources[0].get("url") if sources else None

        h_node = artist_data.get("headerImage", {})
        h_sources = h_node.get("sources", []) or (h_node.get("data") or {}).get(
            "sources",
            [],
        )
        header_url = h_sources[0].get("url") if h_sources else None

        return {
            "id": artist_id,
            "profile": {
                "name": (profile or {}).get("name", ""),
                "biography": re.sub(
                    r"<[^>]+>",
                    "",
                    (
                        ((profile.get("biography") or {}).get("text") or "")
                        if isinstance(profile.get("biography"), dict)
                        else (profile.get("biography") or "")
                    ),
                ),
                "verified": bool((profile or {}).get("verified", False)),
            },
            "stats": {
                "followers": int(stats.get("followers") or 0),
                "listeners": int(stats.get("monthlyListeners") or 0),
                "rank": int(stats["worldRank"]) if stats.get("worldRank") else None,
            },
            "avatar": avatar_url,
            "header": header_url,
            "discography_total": int(
                artist_data.get("discography", {}).get("all", {}).get("totalCount")
                or 0,
            ),
        }
    except Exception as e:
        logger.warning(f"[spotify] Profile fetch failed: {e}")
        return {"profile": {"name": "Unknown"}, "stats": {}}
