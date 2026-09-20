"""Windows-safe archive paths used by the desktop bundle and launcher."""

from __future__ import annotations

import json
import pathlib
import re
from functools import lru_cache


WINDOWS_RESERVED_BASENAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)
_WINDOWS_INVALID_CHARS = frozenset('<>:"|?*')
_WINDOWS_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


def windows_safe_component(component: str) -> str:
    """Return a filename component that can be created on Windows."""
    cleaned = "".join(
        "_" if character in _WINDOWS_INVALID_CHARS or ord(character) < 32 else character
        for character in str(component)
    ).rstrip(" .")
    if not cleaned:
        cleaned = "_"

    basename = cleaned.split(".", 1)[0].rstrip(" ").upper()
    if basename in WINDOWS_RESERVED_BASENAMES:
        cleaned = f"_{cleaned}"
    return cleaned


def windows_safe_archive_parts(member_name: str) -> tuple[str, ...]:
    """Normalize a ZIP member name and reject paths that could escape its target."""
    normalized = str(member_name).replace("\\", "/")
    if normalized.startswith("/") or _WINDOWS_DRIVE_PREFIX.match(normalized):
        raise ValueError(f"Unsafe absolute archive path: {member_name!r}")

    parts: list[str] = []
    for component in normalized.split("/"):
        if not component or component == ".":
            continue
        if component == "..":
            raise ValueError(f"Unsafe parent path in archive member: {member_name!r}")
        parts.append(windows_safe_component(component))

    if not parts:
        raise ValueError(f"Empty archive member path: {member_name!r}")
    return tuple(parts)


def windows_safe_archive_name(parts: tuple[str, ...] | list[str]) -> str:
    """Build a portable ZIP member name from relative filesystem parts."""
    if not parts:
        raise ValueError("Archive member must contain at least one path component")
    safe_parts: list[str] = []
    for component in parts:
        if component in ("", ".", ".."):
            raise ValueError(f"Unsafe archive path component: {component!r}")
        safe_parts.append(windows_safe_component(component))
    return "/".join(safe_parts)


def windows_safe_destination(target: pathlib.Path, member_name: str) -> pathlib.Path:
    """Resolve a sanitized ZIP member beneath *target*."""
    return pathlib.Path(target).joinpath(*windows_safe_archive_parts(member_name))


def install_countrystatecity_windows_path_compat() -> None:
    """Teach countrystatecity-countries to read sanitized reserved state paths.

    PyInstaller and Mindinguflac both map a state code such as ``CON`` to
    ``_CON`` on Windows. The data model must keep the real state code, so this
    fallback changes only the on-disk lookup when the original path is absent.
    """
    try:
        from countrystatecity_countries.loaders import DataLoader
    except Exception:
        return

    if getattr(DataLoader, "_mindinguflac_windows_path_compat", False):
        return

    original_load_cities = DataLoader.load_cities

    @classmethod
    @lru_cache(maxsize=5000)
    def load_cities(cls, country_code: str, state_code: str):
        cities = original_load_cities(country_code, state_code)
        if cities:
            return cities

        safe_state_code = windows_safe_component(str(state_code).upper())
        if safe_state_code == str(state_code).upper():
            return cities

        file_path = (
            cls._data_dir
            / "by-country"
            / str(country_code).upper()
            / "states"
            / safe_state_code
            / "cities.json"
        )
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return cities
        return data if isinstance(data, list) else cities

    DataLoader.load_cities = load_cities
    DataLoader._mindinguflac_windows_path_compat = True
