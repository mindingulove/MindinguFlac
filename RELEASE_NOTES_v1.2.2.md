# Mindinguflac v1.2.2

This release focuses on macOS desktop stability, Bluetooth output recovery, and video playback behavior.

## Fixed

- Prevented duplicate Mindinguflac app instances from opening a second desktop window on macOS startup or relaunch.
- Connected Bluetooth devices in the Connect panel now actively try to switch to the matching audio output instead of showing a dead connected row.
- Saved or selected Bluetooth outputs now fall back to `This computer` when the device is connected but not reachable as an audio output.
- Side video playback now keeps playing when audio is routed through native output, including tracks started from Recently Played.

## Updated

- Visible Settings footer, backend user-agent, release helper, and macOS About/bundle metadata now report `1.2.2`.
