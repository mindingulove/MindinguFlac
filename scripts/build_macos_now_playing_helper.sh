#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="$ROOT/build/macos"
CACHE_DIR="$ROOT/build/swift-module-cache"
SRC="$ROOT/macos/MindinguflacNowPlaying.swift"
OUT="$OUT_DIR/MindinguflacNowPlayingHelper"

mkdir -p "$OUT_DIR"
mkdir -p "$CACHE_DIR"

export CLANG_MODULE_CACHE_PATH="$CACHE_DIR"
export SWIFT_MODULECACHE_PATH="$CACHE_DIR"

PLIST="$ROOT/macos/MindinguflacNowPlayingHelper-Info.plist"

TARGET_ARGS=()
if [[ -n "${MACOS_ARCH:-}" ]]; then
  DEPLOYMENT_TARGET="${MACOSX_DEPLOYMENT_TARGET:-12.0}"
  TARGET_ARGS=(-target "${MACOS_ARCH}-apple-macosx${DEPLOYMENT_TARGET}")
fi

swiftc -O \
  "${TARGET_ARGS[@]}" \
  -parse-as-library \
  -module-cache-path "$CACHE_DIR" \
  -framework AppKit \
  -framework Foundation \
  -framework MediaPlayer \
  -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker "$PLIST" \
  "$SRC" \
  -o "$OUT"
