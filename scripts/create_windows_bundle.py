"""Create a deterministic Windows-safe ZIP from a PyInstaller onedir build."""

from __future__ import annotations

import argparse
import pathlib
import zipfile

from windows_bundle import windows_safe_archive_name, windows_safe_archive_parts


def create_windows_bundle(source: pathlib.Path, destination: pathlib.Path) -> int:
    source = pathlib.Path(source).resolve()
    destination = pathlib.Path(destination).resolve()
    if not source.is_dir():
        raise ValueError(f"Bundle source is not a directory: {source}")

    files = sorted(path for path in source.rglob("*") if path.is_file())
    archive_names: dict[str, pathlib.Path] = {}
    sanitized_count = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f"{destination.name}.tmp")
    temporary.unlink(missing_ok=True)

    try:
        with zipfile.ZipFile(
            temporary,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as archive:
            for path in files:
                relative = path.relative_to(source)
                archive_name = windows_safe_archive_name(list(relative.parts))
                original_name = "/".join(relative.parts)
                if archive_name != original_name:
                    sanitized_count += 1

                collision_key = archive_name.casefold()
                previous = archive_names.get(collision_key)
                if previous is not None:
                    raise ValueError(
                        f"Windows archive path collision: {previous} and {path} "
                        f"both map to {archive_name!r}"
                    )
                archive_names[collision_key] = path
                archive.write(path, archive_name)

        with zipfile.ZipFile(temporary) as archive:
            bad_member = archive.testzip()
            if bad_member is not None:
                raise ValueError(f"Corrupt ZIP member after packaging: {bad_member}")
            for member in archive.infolist():
                normalized = "/".join(windows_safe_archive_parts(member.filename))
                if normalized != member.filename:
                    raise ValueError(f"Unsafe ZIP member after packaging: {member.filename!r}")

        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    print(
        f"Created {destination} with {len(files)} files "
        f"({sanitized_count} paths sanitized)."
    )
    return sanitized_count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=pathlib.Path)
    parser.add_argument("destination", type=pathlib.Path)
    args = parser.parse_args()
    create_windows_bundle(args.source, args.destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
