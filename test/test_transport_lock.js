const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../static/app.js'), 'utf8');
function section(start, end) {
  const index = source.indexOf(start);
  assert.notEqual(index, -1, start);
  return source.slice(index, source.indexOf(end, index));
}
const icon = {};
const button = { querySelector: () => icon, setAttribute: () => {} };
const state = { nativeAudio: { active: false }, playbackRequestId: 1, currentTrack: { title: 'Song' }, nativeAudioStart: null };
const context = vm.createContext({
  console, state, $: id => id === 'playPause' ? button : { paused: true }, IS_ANDROID: true,
  renderPlayerStatusIcon: () => {}, publishDockPlayingState: () => {}, persistPlaybackSnapshot: () => {},
  isNativeAudioSelected: () => true, isMonochromeDirectStreamUrl: () => true,
  nativeAudioVolume: () => 1, _nativeAudioDeviceUid: '', _outputSwitchesInFlight: 1,
  setPlayerStatus: () => {}, setPlayerStatusIcon: () => {}, updateMediaSession: () => {},
  updateListeningSessionPosition: () => {}, ensureOutputDisconnectListener: () => {},
  followAudioWithVideo: () => {}, updateLyricsPosition: () => {}, audiblePlaybackSeconds: () => 0, maybePrefetchUpcomingTracks: () => {},
  clearInterval: () => {}, startNativeAudioPolling: () => {},
});
vm.runInContext(section('function playbackTransportBusy()', 'let _lastDockPlayingState'), context);
vm.runInContext(section('async function startNativeAudio(', '// Monochrome answers repeated requests'), context);
function sync() { vm.runInContext('syncPlayPauseButton()', context); return button.disabled; }

(async () => {
  state.audioBuffering = true;
  assert.equal(sync(), true, 'browser buffering locks desktop and phone');
  state.audioBuffering = false;
  state.nativeAudio = { active: true, stream_url: 'https://tracks.monochrome.st/track/1', playing: false, stream_phase: 'buffering', buffering: true };
  assert.equal(sync(), true, 'ExoPlayer buffering locks even after shared flag is cleared');
  state.nativeAudio = { ...state.nativeAudio, playing: true, buffering: false, stream_phase: 'playing' };
  assert.equal(sync(), false, 'confirmed native playback unlocks');
  state.nativeAudio = { ...state.nativeAudio, playing: false, buffering: true, stream_phase: 'buffering' };
  state.manualPauseRequested = true;
  assert.equal(sync(), false, 'a user-paused player remains resumable');
  state.manualPauseRequested = false;
  state.nativeAudio = { active: false };

  let rejectStart;
  context.api = () => new Promise((resolve, reject) => { rejectStart = reject; });
  const failedStart = vm.runInContext('startNativeAudio("", state.currentTrack, 1, 0, "https://tracks.monochrome.st/track/1")', context);
  // Simulate an old WebView/stop callback clearing the shared startup flags.
  state.audioBuffering = false;
  state.nativeAudioStarting = false;
  assert.equal(sync(), true, 'in-flight native initialization keeps the lock');
  rejectStart(new Error('Network unavailable'));
  await assert.rejects(failedStart, /Network unavailable/);
  assert.equal(sync(), false, 'a failed start releases the lock for retry');

  let poll;
  context.setInterval = callback => { poll = callback; return 1; };
  context.syncNativeAudioUi = () => sync();
  vm.runInContext(section('function startNativeAudioPolling(', 'function syncNativeAudioUi('), context);
  state.nativeAudio = { active: true, stream_url: 'https://tracks.monochrome.st/track/1' };
  context.api = async () => ({ playing: false, buffering: true, stream_phase: 'buffering' });
  vm.runInContext('startNativeAudioPolling(1)', context);
  await poll();
  assert.equal(button.disabled, true);
  assert.equal(state.nativeAudio.buffering, true);
  context.api = async () => ({ playing: true, buffering: false, stream_phase: 'playing', position: 1 });
  await poll();
  assert.equal(button.disabled, false);
  console.log('Browser/native buffering, Android status polling, startup race and failed-start retry lock checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
