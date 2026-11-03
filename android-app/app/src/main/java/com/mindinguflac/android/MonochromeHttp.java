package com.mindinguflac.android;

import org.json.JSONObject;

import java.io.IOException;
import java.io.InputStream;
import java.util.Arrays;
import java.util.Iterator;
import java.util.concurrent.TimeUnit;

import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;

/**
 * Monochrome downloads over OkHttp, the client ExoPlayer streams with.
 *
 * Python's native_audio._MonochromeFetch drives this through Chaquopy for
 * offline downloads. Without curl_cffi on the phone its fallback was httpx,
 * whose Python TLS handshake (under a Safari User-Agent) Monochrome answers
 * with 403 while the player's OkHttp requests play fine. Each call is one
 * plain request; retry policy stays in Python.
 */
public final class MonochromeHttp {
    private static final OkHttpClient CLIENT = new OkHttpClient.Builder()
            .connectTimeout(20, TimeUnit.SECONDS)
            .readTimeout(180, TimeUnit.SECONDS)
            .build();

    private MonochromeHttp() {}

    /** Open a GET with the given JSON headers; the caller must close the response. */
    public static Response get(String url, String headersJson) throws Exception {
        Request.Builder request = new Request.Builder().url(url).get();
        if (headersJson != null && !headersJson.isEmpty()) {
            JSONObject headers = new JSONObject(headersJson);
            Iterator<String> keys = headers.keys();
            while (keys.hasNext()) {
                String key = keys.next();
                request.header(key, headers.getString(key));
            }
        }
        return CLIENT.newCall(request.build()).execute();
    }

    /** Up to {@code max} bytes from the body stream, or null at the end. */
    public static byte[] read(InputStream in, int max) throws IOException {
        byte[] buffer = new byte[max];
        int count = in.read(buffer);
        if (count < 0) return null;
        return count == buffer.length ? buffer : Arrays.copyOf(buffer, count);
    }
}
