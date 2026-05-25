from __future__ import annotations

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "static" / "assets" / "app_icon.png"
OUT = ROOT / "build" / "icons"


def process_icon(size: int) -> Image.Image:
    source = Image.open(SOURCE).convert("RGBA")
    bounds = source.getchannel("A").getbbox()
    if bounds:
        source = source.crop(bounds)
    target_size = int(size * 0.98)
    scale = min(target_size / source.width, target_size / source.height)
    dimensions = (round(source.width * scale), round(source.height * scale))
    source = source.resize(dimensions, Image.Resampling.LANCZOS)

    # Explicitly transparent canvas
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
    
    # macOS iconset naming requirements
    # 16, 32, 128, 256, 512 + @2x versions
    configs = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]
    for size, name in configs:
        process_icon(size).save(iconset / name)


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
