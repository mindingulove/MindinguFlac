import shutil
from pathlib import Path
from config import AppConfig, default_cache_dir
from service_downloader import ServiceDownloadManager

app_config = AppConfig()
app_config.cache_dir.mkdir(parents=True, exist_ok=True)
(app_config.cache_dir / "test.txt").write_text("hello")

sd = ServiceDownloadManager(app_config)

print("Before:", sd.clear_cache())
print("After:", list(app_config.cache_dir.iterdir()))
