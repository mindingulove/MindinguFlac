#!/usr/bin/env python3
"""Build ffmpeg and ffprobe executables for Android arm64 from pinned FFmpeg source.

Mornye's providers run ``ffmpeg``/``ffprobe`` as programs to remux, decrypt
(``-decryption_key``), convert to FLAC and validate downloads. Android ships
neither, and FFmpegKit only offers libraries behind a Java API, so the two
programs are cross-compiled here with the NDK and packaged as lib*.so, the
same way as Node (see prepare_android_node.py). No external libraries: every
input Mornye passes is a local file.
"""
from pathlib import Path
import argparse
import hashlib
import os
import shutil
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SOURCE = {
    # Same release as the desktop app's bundled ffmpeg. Signed by the FFmpeg
    # release key FCF986EA15E6E293A5644F10B4322F04D67658D8.
    'url': 'https://ffmpeg.org/releases/ffmpeg-8.1.tar.xz',
    'sha256': 'b072aed6871998cce9b36e7774033105ca29e33632be5b6347f3206898e0756a',
}
API_LEVEL = 26  # minSdk
CONFIGURE = [
    '--target-os=android', '--arch=aarch64', '--cpu=armv8-a', '--enable-cross-compile',
    '--enable-pic', '--disable-shared', '--enable-static', '--disable-debug', '--disable-doc',
    '--disable-autodetect', '--enable-zlib', '--disable-ffplay', '--enable-ffmpeg', '--enable-ffprobe',
    '--disable-indevs', '--disable-outdevs', '--disable-vulkan', '--disable-mediacodec', '--disable-jni',
    # Android 15+ devices may use 16 KB pages.
    '--extra-ldflags=-Wl,-z,max-page-size=16384',
]
BUILD = ROOT / 'build/android-ffmpeg'


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
        with urllib.request.urlopen(request, timeout=300) as source, temporary.open('wb') as output:
            shutil.copyfileobj(source, output)
        if digest(temporary) != spec['sha256']:
            raise RuntimeError(f'Hash mismatch for {path.name}')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def toolchain(ndk):
    prebuilt = ndk / 'toolchains/llvm/prebuilt'
    hosts = sorted(path for path in prebuilt.iterdir() if (path / 'bin').is_dir()) if prebuilt.is_dir() else []
    if not hosts:
        raise RuntimeError(f'No NDK LLVM toolchain under {prebuilt}')
    return hosts[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ndk', type=Path, required=True)
    parser.add_argument('ffmpeg', type=Path, help='output path for the ffmpeg executable (lib*.so)')
    parser.add_argument('ffprobe', type=Path, help='output path for the ffprobe executable (lib*.so)')
    args = parser.parse_args()

    # Rebuild only when the source, flags or NDK change.
    recipe = hashlib.sha256('\n'.join([SOURCE['sha256'], str(API_LEVEL), args.ndk.name, *CONFIGURE]).encode()).hexdigest()
    stamp = BUILD / 'build.sha256'
    built = BUILD / 'out'
    if not (stamp.is_file() and stamp.read_text().strip() == recipe
            and (built / 'ffmpeg').is_file() and (built / 'ffprobe').is_file()):
        archive = BUILD / SOURCE['url'].rsplit('/', 1)[1]
        download(SOURCE, archive)
        source = BUILD / 'src'
        shutil.rmtree(source, ignore_errors=True)
        source.mkdir(parents=True)
        with tarfile.open(archive) as package:
            package.extractall(source, filter='data')
        tree = next(source.iterdir())
        tools = toolchain(args.ndk)
        bin_dir = tools / 'bin'
        target = f'aarch64-linux-android{API_LEVEL}'
        subprocess.run([
            './configure', *CONFIGURE,
            f'--cc={bin_dir / (target + "-clang")}', f'--cxx={bin_dir / (target + "-clang++")}',
            f'--ar={bin_dir / "llvm-ar"}', f'--nm={bin_dir / "llvm-nm"}', f'--ranlib={bin_dir / "llvm-ranlib"}',
            f'--strip={bin_dir / "llvm-strip"}', f'--sysroot={tools / "sysroot"}',
        ], cwd=tree, check=True)
        subprocess.run(['make', f'-j{os.cpu_count() or 4}', 'ffmpeg', 'ffprobe'], cwd=tree, check=True)
        shutil.rmtree(built, ignore_errors=True)
        built.mkdir(parents=True)
        for name in ('ffmpeg', 'ffprobe'):
            subprocess.run([str(bin_dir / 'llvm-strip'), '-o', str(built / name), str(tree / name)], check=True)
        stamp.write_text(recipe + '\n')
        shutil.rmtree(source, ignore_errors=True)

    for name, output in (('ffmpeg', args.ffmpeg), ('ffprobe', args.ffprobe)):
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(built / name, output)
        output.chmod(0o755)
    print(f'Android ffmpeg/ffprobe ready: {args.ffmpeg.parent}')


if __name__ == '__main__':
    main()
