import sys
import requests
import os
from pathlib import Path

# Ensure we can import local modules
sys.path.append(os.getcwd())

import backend_tidal_hifi

def test_monochrome_tf():
    print("--- Testing tidal-proxy.monochrome.tf (Authenticated) ---")
    
    # 77447199
    track_id = 77447199
    
    url = "https://tidal-proxy.monochrome.tf"
    auth = backend_tidal_hifi._auth_headers(requests)
    
    print(f"Trying proxy: {url} ...")
    res = backend_tidal_hifi._fetch_manifest(requests, url, track_id, "LOSSLESS", headers=auth)
    if res:
        is_full = res[3]
        print(f"   -> Success! Mime: {res[1]}, Full Track: {is_full}")
    else:
        print("   -> Failed.")

if __name__ == "__main__":
    test_monochrome_tf()
