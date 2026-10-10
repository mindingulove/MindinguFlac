# Android vendoring note

This directory is the Python source from SpotiFLAC 3.9.0, pinned by the desktop
project to upstream commit `a471fdc`. It is embedded as source because installing
the upstream wheel would also force desktop-only `pywebview` and `pydoll`
dependencies onto Android. The Android build supplies the network, crypto,
tagging, model, and progress dependencies used by Mindinguflac while excluding
desktop window/browser automation.
