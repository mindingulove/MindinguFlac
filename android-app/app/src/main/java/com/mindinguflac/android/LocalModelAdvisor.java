package com.mindinguflac.android;

import android.content.ContentResolver;
import android.content.Context;
import android.net.Uri;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.os.Build;

import com.google.mediapipe.tasks.genai.llminference.LlmInference;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.FileInputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Token-free fallback backed by a model this app fetches and installs itself.
 *
 * Gemma's official MediaPipe bundle is license-gated on Hugging Face: Google
 * requires an authenticated, license-accepting download, which an app cannot
 * legitimately do on a user's behalf without embedding credentials. Qwen2.5
 * 1.5B Instruct is Apache-2.0 licensed by Alibaba, and LiteRT Community's
 * conversion of it is a genuinely public, ungated download — proven with a
 * real anonymous request (HTTP 200, no auth header) before this was wired up.
 * That is what makes a real auto-download possible here, where Gemma could
 * only ever be a manual "pick a file you already downloaded yourself" flow.
 */
public final class LocalModelAdvisor {
    private static final String MODEL_DIRECTORY = "models";
    private static final String MODEL_NAME = "local-model.task";
    private static final String MODEL_URL =
            "https://huggingface.co/litert-community/Qwen2.5-1.5B-Instruct/resolve/main/"
                    + "Qwen2.5-1.5B-Instruct_seq128_q8_ekv1280.task";
    // The .task bundle is a zip; a corrupt/partial download is still a valid
    // file up to a point, so a plain existence check cannot tell a finished
    // download from one that died mid-stream. Below this, treat it as absent.
    private static final long MIN_VALID_BYTES = 1_400_000_000L;

    private static volatile Context applicationContext;
    private static final AtomicBoolean downloading = new AtomicBoolean(false);
    private static volatile boolean lastDownloadFailed;

    private LocalModelAdvisor() {
    }

    public static void initialize(Context context) {
        applicationContext = context.getApplicationContext();
    }

    /**
     * Manual override: install a .task bundle the user picked themselves,
     * e.g. a different model entirely, or a retry via a browser download when
     * auto-download can't reach Hugging Face. Same destination slot as the
     * auto-downloaded model — whichever was installed most recently is what
     * generate() uses. Mirrors the old Gemma file-picker flow exactly.
     */
    public static synchronized boolean install(ContentResolver resolver, Uri source) {
        File target = modelFile();
        if (target == null || resolver == null || source == null) return false;
        File parent = target.getParentFile();
        if (parent == null || (!parent.isDirectory() && !parent.mkdirs())) return false;
        File temporary = new File(parent, MODEL_NAME + ".manual-partial");
        try (InputStream input = resolver.openInputStream(source);
             FileOutputStream output = new FileOutputStream(temporary)) {
            if (input == null) return false;
            byte[] buffer = new byte[1024 * 1024];
            int count;
            long copied = 0;
            while ((count = input.read(buffer)) != -1) {
                output.write(buffer, 0, count);
                copied += count;
            }
            output.flush();
            if (copied < 1024 * 1024) return false;
            if (target.exists() && !target.delete()) return false;
            if (temporary.renameTo(target)) {
                lastDownloadFailed = false;
                return true;
            }
            try (InputStream retryInput = new FileInputStream(temporary);
                 FileOutputStream retryOutput = new FileOutputStream(target)) {
                while ((count = retryInput.read(buffer)) != -1) retryOutput.write(buffer, 0, count);
            }
            boolean ok = target.isFile() && target.length() == copied;
            if (ok) lastDownloadFailed = false;
            return ok;
        } catch (Throwable ignored) {
            return false;
        } finally {
            if (temporary.exists() && !temporary.equals(target)) temporary.delete();
        }
    }

    private static File modelFile() {
        Context context = applicationContext;
        if (context == null) return null;
        return new File(new File(context.getFilesDir(), MODEL_DIRECTORY), MODEL_NAME);
    }

    public static String status() {
        File model = modelFile();
        if (model != null && model.isFile() && model.length() >= MIN_VALID_BYTES) {
            return "installed";
        }
        if (downloading.get()) return "downloading";
        if (lastDownloadFailed) return "downloadable";
        return "not_installed";
    }

