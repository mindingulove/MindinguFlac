#!/usr/bin/env python3
"""Fetch the pinned standalone Node.js for Android that runs Mornye's JS providers.

The binary is packaged as a native library (lib*.so) because Android only lets
an app execute files from its read-only native library directory.
"""
from pathlib import Path
import argparse
import hashlib
import shutil
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
# Standalone, statically linked against libc++, 16 KB page aligned.
# https://github.com/Towartz/nodejs-arm/releases/tag/node-android-v26.7.0-run165
NODE = {
    'url': 'https://github.com/Towartz/nodejs-arm/releases/download/node-android-v26.7.0-run165/'
           'node-v26.7.0-android-arm64-v8a.zip',
    'sha256': '5f815af78861ebbb7850e2e27d393b6f6f6cc55225f6d008ffe955f409f73ed3',
}


def digest(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def download(spec, path):
    if path.is_file() and digest(path) == spec['sha256']:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.part')
    try:
        request = urllib.request.Request(spec['url'], headers={'User-Agent': 'Mindinguflac-build/1.4'})
        with urllib.request.urlopen(request, timeout=120) as source, temporary.open('wb') as output:
            shutil.copyfileobj(source, output)
        if digest(temporary) != spec['sha256']:
            raise RuntimeError(f'Hash mismatch for {path.name}')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path, help='where to write the executable (lib*.so)')
    args = parser.parse_args()
    archive = ROOT / 'build/android-node' / NODE['url'].rsplit('/', 1)[1]
    download(NODE, archive)
    stamp = archive.with_name(args.output.name + '.sha256')  # not beside the .so: jniLibs is packaged
    if args.output.is_file() and stamp.is_file() and stamp.read_text().strip() == NODE['sha256']:
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as package, package.open('node') as source, args.output.open('wb') as output:
        shutil.copyfileobj(source, output)
    args.output.chmod(0o755)
    stamp.write_text(NODE['sha256'] + '\n')
    print(f'Android Node.js runtime ready: {args.output}')


if __name__ == '__main__':
    main()
