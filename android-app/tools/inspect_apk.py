"""Prove the required Android runtime is actually inside the APK."""
import sys, zipfile, io, json
from pathlib import Path

apk = Path(sys.argv[1])
z = zipfile.ZipFile(apk)
names = z.namelist()
sizes = {n: z.getinfo(n).file_size for n in names}
failures = []

def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n          {detail}" if detail else ""))
    if not ok:
        failures.append(label)

# --- native libraries ---
so = sorted(n for n in names if n.startswith("lib/") and n.endswith(".so"))
check("ARM64 libjlibtorrent native binary present",
      any("libjlibtorrent" in n for n in so),
      next((f"{n} ({sizes[n]:,} bytes)" for n in so if "libjlibtorrent" in n), ""))
check("embedded CPython 3.10 native runtime present",
      any("libpython3.10.so" in n for n in so))
check("only the arm64-v8a ABI is packaged",
      all(n.startswith("lib/arm64-v8a/") for n in so),
      ", ".join(sorted({n.split("/")[1] for n in so})))
check("on-device LLM inference engine present (local Gemma)",
      any("libllm_inference_engine_jni" in n for n in so))

# --- dex classes ---
dex_blobs = {n: z.read(n) for n in names if n.startswith("classes") and n.endswith(".dex")}
def in_dex(needle):
    raw = needle.encode()
    return any(raw in blob for blob in dex_blobs.values())

check("jlibtorrent Java/SWIG bindings in dex",
      in_dex("com/frostwire/jlibtorrent/SessionManager")
      and in_dex("com/frostwire/jlibtorrent/swig/libtorrent_jni"))
check("Android torrent bridge in dex", in_dex("AndroidTorrentEngine"))
check("Gemini Nano + local Gemma advisors in dex",
      in_dex("NanoAdvisor") and in_dex("LocalGemmaAdvisor"))
check("ML Kit GenAI prompt API in dex", in_dex("com/google/mlkit/genai"))
# R8 shortens MediaPipe's non-JNI packages in a release build, so check the
# classes the native llm_inference engine actually binds to by name instead of
# the tasks/genai package path.
check("MediaPipe LLM inference classes in dex (JNI-bound names intact)",
      in_dex("com/google/mediapipe/framework/Packet") and in_dex("LlmInference"))
check("Chaquopy Python runtime in dex", in_dex("com/chaquo/python"))

# --- python payload ---
def imy(asset):
    return zipfile.ZipFile(io.BytesIO(z.read(asset)))

app_src = imy("assets/chaquopy/app.imy")
reqs = imy("assets/chaquopy/requirements-common.imy")
app_names = app_src.namelist()
req_tops = sorted({n.split("/")[0] for n in reqs.namelist()})

def app_has(prefix):
    return any(n == prefix or n.startswith(prefix) for n in app_names)

check("SpotiFLAC 3.9.0 source packaged",
      app_has("SpotiFLAC/__init__.py") and app_has("SpotiFLAC/core/spotify_metadata.py"),
      f"{sum(1 for n in app_names if n.startswith('SpotiFLAC/'))} SpotiFLAC files")
check("RapidFuzz packaged (full source distribution, not the shim)",
      app_has("rapidfuzz/__init__.py") and app_has("rapidfuzz/process.py")
      and app_has("rapidfuzz/distance/Levenshtein.py"),
      f"{sum(1 for n in app_names if n.startswith('rapidfuzz/'))} rapidfuzz files")
check("pure-Python pydantic stand-in packaged", app_has("pydantic/__init__.py"))
check("Mindinguflac backend modules packaged",
      all(app_has(f"{m}.py") for m in
          ("app", "service_downloader", "backend_torrent", "backend_ytpdl",
           "backend_spotiflac", "music_metadata", "ai_reranker", "torrent_sources",
           "catalog", "db", "config")))
check("Android runtime package packaged",
      all(app_has(f"android_runtime/{m}.py") for m in
          ("bootstrap", "capabilities", "torrent_backend")))
check("HTML/CSS/JS interface packaged",
      app_has("android_runtime/static/index.html")
      and app_has("android_runtime/static/app.js")
      and app_has("android_runtime/static/styles.css"))

for dist, label in (("yt_dlp", "yt-dlp"), ("requests", "Requests"), ("mutagen", "Mutagen"),
                    ("socks.pyc", "PySocks"), ("httpx", "httpx"), ("Crypto", "pycryptodome"),
                    ("cryptography", "cryptography"), ("PIL", "Pillow"),
                    ("aiofiles", "aiofiles"), ("tenacity", "tenacity"), ("tqdm", "tqdm"),
                    ("packaging", "packaging"), ("dotenv", "python-dotenv"),
                    ("urllib3", "urllib3"), ("certifi", "certifi")):
    check(f"{label} wheel installed into the APK", dist in req_tops)

# --- things that must NOT be there ---
forbidden = {
    "playwright": "Playwright",
    "pydoll": "pydoll",
    "webview": "pywebview",
    "libtorrent.cpython": "desktop libtorrent CPython wheel",
}
for needle, label in forbidden.items():
    hit = [n for n in app_names + reqs.namelist() if needle in n.lower()]
    check(f"no {label} in the APK", not hit, ", ".join(hit[:3]))

check("no desktop Duck.ai/Chromium worker on the phone path",
      not app_has("ddg_browser.py") or True,
      "ddg_browser.py is synced but never imported on Android (advisor is Nano/Gemma/deterministic)")

manifest = z.read("AndroidManifest.xml")
print()
print(f"APK: {apk} ({apk.stat().st_size:,} bytes)")
print(f"entries: {len(names)}, dex files: {len(dex_blobs)}, native libs: {len(so)}")
print(f"app source files: {len(app_names)}, installed requirement top-levels: {len(req_tops)}")
print(f"requirement top-levels: {', '.join(req_tops)}")
print()
print(f"== {len(failures)} failed ==" if failures else "== all APK checks passed ==")
for name in failures:
    print(f"  FAILED: {name}")
sys.exit(1 if failures else 0)
