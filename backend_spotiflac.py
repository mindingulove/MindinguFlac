"""Compatibility for saved `spotiflac` engine settings. Downloads use Mornye REST.

No SpotiFLAC package, provider internals or monkeypatches are required.
"""
from pathlib import Path
from backend_mornye import run
_LOSSY_ONLY_SERVICES = {"soundcloud", "youtube"}
_LOSSLESS_REQUEST_QUALITIES = {"DOLBY_ATMOS", "HI_RES_LOSSLESS", "HI_RES", "LOSSLESS", "27", "7", "6", "ALAC"}

def spotiflac_fallback_services(selected_service: str, quality: str) -> list[str]:
    # Prioritize Qobuz and Deezer over Amazon for better stability
    fallback_order = ["qobuz", "deezer", "amazon", "apple", "tidal"]
    if selected_service in _LOSSY_ONLY_SERVICES:
        peers = []
        lossless = [service for service in fallback_order if service not in _LOSSY_ONLY_SERVICES and service != selected_service]
        return [selected_service, *peers, *lossless]
    candidates = [selected_service, *[service for service in fallback_order if service != selected_service]]
    if str(quality or "").upper() in _LOSSLESS_REQUEST_QUALITIES:
        return [service for service in candidates if service not in _LOSSY_ONLY_SERVICES]
    return candidates


def spotiflac_provider_quality(requested_quality: str, service: str) -> str:
    requested = str(requested_quality or "LOSSLESS").upper()
    if requested == "DOLBY_ATMOS":
        return {"tidal": "DOLBY_ATMOS", "qobuz": "27", "amazon": "LOSSLESS", "deezer": "LOSSLESS", "apple": "ATMOS"}.get(service, requested)
    if requested in {"HI_RES", "HI_RES_LOSSLESS"}:
        return {"tidal": "HI_RES_LOSSLESS", "qobuz": "27", "amazon": "LOSSLESS", "deezer": "LOSSLESS", "apple": "ALAC"}.get(service, requested)
    if requested == "LOSSLESS":
        return {"qobuz": "6", "apple": "ALAC"}.get(service, requested)
    return requested_quality


def spotiflac_failure_message(messages: list[str]) -> str:
    incidental = ("gist fetch failed", "failed to refresh api list")
    meaningful = [message for message in messages if not any(token in message.lower() for token in incidental)]
    return meaningful[-1] if meaningful else "All providers failed and no playable audio file was found"


def spotiflac_download_options(output_dir: Path, job: dict, track_max_retries: int, services: list[str]) -> dict:
    from service_downloader import clean_part
    title = clean_part(job.get("title") or "Unknown Track")
    artist = clean_part(job.get("artist") or "Unknown Artist")
    metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
    include_featuring = bool(
        job.get("include_featuring") or metadata.get("include_featuring")
    )
    options = {
        "url": job.get("resolved_url") or job.get("url") or "",
        "output_dir": str(output_dir),
        "output_path": str(output_dir / f"{title} - {artist}.flac"),
        "services": services,
        "track_max_retries": track_max_retries,
        "filename_format": "{title} - {artist}",
        "embed_lyrics": True,
        "lyrics_providers": ["spotify", "apple", "musixmatch", "lrclib", "amazon"],
        "enrich_metadata": True,
        "enrich_providers": ["deezer", "apple", "qobuz", "tidal", "soundcloud"],
        "allow_fallback": False,
        "use_artist_subfolders": False,
        "use_album_subfolders": False,
    }
    if include_featuring:
        options["include_featuring"] = True
    if job.get("quality"):
        options["quality"] = job["quality"]
    return options



def requested_spotiflac_track_metadata(track, job: dict):
    from service_downloader import _parse_duration_ms
    metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
    updates = {
        "title": job.get("title") or metadata.get("title") or track.title,
        "artists": job.get("artist") or metadata.get("artist") or track.artists,
        "album": job.get("album") or metadata.get("album") or track.album,
        "album_artist": job.get("artist") or metadata.get("artist") or track.album_artist,
    }
    expected_duration = (
        _parse_duration_ms(metadata.get("duration_ms"))
        or _parse_duration_ms(metadata.get("length"))
        or _parse_duration_ms(metadata.get("duration"))
    )
    if expected_duration:
        updates["duration_ms"] = expected_duration
    if job.get("isrc") or metadata.get("isrc"):
        updates["isrc"] = job.get("isrc") or metadata.get("isrc")
    if job.get("artwork_url") or metadata.get("artwork_url"):
        updates["cover_url"] = job.get("artwork_url") or metadata.get("artwork_url")
    return track.model_copy(update=updates)
