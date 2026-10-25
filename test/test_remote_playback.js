const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function setup(android=true) {
 const elements=new Map(),calls=[],localCalls=[],messages=[],listeners=[];
 function element(id='') {const classes=new Set();return {id,hidden:true,style:{},dataset:{},value:0,textContent:'',innerHTML:'',disabled:false,
   paused:false,volume:.4,duration:100,currentTime:10,onclick:()=>localCalls.push(id),oninput:()=>localCalls.push(id),
   classList:{toggle:(k,v)=>v?classes.add(k):classes.delete(k),remove:k=>classes.delete(k)},
   appendChild(){},append(){},replaceChildren(){},setAttribute(k,v){this[k]=v;},querySelector:()=>({className:''}),querySelectorAll:()=>[],
   pause(){this.paused=true;localCalls.push('pause-local');},removeAttribute(){},load(){},click(){return this.onclick();}};}
 const $=id=>{if(!elements.has(id))elements.set(id,element(id));return elements.get(id);};
 const original={title:'Phone song',spotify_id:'phone-song',library_path:'/phone/private.flac'};
 const remote={track:{title:'Mac song',spotify_id:'mac-song'},queue:[{title:'Mac song',spotify_id:'mac-song'}],queue_index:0,
   playing:true,buffering:false,position:40,duration:200,volume:.6,shuffle:false,repeat:false};
 const state={currentTrack:original,queue:[original],originalQueue:[original],queueIndex:0,queueContext:{title:'Local album'},
   nativeAudio:{active:true,playing:true},nativeAudioStart:null,isShuffle:false,isRepeat:false,playbackRequestId:1,activeJobId:'local-stream',
   videoFetch:{},lyrics:{open:false},prefetchJobs:new Map()};
 const context=vm.createContext({window:{addEventListener(){}},document:{body:{appendChild(){},classList:{toggle(){}}},
   createElement:()=>element(),querySelector:()=>element(),addEventListener:(...args)=>listeners.push(args)},state,$,IS_ANDROID:android,console,setInterval:()=>1,
   renderDetailsSidebar(){},showToast:msg=>messages.push(msg),trackIdentitySnapshot:t=>({...t}),playableQueueItem:t=>!!t?.title,trackKey:t=>t?.spotify_id||t?.title||'',
   formatTime:n=>String(n),knownTrackDurationSeconds:()=>100,bindEntityLinks(){},renderSideCover(){},albumLinkHtml:(t)=>t.title,artistLinkHtml:t=>t.artist||'',
   syncActiveTrackRows(){},updateSidebarNextQueue(){},refreshQueuePanel(){},updateLyricsPosition(){},resetSeekUi(){},
   pushAndroidNowPlaying(){},clearMediaSession(){},loadLyricsForTrack:async()=>{},_refreshConnectPanel:async()=>{},cancelAllPrefetchJobs:()=>localCalls.push('cancel-prefetch'),
   stopNativeAudio:async()=>{state.nativeAudio.active=false;state.nativeAudio.playing=false;localCalls.push('stop-native');},
   prepareSelectedTrackUi:()=>localCalls.push('restore-paused'),
   selectMusicItem:(...args)=>{localCalls.push(['select',...args]);return Promise.resolve();},playQueueOffset:d=>localCalls.push(['offset',d]),
   seekBy:n=>localCalls.push(['seek',n]),setPlayerVolume:n=>localCalls.push(['volume',n]),reorderQueueTrack:()=>true,
   appendTracksToPlaybackQueue:()=>1,currentPlaybackSeconds:()=>10,audiblePlaybackSeconds:()=>10,isPlaybackVisiblyActive:()=>true,
   playbackTransportBusy:()=>false,persistPlaybackSnapshot(){},syncPlayPauseButton(){},
   api:async(path,options={})=>{
    const body=options.body?JSON.parse(options.body):{};calls.push({path,body});
    if(path==='/api/remote/connect') { if(context.failConnect)throw Error('No player acknowledgement');return {ok:true,session:{id:'session'},snapshot:{...remote}}; }
    if(path==='/api/remote/status')return context.failPoll?{ok:false,error:'Disconnected'}:{ok:true,route:{device_id:'mac'},session:{id:'session'},snapshot:{...remote}};
    if(path==='/api/remote/command') {if(body.action==='pause')remote.playing=false;if(body.action==='volume')remote.volume=body.payload.volume;return {ok:true,session:{id:'session'},snapshot:{...remote}};}
    if(path==='/api/remote/local')return {ok:true,session:null,commands:[]};
    return {ok:true};
   }});
 vm.runInContext(fs.readFileSync('static/remote_playback.js','utf8'),context);
 return {context,remote,state,elements,calls,localCalls,messages,$,api:context.window.MindinguflacRemote};
}
const tick=()=>new Promise(r=>setImmediate(r));
(async()=>{
 const s=setup();await s.api.initialize();await s.api.connect({device_id:'mac',name:'My Mac'});
 assert.ok(s.localCalls.includes('pause-local'));assert.ok(s.localCalls.includes('stop-native'));
 assert.equal(s.state.currentTrack.title,'Mac song');assert.match(s.$('remotePlaybackBanner').hidden.toString(),/false/);
 assert.equal(s.context.currentPlaybackSeconds(),40);
 const before=s.localCalls.length;
 await s.context.selectMusicItem({title:'New song'},'stream',[{title:'New song'}]);
 await s.context.playQueueOffset(1);await s.context.seekBy(5);await s.context.setPlayerVolume(.2);
 await s.$('playPause').onclick();await tick();
 assert.equal(s.localCalls.length,before,'remote transport never invokes the phone player');
 assert.deepEqual(s.calls.filter(c=>c.path==='/api/remote/command').map(c=>c.body.action),['select','next','seek','volume','pause']);
 s.context.failPoll=true;await s.api.poll();
 assert.ok(s.api.isController(),'disconnect does not silently route transport back to local playback');
 await s.$('playPause').onclick();assert.equal(s.localCalls.length,before);
 await s.api.disconnect();assert.equal(s.state.currentTrack.title,'Phone song');assert.equal(s.state.pendingResumePosition,10);
 assert.ok(s.state.restoredPlaybackPending);assert.ok(s.localCalls.includes('restore-paused'));
 assert.equal(s.api.isController(),false);assert.equal(s.$('remotePlaybackBanner').hidden,true);
 s.context.failConnect=true;await assert.rejects(s.api.connect({device_id:'mac',name:'My Mac'}),/acknowledgement/);
 assert.ok(s.api.isController());await s.api.disconnect();
 const receiver=setup(false);await receiver.api.initialize();
 await receiver.api.applyCommand({action:'select',payload:{track:{title:'Remote song'},queue:[{title:'Remote song'}]}});
 assert.ok(receiver.localCalls.some(c=>Array.isArray(c)&&c[0]==='select'&&c[1].title==='Remote song'));
 assert.ok(receiver.calls.some(c=>c.path==='/api/remote/local'));
 receiver.state.restoredPlaybackPending=true;receiver.state.pendingResumePosition=10;
 await receiver.api.applyCommand({action:'seek',payload:{position:30}});
 assert.equal(receiver.state.pendingResumePosition,30,'seeking a restored paused track changes its actual resume position');
 console.log('Paired remote transport, phone audio suppression, receiver dispatch, clocks, disconnect cleanup and failed acknowledgement passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
