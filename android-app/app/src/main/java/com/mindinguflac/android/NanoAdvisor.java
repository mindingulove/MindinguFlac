package com.mindinguflac.android;

import com.google.mlkit.genai.common.DownloadCallback;
import com.google.mlkit.genai.common.FeatureStatus;
import com.google.mlkit.genai.common.GenAiException;
import com.google.mlkit.genai.prompt.GenerateContentRequest;
import com.google.mlkit.genai.prompt.GenerateContentResponse;
import com.google.mlkit.genai.prompt.Generation;
import com.google.mlkit.genai.prompt.TextPart;
import com.google.mlkit.genai.prompt.java.GenerativeModelFutures;

import java.util.concurrent.TimeUnit;

/** Thin synchronous bridge used by the embedded Python advisor.
 *
 * The Python worker already runs off Android's main thread. Unsupported or
 * not-yet-ready devices return an empty string so Python can immediately try
 * the installed local Gemma model and finally its deterministic ranker.
 */
public final class NanoAdvisor {
    private static final GenerativeModelFutures MODEL = GenerativeModelFutures.from(
            Generation.INSTANCE.getClient());
    private static volatile boolean downloadRequested = false;

    private NanoAdvisor() {
    }

    /**
     * Kick off the AICore feature download at app start rather than waiting
     * for the first ranking prompt. Does nothing unless AICore is present on
     * this device and the feature is DOWNLOADABLE — there is no way to install
     * AICore itself; that is a Play Services device allowlist, not something
     * an app can request.
     */
    public static void maybeStartDownload() {
        try {
            MODEL.checkStatus().addListener(() -> {
                try {
                    int status = MODEL.checkStatus().get();
                    if (status == FeatureStatus.DOWNLOADABLE) requestDownload();
                } catch (Throwable ignored) {
                }
            }, Runnable::run);
        } catch (Throwable ignored) {
        }
    }

    public static String status() {
        try {
            int status = MODEL.checkStatus().get(4, TimeUnit.SECONDS);
            if (status == FeatureStatus.AVAILABLE) return "available";
            if (status == FeatureStatus.DOWNLOADABLE) return "downloadable";
            if (status == FeatureStatus.DOWNLOADING) return "downloading";
            return "unavailable";
        } catch (Throwable ignored) {
            return "unavailable";
        }
    }

    public static synchronized String generate(String prompt) {
        if (prompt == null || prompt.trim().isEmpty()) return "";
        try {
            int status = MODEL.checkStatus().get(4, TimeUnit.SECONDS);
            if (status == FeatureStatus.DOWNLOADABLE) {
                requestDownload();
                return "";
            }
            if (status != FeatureStatus.AVAILABLE) return "";

            GenerateContentRequest.Builder request = new GenerateContentRequest.Builder(
                    new TextPart(prompt));
            request.setTemperature(0.2f);
            request.setTopK(10);
            request.setMaxOutputTokens(700);
            GenerateContentResponse response = MODEL.generateContent(request.build())
                    .get(55, TimeUnit.SECONDS);
            if (response.getCandidates().isEmpty()) return "";
            String text = response.getCandidates().get(0).getText();
            return text == null ? "" : text.trim();
        } catch (Throwable ignored) {
            return "";
        }
    }

    private static void requestDownload() {
        if (downloadRequested) return;
        downloadRequested = true;
        try {
            MODEL.download(new DownloadCallback() {
                @Override
                public void onDownloadStarted(long bytesToDownload) {
                }

                @Override
                public void onDownloadProgress(long totalBytesDownloaded) {
                }

                @Override
                public void onDownloadCompleted() {
                }

                @Override
                public void onDownloadFailed(GenAiException error) {
                    downloadRequested = false;
                }
            });
        } catch (Throwable ignored) {
            downloadRequested = false;
        }
    }
}
