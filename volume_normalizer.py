"""Playback-only, gated RMS level matching (not an offline LUFS scan).

A 400 ms gate excludes silence and passages >10 dB below the running track
level. The integrated estimate preserves song dynamics; gain settles smoothly,
boost is limited to 12 dB, and a linked-channel peak ceiling prevents clipping.
"""
from __future__ import annotations

import math


class VolumeNormalizer:
    def __init__(self):
        self.reset()

    def reset(self):
        self.energy = 0.0
        self.frames = 0
        self.window_energy = 0.0
        self.window_frames = 0
        self.gain = 1.0
        self.target = 1.0

    def process(self, pcm, sample_rate: int, enabled: bool):
        if not enabled:
            self.reset()
            return pcm
        import numpy as np

        # Integrate fixed windows so decoder/output block sizes do not change
        # the measurement. Channels are averaged, not summed (stereo-linked).
        window = max(1, round(sample_rate * 0.4))
        offset = 0
        while offset < len(pcm):
            count = min(window - self.window_frames, len(pcm) - offset)
            segment = pcm[offset:offset + count]
            self.window_energy += float(np.sum(np.square(segment, dtype=np.float64))) / pcm.shape[1]
            self.window_frames += count
            offset += count
            if self.window_frames == window:
                mean = self.window_energy / window
                gate = max(1e-5, (self.energy / self.frames) * 0.1 if self.frames else 0)
                if mean > gate:
                    self.energy += self.window_energy
                    self.frames += window
                    self.target = max(10 ** (-24 / 20), min(10 ** (12 / 20),
                                      10 ** (-18 / 20) / math.sqrt(self.energy / self.frames)))
                self.window_energy = 0.0
                self.window_frames = 0
        peak = float(np.max(np.abs(pcm))) if pcm.size else 0.0
        ceiling = 0.98 / peak if peak > 0 else float('inf')
        start = min(self.gain, ceiling)
        end = min(self.target + (start - self.target) * math.exp(-len(pcm) / (sample_rate * 0.5)), ceiling)
        self.gain = end
        return pcm * np.linspace(start, end, len(pcm), dtype=np.float32)[:, None]
