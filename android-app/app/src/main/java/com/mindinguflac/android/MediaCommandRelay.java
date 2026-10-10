package com.mindinguflac.android;

/**
 * One-way channel from the media notification back into the WebView player.
 *
 * The audio element lives in the page, so the service cannot act on a
 * notification button or a Bluetooth media key itself — it has to ask the
 * Activity to click the corresponding control. The Activity registers a
 * listener while it exists; if the Activity has been destroyed the command is
 * dropped rather than queued, because the page it would have driven is gone
 * too.
 */
public final class MediaCommandRelay {

    /**
     * Deliberately prefixed names: the Activity implements this, and a bare
     * {@code onStop()} here would override {@link android.app.Activity#onStop()}
     * instead of adding to it — which crashed the app with
     * SuperNotCalledException the moment it was backgrounded.
     */
    public interface Listener {
        void onMediaPlayPause();

        void onMediaPrevious();

        void onMediaNext();

        void onMediaStop();
    }

    private static volatile Listener listener;

    private MediaCommandRelay() {}

    public static void setListener(Listener value) {
        listener = value;
    }

    public static void clearListener(Listener value) {
        if (listener == value) listener = null;
    }

    static void playPause() {
        Listener current = listener;
        if (current != null) current.onMediaPlayPause();
    }

    static void previous() {
        Listener current = listener;
        if (current != null) current.onMediaPrevious();
    }

    static void next() {
        Listener current = listener;
        if (current != null) current.onMediaNext();
    }

    static void stop() {
        Listener current = listener;
        if (current != null) current.onMediaStop();
    }
}
