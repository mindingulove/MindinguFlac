import requests
import sys
sys.path.append(".")
import backend_tidal_hifi

auth = backend_tidal_hifi._auth_headers(requests)
headers = auth.copy()
headers.update({"Origin": "https://monochrome.samidy.com"})

# Try the replacement seen in monochrome js repo
url = "https://tidal-proxy.monochrome.tf/openapi/v2/trackManifests/77447199"
params = {
    "quality": "LOSSLESS",
    "formats": "FLAC",
    "adaptive": "false"
}

r = requests.get(url, params=params, headers=headers)
print(r.status_code)
if r.status_code == 200:
    data = r.json()
    print("Presentation:", data.get("data", {}).get("attributes", {}).get("trackPresentation"))
else:
    print(r.text)
