import os
import sys
from pathlib import Path
import threading
import json

sys.path.append(str(Path(__file__).parent))
import backend_monochrome
import config

class MockManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._cancel_flags = set()
    def _append_cache_event(self, job, event_type, message):
        print(f"[{event_type.upper()}] {message}")

def main():
    output_dir = Path("test_output") / "cf_bypass_test"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Check if we have a saved config with cf_clearance
    conf_path = Path("data/config.json")
    cf_val = ""
    if conf_path.exists():
        try:
            cdata = json.loads(conf_path.read_text())
            cf_val = cdata.get("cf_clearance", "")
            print(f"Found saved cf_clearance: {cf_val[:10]}...")
        except: pass

    job = {
        "id": "test-cf-bypass",
        "title": "Money for Nothing",
        "artist": "Dire Straits",
        "quality": "27",
        "mode": "stream",
        "service": "monochrome",
        "metadata": {
            "cf_clearance": cf_val
        }
    }
    
    print(f"Testing DAB/Squid with CF bypass...")
    try:
        backend_monochrome.run(output_dir, job, MockManager())
        print("\nSUCCESS!")
    except Exception as e:
        print(f"\nFAILED: {e}")

if __name__ == "__main__":
    main()
