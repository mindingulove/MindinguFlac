from __future__ import annotations

import sys
from pathlib import Path
import shutil


try:
    from config import app_data_dir
    import SpotiFLAC.core as endpoints

    cache_dir = app_data_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    writable_cache = cache_dir / "spotiflac_endpoints_cache.txt"

    seed_candidates = [
        Path(getattr(sys, "_MEIPASS", "")) / "spotiflac_cache" / "endpoints_cache.txt",
        Path(getattr(endpoints, "_CACHE_FILE", "")),
    ]
    if not writable_cache.exists():
        for bundled_cache in seed_candidates:
            if bundled_cache.is_file():
                try:
                    shutil.copy2(bundled_cache, writable_cache)
                    break
                except Exception:
                    pass

    endpoints._CACHE_DIR = str(cache_dir)
    endpoints._CACHE_FILE = str(writable_cache)
except Exception:
    pass
