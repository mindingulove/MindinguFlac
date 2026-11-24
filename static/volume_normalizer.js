/* Playback-only gated RMS matching. Keep constants aligned with volume_normalizer.py. */
class VolumeNormalizerProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.enabled = false;
    this.volume = 1;
    this.reset();
    this.port.onmessage = ({ data }) => {
      if (data.reset || (data.enabled !== undefined && data.enabled !== this.enabled)) this.reset();
      if (data.enabled !== undefined) this.enabled = data.enabled;
      if (data.volume !== undefined) this.volume = data.volume;
    };
  }
  reset() {
    this.energy = this.frames = this.windowEnergy = this.windowFrames = 0;
    this.gain = this.target = 1;
  }
  process(inputs, outputs) {
    const input = inputs[0], output = outputs[0];
    if (!input?.length || !output?.length) return true;
    const count = input[0].length;
    if (!this.enabled || this.volume <= 0.0001) {
      for (let c = 0; c < output.length; c++) output[c].set(input[c] || input[0]);
      return true;
    }
    let peak = 0;
    for (let i = 0; i < count; i++) {
      let energy = 0;
      for (const channel of input) {
        // HTMLMediaElement volume is applied before its MediaElementSource.
        const sample = channel[i] / this.volume;
        energy += sample * sample;
        peak = Math.max(peak, Math.abs(sample));
      }
      this.windowEnergy += energy / input.length;
      if (++this.windowFrames >= Math.round(sampleRate * 0.4)) {
        const mean = this.windowEnergy / this.windowFrames;
        const gate = Math.max(1e-5, this.frames ? this.energy / this.frames * 0.1 : 0);
        if (mean > gate) {
          this.energy += this.windowEnergy;
          this.frames += this.windowFrames;
          this.target = Math.max(10 ** (-24 / 20), Math.min(10 ** (12 / 20),
            10 ** (-18 / 20) / Math.sqrt(this.energy / this.frames)));
        }
        this.windowEnergy = this.windowFrames = 0;
      }
    }
    const ceiling = peak ? 0.98 / peak : Infinity;
    const start = Math.min(this.gain, ceiling);
    const end = Math.min(this.target + (start - this.target) * Math.exp(-count / (sampleRate * 0.5)), ceiling);
    for (let c = 0; c < output.length; c++) {
      const source = input[c] || input[0];
      for (let i = 0; i < count; i++) output[c][i] = source[i] * (start + (end - start) * i / Math.max(1, count - 1));
    }
    this.gain = end;
    return true;
  }
}
registerProcessor("volume-normalizer", VolumeNormalizerProcessor);
