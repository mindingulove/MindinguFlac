"""Align a music video to the song's audio by matching their soundtracks.

A music video and the album recording are the same song, but videos add
intros, outros or a cold open, so "second N of the song" is rarely "second N
of the video". Both files carry the song's audio, so the offset between them
is found by cross-correlating their onset envelopes (spectral flux), which
survives the codec, mastering, EQ and loudness differences between a lossless
album master and a YouTube upload.

Result: ``video_time = audio_time + offset``. A weak or ambiguous match is
reported as unmatched instead of guessed, and the player then keeps plain
timestamp sync.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

SAMPLE_RATE = 11025
HOP = 256                      # ~23 ms per onset frame
N_FFT = 1024
AUDIO_SECONDS = 120.0           # how much of the song to match
VIDEO_SECONDS = 190.0          # video window: allows intros up to ~70 s
MIN_AUDIO_SECONDS = 40.0       # below this the match is not trustworthy yet
MAX_INTRO_SECONDS = 70.0       # video starts this much before the song
MAX_LATE_START_SECONDS = 70.0  # video skips this much of the song's start
# Acceptance, tuned on 12 real music videos x 3 offsets plus unrelated pairs:
# accepted 29/34 correct offsets (all within 10 ms) and 0/14 wrong ones.
MIN_Z = 5.0                    # best offset vs the score at every other offset
MIN_Z_GAP = 1.5                # best vs best competing offset more than 1 s away

MEDIA_SUFFIXES = {".flac", ".m4a", ".mp3", ".mp4", ".m4v", ".webm", ".weba", ".opus",
                  ".ogg", ".oga", ".wav", ".aac", ".alac", ".mkv", ".mov", ".audio"}


def _ffmpeg() -> str:
    from native_audio import _ffmpeg_exe
    return _ffmpeg_exe()


def _on_android() -> bool:
    import os
    return os.environ.get("MINDINGUFLAC_ANDROID") == "1"


def decoder_available() -> bool:
    """ffmpeg on desktop; Android's MediaCodec (AudioPcmDecoder.java) on the phone."""
    if _on_android():
        try:
            from java import jclass  # type: ignore
            jclass("com.mindinguflac.android.AudioPcmDecoder")
            return True
        except Exception:
            return False
    return bool(_ffmpeg())


