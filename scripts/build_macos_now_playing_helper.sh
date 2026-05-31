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

swiftc -O \
  -parse-as-library \
  -module-cache-path "$CACHE_DIR" \
  -framework AppKit \
  -framework Foundation \
  -framework MediaPlayer \
  -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker "$PLIST" \
  "$SRC" \
  -o "$OUT"
