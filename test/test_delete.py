import shutil
import os
from pathlib import Path

p = Path("test_data/cache")
p.mkdir(parents=True, exist_ok=True)
(p / "test.txt").write_text("test")

# Leave a file opened
f = open(p / "test.txt", "r")

try:
    shutil.rmtree(p, ignore_errors=False)
    print("rmtree successful with open file!")
except Exception as e:
    print(f"Error: {e}")

f.close()
