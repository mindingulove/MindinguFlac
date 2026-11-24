package com.mindinguflac.android;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;

/**
 * Receives Spotify links ("Open with" an open.spotify.com / spotify: link, or
 * Share > Mindinguflac) and forwards them to MainActivity in its own task, so
 * the link never starts a second MainActivity inside the sharing app's task.
 */
public final class SpotifyLinkActivity extends Activity {
    static final String EXTRA_SPOTIFY_LINK = "com.mindinguflac.android.SPOTIFY_LINK";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        String link = linkFrom(getIntent());
        Intent open = new Intent(this, MainActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                        | Intent.FLAG_ACTIVITY_CLEAR_TOP
                        | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        if (link != null) open.putExtra(EXTRA_SPOTIFY_LINK, link);
        startActivity(open);
        finish();
    }

    private static String linkFrom(Intent intent) {
        if (intent == null) return null;
        if (Intent.ACTION_SEND.equals(intent.getAction())) {
            CharSequence text = intent.getCharSequenceExtra(Intent.EXTRA_TEXT);
            if (text == null) return null;
            // Shares carry "Song by Artist https://open.spotify.com/..." text.
            java.util.regex.Matcher m = java.util.regex.Pattern
                    .compile("(https?://\\S+|spotify:\\S+)").matcher(text);
            return m.find() ? m.group(1) : text.toString().trim();
        }
        return intent.getData() != null ? intent.getData().toString() : null;
    }
}