def decode_mono(path: str | Path, seconds: float, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """First ``seconds`` of a file's audio as mono float32 at SAMPLE_RATE.

    Reads a partially downloaded file too (decoding stops at what exists).
    """
    if _on_android():
        from java import jclass  # type: ignore
        decoder = jclass("com.mindinguflac.android.AudioPcmDecoder")
        return np.frombuffer(bytes(decoder.decodeMono(str(path), float(seconds), sample_rate)), dtype="<f4")
    ffmpeg = _ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required for video sync")
    command = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-t", f"{seconds:.2f}",
               "-i", str(path), "-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "f32le", "pipe:1"]
    result = subprocess.run(command, capture_output=True, timeout=60,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    samples = np.frombuffer(result.stdout, dtype=np.float32)
    if not samples.size and result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", "replace").strip()[-300:] or "could not decode audio")
    return samples


def _log_spectrogram(samples: np.ndarray) -> np.ndarray:
    if samples.size < N_FFT * 2:
        return np.zeros((0, N_FFT // 2 + 1), dtype=np.float32)
    frames = 1 + (samples.size - N_FFT) // HOP
    index = np.arange(N_FFT)[None, :] + HOP * np.arange(frames)[:, None]
    spectrum = np.abs(np.fft.rfft(samples[index] * np.hanning(N_FFT).astype(np.float32), axis=1))
    # Log compression makes the match insensitive to loudness and mastering.
    return np.log1p(100.0 * spectrum).astype(np.float32)


def _zscore(values: np.ndarray, axis: int = 0) -> np.ndarray:
    std = values.std(axis=axis, keepdims=True)
    return np.where(std > 0, (values - values.mean(axis=axis, keepdims=True)) / np.where(std > 0, std, 1), 0.0)


def features(samples: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(onset envelope, band-energy contours) per ~23 ms frame.

    Onsets pin the offset to a few milliseconds but repeat every bar, so on
    their own a match one or two bars off scores almost as well. Band energy
    over time follows the song's structure and vocal lines, which tells one
    verse/bar from the next; z-scoring each band cancels static EQ.
    """
    spectrum = _log_spectrogram(samples)
    if not spectrum.shape[0]:
        return np.zeros(0, dtype=np.float32), np.zeros((0, 0), dtype=np.float32)
    flux = np.maximum(np.diff(spectrum, axis=0), 0.0).sum(axis=1)
    window = 43  # ~1 s: remove the slow loudness contour, keep onset detail
    flux = np.maximum(flux - np.convolve(flux, np.ones(window) / window, mode="same"), 0.0)
    onsets = _zscore(flux).astype(np.float32)
    edges = np.unique(np.geomspace(4, spectrum.shape[1] - 1, 13).astype(int))
    bands = np.stack([spectrum[1:, lo:hi].mean(axis=1) for lo, hi in zip(edges[:-1], edges[1:])], axis=1)
    smooth = 9  # ~0.2 s
    kernel = np.ones(smooth) / smooth
    bands = np.stack([np.convolve(bands[:, i], kernel, mode="same") for i in range(bands.shape[1])], axis=1)
    return onsets, _zscore(bands).astype(np.float32)


def _correlate(audio_env: np.ndarray, video_env: np.ndarray, min_lag: int, max_lag: int):
    """Normalised correlation for each lag where video[t + lag] ~ audio[t]."""
    size = 1
    while size < audio_env.size + video_env.size:
        size *= 2
    spectrum = np.fft.rfft(video_env, size) * np.conj(np.fft.rfft(audio_env, size))
    raw = np.fft.irfft(spectrum, size)
    lags = np.arange(min_lag, max_lag + 1)
    values = raw[lags % size]
    # Divide by the overlap at each lag so short overlaps cannot win on luck.
    overlap = np.minimum(audio_env.size, video_env.size - lags) - np.maximum(0, -lags)
    overlap = np.clip(overlap, 1, None)
    return lags, values / overlap, overlap


def match_features(audio_features, video_features) -> dict:
    """Find where the song's audio sits inside the video's soundtrack.

    Every candidate offset is scored by how well onsets plus band energy line
    up. The best offset is accepted only if it stands out from the score at
    all other offsets (robust z-score) AND clearly beats the best competing
    offset more than 1 s away. Loop-based tracks whose bars repeat exactly,
    and unrelated songs, fail the second test, so they are reported as
    unmatched instead of synced to the wrong bar.
    """
    frame_seconds = HOP / SAMPLE_RATE
    audio_onsets, audio_bands = audio_features
    video_onsets, video_bands = video_features
    if not audio_onsets.size or not video_onsets.size:
        return {"matched": False, "reason": "no usable audio"}
    min_overlap = int(MIN_AUDIO_SECONDS * 0.75 / frame_seconds)
    min_lag = -int(MAX_LATE_START_SECONDS / frame_seconds)
    max_lag = int(MAX_INTRO_SECONDS / frame_seconds)
    lags, scores, overlap = _correlate(audio_onsets, video_onsets, min_lag, max_lag)
    band_scores = sum(_correlate(audio_bands[:, band], video_bands[:, band], min_lag, max_lag)[1]
                      for band in range(audio_bands.shape[1])) / audio_bands.shape[1]
    scores = scores + band_scores
    valid = overlap >= min_overlap
    if valid.sum() < 10:
        return {"matched": False, "reason": "not enough overlapping audio"}
    lags, scores = lags[valid], scores[valid]
    median = float(np.median(scores))
    spread = float(np.median(np.abs(scores - median))) * 1.4826 or 1e-9
    best = int(np.argmax(scores))
    z_best = (float(scores[best]) - median) / spread
    guard = int(1.0 / frame_seconds)
    rest = np.concatenate([scores[:max(0, best - guard)], scores[best + guard + 1:]])
    z_second = (float(rest.max()) - median) / spread if rest.size else 0.0
    refined = float(lags[best])
    if 0 < best < len(scores) - 1:
        left, mid, right = scores[best - 1], scores[best], scores[best + 1]
        denominator = left - 2 * mid + right
        if denominator < 0:
            refined += 0.5 * (left - right) / denominator
    matched = z_best >= MIN_Z and (z_best - z_second) >= MIN_Z_GAP
    return {
        "matched": bool(matched),
        "offset": round(float(refined * frame_seconds), 3),
        "confidence": round(z_best, 2),
        "margin": round(z_best - z_second, 2),
        **({} if matched else {"reason": "soundtracks do not match clearly"}),
    }


def compute_offset(audio_path: str | Path, video_path: str | Path) -> dict:
    """Offset (seconds) to add to the song position to get the video position."""
    audio = decode_mono(audio_path, AUDIO_SECONDS)
    if audio.size < MIN_AUDIO_SECONDS * SAMPLE_RATE:
        return {"matched": False, "pending": True, "reason": "not enough audio downloaded yet"}
    video = decode_mono(video_path, VIDEO_SECONDS)
    if video.size < MIN_AUDIO_SECONDS * SAMPLE_RATE:
        return {"matched": False, "reason": "video has no usable soundtrack"}
    return {**match_features(features(audio), features(video)),
            "audio_seconds": audio.size / SAMPLE_RATE, "video_seconds": video.size / SAMPLE_RATE}
