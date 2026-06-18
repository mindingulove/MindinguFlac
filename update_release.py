from __future__ import annotations

import glob
import json
import os
import urllib.error
import urllib.request
from pathlib import Path


OWNER = "mindingulove"
REPO = "MindinguFlac"
TAG = "v1.1.1"
NOTES_PATH = Path("RELEASE_NOTES_v1.1.1.md")
ENV_PATH = Path(".env")


def load_env_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        return token

    if not ENV_PATH.exists():
        return ""

    for raw_line in ENV_PATH.read_text("utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "GITHUB_TOKEN":
            return value.strip().strip('"').strip("'")
    return ""


def gh_request(url: str, token: str, method: str = "GET", payload: dict | None = None):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read().decode("utf-8"))


def get_or_create_release(token: str) -> dict:
    release_url = f"https://api.github.com/repos/{OWNER}/{REPO}/releases/tags/{TAG}"
    try:
        return gh_request(release_url, token)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    body = NOTES_PATH.read_text("utf-8")
    create_url = f"https://api.github.com/repos/{OWNER}/{REPO}/releases"
    return gh_request(
        create_url,
        token,
        method="POST",
        payload={
            "tag_name": TAG,
            "name": TAG,
            "body": body,
            "draft": False,
            "prerelease": False,
        },
    )


def upload_asset(token: str, upload_url: str, path: Path, name: str) -> None:
    data = path.read_bytes()
    req = urllib.request.Request(
        f"{upload_url}?name={name}",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/zip",
            "Content-Length": str(len(data)),
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="POST",
    )
    with urllib.request.urlopen(req):
        pass


def delete_asset(token: str, asset_id: int) -> None:
    delete_url = f"https://api.github.com/repos/{OWNER}/{REPO}/releases/assets/{asset_id}"
    req = urllib.request.Request(
        delete_url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="DELETE",
    )
    with urllib.request.urlopen(req):
        pass


def candidate_assets() -> list[tuple[Path, str]]:
    candidates: list[tuple[Path, str]] = []
    mac_path = Path("Mindinguflac-macos-arm64.zip")
    if mac_path.exists():
        candidates.append((mac_path, "Mindinguflac-macos-arm64.zip"))
    for pattern in ("Mindinguflac-windows*.zip", "dist/Mindinguflac-windows*.zip"):
        for path_str in sorted(glob.glob(pattern)):
            path = Path(path_str)
            if path.is_file():
                candidates.append((path, path.name))
    return candidates


def main() -> int:
    token = load_env_token()
    if not token:
        raise SystemExit("Missing GITHUB_TOKEN in .env or environment")

    release = get_or_create_release(token)
    release_id = release["id"]
    upload_url = release["upload_url"].split("{", 1)[0]

    body = NOTES_PATH.read_text("utf-8")
    gh_request(
        f"https://api.github.com/repos/{OWNER}/{REPO}/releases/{release_id}",
        token,
        method="PATCH",
        payload={"body": body},
    )

    for asset in release.get("assets", []):
        delete_asset(token, asset["id"])

    assets = candidate_assets()
    if not assets:
        print("No release assets found.")
    for path, name in assets:
        print(f"Uploading {name}...")
        upload_asset(token, upload_url, path, name)

    print(f"Release {TAG} is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
