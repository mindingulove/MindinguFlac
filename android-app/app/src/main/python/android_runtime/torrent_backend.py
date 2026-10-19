"""Compatibility import for the shared Android and desktop torrent race."""
import sys
import torrent_race as _shared_race

# Alias the module itself so test seams and runtime monkeypatches address the
# same function globals on Android and desktop.
sys.modules[__name__] = _shared_race
