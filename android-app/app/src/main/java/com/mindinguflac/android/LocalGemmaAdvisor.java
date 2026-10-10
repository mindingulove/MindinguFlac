package com.mindinguflac.android;

import android.content.ContentResolver;
import android.content.Context;
import android.net.Uri;

import com.google.mediapipe.tasks.genai.llminference.LlmInference;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;

/** Token-free fallback backed by a Gemma MediaPipe task bundle installed by the user. */
public final class LocalGemmaAdvisor {
    private static final String MODEL_DIRECTORY = "models";
    private static final String MODEL_NAME = "gemma.task";
    private static volatile Context applicationContext;

    private LocalGemmaAdvisor() {
    }

    public static void initialize(Context context) {
        applicationContext = context.getApplicationContext();
    }

    private static File modelFile() {
        Context context = applicationContext;
        if (context == null) return null;
        return new File(new File(context.getFilesDir(), MODEL_DIRECTORY), MODEL_NAME);
    }

    public static String status() {
        File model = modelFile();
        if (model == null || !model.isFile() || model.length() < 1024 * 1024) return "not_installed";
        return "installed";
    }

    public static synchronized boolean install(ContentResolver resolver, Uri source) {
        File target = modelFile();
        if (target == null || resolver == null || source == null) return false;
        File parent = target.getParentFile();
        if (parent == null || (!parent.isDirectory() && !parent.mkdirs())) return false;
        File temporary = new File(parent, MODEL_NAME + ".partial");
        try (InputStream input = resolver.openInputStream(source);
             OutputStream output = new FileOutputStream(temporary)) {
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
            if (temporary.renameTo(target)) return true;
            try (InputStream retryInput = new FileInputStream(temporary);
                 OutputStream retryOutput = new FileOutputStream(target)) {
                while ((count = retryInput.read(buffer)) != -1) retryOutput.write(buffer, 0, count);
            }
            return target.isFile() && target.length() == copied;
        } catch (Throwable ignored) {
            return false;
        } finally {
            if (temporary.exists() && !temporary.equals(target)) temporary.delete();
        }
    }

    public static synchronized String generate(String prompt) {
        Context context = applicationContext;
        File model = modelFile();
        if (context == null || model == null || !model.isFile() || prompt == null || prompt.trim().isEmpty()) {
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
