package com.mindinguflac.android;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.Manifest;
import android.content.ContentValues;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.os.Environment;
import android.provider.MediaStore;
import android.media.AudioManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.window.OnBackInvokedDispatcher;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.JavascriptInterface;
import android.webkit.CookieManager;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.ProgressBar;
import android.widget.TextView;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.io.File;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity implements MediaCommandRelay.Listener {
    private static final int REQUEST_GEMMA_MODEL = 3401;
    private static final int REQUEST_POST_NOTIFICATIONS = 3402;
    private final ExecutorService startupExecutor = Executors.newSingleThreadExecutor();
    private WebView webView;
    private View loadingView;
    private String apiToken;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // Route the hardware volume keys at the media stream, so they adjust
        // playback even before the first track starts. The page itself always
        // plays at unity gain on Android; the system owns volume.
        setVolumeControlStream(AudioManager.STREAM_MUSIC);
        getWindow().setStatusBarColor(Color.rgb(9, 10, 13));
        getWindow().setNavigationBarColor(Color.rgb(5, 6, 8));
        setContentView(createContentView());
        configureWebView();
        LocalModelAdvisor.initialize(getApplicationContext());
        // Auto-download runs on its own over Wi-Fi; on mobile data it waits
        // for the user to explicitly ask for it (the Settings "Download now"
        // button), rather than silently spending a ~1.5 GB data allowance.
        LocalModelAdvisor.maybeAutoDownload();
        // Starts the AICore feature download immediately if it is downloadable,
        // instead of waiting for the first on-device ranking request.
        NanoAdvisor.maybeStartDownload();
        MediaCommandRelay.setListener(this);
        registerBackHandler();
        requestNotificationPermission();
        startPythonBackend();
    }

    private View createContentView() {
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.rgb(9, 10, 13));

        webView = new BackgroundAudioWebView(this);
        webView.setBackgroundColor(Color.rgb(9, 10, 13));
        root.addView(webView, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));

        FrameLayout loading = new FrameLayout(this);
        loading.setBackgroundColor(Color.rgb(9, 10, 13));
        ProgressBar progress = new ProgressBar(this);
        FrameLayout.LayoutParams progressParams = new FrameLayout.LayoutParams(72, 72);
        progressParams.gravity = android.view.Gravity.CENTER;
        loading.addView(progress, progressParams);

        TextView label = new TextView(this);
        label.setText("Starting Mindinguflac…");
        label.setTextColor(Color.WHITE);
        label.setTextSize(16);
        label.setGravity(android.view.Gravity.CENTER);
        FrameLayout.LayoutParams labelParams = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 120);
        labelParams.gravity = android.view.Gravity.CENTER;
        labelParams.topMargin = 110;
        loading.addView(label, labelParams);
        root.addView(loading, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));
        loadingView = loading;
        return root;
    }

    @SuppressLint({"SetJavaScriptEnabled", "JavascriptInterface"})
    private void configureWebView() {
        // Debug builds expose the WebView to Chrome DevTools over adb, which is
        // the only practical way to inspect the phone layout against a real
        // device. Release builds never enable it.
        if ((getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0) {
            WebView.setWebContentsDebuggingEnabled(true);
        }
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        // Playback starts after the Python download worker has produced enough
        // audio, which can be several seconds after the user's tap.
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setUserAgentString(settings.getUserAgentString() + " Mindinguflac-Android/0.1");
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, false);
        webView.addJavascriptInterface(new AndroidBridge(), "MindinguflacAndroid");
        webView.setWebChromeClient(new WebChromeClient());
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                String host = uri.getHost();
                if ("http".equals(uri.getScheme()) && "127.0.0.1".equals(host)) {
                    return false;
                }
                if ("https".equals(uri.getScheme())) {
                    startActivity(new Intent(Intent.ACTION_VIEW, uri));
                }
                return true;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                loadingView.animate().alpha(0f).setDuration(180).withEndAction(() -> {
                    loadingView.setVisibility(View.GONE);
                }).start();
            }
        });
    }

    private void startPythonBackend() {
        apiToken = UUID.randomUUID().toString().replace("-", "");
        startupExecutor.execute(() -> {
            try {
                if (!Python.isStarted()) {
                    Python.start(new AndroidPlatform(getApplicationContext()));
                }
                File externalRoot = getExternalFilesDir(null);
                File storageRoot = new File(
                        externalRoot != null ? externalRoot : getFilesDir(),
                        "Mindinguflac");
                File cacheRoot = new File(storageRoot, "cache");
                File musicRoot = new File(storageRoot, "music");
                if ((!cacheRoot.isDirectory() && !cacheRoot.mkdirs())
                        || (!musicRoot.isDirectory() && !musicRoot.mkdirs())) {
                    throw new IllegalStateException("Could not create managed music storage");
                }
                PyObject bootstrap = Python.getInstance().getModule("android_runtime.bootstrap");
                int port = bootstrap.callAttr(
                        "start",
                        getFilesDir().getAbsolutePath(),
                        cacheRoot.getAbsolutePath(),
                        musicRoot.getAbsolutePath(),
                        apiToken).toInt();
                String origin = "http://127.0.0.1:" + port;
                runOnUiThread(() -> {
                    CookieManager cookies = CookieManager.getInstance();
                    cookies.setCookie(
                            origin,
                            "mindinguflac_token=" + apiToken + "; Path=/; HttpOnly; SameSite=Strict",
                            accepted -> {
                                if (!Boolean.TRUE.equals(accepted)) {
                                    showStartupError(new IllegalStateException("Could not secure the local backend session"));
                                    return;
                                }
                                cookies.flush();
                                webView.loadUrl(origin + "/index.html");
                            });
                });
            } catch (Throwable error) {
                runOnUiThread(() -> showStartupError(error));
            }
        });
    }

    /**
     * The media notification and Bluetooth keys act on the page's own controls.
     * Clicking the real buttons keeps one code path for playback state instead
     * of a second, drifting one on the Java side.
     */
    private void clickPlayerControl(String elementId) {
        runOnUiThread(() -> {
            if (webView == null) return;
            webView.evaluateJavascript(
                    "(function(){var b=document.getElementById('" + elementId + "');"
                    + "if(b)b.click();})()", null);
        });
    }

    @Override
    public void onMediaPlayPause() {
        clickPlayerControl("playPause");
    }

    @Override
    public void onMediaPrevious() {
        clickPlayerControl("btnPrev");
    }

    @Override
    public void onMediaNext() {
        clickPlayerControl("btnNext");
    }

    @Override
    public void onMediaStop() {
        runOnUiThread(() -> {
            if (webView == null) return;
            webView.evaluateJavascript(
                    "(function(){var a=document.getElementById('audioPlayer');"
                    + "if(a&&!a.paused){var b=document.getElementById('playPause');if(b)b.click();}})()",
                    null);
        });
    }

    /**
     * Route the back gesture into the page instead of finishing the Activity.
     *
     * The interface is a JavaScript view stack, so {@code WebView.canGoBack()}
     * is always false and the old {@code onBackPressed()} override fell
     * straight through to closing the app. Targeting SDK 35 also opts into
     * predictive back, where {@code onBackPressed()} is never called at all —
     * so the callback has to be registered explicitly on API 33+.
     */
    private void registerBackHandler() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(
                    OnBackInvokedDispatcher.PRIORITY_DEFAULT, this::dispatchBackToPage);
        }
    }

    private void dispatchBackToPage() {
        if (webView == null) {
            finish();
            return;
        }
        // The page decides: close a panel, collapse now-playing, pop a view, or
        // call back into exitApp() when there is nothing left to unwind.
        webView.evaluateJavascript(
                "(function(){ if (window.__androidBack) { window.__androidBack(); return 1; } return 0; })()",
                handled -> {
                    if (!"1".equals(handled)) finish();
                });
    }

    private void requestNotificationPermission() {
        // Android 13+ will not show the playback notification without this, and
        // without the notification the foreground service cannot run.
        if (android.os.Build.VERSION.SDK_INT < android.os.Build.VERSION_CODES.TIRAMISU) return;
        if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                == PackageManager.PERMISSION_GRANTED) {
            return;
        }
        requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS},
                REQUEST_POST_NOTIFICATIONS);
    }

    private void showStartupError(Throwable error) {
        loadingView.setVisibility(View.GONE);
        TextView message = new TextView(this);
        message.setPadding(40, 40, 40, 40);
        message.setTextColor(Color.WHITE);
        message.setTextSize(15);
        message.setText("Mindinguflac could not start.\n\n" + error);
        setContentView(message);
    }

    private void chooseGemmaModel() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("application/octet-stream");
        startActivityForResult(intent, REQUEST_GEMMA_MODEL);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQUEST_GEMMA_MODEL || resultCode != RESULT_OK || data == null || data.getData() == null) {
            return;
        }
        Uri source = data.getData();
        startupExecutor.execute(() -> {
            boolean installed = LocalModelAdvisor.install(getContentResolver(), source);
            runOnUiThread(() -> {
                if (webView != null) {
                    webView.evaluateJavascript(
                            "window.onLocalModelInstalled && window.onLocalModelInstalled(" + installed + ")",
                            null);
                }
            });
        });
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        // Only reached below API 33; newer releases go through the
        // OnBackInvokedDispatcher callback registered above.
        dispatchBackToPage();
    }

    @Override
    protected void onDestroy() {
        MediaCommandRelay.clearListener(this);
        if (isFinishing()) {
            MediaPlaybackService.clear(getApplicationContext());
        }
        if (isFinishing() && Python.isStarted()) {
            try {
                Python.getInstance().getModule("android_runtime.bootstrap").callAttr("stop");
            } catch (Throwable ignored) {
            }
        }
        if (webView != null) {
            webView.destroy();
        }
        startupExecutor.shutdownNow();
        super.onDestroy();
    }

    /**
     * A WebView that does not stop its audio when the app is backgrounded.
     *
     * Chromium suspends media playback when the WebView's window becomes
     * invisible, which is what paused the track the instant you left the app —
     * the foreground service keeps the *process* alive, but nothing stops the
     * renderer from pausing the &lt;audio&gt; element itself. Swallowing the
     * hidden-window notification is the documented way to keep it running;
     * everything else about visibility handling is left alone.
     */
    private static final class BackgroundAudioWebView extends WebView {
        BackgroundAudioWebView(android.content.Context context) {
            super(context);
        }

        @Override
        protected void onWindowVisibilityChanged(int visibility) {
            if (visibility == View.GONE || visibility == View.INVISIBLE) return;
            super.onWindowVisibilityChanged(visibility);
        }
    }

    /**
     * Copy a file the backend already saved into the app's private storage
     * into the phone's shared Music library (MediaStore), so it shows up in
     * the system Music app, a file manager, and other music apps — not just
     * inside this one. The private copy under getExternalFilesDir() is left
     * alone; this adds a second, MediaStore-registered copy rather than
     * moving anything, so nothing the backend already tracks by path changes.
     *
     * Desktop is unaffected: this method only exists on the Android build and
     * is only ever called from the phone frontend.
     */
    private boolean exportToSharedMusicLibrary(String sourcePath, String displayName, String mimeType) {
        if (sourcePath == null || sourcePath.isEmpty()) return false;
        File source = new File(sourcePath);
        if (!source.isFile()) return false;

        String name = (displayName == null || displayName.isEmpty())
                ? source.getName() : displayName;
        String type = (mimeType == null || mimeType.isEmpty()) ? "audio/mpeg" : mimeType;

        android.content.ContentResolver resolver = getContentResolver();
        android.net.Uri collection = MediaStore.Audio.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY);
        String relativePath = Environment.DIRECTORY_MUSIC + "/Mindinguflac";

        // Skip re-exporting a file already registered under this name and
        // path, so repeat "add to library" calls (resume after a restart,
        // retrying a stuck UI) do not pile up duplicate MediaStore rows.
        try (Cursor existing = resolver.query(collection,
                new String[]{MediaStore.Audio.Media._ID},
                MediaStore.Audio.Media.DISPLAY_NAME + "=? AND " + MediaStore.Audio.Media.RELATIVE_PATH + "=?",
                new String[]{name, relativePath + "/"}, null)) {
            if (existing != null && existing.getCount() > 0) return true;
        } catch (Throwable ignored) {
        }

        ContentValues values = new ContentValues();
        values.put(MediaStore.Audio.Media.DISPLAY_NAME, name);
        values.put(MediaStore.Audio.Media.MIME_TYPE, type);
        values.put(MediaStore.Audio.Media.RELATIVE_PATH, relativePath);
        values.put(MediaStore.Audio.Media.IS_PENDING, 1);

        android.net.Uri item = null;
        try {
            item = resolver.insert(collection, values);
            if (item == null) return false;
            try (java.io.OutputStream out = resolver.openOutputStream(item);
                 java.io.InputStream in = new java.io.FileInputStream(source)) {
                if (out == null) return false;
                byte[] buffer = new byte[256 * 1024];
                int count;
                while ((count = in.read(buffer)) != -1) out.write(count == buffer.length ? buffer : java.util.Arrays.copyOf(buffer, count));
            }
            values.clear();
            values.put(MediaStore.Audio.Media.IS_PENDING, 0);
            resolver.update(item, values, null, null);
            return true;
        } catch (Throwable error) {
            // A half-written row is worse than none: drop it rather than leave
            // a broken, unplayable entry in the user's Music library.
            if (item != null) {
                try {
                    resolver.delete(item, null, null);
                } catch (Throwable ignoredDelete) {
                }
            }
            return false;
        }
    }

    public final class AndroidBridge {
        @JavascriptInterface
        public String platform() {
            return "android";
        }

        @JavascriptInterface
        public String nanoStatus() {
            return NanoAdvisor.status();
        }

        @JavascriptInterface
        public String localModelStatus() {
            return LocalModelAdvisor.status();
        }

        /** Pick a .task bundle manually — a different model, or a retry via a browser download. */
        @JavascriptInterface
        public void installLocalModel() {
            runOnUiThread(MainActivity.this::chooseGemmaModel);
        }

        /** Force the auto-download now, including over a metered connection. */
        @JavascriptInterface
        public void downloadLocalModel() {
            startupExecutor.execute(LocalModelAdvisor::forceDownload);
        }

        /**
         * Mirror the page's now-playing state into the media notification.
         * Called whenever the track or the play/pause state changes.
         */
        @JavascriptInterface
        public void updateNowPlaying(String json) {
            try {
                org.json.JSONObject value = new org.json.JSONObject(json);
                // The artwork is served by the app's own authenticated loopback
                // API, so the service needs this session's token to fetch it.
                value.put("token", apiToken == null ? "" : apiToken);
                MediaPlaybackService.update(getApplicationContext(), value.toString());
            } catch (Throwable ignored) {
            }
        }

        @JavascriptInterface
        public void clearNowPlaying() {
            try {
                MediaPlaybackService.clear(getApplicationContext());
            } catch (Throwable ignored) {
            }
        }

        /** Called by the page when back has nothing left to unwind. */
        @JavascriptInterface
        public void exitApp() {
            runOnUiThread(MainActivity.this::finish);
        }

        /**
         * Called once a track finishes an explicit "add to library" download.
         * Copies it into the phone's shared Music library in the background;
         * never blocks or fails the download itself if this fails.
         */
        @JavascriptInterface
        public void exportDownloadToMusicLibrary(String path, String displayName, String mimeType) {
            startupExecutor.execute(() -> exportToSharedMusicLibrary(path, displayName, mimeType));
        }

        @JavascriptInterface
        public void openExternal(String url) {
            runOnUiThread(() -> {
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
                } catch (Exception ignored) {
                }
            });
        }

        @JavascriptInterface
        public void share(String text) {
            runOnUiThread(() -> {
                Intent intent = new Intent(Intent.ACTION_SEND);
                intent.setType("text/plain");
                intent.putExtra(Intent.EXTRA_TEXT, text);
                startActivity(Intent.createChooser(intent, "Share"));
            });
        }
    }
}
