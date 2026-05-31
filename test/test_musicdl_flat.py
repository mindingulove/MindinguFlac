import os
import shutil
from pathlib import Path

# Simulate musicdl library structure
class FakeMusicClient:
    def __init__(self, work_dir):
        self.work_dir = work_dir
    def download(self, song_infos):
        # musicdl typically creates: work_dir / ClientName / YYYY-MM-DD-HH-MM-SS SearchTerm / song.flac
        sub_dir = Path(self.work_dir) / "FakeClient" / "2026-05-27-00-00-00 Search"
        sub_dir.mkdir(parents=True, exist_ok=True)
        (sub_dir / "song.flac").write_text("audio data")

def fix_musicdl_subfolder(output_dir: Path):
    # Flatten the folder: move everything from subfolders to output_dir
    for item in list(output_dir.rglob("*")):
        if item.is_file() and item.parent != output_dir:
            dest = output_dir / item.name
            # Handle name collisions if necessary, though unlikely in a single job folder
            print(f"Moving {item} to {dest}")
            shutil.move(str(item), str(dest))
    
    # Cleanup empty subdirectories
    for item in output_dir.iterdir():
        if item.is_dir():
            print(f"Removing empty dir {item}")
            shutil.rmtree(item)

# Test
out = Path("test_output")
if out.exists(): shutil.rmtree(out)
out.mkdir()

client = FakeMusicClient(out)
client.download([])

print(f"Before: {list(out.rglob('*'))}")
fix_musicdl_subfolder(out)
print(f"After: {list(out.rglob('*'))}")
