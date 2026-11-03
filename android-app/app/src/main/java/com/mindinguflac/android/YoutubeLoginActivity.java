package com.mindinguflac.android;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.view.Gravity;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.LinearLayout;
import android.widget.TextView;

import com.chaquo.python.Python;

/**
 * Signs in to YouTube in a WebView and saves the session for yt-dlp, as the
 * desktop app's login window does. Once CookieManager holds a signed-in
 * YouTube cookie, android_runtime/youtube_login.py stores the cookies and the
 * screen closes.
 */
public final class YoutubeLoginActivity extends Activity {
    private static final String SIGN_IN_URL = "https://accounts.google.com/ServiceLogin?service=youtube"
            + "&continue=" + Uri.encode("https://www.youtube.com/signin?action_handle_signin=true&next=%2F");
    private static volatile Context appContext;
    private static volatile boolean open;
    // idle, completed or cancelled; read by app.py's login-status endpoint.
    private static volatile String outcome = "idle";
    private boolean saved;
    // Google may follow sign-in with prompts (profile picture, recovery
    // phone...) before returning to YouTube; once signed in, go there directly.
    private boolean sentToYoutube;
    private WebView web;

    public static void attach(Context context) {
        appContext = context.getApplicationContext();
    }

    /** Opens the sign-in screen; called from Python. */
    public static boolean open() {
        Context context = appContext;
        if (context == null) return false;
        outcome = "idle";
        open = true;
        context.startActivity(new Intent(context, YoutubeLoginActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        return true;
    }

    public static boolean isOpen() {
        return open;
    }

    public static String outcome() {
        return outcome;
    }

    /** Drops the WebView's YouTube and Google session (Sign out). */
    public static void clearSession() {
        CookieManager cookies = CookieManager.getInstance();
        String[][] sites = {
                {"https://www.youtube.com", ".youtube.com"},
                {"https://accounts.google.com", ".google.com"},
        };
        for (String[] site : sites) {
            String header = cookies.getCookie(site[0]);
            if (header == null) continue;
            for (String part : header.split(";")) {
                String name = part.trim().split("=", 2)[0];
                if (name.isEmpty()) continue;
                // Expire it for both the host and the parent domain.
                cookies.setCookie(site[0], name + "=; Max-Age=0; Path=/");
                cookies.setCookie(site[0], name + "=; Max-Age=0; Path=/; Domain=" + site[1]);
            }
        }
        cookies.flush();
    }

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        open = true;
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setBackgroundColor(Color.rgb(9, 10, 13));
        TextView title = new TextView(this);
        title.setText("Sign in to YouTube. The session stays on this phone.");
        title.setTextColor(Color.WHITE);
        title.setGravity(Gravity.CENTER);
        int pad = Math.round(14 * getResources().getDisplayMetrics().density);
        title.setPadding(pad, pad, pad, pad);
        layout.addView(title);

        web = new WebView(this);
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(true);
        cookies.setAcceptThirdPartyCookies(web, true);
        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView view, String url) {
                trySave();
            }
        });
        layout.addView(web, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        setContentView(layout);
        web.loadUrl(SIGN_IN_URL);
    }

    private void trySave() {
        if (saved) return;
        CookieManager cookies = CookieManager.getInstance();
        String youtube = cookies.getCookie("https://www.youtube.com");
        if (youtube == null || !(youtube.contains("SAPISID=") || youtube.contains("LOGIN_INFO="))) {
            String account = cookies.getCookie("https://accounts.google.com");
            if (!sentToYoutube && account != null && account.contains("SAPISID=")) {
                sentToYoutube = true;
                // Signed in with Google but not yet on YouTube: a passive sign-in
                // sets YouTube's cookies without showing Google's prompts.
                web.loadUrl("https://accounts.google.com/ServiceLogin?service=youtube&passive=true"
                        + "&continue=" + Uri.encode("https://www.youtube.com/signin?action_handle_signin=true&next=%2F"));
            }
            return;
        }
        String google = cookies.getCookie("https://accounts.google.com");
        cookies.flush();
        // The Python save writes files; keep it off the UI thread.
        new Thread(() -> {
            boolean ok;
            try {
                ok = Python.getInstance().getModule("android_runtime.youtube_login")
                        .callAttr("save", youtube, google == null ? "" : google).toBoolean();
            } catch (RuntimeException exc) {
                ok = false;
            }
            if (ok) {
                runOnUiThread(() -> {
                    saved = true;
                    outcome = "completed";
                    finish();
                });
            }
        }, "youtube-sign-in").start();
    }

    @Override
    protected void onDestroy() {
        if (!saved && "idle".equals(outcome)) outcome = "cancelled";
        open = false;
        if (web != null) {
            ViewGroup parent = (ViewGroup) web.getParent();
            if (parent != null) parent.removeView(web);
            web.destroy();
        }
        super.onDestroy();
    }
}
