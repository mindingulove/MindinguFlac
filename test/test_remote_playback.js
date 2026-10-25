const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function setup(android=true) {
 const elements=new Map(),calls=[],localCalls=[],statusCalls=[],messages=[],listeners=[];
 function element(id='') {const classes=new Set();return {id,hidden:true,style:{},dataset:{},value:0,textContent:'',innerHTML:'',disabled:false,
   paused:false,volume:.4,duration:100,currentTime:10,onclick:()=>localCalls.push(id),oninput:()=>localCalls.push(id),
   classList:{toggle:(k,v)=>v?classes.add(k):classes.delete(k),remove:k=>classes.delete(k)},
   children:[],appendChild(child){this.children.push(child);},append(){},replaceChildren(){this.children=[];},setAttribute(k,v){this[k]=v;},querySelector:()=>({className:''}),querySelectorAll:()=>[],
   pause(){this.paused=true;localCalls.push('pause-local');},removeAttribute(){},load(){},click(){return this.onclick();}};}
 const $=id=>{if(id==='remotePlaybackBanner'&&!elements.has(id))return null;if(!elements.has(id))elements.set(id,element(id));return elements.get(id);};
 const original={title:'Phone song',spotify_id:'phone-song',library_path:'/phone/private.flac'};
 const remote={track:{title:'Mac song',spotify_id:'mac-song'},queue:[{title:'Mac song',spotify_id:'mac-song'}],queue_index:0,
   playing:true,buffering:false,position:40,duration:200,volume:.6,shuffle:false,repeat:false};
 const state={currentTrack:original,queue:[original],originalQueue:[original],queueIndex:0,queueContext:{title:'Local album'},
   nativeAudio:{active:true,playing:true},nativeAudioStart:null,isShuffle:false,isRepeat:false,playbackRequestId:1,activeJobId:'local-stream',
   videoFetch:{},lyrics:{open:false},prefetchJobs:new Map()};
 const context=vm.createContext({URL,URLSearchParams,API_BASE:'',window:{location:{origin:'http://127.0.0.1:12345'},addEventListener(){}},document:{body:{appendChild(el){elements.set(el.id,el);},classList:{toggle(){}}},
   createElement:()=>element(),querySelector:()=>element(),addEventListener:(...args)=>listeners.push(args)},state,$,IS_ANDROID:android,console,setInterval:()=>1,
   renderDetailsSidebar(){},showToast:msg=>messages.push(msg),trackIdentitySnapshot:t=>({...t}),playableQueueItem:t=>!!t?.title,trackKey:t=>t?.spotify_id||t?.title||'',
   absoluteUrl:url=>url?new URL(url,'http://127.0.0.1:12345').href:'',esc:s=>s,qualityLabelForTrack:()=> 'HI-RES',setPlayerStatusIcon:(mode,pct)=>statusCalls.push(['status',mode,pct]),renderSideVideoButton(){},openConnectPanel:()=>localCalls.push('open-devices'),formatTime:n=>String(n),knownTrackDurationSeconds:()=>100,bindEntityLinks(){},renderSideCover(){},albumLinkHtml:(t)=>t.title,artistLinkHtml:t=>t.artist||'',
   syncActiveTrackRows(){},updateSidebarNextQueue(){},refreshQueuePanel(){},updateLyricsPosition(){},resetSeekUi(){},
   pushAndroidNowPlaying(){},clearMediaSession(){},loadLyricsForTrack:async()=>{},_refreshConnectPanel:async()=>{},cancelAllPrefetchJobs:()=>localCalls.push('cancel-prefetch'),
   stopNativeAudio:async()=>{state.nativeAudio.active=false;state.nativeAudio.playing=false;localCalls.push('stop-native');},
   prepareSelectedTrackUi:()=>localCalls.push('restore-paused'),
   prefetchOneTrack:async()=>localCalls.push('prefetch'),prefetchNextTracks:async()=>localCalls.push('prefetch-next'),prefetchNextVideos:()=>localCalls.push('prefetch-video'),_triggerVideoFetchForTrack:()=>localCalls.push('trigger-video'),fetchVideoForTrack:async()=>localCalls.push('video'),startServiceDownload:async()=>localCalls.push('download'),playFromLibraryPath:async()=>localCalls.push('library-play'),startNativeAudio:async()=>localCalls.push('native-start'),selectMusicItem:(...args)=>{localCalls.push(['select',...args]);return Promise.resolve();},playQueueOffset:d=>localCalls.push(['offset',d]),
   seekBy:n=>localCalls.push(['seek',n]),setPlayerVolume:n=>localCalls.push(['volume',n]),reorderQueueTrack:()=>true,
   appendTracksToPlaybackQueue:()=>1,currentPlaybackSeconds:()=>10,audiblePlaybackSeconds:()=>10,isPlaybackVisiblyActive:()=>true,
   playbackTransportBusy:()=>false,persistPlaybackSnapshot(){},syncPlayPauseButton(){},
   api:async(path,options={})=>{
    const body=options.body?JSON.parse(options.body):{};calls.push({path,body});
    if(path==='/api/remote/connect') { if(context.failConnect)throw Error('No player acknowledgement');return {ok:true,session:{id:'session'},snapshot:{...remote}}; }
    if(path==='/api/remote/status')return context.failPoll?{ok:false,error:'Disconnected'}:{ok:true,route:{device_id:'mac'},session:{id:'session'},snapshot:{...remote}};
    if(path==='/api/remote/command') {if(body.action==='pause')remote.playing=false;if(body.action==='volume')remote.volume=body.payload.volume;return {ok:true,session:{id:'session'},snapshot:{...remote}};}
    if(path.startsWith('/api/music/album_tracks?'))return {artwork_url:'https://art.example/exact-album.jpg'};
    if(path==='/api/music/track_metadata')return {track:{artwork_url:'https://art.example/fallback.jpg'}};
    if(path==='/api/remote/local')return {ok:true,session:null,commands:[]};
    return {ok:true};
   }});
 vm.runInContext(fs.readFileSync('static/remote_playback.js','utf8'),context);
 return {context,remote,state,elements,calls,localCalls,statusCalls,messages,$,api:context.window.MindinguflacRemote};
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
 const commandCount=s.calls.filter(c=>c.path==='/api/remote/command').length;
 s.$('remotePlaybackBanner').onclick();
 assert.ok(s.localCalls.includes('open-devices'));assert.ok(s.api.isController());
 assert.equal(s.$('remotePlaybackBanner').children.length,1,'banner contains only its clickable label');
 const count=s.localCalls.length;
 for(const name of ['prefetchOneTrack','prefetchNextTracks','prefetchNextVideos','_triggerVideoFetchForTrack','fetchVideoForTrack','startServiceDownload','playFromLibraryPath','startNativeAudio']) await s.context[name]();
 assert.equal(s.localCalls.length,count,'controller does not download, prefetch or play media');
 assert.equal(s.calls.filter(c=>c.path==='/api/remote/command').length,commandCount);
 const albumId='a'.repeat(22);
 s.remote.track={title:'Compilation song',spotify_id:'compilation-song',album_spotify_id:albumId};
 s.remote.status='Downloading on Mac';s.remote.status_mode='downloading';s.remote.progress=37;s.remote.quality_label='HI-RES';
 await s.api.poll();await tick();
 assert.equal(s.$('playerMeta').textContent,'Downloading on Mac');
 assert.ok(s.statusCalls.some(c=>Array.isArray(c)&&c[0]==='status'&&c[1]==='downloading'&&c[2]===37));
 assert.match(s.$('sideMeta').innerHTML,/HI-RES/);
 assert.equal(s.state.currentTrack.artwork_url,'/api/image?url=https%3A%2F%2Fart.example%2Fexact-album.jpg');
 assert.ok(s.calls.some(c=>c.path.includes('album_tracks?spotify_id='+albumId)));
 assert.ok(s.calls.every(c=>!/^\/api\/(service\/start|video\/fetch)/.test(c.path)));
 s.context.failPoll=true;await s.api.poll();
 assert.ok(s.api.isController(),'disconnect does not silently route transport back to local playback');
 const failedCount=s.localCalls.length;await s.$('playPause').onclick();assert.equal(s.localCalls.length,failedCount);
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