    /**
     * Start the download automatically at app launch if nothing usable is
     * installed yet. Only proceeds on its own over an unmetered connection —
     * this bundle is ~1.5 GB, and starting that silently over mobile data
     * would be a bad default. {@link #forceDownload()} is the explicit,
     * user-initiated override for "download anyway."
     */
    public static void maybeAutoDownload() {
        if (!"not_installed".equals(status())) return;
        if (!isUnmeteredNetworkAvailable()) return;
        startDownload();
    }

    /** Explicit user request — e.g. the Settings retry button — downloads regardless of network type. */
    public static void forceDownload() {
        startDownload();
    }

    private static boolean isUnmeteredNetworkAvailable() {
        Context context = applicationContext;
        if (context == null) return false;
        try {
            ConnectivityManager manager = context.getSystemService(ConnectivityManager.class);
            if (manager == null) return false;
            Network network = manager.getActiveNetwork();
            if (network == null) return false;
            NetworkCapabilities capabilities = manager.getNetworkCapabilities(network);
            return capabilities != null
                    && capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                    && capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED);
        } catch (Throwable ignored) {
            return false;
        }
    }

    private static void startDownload() {
        if (!downloading.compareAndSet(false, true)) return;
        Thread thread = new Thread(LocalModelAdvisor::runDownload, "mindinguflac-model-download");
        thread.setDaemon(true);
        thread.start();
    }

    private static void runDownload() {
        try {
            File target = modelFile();
            if (target == null) {
                lastDownloadFailed = true;
                return;
            }
            File parent = target.getParentFile();
            if (parent == null || (!parent.isDirectory() && !parent.mkdirs())) {
                lastDownloadFailed = true;
                return;
            }
            File partial = new File(parent, MODEL_NAME + ".partial");
            if (!downloadTo(partial)) {
                lastDownloadFailed = true;
                partial.delete();
                return;
            }
            if (target.exists()) target.delete();
            if (!partial.renameTo(target)) {
                lastDownloadFailed = true;
                partial.delete();
                return;
            }
            lastDownloadFailed = false;
        } catch (Throwable ignored) {
            lastDownloadFailed = true;
        } finally {
            downloading.set(false);
        }
    }

    private static boolean downloadTo(File destination) {
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(MODEL_URL).openConnection();
            connection.setConnectTimeout(15_000);
            connection.setReadTimeout(30_000);
            connection.setInstanceFollowRedirects(true);
            int code = connection.getResponseCode();
            if (code != HttpURLConnection.HTTP_OK) return false;
            try (InputStream input = connection.getInputStream();
                 FileOutputStream output = new FileOutputStream(destination)) {
                byte[] buffer = new byte[1024 * 1024];
                int count;
                long total = 0;
                while ((count = input.read(buffer)) != -1) {
                    // Give up before filling the phone's storage with a dead
                    // partial file if the network drops mid-download; the
                    // next launch (or an explicit retry) starts over cleanly.
                    output.write(buffer, 0, count);
                    total += count;
                }
                return total >= MIN_VALID_BYTES;
            }
        } catch (IOException error) {
            return false;
        } finally {
            if (connection != null) connection.disconnect();
        }
    }

    public static synchronized String generate(String prompt) {
        Context context = applicationContext;
        File model = modelFile();
        if (context == null || model == null || !model.isFile()
                || model.length() < MIN_VALID_BYTES
                || prompt == null || prompt.trim().isEmpty()) {
            return "";
        }
        LlmInference engine = null;
        try {
            LlmInference.LlmInferenceOptions options = LlmInference.LlmInferenceOptions.builder()
                    .setModelPath(model.getAbsolutePath())
                    .setMaxTokens(1024)
                    .build();
            engine = LlmInference.createFromOptions(context, options);
            String response = engine.generateResponse(prompt);
            return response == null ? "" : response.trim();
        } catch (Throwable ignored) {
            return "";
        } finally {
            if (engine != null) {
                try {
                    engine.close();
                } catch (Throwable ignored) {
                }
            }
        }
    }
}
