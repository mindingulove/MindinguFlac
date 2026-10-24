"""Align timed lyric lines to independently recognized buffered vocals.

Recognition is offline. Text is never supplied as a prompt: only observed
phrases agreeing across several lines may move the provider timestamps.
"""
from __future__ import annotations

import ctypes
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import threading
import unicodedata

import numpy as np

SAMPLE_RATE = 16000
AUDIO_SECONDS = 120
MIN_SECONDS = 55
MAX_OFFSET = 75
_LOCK = threading.Lock()
_ENGINE = None


def _words(text):
    text = unicodedata.normalize('NFKD', text.casefold())
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return re.findall(r"[^\W_]+(?:['’][^\W_]+)*", text, re.UNICODE)


def _normalized(text):
    return [word.replace('’', '').replace("'", '') for word in _words(text)]


def parse_lines(lyrics: str) -> list[dict]:
    offset = re.search(r'\[offset:([+-]?\d+)\]', lyrics, re.I)
    # LRC offsets advance timestamps: a positive tag makes text earlier.
    advance = int(offset[1]) / 1000 if offset else 0
    result = []
    for line in lyrics.splitlines():
        stamps = re.findall(r'\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]', line)
        if not stamps:
            stamps = re.findall(r'<(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?>', line)[:1]
        text = re.sub(r'\[[^\]]*\]|<\d{1,2}:\d{2}(?:[.:]\d{1,3})?>', '', line).strip()
        words = _normalized(text)
        for minute, second, fraction in stamps:
            time = int(minute) * 60 + int(second) + (int(fraction) / 10 ** len(fraction) if fraction else 0) - advance
            if words:
                result.append({'time': time, 'words': words})
    return sorted(result, key=lambda row: row['time'])


def model_path() -> Path:
    if os.environ.get('MINDINGUFLAC_ANDROID') == '1':
        import android_runtime
        return Path(android_runtime.__file__).parent / 'lyrics_models/ggml-base-q5_1.bin'
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    return root / 'assets/lyrics-alignment/ggml-base-q5_1.bin'


def _library_path() -> Path:
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    name = 'lyrics_whisper.dll' if os.name == 'nt' else 'liblyrics_whisper.dylib'
    paths = [root / name, root / 'build/lyrics-whisper/macos' / name,
             root / 'build/lyrics-whisper/windows/Release' / name]
    return next((p for p in paths if p.is_file()), paths[0])


def available() -> bool:
    if not model_path().is_file():
        return False
    if os.environ.get('MINDINGUFLAC_ANDROID') == '1':
        try:
            from java import jclass
            jclass('com.mindinguflac.android.LyricsAlignment')
            return True
        except Exception:
            return False
    return _library_path().is_file()


def recognize(pcm: np.ndarray) -> list[dict]:
    global _ENGINE
    pcm = np.ascontiguousarray(pcm, dtype='<f4')
    with _LOCK:
        if os.environ.get('MINDINGUFLAC_ANDROID') == '1':
            from java import jclass
            result = jclass('com.mindinguflac.android.LyricsAlignment').transcribeNative(str(model_path()), pcm.tobytes())
            data = json.loads(bytes(result).decode('utf-8')) if result is not None else {}
        else:
            if _ENGINE is None:
                _ENGINE = ctypes.CDLL(str(_library_path()))
                _ENGINE.lyrics_transcribe.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_float), ctypes.c_int]
                _ENGINE.lyrics_transcribe.restype = ctypes.c_void_p
                _ENGINE.lyrics_free.argtypes = [ctypes.c_void_p]
            result = _ENGINE.lyrics_transcribe(os.fsencode(model_path()), pcm.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), len(pcm))
            if not result:
                raise RuntimeError('Offline lyrics recognition failed')
            try:
                data = json.loads(ctypes.string_at(result).decode('utf-8'))
            finally:
                _ENGINE.lyrics_free(result)
    if data.get('error'):
        raise RuntimeError(data['error'])
    return data.get('words') or []


