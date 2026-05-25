from app import *
from config import AppConfig
import catalog
import music_metadata

c = AppConfig()
cat = catalog.discover_catalog(c)
print("Artists:", len(cat["artists"]))
print("Albums:", len(cat["albums"]))
print("Top Tracks:", len(cat["top_tracks"]))
