#!/usr/bin/env python3
"""Fetch pinned offline alignment assets; optionally build the desktop bridge."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import sys
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'native/lyrics_alignment/assets.json'


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
        with urllib.request.urlopen(request, timeout=60) as source, temporary.open('wb') as output:
            shutil.copyfileobj(source, output)
        if digest(temporary) != spec['sha256']:
            raise RuntimeError(f'Hash mismatch for {path.name}')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--build-desktop', action='store_true')
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text())
    build = ROOT / 'build/lyrics-whisper'
    archive = build / 'whisper-source.tar.gz'
    download(manifest['source'], archive)
    source = build / 'source'
    stamp = source / '.mindinguflac-source-sha256'
    if not stamp.exists() or stamp.read_text().strip() != manifest['source']['sha256']:
        staging = build / 'extract'
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir()
        with tarfile.open(archive) as package:
            package.extractall(staging, filter='data')
        extracted = next(staging.iterdir())
        shutil.rmtree(source, ignore_errors=True)
        extracted.rename(source)
        shutil.rmtree(staging)
        stamp.write_text(manifest['source']['sha256'] + '\n')
    download(manifest['model'], ROOT / 'assets/lyrics-alignment' / manifest['model']['filename'])
    shutil.copy2(source / 'LICENSE', ROOT / 'assets/lyrics-alignment/LICENSE-whisper.cpp')
    if args.build_desktop:
        target = build / ('windows' if os.name == 'nt' else 'macos')
        configure = ['cmake', '-S', str(ROOT / 'native/lyrics_alignment'), '-B', str(target), '-DCMAKE_BUILD_TYPE=Release']
        if sys.platform == 'darwin':
            configure.append('-DCMAKE_OSX_DEPLOYMENT_TARGET=11.0')
        subprocess.run(configure, check=True)
        subprocess.run(['cmake', '--build', str(target), '--config', 'Release', '--target',
                        'lyrics_whisper', '--parallel', '4'], check=True)
    print('Offline lyrics alignment source and model verified')


if __name__ == '__main__':
    main()
