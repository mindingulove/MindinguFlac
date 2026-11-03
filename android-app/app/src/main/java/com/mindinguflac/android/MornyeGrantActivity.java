package com.mindinguflac.android;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;

/**
 * Receives mornye://session-grant?grant=...&state=... from the provider check
 * in the Custom Tab, hands it to {@link MornyeVerification}, and returns to the
 * app (closing the tab). A separate activity, so the link never starts a
 * second MainActivity over the tab.
 */
public final class MornyeGrantActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Intent intent = getIntent();
        if (intent != null && intent.getData() != null) {
            MornyeVerification.deliver(intent.getData());
        }
        startActivity(new Intent(this, MainActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP));
        finish();
    }
}
