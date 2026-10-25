// The side video follows the audio clock without flipping its playback rate on
// clock jitter: WebKit stutters on every rate change.
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('static/app.js','utf8');
const grab=name=>source.slice(source.indexOf(`function ${name}(`),source.indexOf('\n}\n',source.indexOf(`function ${name}(`))+2);
let now=0;
const context=vm.createContext({performance:{now:()=>now},Math,videoSyncOffset:()=>0,VIDEO_RATE_STEERING:true});
vm.runInContext(['videoTimeForAudio','steerVideoToAudio','setVideoRate'].map(grab).join('\n'),context);
const video={duration:300,currentTime:50,playbackRate:1,paused:false,seeking:false,readyState:4,play:async()=>{}};
let changes=0;const rate=video.playbackRate;
Object.defineProperty(video,'playbackRate',{get(){return this._r ?? 1;},set(v){this._r=v;changes++;}});
for(let i=0;i<40;i++){now+=500;video.currentTime=50+i*0.5;context.steerVideoToAudio(video,50+i*0.5+(i%2?0.12:-0.12));}
assert.equal(changes,0,'±0.12 s jitter never changes the rate');
now+=2000;video.currentTime=100;context.steerVideoToAudio(video,100.4);
assert.equal(video.playbackRate,1.03,'a settled 0.4 s lag speeds the video up gently');
now+=500;video.currentTime=100.6;context.steerVideoToAudio(video,100.62);
assert.equal(video.playbackRate,1,'correction stops once caught up');
now+=500;video.currentTime=10;context.steerVideoToAudio(video,100);
assert.equal(video.currentTime,100,'a large jump seeks');
// macOS WebKit: never changes rate; a settled drift is fixed by one seek, rarely.
context.VIDEO_RATE_STEERING=false;changes=0;now+=5000;
for(let i=0;i<10;i++){now+=500;video.currentTime=150+i*0.5;context.steerVideoToAudio(video,150+i*0.5+(i%2?0.12:-0.12));}
assert.equal(changes,0,'WebKit rate stays at 1');assert.equal(video.currentTime,154.5,'jitter causes no seeks');
now+=500;video.currentTime=160;context.steerVideoToAudio(video,160.5);assert.equal(video.currentTime,160.5);assert.equal(changes,0);
now+=500;video.currentTime=161;context.steerVideoToAudio(video,161.5);assert.equal(video.currentTime,161,'seeks are rate-limited');
// A slow seek over the local stream is never restarted before it lands.
context.VIDEO_RATE_STEERING=true;now+=5000;video.currentTime=10;context.steerVideoToAudio(video,200);assert.equal(video.currentTime,200);
video.seeking=true;video.currentTime=200;now+=500;context.steerVideoToAudio(video,201.5);assert.equal(video.currentTime,200,'no seek while one is in flight');
video.seeking=false;video.readyState=1;now+=500;context.steerVideoToAudio(video,202);assert.equal(video.currentTime,200,'no seek without data');
video.readyState=4;now+=500;context.steerVideoToAudio(video,202.5);assert.equal(video.currentTime,200,'large seeks are rate-limited');
now+=2000;context.steerVideoToAudio(video,205);assert.equal(video.currentTime,205);
console.log('Video steering ignores clock jitter, corrects settled drift gently and seeks large jumps');
