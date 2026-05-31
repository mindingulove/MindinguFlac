from curl_cffi import requests
import json

track_id = "161150249"
quality = "7"
url = f"https://qobuz.squid.wtf/api/download-music?trackId={track_id}&quality={quality}"

# Every single header from a real browser request
headers = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Host": "qobuz.squid.wtf",
    "Origin": "https://qobuz.squid.wtf",
    "Referer": "https://qobuz.squid.wtf/",
    "Sec-CH-UA": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

print(f"Testing Squid with Perfect Headers: {url}")
try:
    with requests.Session() as s:
        # 1. Warm up with the root page
        s.get("https://qobuz.squid.wtf/", impersonate="chrome120", timeout=10)
        # 2. Try the API with full browser signals
        r = s.post(url, headers=headers, impersonate="chrome120", timeout=15)
        print(f"Status: {r.status_code}")
        print(f"Body: {r.text}")
except Exception as e:
    print(f"Failed: {e}")
