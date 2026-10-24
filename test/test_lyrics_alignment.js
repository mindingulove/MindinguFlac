const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../static/app.js'),'utf8');
const section=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b,source.indexOf(a)));
const state={lyrics:{lines:[{time:10},{time:20},{time:30}],autoOffset:5,syncOffset:.25}};
const context=vm.createContext({state});
vm.runInContext(section('function currentLyricsIndex(', 'function renderLyricsContent('),context);
assert.equal(context.currentLyricsIndex(15),-1);
assert.equal(context.currentLyricsIndex(15.25),0);
assert.equal(context.currentLyricsIndex(25.25),1);
vm.runInContext(section('function parseLrcTimestamp(', 'function proxiedImageUrl('),context);
assert.equal(context.parseLyrics('[offset:500]\n[00:10.00]A lyric line')[0].time,9.5);
assert.ok(source.includes('updateLyricsPosition(audiblePlaybackSeconds());'));
console.log('Measured lyric offset, manual fine tuning, LRC offset tags and audible native clock checks passed');
const pending=[];
const asyncState={currentTrack:{title:'first'},currentLibraryPath:'',currentStreamUrl:'one',nativeAudio:{},
  lyrics:{open:true,lines:[{time:1}],alignmentKey:'',alignmentStatus:'',alignmentAttempts:0,autoOffset:0,syncOffset:0}};
let body={lyrics:'first lyrics',stream_url:'one'};
const polling=vm.createContext({state:asyncState,clearTimeout:()=>{},setTimeout:()=>1,
  lyricsAlignmentBody:()=>body,renderLyricsAlignment:()=>{},updateLyricsPosition:()=>{},audiblePlaybackSeconds:()=>1,
  api:()=>new Promise(resolve=>pending.push(resolve))});
vm.runInContext(section('async function refreshLyricsAlignment(', 'function prefetchLyricsForTrack('),polling);
(async()=>{
  const first=polling.refreshLyricsAlignment();
  body={lyrics:'second lyrics',stream_url:'two'};asyncState.currentTrack={title:'second'};
  const second=polling.refreshLyricsAlignment();
  pending[1]({status:'matched',offset:2,manual_offset:.25});await second;
  pending[0]({status:'matched',offset:99,manual_offset:99});await first;
  assert.equal(asyncState.lyrics.autoOffset,2);assert.equal(asyncState.lyrics.syncOffset,.25);
  console.log('Stale alignment responses cannot overwrite another recording');
})().catch(error=>{console.error(error);process.exitCode=1;});

context.state.nativeAudio={active:true,position:10,output_latency:.8};
context.currentPlaybackSeconds=()=>10;
context.browserOutputLatencySeconds=()=>0;
vm.runInContext(section('function audiblePlaybackSeconds(', '// Keep the side video locked'),context);
assert.equal(context.audiblePlaybackSeconds(),9.2);
context.state.nativeAudio.active=false;
assert.equal(context.audiblePlaybackSeconds(),10);

const clock=vm.createContext({_activeSinkId:"",_audioSrcNode:{},_audioCtx:{state:'running',currentTime:100,
 getOutputTimestamp:()=>({contextTime:99,performanceTime:1000}),outputLatency:.35,baseLatency:.05},performance:{now:()=>1200}});
vm.runInContext(section('function browserOutputLatencySeconds(', 'function isPlaybackVisiblyActive('),clock);
assert.ok(Math.abs(clock.browserOutputLatencySeconds()-.8)<1e-6);
clock._audioCtx.getOutputTimestamp=()=>({contextTime:0,performanceTime:0});
assert.ok(Math.abs(clock.browserOutputLatencySeconds()-.4)<1e-6);
clock._audioCtx.state='suspended';assert.equal(clock.browserOutputLatencySeconds(),0);
console.log('Browser output timestamps and latency fallback compensate the audible clock');
const routeCalls=[];
function ClockConstructor() {}
ClockConstructor.prototype.getOutputTimestamp=()=>({});
const suspended={state:'suspended',resume:()=>new Promise(()=>{})};
const setup=vm.createContext({window:{AudioContext:ClockConstructor,location:{origin:'http://127.0.0.1',href:'http://127.0.0.1/index.html'}},
  URL,_ensureAudioContext:route=>{routeCalls.push(route);return suspended;},setTimeout:callback=>{callback();return 1;}});
vm.runInContext(section('async function prepareBrowserAudioClock(', 'function browserOutputLatencySeconds('),setup);
setup.prepareBrowserAudioClock({src:'http://127.0.0.1/api/monochrome/stream'}).then(()=>{
  assert.deepEqual(routeCalls,[false]);
  console.log('A suspended audio context cannot block playback or capture its output');
}).catch(error=>{console.error(error);process.exitCode=1;});
const events={};
const followState={lyrics:{open:true,synced:true,lastScrollAt:0}};
const follow=vm.createContext({state:followState,Date,$:()=>({addEventListener:(name,fn)=>events[name]=fn}),
  setLyricsSynced:value=>followState.lyrics.synced=value});
vm.runInContext(section('function pauseLyricsFollowFromInput(', '$("sideVideoSwitch").onclick'),follow);
assert.equal(events.scroll,undefined,'programmatic scroll events cannot disable following');
assert.equal(followState.lyrics.synced,true);
events.wheel();assert.equal(followState.lyrics.synced,false);
followState.lyrics.synced=true;events.touchmove();assert.equal(followState.lyrics.synced,false);
console.log('Only user scrolling pauses lyric following; automatic animations keep following');
