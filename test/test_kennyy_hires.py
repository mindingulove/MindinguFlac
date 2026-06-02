import requests

url = "https://hifi-api.kennyy.com.br/trackManifests/"
params = {
    "id": "77447199", 
    "quality": "HI_RES_LOSSLESS", 
    "formats": "FLAC_HIRES", 
    "adaptive": "false",
    "manifestType": "MPEG_DASH",
    "usage": "PLAYBACK"
}
headers = {"Origin": "https://monochrome.samidy.com", "Referer": "https://monochrome.samidy.com/"}

r = requests.get(url, params=params, headers=headers)
print(r.status_code)
if r.status_code == 200:
    data = r.json()
    attr = data.get("data", {}).get("data", {}).get("attributes", {}) or data.get("data", {}).get("attributes", {})
    print("Presentation:", attr.get("trackPresentation"))
else:
    print(r.text)
