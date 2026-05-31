import requests
import concurrent.futures

providers = {
    "Tidal": [
        "https://eu-central.monochrome.tf",
        "https://us-west.monochrome.tf",
        "https://api.monochrome.tf",
        "https://monochrome-api.samidy.com",
        "https://tidal-api.binimum.org",
        "https://tidal.kinoplus.online",
        "https://triton.squid.wtf",
        "https://vogel.qqdl.site",
        "https://maus.qqdl.site",
        "https://hund.qqdl.site",
        "https://katze.qqdl.site",
        "https://wolf.qqdl.site",
        "https://hifi-one.spotisaver.net",
        "https://hifi-two.spotisaver.net",
        "https://api.zarz.moe/v1/dl/tid2"
    ],
    "Qobuz": [
        "https://dab.yeet.su/api/stream",
        "https://dabmusic.xyz/api/stream",
        "https://qbz.afkarxyz.qzz.io/api/track/",
        "https://qobuz.spotbye.qzz.io/api/track/",
        "https://qobuz.squid.wtf/api/download-music",
        "https://api.zarz.moe/v1/dl/qbz",
        "https://api.zarz.moe/v1/dl/qbz2",
        "https://www.musicdl.me/api/qobuz/download",
        "https://dl.musicdl.me/qobuz/download",
        "https://music.gdstudio.xyz/api.php",
        "https://music.gdstudio.org/api.php",
        "https://music.wjhe.top/api/music/qobuz/url"
    ],
    "Amazon": [
        "https://amz.spotbye.qzz.io/api",
        "https://amazon.spotbye.qzz.io/api",
        "https://api.zarz.moe/v1/dl/amazeamazeamaze"
    ],
    "Deezer": [
        "https://api.zarz.moe/v1/dl/dzr"
    ],
    "Soundcloud": [
        "https://api.zarz.moe/v1/dl/cobalt/"
    ],
    "Apple": [
        "https://api.zarz.moe/v1/dl/app2",
        "https://api.zarz.moe/v1/dl/app"
    ]
}

# Money for Nothing track ID
track_id = "161150249"
qid = "7" # Hi-Res

stream_test_urls = [
    ("Squid US", f"https://us.qobuz.squid.wtf/api/download-music?trackId={track_id}&quality={qid}"),
    ("Squid", f"https://qobuz.squid.wtf/api/download-music?trackId={track_id}&quality={qid}"),
    ("DAB Yeet", f"https://dab.yeet.su/api/stream?trackId={track_id}&quality={qid}"),
    ("DAB Music", f"https://dabmusic.xyz/api/stream?trackId={track_id}&quality={qid}"),
    ("Kennyy", f"https://qobuz.kennyy.com.br/api/download-music?track_id={track_id}&quality={qid}"),
]

def check_stream(name, url):
    try:
        from curl_cffi import requests as _requests
        resp = _requests.get(url, impersonate="chrome120", timeout=15)
        return name, url, resp.status_code, resp.text[:100]
    except Exception as e:
        return name, url, "Error", str(e)

print(f"{'Name':<12} | {'Status':<6} | {'Body (first 100 chars)'}")
print("-" * 80)

for name, url in stream_test_urls:
    n, u, status, body = check_stream(name, url)
    # Remove newlines for cleaner output
    clean_body = body.replace('\n', ' ').replace('\r', '')
    print(f"{n:<12} | {status:<6} | {clean_body}")

