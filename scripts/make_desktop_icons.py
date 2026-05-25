from __future__ import annotations

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "static" / "assets" / "app_icon.png"
OUT = ROOT / "build" / "icons"


def process_icon(size: int) -> Image.Image:
    source = Image.open(SOURCE).convert("RGBA")
    # 80% scale provides enough padding to avoid the forced OS square background.
    target_size = int(size * 0.80)
    source.thumbnail((target_size, target_size), Image.Resampling.LANCZOS)
    
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    x = (size - source.width) // 2
    y = (size - source.height) // 2
    canvas.alpha_composite(source, (x, y))
    return canvas


def write_iconset() -> None:
    iconset = OUT / "mindinguflac.iconset"
    iconset.mkdir(parents=True, exist_ok=True)
    for stale in iconset.glob("*.png"):
        stale.unlink()
    # Required sizes for macOS icns
    for size in (16, 32, 128, 256, 512):
        process_icon(size).save(iconset / f"icon_{size}x{size}.png")
        process_icon(size * 2).save(iconset / f"icon_{size}x{size}@2x.png")


def write_ico() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    image = process_icon(1024)
    image.save(
        OUT / "mindinguflac.ico",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )


def write_icns() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    iconset = OUT / "mindinguflac.iconset"
    if not iconset.exists():
        write_iconset()
    
    # Use native macOS iconutil for the most compatible ICNS file
    import subprocess
    try:
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(OUT / "mindinguflac.icns")], check=True)
    except Exception as e:
        print(f"iconutil failed, falling back to Pillow: {e}")
        image = process_icon(1024)
        image.save(OUT / "mindinguflac.icns")


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"Missing source icon: {SOURCE}")
    write_iconset()
    write_ico()
    write_icns()


if __name__ == "__main__":
    main()