def align_words(lyrics: str, observed: list[dict]) -> dict:
    """Robust phrase consensus: audio_time = lyric_time * scale + offset."""
    lines = parse_lines(lyrics)
    tokens = []
    for row in observed:
        words = _normalized(str(row.get('text') or ''))
        tokens.extend((word, float(row.get('start') or 0),
                       float(row.get('confidence') or 0) if row.get('timing_confident', True) else 0) for word in words)
    anchors = []
    for index, line in enumerate(lines):
        reference = line['words']
        length = len(reference)
        if length < 3 or sum(len(w) for w in reference) < 9:
            continue
        for j, token in enumerate(tokens):
            if token[0] != reference[0] or token[2] <= 0 or abs(token[1] - line['time']) > MAX_OFFSET:
                continue
            window = tokens[j:j + length + 3]
            blocks = difflib.SequenceMatcher(None, reference, [w[0] for w in window], autojunk=False).get_matching_blocks()
            pairs = [(block.a + k, block.b + k) for block in blocks for k in range(block.size)]
            if not pairs or pairs[0] != (0, 0):
                continue
            # Validate the whole phrase, tolerating recognition substitutions
            # without inventing a start time for a missing first word.
            matched = len(pairs)
            coverage = matched / max(length, pairs[-1][1] + 1)
            confidence = sum(window[y][2] for _, y in pairs) / matched
            if matched >= min(4, length) and coverage >= 0.7 and confidence >= 0.55:
                anchors.append((index, line['time'], token[1], tuple(reference)))
    if len(anchors) < 4:
        return {'matched': False, 'reason': 'not enough recognized lyric phrases'}

    def consensus(delta):
        near = [a for a in anchors if abs((a[2] - a[1]) - delta) <= 1.25]
        # Each audio phrase and lyric line may support a hypothesis only once.
        chosen, used_line, used_audio = [], set(), set()
        for a in sorted(near, key=lambda a: abs((a[2] - a[1]) - delta)):
            if a[0] not in used_line and a[2] not in used_audio:
                chosen.append(a); used_line.add(a[0]); used_audio.add(a[2])
        return chosen

    groups = sorted((consensus(a[2] - a[1]) for a in anchors), key=len, reverse=True)
    best = groups[0]
    offset = float(np.median([a[2] - a[1] for a in best]))
    second = max((len(g) for g in groups if abs(np.median([a[2] - a[1] for a in g]) - offset) > 3), default=0)
    span = max(a[1] for a in best) - min(a[1] for a in best)
    if len(best) < 4 or len({a[3] for a in best}) < 3 or span < 25 or len(best) < second + 2:
        return {'matched': False, 'reason': 'ambiguous or short lyric phrase agreement'}
    # A correction must explain most independently recognized line starts.
    eligible = {a[0] for a in anchors if min(b[1] for b in best) <= a[1] <= max(b[1] for b in best)}
    if len(best) / max(1, len(eligible)) < 0.6:
        return {'matched': False, 'reason': 'recording edits do not share consistent lyric timing'}
    residual = float(np.median([abs(a[2] - a[1] - offset) for a in best]))
    return {'matched': True, 'offset': round(offset, 3), 'scale': 1.0,
            'anchors': len(best), 'span': round(span, 2), 'residual': round(residual, 3)}


def compute_alignment(audio_path: Path, lyrics: str) -> dict:
    from video_sync import decode_mono
    pcm = decode_mono(audio_path, AUDIO_SECONDS, sample_rate=SAMPLE_RATE)
    seconds = len(pcm) / SAMPLE_RATE
    if seconds < MIN_SECONDS:
        return {'matched': False, 'pending': True, 'audio_seconds': seconds}
    return {**align_words(lyrics, recognize(pcm)), 'audio_seconds': seconds}
