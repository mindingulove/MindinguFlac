from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
import zipfile

import launcher
from scripts.create_windows_bundle import create_windows_bundle
from windows_bundle import (
    install_countrystatecity_windows_path_compat,
    windows_safe_archive_parts,
    windows_safe_component,
)


class WindowsBundlePathTests(unittest.TestCase):
    def test_reserved_windows_names_are_prefixed(self):
        for name in ("CON", "con.txt", "CON .json", "PRN", "AUX.json", "NUL", "COM1", "LPT9.log"):
            with self.subTest(name=name):
                self.assertEqual(windows_safe_component(name), f"_{name}")
        self.assertEqual(windows_safe_component("CONCERT"), "CONCERT")

    def test_archive_paths_accept_both_separators_and_sanitize_reserved_parts(self):
        self.assertEqual(
            windows_safe_archive_parts(
                r"_internal\countrystatecity_countries\data\by-country\GB\states\CON\cities.json"
            ),
            (
                "_internal",
                "countrystatecity_countries",
                "data",
                "by-country",
                "GB",
                "states",
                "_CON",
                "cities.json",
            ),
        )

    def test_archive_paths_reject_traversal_and_absolute_names(self):
        for name in ("../outside.txt", "folder/../../outside.txt", "/absolute.txt", r"C:\outside.txt"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    windows_safe_archive_parts(name)

    def test_bundle_creation_renames_reserved_components(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            source = root / "source"
            city_file = source / "_internal" / "data" / "GB" / "states" / "CON" / "cities.json"
            city_file.parent.mkdir(parents=True)
            city_file.write_text("[]", encoding="utf-8")
            destination = root / "bundle.zip"

            self.assertEqual(create_windows_bundle(source, destination), 1)
            with zipfile.ZipFile(destination) as archive:
                self.assertEqual(
                    archive.namelist(),
                    ["_internal/data/GB/states/_CON/cities.json"],
                )

    def test_launcher_extracts_raw_reserved_member_to_safe_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            bundle = root / "bundle.zip"
            target = root / "target"
            with zipfile.ZipFile(bundle, "w") as archive:
                archive.writestr(r"_internal\data\GB\states\CON\cities.json", "[]")

            launcher._extract_silent(bundle, target)

            self.assertEqual(
                (target / "_internal" / "data" / "GB" / "states" / "_CON" / "cities.json").read_text(),
                "[]",
            )

    def test_launcher_rejects_archive_traversal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            bundle = root / "bundle.zip"
            target = root / "target"
            with zipfile.ZipFile(bundle, "w") as archive:
                archive.writestr("../outside.txt", "unsafe")

            with self.assertRaisesRegex(ValueError, "Unsafe parent path"):
                launcher._extract_silent(bundle, target)
            self.assertFalse((root / "outside.txt").exists())

    def test_countrystatecity_can_read_sanitized_con_directory(self):
        from countrystatecity_countries.loaders import DataLoader

        original_descriptor = DataLoader.__dict__["load_cities"]
        original_data_dir = DataLoader._data_dir
        original_flag = getattr(DataLoader, "_mindinguflac_windows_path_compat", None)
        original_load_cities = DataLoader.load_cities
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = pathlib.Path(temp_dir)
            city_file = data_dir / "by-country" / "GB" / "states" / "_CON" / "cities.json"
            city_file.parent.mkdir(parents=True)
            city_file.write_text(json.dumps([{"name": "Bodmin"}]), encoding="utf-8")
            try:
                DataLoader._data_dir = data_dir
                original_load_cities.cache_clear()
                if hasattr(DataLoader, "_mindinguflac_windows_path_compat"):
                    delattr(DataLoader, "_mindinguflac_windows_path_compat")
                install_countrystatecity_windows_path_compat()
                self.assertEqual(DataLoader.load_cities("GB", "CON"), [{"name": "Bodmin"}])
            finally:
                DataLoader.load_cities = original_descriptor
                DataLoader._data_dir = original_data_dir
                original_load_cities.cache_clear()
                if original_flag is None:
                    if hasattr(DataLoader, "_mindinguflac_windows_path_compat"):
                        delattr(DataLoader, "_mindinguflac_windows_path_compat")
                else:
                    DataLoader._mindinguflac_windows_path_compat = original_flag


if __name__ == "__main__":
    unittest.main()
