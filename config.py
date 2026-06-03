from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


ROOT = Path(__file__).resolve().parent
APP_NAME = "Mindinguflac"


if getattr(sys, "frozen", False):
    os.environ.setdefault("MINDINGUFLAC_DESKTOP", "1")


def is_desktop_mode() -> bool:
    return os.environ.get("MINDINGUFLAC_DESKTOP") == "1"


def _windows_dir(env_name: str, fallback: Path) -> Path:
    value = os.environ.get(env_name)
    return Path(value) if value else fallback


def app_data_dir() -> Path:
    if not is_desktop_mode():
        return ROOT / "data"
    try:
        home = Path.home()
    except Exception:
        return ROOT / "data"
        
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / APP_NAME
    if sys.platform == "win32":
        return _windows_dir("APPDATA", home / "AppData" / "Roaming") / APP_NAME
    return Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / APP_NAME


def default_cache_dir() -> Path:
    if not is_desktop_mode():
        return ROOT / "data" / "cache"
    try:
        home = Path.home()
    except Exception:
        return ROOT / "data" / "cache"

    if sys.platform == "darwin":
        return home / "Library" / "Caches" / APP_NAME / "cache"
    if sys.platform == "win32":
        return _windows_dir("LOCALAPPDATA", home / "AppData" / "Local") / APP_NAME / "Cache"
    return Path(os.environ.get("XDG_CACHE_HOME", home / ".cache")) / APP_NAME / "cache"


def default_music_dir() -> Path:
    if not is_desktop_mode():
        return ROOT / "data" / "music"
    try:
        return Path.home() / "Music" / APP_NAME
    except Exception:
        return ROOT / "data" / "music"


def jobs_path() -> Path:
    return app_data_dir() / "jobs.json"


@dataclass
class MusicIndexerConfig:
    name: str
    type: str = "musicbrainz"
    url: str = ""
    api_key: str = ""
    enabled: bool = True


@dataclass
class AppConfig:
    cache_dir: Path = field(default_factory=default_cache_dir)
    music_dir: Path = field(default_factory=default_music_dir)
    default_quality: str = "LOSSLESS"
    download_service: str = "amazon"
    cache_cleanup_frequency: str = "never"
    last_cache_cleanup: float = 0
    strict_title_match: bool = False
    demo_music_indexer: bool = True
    music_indexers: list[MusicIndexerConfig] = field(default_factory=list)
    volume: float = 1.0
    track_max_retries: int = 1
    download_engine: str = "ytp-dl"
    discogs_token: str = ""
    qobuz_token: str = ""

    def public_dict(self) -> dict:
        def _safe_path(p: Path) -> str:
            try:
                # expanduser() handles ~ while absolute() makes it full path without symlink resolution
                return str(p.expanduser().absolute())
            except Exception:
                return str(p)

        return {
            "cache_dir": _safe_path(self.cache_dir),
            "music_dir": _safe_path(self.music_dir),
            "default_quality": self.default_quality,
            "download_service": self.download_service,
            "download_engine": self.download_engine,
            "cache_cleanup_frequency": self.cache_cleanup_frequency,
            "last_cache_cleanup": self.last_cache_cleanup,
            "strict_title_match": self.strict_title_match,
            "demo_music_indexer": self.demo_music_indexer,
            "music_indexers": [vars(item) for item in self.music_indexers],
            "volume": self.volume,
            "track_max_retries": self.track_max_retries,
            "discogs_token": self.discogs_token,
            "qobuz_token": self.qobuz_token,
        }

    @classmethod
    def from_public_dict(cls, value: dict) -> "AppConfig":
        music_indexers = [MusicIndexerConfig(**item) for item in value.get("music_indexers", [])]
        
        cache_dir_str = (value.get("cache_dir") or "").strip()
        music_dir_str = (value.get("music_dir") or "").strip()
        
        def _to_path(s: str, default_fn) -> Path:
            if not s:
                return default_fn().expanduser().absolute()
            try:
                return Path(s).expanduser().absolute()
            except Exception:
                return default_fn().expanduser().absolute()

        rt = value.get("track_max_retries")
        if rt is None:
            rt = 1
        else:
            try: rt = int(rt)
            except: rt = 1

        return cls(
            cache_dir=_to_path(cache_dir_str, default_cache_dir),
            music_dir=_to_path(music_dir_str, default_music_dir),
            default_quality=value.get("default_quality", "LOSSLESS"),
            download_service=value.get("download_service", cls.download_service),
            cache_cleanup_frequency=value.get("cache_cleanup_frequency", "never"),
            last_cache_cleanup=float(value.get("last_cache_cleanup", 0) or 0),
            strict_title_match=bool(value.get("strict_title_match", False)),
            demo_music_indexer=bool(value.get("demo_music_indexer", True)),
            music_indexers=music_indexers,
            volume=float(value.get("volume", 1.0)),
            track_max_retries=rt,
            download_engine=value.get("download_engine", cls.download_engine),
            discogs_token=str(value.get("discogs_token", "") or "").strip(),
            qobuz_token=str(value.get("qobuz_token", "") or "").strip(),
        )


def load_config(path: Path) -> AppConfig:
    if not path.exists():
        return AppConfig()
    try:
        return AppConfig.from_public_dict(json.loads(path.read_text("utf-8")))
    except Exception:
        return AppConfig()


def save_config(path: Path, config: AppConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config.public_dict(), indent=2), "utf-8")
