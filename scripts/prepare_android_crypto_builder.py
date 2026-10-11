"""Let the pinned Chaquopy builder use our patched static OpenSSL."""
from pathlib import Path
import sys

path = Path(sys.argv[1]) / "build-wheel.py"
text = path.read_text()
needle = '            env["OPENSSL_DIR"] = f"{self.host_env}/chaquopy"\n'
replacement = needle + '''
        if prefix := os.environ.get("MINDINGUFLAC_OPENSSL_DIR"):
            env["OPENSSL_DIR"] = prefix
            env["OPENSSL_STATIC"] = "1"
            env["CFLAGS"] = f"-I{prefix}/include " + env["CFLAGS"]
            env["CXXFLAGS"] = f"-I{prefix}/include " + env["CXXFLAGS"]
            env["LDFLAGS"] = f"-L{prefix}/lib -Wl,-Bsymbolic-functions " + env["LDFLAGS"]
'''
if 'if prefix := os.environ.get("MINDINGUFLAC_OPENSSL_DIR"):' not in text:
    if text.count(needle) != 1:
        raise SystemExit("Unexpected Chaquopy OpenSSL environment setup")
    path.write_text(text.replace(needle, replacement))

text = path.read_text()
needle = '                reqs.update(self.check_requirements(fixed_path, available_libs))\n'
replacement = '''                if self.needs_python:
                    needed = run(f"patchelf --print-needed {fixed_path}", capture_output=True).stdout.splitlines()
                    if "libpython3.so" in needed:
                        run(f"patchelf --replace-needed libpython3.so libpython{self.python}.so {fixed_path}")
''' + needle
if 'patchelf --replace-needed libpython3.so ' not in text:
    if text.count(needle) != 1:
        raise SystemExit("Unexpected Chaquopy native dependency check")
    path.write_text(text.replace(needle, replacement))

# PyO3's stable ABI links against libpython3, while Chaquopy ships the
# versioned library. Packaging above rewrites the dependency to that filename.
text = path.read_text()
needle = '        assert_exists(self.python_lib)\n'
replacement = needle + '''
        generic_python_lib = f"{self.host_env}/chaquopy/lib/libpython3.so"
        if not exists(generic_python_lib):
            os.symlink(os.path.basename(self.python_lib), generic_python_lib)
'''
if 'generic_python_lib = ' not in text:
    if text.count(needle) != 1:
        raise SystemExit("Unexpected Chaquopy Python library setup")
    path.write_text(text.replace(needle, replacement))
