from app import *
from config import AppConfig
import catalog
import music_metadata

c = AppConfig()
try:
    cat = catalog.discover_catalog(c)
    print("Catalog fetch successful.")
except Exception as e:
    import traceback
    traceback.print_exc()
