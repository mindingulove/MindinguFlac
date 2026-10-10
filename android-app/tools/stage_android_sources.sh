#!/bin/sh
# Reproduce the APK's Python sys.path root on the host.
#
# Chaquopy flattens three things into one import root: the repository's
# top-level modules, android-app/app/src/main/python, and the desktop
# static/ directory mounted at android_runtime/static. The Gradle
# `syncPythonSources` task does this during a build; this script does the
# same thing outside Gradle so the audit and runtime verification tools can
# import exactly what the device imports.
#
# Usage: tools/stage_android_sources.sh <stage-dir>
set -eu

STAGE=${1:?usage: stage_android_sources.sh <stage-dir>}
HERE=$(cd "$(dirname "$0")" && pwd)
ANDROID_APP=$(dirname "$HERE")
REPO=$(dirname "$ANDROID_APP")

rm -rf "$STAGE"
mkdir -p "$STAGE/android_runtime/static"

# Repository top-level modules (the Sync task's `include("*.py")`).
find "$REPO" -maxdepth 1 -name '*.py' -exec cp {} "$STAGE/" \;

# Vendored Android-only source: SpotiFLAC, RapidFuzz, pydantic shim,
# android_runtime. Its own static/ is excluded, as in build.gradle.kts.
rsync -a --exclude '__pycache__' --exclude '*.pyc' \
    --exclude 'android_runtime/static' \
    "$ANDROID_APP/app/src/main/python/" "$STAGE/"

# The desktop interface, served by the backend over authenticated loopback.
rsync -a --exclude '.DS_Store' "$REPO/static/" "$STAGE/android_runtime/static/"

echo "staged $(find "$STAGE" -name '*.py' | wc -l | tr -d ' ') Python files in $STAGE"
