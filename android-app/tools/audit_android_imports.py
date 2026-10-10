"""Android runtime dependency audit.

Imports every backend module the Android build loads, under the Android
environment flags and the device sys.path layout, then reports which
third-party top-level modules were pulled in and whether each one is
packaged (bundled wheel or vendored source).
"""
from __future__ import annotations

import json
import os
import sys
import sysconfig
import types
from pathlib import Path

STAGE = Path(sys.argv[1]).resolve()
WHEEL_DIR = Path(sys.argv[2]).resolve()
OUT = Path(sys.argv[3]).resolve()

# ---- Android environment, mirroring android_runtime.bootstrap.start() -------
WORK = STAGE.parent / "devicefs"
DATA = WORK / "files" / "mindinguflac"
CACHE = WORK / "cache"
MUSIC = WORK / "music"
for d in (DATA, CACHE, MUSIC):
    d.mkdir(parents=True, exist_ok=True)

os.environ["MINDINGUFLAC_ANDROID"] = "1"
os.environ.pop("MINDINGUFLAC_DESKTOP", None)
os.environ["MINDINGUFLAC_DATA_DIR"] = str(DATA)
os.environ["MINDINGUFLAC_CACHE_DIR"] = str(CACHE)
os.environ["MINDINGUFLAC_MUSIC_DIR"] = str(MUSIC)
os.environ["MINDINGUFLAC_API_TOKEN"] = "audit-token"
os.environ["MINDINGUFLAC_STATIC_DIR"] = str(STAGE / "android_runtime" / "static")
os.environ["MINDINGUFLAC_AI_RERANK_PROVIDER"] = "none"
os.environ["RAPIDFUZZ_IMPLEMENTATION"] = "python"

sys.path.insert(0, str(STAGE))

# ---- Chaquopy's `java` module is not available off-device --------------------
java = types.ModuleType("java")
_seen_jclass: list[str] = []


def _jclass(name):
    _seen_jclass.append(name)
    raise RuntimeError(f"java.jclass({name}) is only available on-device")


java.jclass = _jclass
sys.modules["java"] = java

# ---- Record third-party imports ---------------------------------------------
STDLIB = set(sys.stdlib_module_names)
STDLIB |= {"java"}
VENDORED = {p.name for p in STAGE.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
LOCAL = {p.stem for p in STAGE.glob("*.py")}

site_packages = Path(sysconfig.get_paths()["purelib"])


def classify(name: str) -> dict:
    module = sys.modules.get(name)
    origin = getattr(getattr(module, "__spec__", None), "origin", None) or ""
    if name in STDLIB:
        return {"kind": "stdlib"}
    if name in LOCAL:
        return {"kind": "app-module"}
    if origin and str(STAGE) in origin:
        return {"kind": "vendored-source", "path": origin.replace(str(STAGE) + "/", "")}
    if origin and str(site_packages) in origin:
        try:
            import importlib.metadata as md

            dist = md.distribution(name)
            version = dist.version
            project = dist.metadata["Name"]
        except Exception:
            version, project = "?", name
        return {"kind": "wheel", "project": project, "version": version}
    return {"kind": "unknown", "origin": origin}


results: dict[str, object] = {"imports": {}, "failures": [], "checks": []}


def check(label: str, fn):
    try:
        value = fn()
        results["checks"].append({"name": label, "ok": True, "detail": value})
        print(f"  PASS  {label}" + (f" :: {value}" if value else ""))
        return True
    except Exception as exc:
        results["checks"].append(
            {"name": label, "ok": False, "detail": f"{type(exc).__name__}: {exc}"}
        )
        print(f"  FAIL  {label} :: {type(exc).__name__}: {exc}")
        return False


print("== import the Android backend surface ==")

MODULES = [
    "config",
    "db",
    "rapidfuzz",
    "SpotiFLAC",
    "spotiflac_compat",
    "torrent_sources",
    "music_metadata",
    "catalog",
    "isrc_resolver",
    "taste_profile",
    "playlist_recommender",
    "ai_reranker",
    "backend_ytpdl",
    "backend_torrent",
    "backend_spotiflac",
    "backend_video",
    "service_downloader",
    "hypebot_tour",
    "native_audio",
    "app",
    "android_runtime.bootstrap",
    "android_runtime.torrent_backend",
]

for name in MODULES:
    def _imp(name=name):
        import importlib

        module = importlib.import_module(name)
        return getattr(module, "__file__", "") or ""

    if not check(f"import {name}", _imp):
        results["failures"].append(name)

# ---- Build the manifest ------------------------------------------------------
tops = sorted({name.split(".")[0] for name in sys.modules if not name.startswith("_")})
for name in tops:
    info = classify(name)
    if info["kind"] in {"stdlib", "app-module"}:
        continue
    results["imports"][name] = info

results["jclass_requests"] = sorted(set(_seen_jclass))

# ---- Bundled wheels ----------------------------------------------------------
results["bundled_wheels"] = sorted(p.name for p in WHEEL_DIR.glob("*.whl"))

OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
print()
print("== third-party modules actually imported ==")
for name, info in sorted(results["imports"].items()):
    print(f"  {name:28s} {info}")
print()
print(f"failures: {results['failures'] or 'none'}")
sys.exit(1 if results["failures"] else 0)
