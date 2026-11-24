# Paired-device playback, 24 October 2026

Queued after the Miami building update, as requested by the user. This is
playback control over the existing app pairing, separate from Bluetooth audio
routing. Preserve the current Bluetooth device list and its selection behavior.

## Required behavior

- In the Android Devices tab, selecting an already paired app device starts a
  remote playback session for that device.
- Transport controls, track selection, queue and current playback state follow
  the selected paired device; avoid simultaneous unintended local playback.
- The controller shows a Spotify-style persistent playback banner:
  **Listening on [receiving device]**. Use "Listening", not "Controlling".
- The receiving device shows **Controlled by [controller device]** while that
  remote session is active.
- Selecting **This device**, exiting the paired-device session, disconnecting,
  or removing the pairing clears the session and both banners. Returning to
  local playback must not leave a stale remote route or remote-control state.
- Distinguish connecting, active, disconnected and failed states. A selected
  device is not proof of an acknowledged playback command.

## Implementation and verification

1. Revalidate current desktop/Android pairing, player and device-picker APIs.
   The worktree has an active metadata/dependency migration; preserve it.
2. Add authenticated remote playback commands and status/session lifecycle over
   the existing pinned pairing transport. Retain device names and state without
   exposing pairing secrets to the frontend.
3. Integrate paired app devices with the Android Devices tab alongside the
   current Bluetooth entries and provide an explicit This device action.
4. Drive both banners from acknowledged session state, with deterministic cleanup
   on local selection, explicit session exit, timeout and pairing removal.
5. Test commands/status, lifecycle cleanup and stale-session rejection; build a
   fresh APK. Verify controller and receiver behavior across two app instances,
   then install/test on connected Android hardware when available. Report any
   physical-device or audible-playback checks that could not be performed.

Status: requirements captured; implementation follows the building installation.
