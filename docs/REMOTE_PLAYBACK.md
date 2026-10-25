# Control paired desktop playback from Android

Both devices must run this update and be on the same Wi-Fi/LAN. Keep the desktop app open.

1. Pair the phone with the computer in **Settings → Device pairing** using the desktop's QR code. Existing pairings continue to work.
2. On Android, open **Devices** and choose the computer under **Paired computers · Wi-Fi**.
3. The phone shows **Listening on [computer]**. Play/pause, seek, next/previous, volume, shuffle/repeat, song selection and queue changes act on that computer. The phone's own audio stops before the connection is activated.
4. The computer shows **Controlled by [phone]** after its player acknowledges the session.
5. Choose **This device** in the banner or a local audio output in Devices to return to the phone. Its previous local track and queue are restored paused. The computer may continue playing locally after remote control ends.

Bluetooth entries still route audio to speakers and headphones; they do not discover computers for app control. A computer must already be paired to accept playback commands. Pairing secrets remain in Python and are never sent to the WebView. Remote connections reuse the existing certificate pin and pair authentication.

A connection or command timeout is shown as a failure, not successful playback. Receiving-player status separately reports buffering and actual playback. Sessions expire after a lost heartbeat, a closed receiving player, or removed pairing. Losing Wi-Fi does not automatically start the phone's player.
