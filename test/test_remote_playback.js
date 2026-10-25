const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function setup(android=true) {
 const elements=new Map(),calls=[],localCalls=[],statusCalls=[],nativeVolumeCalls=[],messages=[],listeners=[];
 function element(id='') {const classes=new Set();return {id,hidden:true,style:{},dataset:{},value:0,textContent:'',innerHTML:'',disabled:false,
   paused:false,volume:.4,duration:100,currentTime:10,onclick:()=>localCalls.push(id),oninput:()=>localCalls.push(id),
   classList:{toggle:(k,v)=>v?classes.add(k):classes.delete(k),remove:k=>classes.delete(k)},
   children:[],appendChild(child){this.children.push(child);},append(){},replaceChildren(){this.children=[];},setAttribute(k,v){this[k]=v;},querySelector:()=>({className:''}),querySelectorAll:()=>[],
   pause(){this.paused=true;localCalls.push("pause-local");},removeAttribute(){},load(){},addEventListener(){},matches:()=>false,click(){return this.onclick();}};}
 const $=id=>{if(id==='remotePlaybackBanner'&&!elements.has(id))return null;if(!elements.has(id))elements.set(id,element(id));return elements.get(id);};
 const original={title:'Phone song',spotify_id:'phone-song',library_path:'/phone/private.flac'};
 const remote={track:{title:'Mac song',spotify_id:'mac-song'},queue:[{title:'Mac song',spotify_id:'mac-song'}],queue_index:0,
   playing:true,buffering:false,position:40,duration:200,volume:.6,shuffle:false,repeat:false};
 const state={currentTrack:original,queue:[original],originalQueue:[original],queueIndex:0,queueContext:{title:'Local album'},
   nativeAudio:{active:true,playing:true},nativeAudioStart:null,isShuffle:false,isRepeat:false,playbackRequestId:1,activeJobId:'local-stream',
   videoFetch:{},videoSync:{},videoMode:false,lyrics:{open:false,lines:[],raw:'',autoOffset:0,syncOffset:0},prefetchJobs:new Map()};
 const context=vm.createContext({URL,URLSearchParams,API_BASE:'',window:{MindinguflacAndroid:{setRemotePlayback:(...args)=>nativeVolumeCalls.push(args)},location:{origin:'http://127.0.0.1:12345'},addEventListener(){}},document:{body:{appendChild(el){elements.set(el.id,el);},classList:{toggle(){}}},
   createElement:()=>element(),querySelector:()=>element(),addEventListener:(...args)=>listeners.push(args)},state,$,IS_ANDROID:android,console,setTimeout:()=>1,clearTimeout(){},setInterval:()=>1,
   renderSidebarPlaylists(){},_renderPlaylistContent(){},renderDetailsSidebar(){},showToast:msg=>messages.push(msg),trackIdentitySnapshot:t=>({...t}),playableQueueItem:t=>!!t?.title,trackKey:t=>t?.spotify_id||t?.title||'',
   absoluteUrl:url=>url?new URL(url,'http://127.0.0.1:12345').href:'',esc:s=>s,qualityLabelForTrack:()=> 'HI-RES',setPlayerStatusIcon:(mode,pct)=>statusCalls.push(['status',mode,pct]),renderSideVideoButton(){},openConnectPanel:()=>localCalls.push('open-devices'),formatTime:n=>String(n),knownTrackDurationSeconds:()=>100,bindEntityLinks(){},renderSideCover(){},albumLinkHtml:(t)=>t.title,artistLinkHtml:t=>t.artist||'',
   syncActiveTrackRows(){},updateSidebarNextQueue(){},refreshQueuePanel(){},updateLyricsPosition(){},resetSeekUi(){},
   pushAndroidNowPlaying(){},clearMediaSession(){},loadLyricsForTrack:async()=>{},_refreshConnectPanel:async()=>{},cancelAllPrefetchJobs:()=>localCalls.push('cancel-prefetch'),
   stopNativeAudio:async()=>{state.nativeAudio.active=false;state.nativeAudio.playing=false;localCalls.push('stop-native');},
   prepareSelectedTrackUi:()=>localCalls.push('restore-paused'),
   prefetchOneTrack:async()=>localCalls.push('prefetch'),prefetchNextTracks:async()=>localCalls.push('prefetch-next'),prefetchNextVideos:()=>localCalls.push('prefetch-video'),_triggerVideoFetchForTrack:()=>localCalls.push('trigger-video'),fetchVideoForTrack:async()=>localCalls.push('video'),startServiceDownload:async()=>localCalls.push('download'),playFromLibraryPath:async()=>localCalls.push('library-play'),startNativeAudio:async()=>localCalls.push('native-start'),selectMusicItem:(...args)=>{localCalls.push(['select',...args]);return Promise.resolve();},playQueueOffset:d=>localCalls.push(['offset',d]),
   seekBy:n=>localCalls.push(['seek',n]),changeVolumeBy:n=>localCalls.push(['adjust-volume',n]),syncVolumeBar:()=>localCalls.push('sync-local-volume'),setPlayerVolume:n=>localCalls.push(['volume',n]),reorderQueueTrack:()=>true,
   appendTracksToPlaybackQueue:()=>1,currentPlaybackSeconds:()=>10,audiblePlaybackSeconds:()=>10,isPlaybackVisiblyActive:()=>true,
   playbackTransportBusy:()=>false,persistPlaybackSnapshot(){},syncPlayPauseButton(){},performance:{now:()=>context.now||0},
   refreshLyricsAlignment:async()=>localCalls.push('align-local'),updateLyricsOffset:async d=>localCalls.push(['lyrics-nudge',d]),
   refreshVideoSync:async()=>localCalls.push('video-sync-local'),nudgeVideoSync:async d=>localCalls.push(['video-nudge',d]),
   setMiniPlayerProgress(){},switchSideVideoMode:on=>{state.videoMode=on;localCalls.push(['switch-video',on]);},followAudioWithVideo(){},steerVideoToAudio:(video,audible)=>localCalls.push(['steer',audible]),renderVideoSyncControls(){},
   renderLyricsContent(){},renderLyricsAlignment(){},setLyricsSynced(){},applyLyricsPalette(){},
   parseLyrics:raw=>raw?[{time:1,text:raw}]:[],lyricsPayload:t=>({title:t?.title||''}),lyricsAlignmentBody:()=>({stream_url:'s'}),
   currentSideVideoPath:()=>state.videoFetch?.status==='ready'?state.videoFetch.path:'',videoSyncKey:(t,p)=>`${t.title}|${p}`,videoSyncOffset:()=>2.5,
   api:async(path,options={})=>{
    const body=options.body?JSON.parse(options.body):{};calls.push({path,body});
    if(path==='/api/remote/connect') { if(context.failConnect)throw Error('No player acknowledgement');return {ok:true,session:{id:'session'},snapshot:{...remote}}; }
    if(path==='/api/remote/offline')return {ok:true,route:{device_id:'mac'},tracks:[{title:'Mac download',spotify_id:'mac-download',album_spotify_id:'a'.repeat(22)}]};
    if(path==='/api/remote/status')return context.failPoll?{ok:false,error:'Disconnected'}:{ok:true,route:{device_id:'mac'},session:{id:'session'},snapshot:{...remote},snapshot_age:context.statusAge||0};
    if(path==='/api/remote/command') {if(body.action==='pause')remote.playing=false;if(body.action==='volume')remote.volume=body.payload.volume;return {ok:true,session:{id:'session'},snapshot:{...remote}};}
    if(path.startsWith('/api/video/fetch?'))return {status:'ready',path:'/phone/clip.mp4',youtube_id:'abcdefghijk',clip_duration:0};
    if(path.startsWith('/api/music/album_tracks?'))return {artwork_url:'https://art.example/exact-album.jpg'};
    if(path==='/api/music/track_metadata')return {track:{artwork_url:'https://art.example/fallback.jpg'}};
    if(path==='/api/remote/local'){context.lastSnapshot=body.snapshot;return {ok:true,session:context.receiverSession||null,commands:context.receiverCommands||[]};}
    return {ok:true};
   }});
 vm.runInContext(fs.readFileSync('static/remote_playback.js','utf8'),context);
 return {context,remote,state,elements,calls,localCalls,statusCalls,nativeVolumeCalls,messages,$,api:context.window.MindinguflacRemote};
}
const tick=()=>new Promise(r=>setImmediate(r));
async function lyricsAndVideo() {
 // Controller: lyrics, their alignment and the clip come from the receiver.
 const s=setup();await s.api.initialize();await s.api.connect({device_id:'mac',name:'My Mac'});
 s.remote.audible_position=39;s.context.now=1000;await s.api.poll();
 s.context.now=1500;assert.ok(Math.abs(s.context.audiblePlaybackSeconds()-39.5)<1e-9,'audible clock advances between polls');
 s.context.now=9000;assert.equal(s.context.audiblePlaybackSeconds(),42,'extrapolation is capped when polls stall');
 // A report that was already 0.6 s old on arrival is advanced by that age.
 s.context.statusAge=0.6;s.remote.audible_position=50;s.context.now=10000;await s.api.poll();
 assert.ok(Math.abs(s.context.audiblePlaybackSeconds()-50.6)<1e-9,'arrival age is compensated');
 s.context.now=10500;assert.ok(Math.abs(s.context.audiblePlaybackSeconds()-51.1)<1e-9);
 s.context.statusAge=0;
 s.state.lyrics.open=true;s.remote.lyrics={key:'k1',raw:'[00:01.00]Hello',synced:true,loading:false,offset:-0.75,status:'matched'};
 await s.context.loadLyricsForTrack(s.state.currentTrack,{force:true});await s.api.poll();await tick();
 assert.deepEqual(s.state.lyrics.lines,[{time:1,text:'[00:01.00]Hello'}]);
 assert.equal(s.state.lyrics.autoOffset,-0.75);assert.equal(s.state.lyrics.syncOffset,0);assert.equal(s.state.lyrics.alignmentStatus,'matched');
 assert.ok(s.calls.some(c=>c.path==='/api/remote/command'&&c.body.action==='lyrics'&&c.body.payload.enabled===true));
 assert.ok(!s.localCalls.includes('align-local'),'the phone never aligns against audio it is not playing');
 await s.context.updateLyricsOffset(0.25);
 assert.ok(s.calls.some(c=>c.body.action==='lyrics_nudge'&&c.body.payload.delta===0.25));
 const fetched=[];s.state.videoMode=true;
 s.remote.video={youtube_id:'abcdefghijk',status:'ready',clip_duration:200,offset:-3,sync_status:'matched'};
 await s.api.poll();await tick();await tick();
 assert.ok(s.calls.some(c=>c.body.action==='video'&&c.body.payload.enabled===true));
 assert.ok(s.calls.some(c=>c.path.startsWith('/api/video/fetch?')&&c.path.includes('youtube_id=abcdefghijk')),'the phone fetches the receiver clip itself');
 assert.equal(s.state.videoFetch.status,'ready');assert.equal(s.state.videoFetch.path,'/phone/clip.mp4');
 const video=s.$('sideVideoPlayer');video.tagName='VIDEO';video.duration=212;video.paused=true;video.play=async()=>{video.paused=false;};
 s.context.followAudioWithVideo();
 assert.equal(s.state.videoSync.offset,9,'receiver offset plus the 12 s the desktop clip was cut');
 assert.equal(video.muted,true);assert.ok(s.localCalls.some(c=>Array.isArray(c)&&c[0]==='steer'));
 s.remote.playing=false;await s.api.poll();video.paused=false;s.context.followAudioWithVideo();
 assert.equal(video.paused,true,'video pauses with the receiver');
 // A switch made on the receiver mirrors here; an unchanged report does not undo a local tap.
 s.remote.video_mode=false;await s.api.poll();assert.equal(s.state.videoMode,false);
 s.state.videoMode=true;await s.api.poll();assert.equal(s.state.videoMode,true,'stale receiver mode keeps the local tap');
 s.remote.video_mode=true;await s.api.poll();s.remote.video_mode=false;await s.api.poll();assert.equal(s.state.videoMode,false);
 await s.api.disconnect();
 // Receiver: sends the measured state only to a phone that asked for it.
 const r=setup(false);await r.api.initialize();
 r.context.receiverSession={id:'remote-session'};
 r.state.currentTrack={title:'Mac song',spotify_id:'mac-song'};
 r.state.lyrics={open:false,lines:[{time:1,text:'x'}],raw:'[00:01.00]x',trackKey:JSON.stringify({title:'Mac song'}),autoOffset:1.5,syncOffset:-0.25,alignmentStatus:'matched',alignmentKey:JSON.stringify({stream_url:'s'})};
 r.state.videoFetch={trackKey:'mac-song',status:'ready',path:'/v.mp4',youtube_id:'abcdefghijk',clip_duration:200};
 r.state.videoSync={key:'Mac song|/v.mp4',status:'matched'};
 r.context.receiverCommands=[{id:'1',action:'lyrics',payload:{enabled:true}},{id:'2',action:'video',payload:{enabled:true}}];
 await r.api.poll();r.context.receiverCommands=[];await r.api.poll();
 assert.equal(r.api.receiverWants('lyrics'),true);
 assert.ok(r.localCalls.some(c=>Array.isArray(c)&&c[0]==='switch-video'&&c[1]===true),'the phone switch mirrors on the receiver');
 assert.equal(r.context.lastSnapshot.video_mode,true);
 assert.deepEqual(r.context.lastSnapshot.lyrics,{key:JSON.stringify({title:'Mac song'}),raw:'[00:01.00]x',synced:true,loading:false,offset:1.25,status:'matched'});
 assert.deepEqual(r.context.lastSnapshot.video,{status:'ready',youtube_id:'abcdefghijk',clip_duration:200,offset:2.5,sync_status:'matched'});
 assert.equal(r.context.lastSnapshot.audible_position,10);
 r.context.receiverSession={id:'next-session'};await r.api.poll();
 assert.equal(r.api.receiverWants('lyrics'),false,'a new controller session starts without requests');
}
(async()=>{
 await lyricsAndVideo();
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
 assert.equal(typeof s.api.backgroundHeartbeat,'function');
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
 const volumeStart=s.calls.length,localStart=s.localCalls.length;
 const pendingVolume=s.api.setVolume(.4);s.api.adjustVolumeBy(.05);s.api.adjustVolumeBy(.05);await pendingVolume;
 assert.ok(Math.abs(s.remote.volume-.5)<.0001,'rapid volume keys accumulate against the pending target');
 assert.equal(s.localCalls.length,localStart,'remote volume never changes local phone audio');
 assert.deepEqual(s.calls.slice(volumeStart).filter(c=>c.path==='/api/remote/command').map(c=>c.body.payload.volume),[.4,.5]);
 assert.deepEqual(s.nativeVolumeCalls.at(-1),[true,50]);
 assert.equal(s.$('remoteVolumeHudDevice').textContent,'My Mac');assert.equal(s.$('remoteVolumeHudPercent').textContent,'50%');assert.equal(s.$('remoteVolumeHudBar').style.width,'50%');
 const playlists=s.api.offlinePlaylists([]);assert.equal(playlists[0].id,'__offline__');assert.equal(playlists[0].remote_placeholder,true);
 assert.match(s.api.offlineTabs(),/This phone/);assert.match(s.api.offlineTabs(),/Connected device/);assert.match(s.api.offlineTabs(),/aria-selected=\"true\"/);assert.match(s.api.offlineTabs(),/aria-selected=\"false\"/);
 const remoteTab={dataset:{offlineDevice:'remote'}};
 s.$('pageContent').querySelectorAll=()=>[remoteTab];
 s.api.bindOfflineTabs(playlists[0]);remoteTab.onclick();await s.api.fetchOffline();await tick();
 const remoteOffline=s.api.offlineView(playlists[0]);assert.equal(remoteOffline.tracks[0].title,'Mac download');
 assert.equal(remoteOffline.tracks[0].remote_device_id,'mac');assert.equal(remoteOffline.tracks[0].library_path,undefined);
 s.context.failPoll=true;await s.api.poll();
 assert.ok(s.api.isController(),'disconnect does not silently route transport back to local playback');
 const failedCount=s.localCalls.length;await s.$('playPause').onclick();assert.equal(s.localCalls.length,failedCount);
 await s.api.disconnect();assert.equal(s.state.currentTrack.title,'Phone song');assert.equal(s.state.pendingResumePosition,10);
 assert.ok(s.state.restoredPlaybackPending);assert.ok(s.localCalls.includes('restore-paused'));
 assert.equal(s.api.isController(),false);assert.equal(s.nativeVolumeCalls.at(-1)[0],false);
 assert.equal(s.api.offlineTabs(),'');assert.equal(s.api.offlinePlaylists(playlists).length,0);
 const offlineSelectStart=s.localCalls.length;await s.context.selectMusicItem({title:'Remote file',remote_device_id:'mac'});assert.equal(s.localCalls.length,offlineSelectStart,'disconnected remote files cannot start on the phone');
 await s.context.changeVolumeBy(.1);assert.deepEqual(s.localCalls.at(-1),['adjust-volume',.1],'local volume is restored after selecting This phone');assert.equal(s.$('remotePlaybackBanner').hidden,true);
 s.context.failConnect=true;await assert.rejects(s.api.connect({device_id:'mac',name:'My Mac'}),/acknowledgement/);
 assert.ok(s.api.isController());await s.api.disconnect();
 const receiver=setup(false);await receiver.api.initialize();
 await receiver.api.applyCommand({action:'select',payload:{track:{title:'Remote song'},queue:[{title:'Remote song'}]}});
 assert.ok(receiver.localCalls.some(c=>Array.isArray(c)&&c[0]==='select'&&c[1].title==='Remote song'));
 assert.ok(receiver.calls.some(c=>c.path==='/api/remote/local'));
 receiver.state.restoredPlaybackPending=true;receiver.state.pendingResumePosition=10;
 receiver.state.nativeAudio.active=false;receiver.$('audioPlayer').paused=true;
 await receiver.api.applyCommand({action:'seek',payload:{position:30}});
 assert.equal(receiver.state.pendingResumePosition,30,'seeking a restored paused track changes its actual resume position');
 console.log('Paired remote transport, phone audio suppression, receiver dispatch, clocks, disconnect cleanup and failed acknowledgement passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
