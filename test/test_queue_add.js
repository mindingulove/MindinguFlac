const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../static/app.js'), 'utf8');
function section(start, end) {
  return source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start)));
}
const t = title => ({ title });
const context = vm.createContext({
  console, Math,
  state: {},
  $: () => ({ hidden: true }),
  trackKey: track => track.title,
  refreshQueuePanel: () => {}, updateSidebarNextQueue: () => {},
  prefetchNextTracks: async () => {},
});
vm.runInContext(section('function getQueueIndex()', 'function currentQueueOrderKey('), context);
vm.runInContext(section('function queueInsertionPoint(', '$("ctxAddQueue")'), context);
const titles = list => list.map(track => track.title).join(',');

// Added songs play next, in the order added, ahead of the rest of the album.
context.state = { queue: ['A', 'B', 'C', 'D'].map(t), queueIndex: 1, currentTrack: t('B'), originalQueue: null };
vm.runInContext('enqueueNext([{ title: "X" }])', context);
vm.runInContext('enqueueNext([{ title: "Y" }, { title: "Z" }])', context);
assert.equal(titles(context.state.queue), 'A,B,X,Y,Z,C,D');

// Once the queued songs have played, a new one goes right after the current song.
context.state.queueIndex = 5;
context.state.currentTrack = t('C');
vm.runInContext('enqueueNext([{ title: "W" }])', context);
assert.equal(titles(context.state.queue), 'A,B,X,Y,Z,C,W,D');

// The shuffle's original order gets them after the current song too.
context.state = { queue: ['C', 'A', 'B'].map(t), queueIndex: 0, currentTrack: t('C'), originalQueue: ['A', 'B', 'C', 'D'].map(t) };
vm.runInContext('enqueueNext([{ title: "X" }])', context);
assert.equal(titles(context.state.queue), 'C,X,A,B');
assert.equal(titles(context.state.originalQueue), 'A,B,C,X,D');

// Playing a song outside any queue: the queue starts with it, then the added song.
context.state = { queue: [], queueIndex: -1, currentTrack: t('Solo'), originalQueue: null };
vm.runInContext('enqueueNext([{ title: "X" }])', context);
assert.equal(titles(context.state.queue), 'Solo,X');
assert.equal(context.state.queueIndex, 0);
console.log('queue add tests passed');
