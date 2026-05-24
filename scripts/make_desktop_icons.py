from __future__ import annotations

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "static" / "assets" / "app_icon.png"
OUT = ROOT / "build" / "icons"


def centered_square(size: int) -> Image.Image:
    source = Image.open(SOURCE).convert("RGBA")
    # To get a shaped icon on macOS without the square background,
    # we need to keep a small margin or it might get forced into a square by the OS.
    # 90% size is usually safe for shaped icons.
    target_size = int(size * 0.94)
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
    for size in (16, 32, 128, 256, 512):
        centered_square(size).save(iconset / f"icon_{size}x{size}.png")
        centered_square(size * 2).save(iconset / f"icon_{size}x{size}@2x.png")


def write_ico() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    image = centered_square(1024)
    image.save(
        OUT / "mindinguflac.ico",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )


def write_icns() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    image = centered_square(1024)
    image.save(
        OUT / "mindinguflac.icns",
        sizes=[(16, 16), (32, 32), (64, 64), (128, 128), (256, 256), (512, 512), (1024, 1024)],
    )


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"Missing source icon: {SOURCE}")
    write_iconset()
    write_ico()
    write_icns()


if __name__ == "__main__":
    main()
