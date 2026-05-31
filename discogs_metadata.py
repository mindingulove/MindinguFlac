from __future__ import annotations

import functools
import json
import os
import urllib.parse
import urllib.request


API_BASE = "https://api.discogs.com"
USER_AGENT = "Mindinguflac/1.0 +https://www.discogs.com/developers/"


def _normalise(value: str) -> str:
    return "".join(char for char in (value or "").lower() if char.isalnum())


class DiscogsClient:
    def __init__(self, token: str = "", timeout: int = 10) -> None:
        self.token = (token or os.environ.get("DISCOGS_TOKEN", "")).strip()
        self.timeout = timeout

    def _json(self, path: str, **params: str) -> dict:
        url = f"{API_BASE}/{path.lstrip('/')}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if self.token:
            headers["Authorization"] = f"Discogs token={self.token}"
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def album_release_images(self, artist: str, album: str, year: str = "") -> dict:
        if not artist or not album:
            return {}

        wanted_title = _normalise(album)
        wanted_artist = _normalise(artist)

        def score_candidate(item: dict) -> int:
            title = _normalise(item.get("title", ""))
            points = 0
            if wanted_title and wanted_title in title:
                points += 20
            if wanted_artist and wanted_artist in title:
                points += 10
            if year and str(item.get("year", "")) == str(year):
                points += 5
            
            formats = [str(v).lower() for v in item.get("format") or []]
            if "vinyl" in formats:
                points += 15  # Strongly prefer vinyl for high-res scans
            if "album" in formats:
                points += 5
            if "unofficial release" in formats:
                points -= 100
            if "promo" in formats:
                points -= 10
            
            # Prefer items that definitely have images
            if item.get("cover_image"):
                points += 5
            return points

        # 1. Search for releases with a generous candidate pool
        try:
            search = self._json(
                "database/search",
                artist=artist,
                release_title=album,
                type="release",
                per_page="15",
            )
            candidates = search.get("results") or []
        except Exception:
            candidates = []

        if not candidates:
            try:
                search = self._json("database/search", q=f"{artist} {album}", type="release", per_page="5")
                candidates = search.get("results") or []
            except Exception:
                pass
        
        if not candidates:
            return {}

        # 2. Rank and pick top 2 release candidates + their Master ID
        candidates.sort(key=score_candidate, reverse=True)
        top_candidates = candidates[:2]
        
        all_images = []
        seen_urls = set()
        
        def collect_from_api(path: str) -> dict:
            try:
                data = self._json(path)
                for img in data.get("images") or []:
                    # Use the 'uri' for highest resolution; fallback to resource_url
                    url = img.get("uri") or img.get("resource_url")
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    
                    # Store metadata to allow sorting by resolution later
                    all_images.append({
                        "url": url,
                        "full_url": img.get("uri") or img.get("resource_url") or "",
                        "thumbnail_url": img.get("uri150", ""),
                        "type": img.get("type", "secondary"),
                        "width": int(img.get("width") or 0),
                        "height": int(img.get("height") or 0),
                    })
                return data
            except Exception:
                return {}

        # 3. Parallel-ish fetch from Master and best Releases
        # First, check if the best match has a Master release (curated source)
        master_id = top_candidates[0].get("master_id")
        if master_id:
            collect_from_api(f"masters/{master_id}")
            
        # Then fetch from the top releases (specific high-quality pressings)
        best_release_data = collect_from_api(f"releases/{top_candidates[0]['id']}")
        if len(top_candidates) > 1:
            collect_from_api(f"releases/{top_candidates[1]['id']}")
            
        if not all_images:
            return {}

        # 4. Final Sort: Primary covers first, then by Area (Width * Height)
        # This ensures that if a Master has a 600px cover but a Release has a 1200px scan, 
        # the 1200px version wins.
        all_images.sort(key=lambda x: (x["type"] == "primary", x["width"] * x["height"]), reverse=True)

        release_id = top_candidates[0].get("id")
        return {
            "release_id": str(release_id),
            "release_url": best_release_data.get("uri") or f"https://www.discogs.com/release/{release_id}",
            "title": best_release_data.get("title", album),
            "images": all_images,
        }


@functools.lru_cache(maxsize=128)
def discogs_album_images(artist: str, album: str, year: str = "", token: str = "") -> dict:
    try:
        return DiscogsClient(token).album_release_images(artist, album, year)
    except Exception:
        return {}
