"""Align, sign, and verify an APK before preparing it for distribution."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--build-tools", type=Path, required=True)
    parser.add_argument("--keystore", type=Path, required=True)
    parser.add_argument("--alias", required=True)
    args = parser.parse_args()
    if args.apk.resolve() == args.output.resolve():
        parser.error("input and output must be different files")
    if "unsigned" in args.output.name.lower():
        parser.error("the distribution filename must not contain 'unsigned'")
    for name in ("APK_STORE_PASSWORD", "APK_KEY_PASSWORD"):
        if not os.environ.get(name):
            parser.error(f"set {name} in the environment")

    def run(*command):
        subprocess.run([str(x) for x in command], check=True)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.output.parent) as directory:
        aligned = Path(directory) / "aligned.apk"
        signed = Path(directory) / "signed.apk"
        run(args.build_tools / "zipalign", "-P", "16", "-f", "4", args.apk, aligned)
        run(args.build_tools / "apksigner", "sign", "--ks", args.keystore,
            "--ks-key-alias", args.alias, "--ks-pass", "env:APK_STORE_PASSWORD",
            "--key-pass", "env:APK_KEY_PASSWORD", "--out", signed, aligned)
        run(args.build_tools / "apksigner", "verify", "--verbose", "--print-certs", signed)
        run(args.build_tools / "zipalign", "-c", "-P", "16", "4", signed)
        run("unzip", "-tq", signed)
        signed.replace(args.output)
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.output.with_suffix(".apk.sha256").write_text(f"{digest}  {args.output.name}\n")
    print(f"Ready to publish: {args.output}\nSHA-256: {digest}")


if __name__ == "__main__":
    main()
