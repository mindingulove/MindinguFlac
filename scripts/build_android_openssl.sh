#!/usr/bin/env bash
set -euo pipefail

# A custom cryptography wheel must use a patched OpenSSL too. Build the
# supported 3.5 LTS release as static Android libraries, with no legacy module.
project_root="$(cd "$(dirname "$0")/.." && pwd)"
build_root="${1:?Pass a build directory inside the Chaquopy workspace}"
mkdir -p "$build_root"
build_root="$(cd "$build_root" && pwd)"
archive="$project_root/.work/openssl-3.5.9.tar.gz"
mkdir -p "$(dirname "$archive")"
if [[ ! -f "$archive" ]]; then
    curl --fail --location --silent --show-error \
        https://github.com/openssl/openssl/releases/download/openssl-3.5.9/openssl-3.5.9.tar.gz \
        --output "$archive"
fi
echo "603f5602e2eef00d77fbd429d34dcd5822bb301757a1bc9cdb24c670f1eb859a  $archive" | sha256sum --check
tar -xzf "$archive" -C "$build_root"
export ANDROID_NDK_ROOT="${ANDROID_NDK_HOME:-${ANDROID_HOME:?}/ndk/27.3.13750724}"
export PATH="$ANDROID_NDK_ROOT/toolchains/llvm/prebuilt/linux-x86_64/bin:$PATH"
cd "$build_root/openssl-3.5.9"
perl Configure android-arm64 -D__ANDROID_API__=24 no-shared no-tests no-module no-legacy \
    -fPIC --prefix="$build_root/prefix" --libdir=lib
make -j"${MINDINGUFLAC_BUILD_JOBS:-6}" build_libs
make install_dev
