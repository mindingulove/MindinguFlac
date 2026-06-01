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

def test_no_auth():
    print("--- Testing WITHOUT Auth Headers ---")
    
    manager = DummyManager()
    # "Smooth Operator - 2011 Remastered" - 103938826
    track_id = 103938826 
    job = {"id": "test", "title": "Test", "artist": "Test", "duration": 258, "mode": "stream"}
    
    output_dir = Path("test_output/final_test_noauth")
    output_dir.mkdir(parents=True, exist_ok=True)
    flac_out = output_dir / "Smooth Operator.flac"
    if flac_out.exists():
        flac_out.unlink()

    api_instances, _ = backend_tidal_hifi._fetch_instances(requests)
    
    manifest_info = None
    for url in api_instances:
        print(f"Trying proxy: {url} ...")
        # Pass headers=None to use default rotation headers without Authorization
        res = backend_tidal_hifi._fetch_manifest(requests, url, track_id, "LOSSLESS", headers=None)
        if res:
            is_full = res[3]
            print(f"   -> Success! Mime: {res[1]}, Full Track: {is_full}")
            if is_full:
                manifest_info = res
                break
    
    if manifest_info and manifest_info[3]:
        print("SUCCESS: Found a FULL track manifest without sending auth headers!")
        content, mime, master_url, is_full = manifest_info
        backend_tidal_hifi._download_dash_native(requests, master_url, flac_out, job, manager)
        print(f"Size: {flac_out.stat().st_size / (1024*1024):.2f} MB")
    else:
        print("FAILED: Only found previews or failed entirely.")

if __name__ == "__main__":
    test_no_auth()
