import sys
import requests
import os
from pathlib import Path

# Ensure we can import local modules
sys.path.append(os.getcwd())

import backend_tidal_hifi

class DummyManager:
    def __init__(self):
        import threading
        self._lock = threading.Lock()
        self._cancel_flags = set()

    def _append_cache_event(self, job, kind, msg):
        print(f"  [{kind.upper()}] {msg}")

def test_full_flow():
    print("--- Starting Final Integration Test ---")
    
    manager = DummyManager()
    # 77447199
    track_id = 77447199
    job = {
        "id": "test_integration_job", 
        "title": "To Be With You", 
        "artist": "Mr. Big", 
        "duration": 207,
        "mode": "stream"
    }
    
    output_dir = Path("test_output/final_test")
    output_dir.mkdir(parents=True, exist_ok=True)
    flac_out = output_dir / "To Be With You.flac"
    if flac_out.exists():
        flac_out.unlink()

    api_instances, _ = backend_tidal_hifi._fetch_instances(requests)
    
    # Run the logic exactly as in backend_tidal_hifi.py run()
    prioritized_proxies = [
        "https://hifi-api.kennyy.com.br",
        "https://monochrome-api.samidy.com",
        "https://api.monochrome.tf",
    ]
    all_instances = prioritized_proxies + [u for u in api_instances if u not in prioritized_proxies]

    manifest_info = None
    best_preview = None
    for s_url in all_instances:
        print(f"Trying {s_url}...")
        res = backend_tidal_hifi._fetch_manifest(requests, s_url, track_id, "LOSSLESS", headers=None)
        if res:
            print(f"   -> Success! is_full={res[3]}")
            if res[3]:
                manifest_info = res
                break
            elif best_preview is None:
                best_preview = res
    
    if not manifest_info:
        manifest_info = best_preview

    if not manifest_info:
        print("   FAILED: Could not fetch manifest.")
        return

    content, mime, master_url, is_full = manifest_info
    print(f"Final Selection: is_full={is_full}")

    try:
        if "dash" in mime.lower() or "MPD" in content:
            backend_tidal_hifi._download_dash_native(requests, master_url, flac_out, job, manager)
        else:
            cdn_url = backend_tidal_hifi._parse_bts(content)
            backend_tidal_hifi._download_direct(requests, cdn_url, flac_out, job, manager)
            
        if flac_out.exists():
            print(f"Size: {flac_out.stat().st_size / (1024*1024):.2f} MB")
    except Exception as e:
        print(f"--- TEST FAILED: {e} ---")

if __name__ == "__main__":
    test_full_flow()
