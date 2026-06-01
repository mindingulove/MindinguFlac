import requests
import sys
sys.path.append(".")
import backend_tidal_hifi

auth = backend_tidal_hifi._auth_headers(requests)
headers = auth.copy()
headers.update({"Origin": "https://monochrome.samidy.com"})

url = "https://tidal-proxy.monochrome.tf/track/"
params = {"id": "77447199", "quality": "LOSSLESS"}

r = requests.get(url, params=params, headers=headers)
print(r.status_code)
if r.status_code == 200:
    data = r.json().get("data", {})
    manifest_mime = data.get("manifestMimeType")
    print("Mime:", manifest_mime)
    if "bts" in manifest_mime:
        import base64
        import json
        manifest = json.loads(base64.b64decode(data.get("manifest")))
        print("URL:", manifest.get("urls")[0][:60])
        # If it has long duration/many segments, it's full
else:
    print(r.text)
