const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
let Processor;
vm.runInNewContext(fs.readFileSync('static/volume_normalizer.js', 'utf8'), {
  AudioWorkletProcessor: class { constructor() { this.port = {}; } },
  sampleRate: 48000,
  registerProcessor: (_, cls) => { Processor = cls; },
});
function render(amplitude, volume = 1) {
  const processor = new Processor();
  processor.port.onmessage({ data: { enabled: true, volume } });
  let energy = 0, frames = 0;
  for (let offset = 0; offset < 48000 * 5; offset += 128) {
    const input = Float32Array.from({ length: 128 }, (_, i) => amplitude * volume * Math.sin(2 * Math.PI * 440 * (offset + i) / 48000));
    const output = new Float32Array(128);
    processor.process([[input]], [[output]]);
    if (offset >= 48000 * 4) for (const sample of output) { energy += sample * sample; frames++; }
  }
  return { rms: Math.sqrt(energy / frames), processor };
}
const quiet = render(0.05), loud = render(0.7), lowered = render(0.7, 0.25);
assert.ok(Math.abs(20 * Math.log10(quiet.rms / loud.rms)) < 0.1, 'songs should match');
assert.ok(Math.abs(20 * Math.log10(loud.rms) + 18) < 0.1, 'target should be -18 dBFS RMS');
assert.ok(Math.abs(lowered.rms / loud.rms - 0.25) < 0.001, 'slider must remain effective');
const p = quiet.processor;
p.port.onmessage({ data: { reset: true } });
assert.equal(p.frames, 0);
assert.equal(p.gain, 1);
p.port.onmessage({ data: { enabled: false } });
const input = new Float32Array([0, -0.5, 0.8]), output = new Float32Array(3);
p.process([[input]], [[output]]);
assert.deepEqual(output, input, 'disabled should be exact bypass');
p.port.onmessage({ data: { enabled: true, volume: 0 } });
const muted = new Float32Array(128), mutedOutput = new Float32Array(128);
p.process([[muted]], [[mutedOutput]]);
assert.deepEqual(mutedOutput, muted, 'mute should remain silent');
console.log('Volume normalization: level matching, volume, reset, bypass and mute passed.');
