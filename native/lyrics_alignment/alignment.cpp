// Independent speech timestamps for aligning provider lyrics to playing audio.
// No microphone, network calls, or lyric prompt (which could bias recognition).
#include "whisper.h"
#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#ifdef __ANDROID__
#include <jni.h>
#endif
#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT __attribute__((visibility("default")))
#endif

static std::mutex recognition_mutex;
static std::string quoted(const char *text) {
    std::ostringstream out;
    out << '"';
    for (const unsigned char *p = (const unsigned char *)text; *p; ++p) {
        if (*p == '"' || *p == '\\') out << '\\' << *p;
        else if (*p == '\n') out << "\\n";
        else if (*p == '\r') out << "\\r";
        else if (*p == '\t') out << "\\t";
        else if (*p >= 32) out << *p;
    }
    out << '"';
    return out.str();
}
static std::string transcribe(const char *model, const float *pcm, int count) {
    std::lock_guard<std::mutex> guard(recognition_mutex);
    whisper_log_set([](enum ggml_log_level, const char *, void *) {}, nullptr);
    auto config = whisper_context_default_params();
    config.use_gpu = false;
    config.flash_attn = false;
    config.dtw_token_timestamps = true;
    config.dtw_aheads_preset = WHISPER_AHEADS_BASE;
    config.dtw_mem_size = 128 * 1024 * 1024;
    auto *ctx = whisper_init_from_file_with_params(model, config);
    if (!ctx) return "{\"error\":\"Could not load lyrics alignment model\"}";
    auto params = whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
    params.n_threads = std::max(1, std::min(4, (int)std::thread::hardware_concurrency() - 1));
    params.print_realtime = false; params.print_progress = false;
    params.print_timestamps = false; params.print_special = false;
    params.translate = false; params.no_context = true;
    params.language = "auto";
    params.token_timestamps = true; params.split_on_word = true; params.max_len = 1;
    params.suppress_nst = true;
    std::ostringstream out;
    if (whisper_full(ctx, params, pcm, count) != 0) {
        whisper_free(ctx);
        return "{\"error\":\"Could not recognize buffered vocals\"}";
    }
    out << "{\"words\":[";
    bool first = true;
    for (int i = 0; i < whisper_full_n_segments(ctx); ++i) {
        const char *text = whisper_full_get_segment_text(ctx, i);
        if (!text || !*text) continue;
        float probability = 0; int tokens = 0; int64_t vocal_start = -1;
        for (int j = 0; j < whisper_full_n_tokens(ctx, i); ++j) {
            auto token = whisper_full_get_token_data(ctx, i, j);
            if (token.id < whisper_token_eot(ctx)) {
                probability += token.p; ++tokens;
                if (token.t_dtw >= 0 && (vocal_start < 0 || token.t_dtw < vocal_start)) vocal_start = token.t_dtw;
            }
        }
        if (!tokens) continue;
        if (!first) out << ',';
        first = false;
        out << "{\"text\":" << quoted(text)
            << ",\"start\":" << (vocal_start >= 0 ? vocal_start : whisper_full_get_segment_t0(ctx, i)) / 100.0
            << ",\"end\":" << std::max(vocal_start, whisper_full_get_segment_t1(ctx, i)) / 100.0
            << ",\"timing_confident\":" << (vocal_start >= 0 ? "true" : "false")
            << ",\"confidence\":" << probability / tokens << '}';
    }
    out << "]}";
    whisper_free(ctx);
    return out.str();
}
extern "C" EXPORT char *lyrics_transcribe(const char *model, const float *pcm, int count) {
    if (!model || !pcm || count <= 0 || count > 16000 * 180) return nullptr;
    try {
        std::string result = transcribe(model, pcm, count);
        char *buffer = (char *)std::malloc(result.size() + 1);
        if (buffer) std::memcpy(buffer, result.c_str(), result.size() + 1);
        return buffer;
    } catch (...) { return nullptr; }
}
extern "C" EXPORT void lyrics_free(void *buffer) { std::free(buffer); }
#ifdef __ANDROID__
extern "C" JNIEXPORT jbyteArray JNICALL
Java_com_mindinguflac_android_LyricsAlignment_transcribeNative(JNIEnv *env, jclass, jstring model, jbyteArray pcm) {
    const char *path = env->GetStringUTFChars(model, nullptr);
    jsize size = env->GetArrayLength(pcm);
    jbyte *samples = env->GetByteArrayElements(pcm, nullptr);
    char *result = lyrics_transcribe(path, reinterpret_cast<float *>(samples), size / 4);
    env->ReleaseByteArrayElements(pcm, samples, JNI_ABORT);
    env->ReleaseStringUTFChars(model, path);
    if (!result) return nullptr;
    jbyteArray output = env->NewByteArray(std::strlen(result));
    if (output) env->SetByteArrayRegion(output, 0, std::strlen(result), reinterpret_cast<jbyte *>(result));
    lyrics_free(result);
    return output;
}
#endif
