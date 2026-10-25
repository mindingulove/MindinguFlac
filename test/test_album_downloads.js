const assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../static/app.js'),'utf8');
const section=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b,source.indexOf(a)));
function button(){const classes=new Set();return {dataset:{},isConnected:false,innerHTML:'',title:'',disabled:false,
 classList:{add:(...a)=>a.forEach(x=>classes.add(x)),remove:(...a)=>a.forEach(x=>classes.delete(x)),contains:x=>classes.has(x),toggle:(x,on)=>on?classes.add(x):classes.delete(x)},
 click(){return this.onclick?.();},setAttribute(name,value){this[name]=value;}};}
function setup(stored='[]',remote=null){
 const elements=new Map(),calls=[],waits=[],messages=[],saved=new Map([['queue',stored]]),selected=[];
 const state={playlists:[],settings:{download_engine:'monochrome',default_quality:'LOSSLESS'},pendingResumePosition:50};
 const context=vm.createContext({console,state,Map,Set,JSON,Date,STORAGE_KEYS:{albumDownloads:'queue'},
  $:id=>{if(!elements.has(id))elements.set(id,button());return elements.get(id);},
  localStorage:{setItem:(k,v)=>saved.set(k,v),getItem:k=>saved.get(k)},document:{createElement:()=>button()},
  albumTarget:a=>({...a,title:a.album||a.title}),spotifyAlbumUrl:a=>a.spotify_id?`https://open.spotify.com/album/${a.spotify_id}`:'',inferPlaylistOrigin:p=>p.playlist_origin,
  isTrackItem:t=>!!t?.title,playableQueueItem:t=>!!t?.title,trackKey:t=>t.spotify_id||t.title,
  serviceDownloadPayload:t=>({title:t.title,engine:state.settings.download_engine,quality:state.settings.default_quality}),
  api:async(path,options)=>{if(path==='/api/library/album_queue') { let snapshot=[];try { snapshot=JSON.parse(saved.get('queue')||'[]'); } catch (_) {} return options?{ok:true}:(remote || (Array.isArray(snapshot)?{updated_at:0,batches:snapshot}:snapshot)); } const body=JSON.parse(options.body);calls.push({path,body});return path==='/api/service/cancel'?{ok:true}:{ok:true,action:context.joinExisting?'queued':'started',job:{id:body.title,mode:'download'}};},
  waitForLibraryToggle:(track,id,btn,options)=>new Promise((resolve,reject)=>waits.push({track,options,resolve,reject})),
  showToast:msg=>messages.push(msg),progressButtonMarkup:()=>'',prefetchLyricsForTrack:()=>{},loadPlaylists:()=>{},
  refreshLibraryButtonState:async()=>{},findLiveLibraryButtonForTrack:()=>null,
  selectMusicItem:(...args)=>selected.push(args),
 });
 vm.runInContext(section('// Album header controls wrap','async function renderAlbumPage('),context);
 vm.runInContext(section('async function toggleTrackLibrary(', 'async function cancelLibraryDownload('),context);
 return {context,state,elements,calls,waits,messages,saved,selected};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 const s=setup(),c=s.context;
 s.elements.set('btnShuffle',button());s.elements.get('btnShuffle').onclick=()=>{s.state.isShuffle=!s.state.isShuffle;};
 const tracks=[{title:'A',spotify_id:'a'},{title:'B',spotify_id:'b'},{title:'C',spotify_id:'c'}];
 c.bindAlbumHeaderControls({spotify_id:'exact-album',album:'Album',saved_playlist_context:{id:'saved',kind:'playlist'}},[...tracks,tracks[0]]);
 c.updateAlbumLibraryStatuses([tracks[1]],[{in_library:true,download_satisfied:true}]);
 await s.elements.get('albumShuffle').onclick();assert.equal(s.state.isShuffle,true);assert.equal(s.elements.get('albumShuffle')['aria-pressed'],'true');
 s.elements.get('albumPlayAll').onclick();assert.equal(s.selected[0][0].title,'A');assert.equal(s.selected[0][2].length,3);
 assert.equal(s.selected[0][3].id,'saved');assert.equal(s.state.pendingResumePosition,0);
 assert.equal(s.elements.get('albumSaveLibrary')['aria-label'],'Add album to library');
 s.state.playlists=[{id:'saved-album',playlist_origin:'album',spotify_url:'https://open.spotify.com/album/exact-album'}];
 c.renderAlbumLibraryControl({spotify_id:'exact-album',album:'Album'});
 assert.equal(s.elements.get('albumSaveLibrary')['aria-label'],'Remove album from library');
 await s.elements.get('albumDownloadAll').onclick();await tick();
 assert.equal(s.calls.length,1);assert.equal(s.calls[0].body.title,'A');assert.equal(s.calls[0].body.ensure_download,true);
 assert.match(s.elements.get('albumDownloadStatus').textContent,/2 tracks remaining/);
 s.waits[0].options.onStatus({progress:80,library_requested:true,in_library:false});
 assert.match(s.elements.get('albumDownloadStatus').textContent,/2 tracks remaining/,'bytes must not count as a completed track');
 s.state.settings.download_engine='ytp-dl';
 s.waits[0].resolve({in_library:true,download_satisfied:true});await tick();await tick();
 assert.equal(s.calls[1].body.title,'C');assert.equal(s.calls[1].body.engine,'monochrome','engine is captured at enqueue');
 assert.match(s.elements.get('albumDownloadStatus').textContent,/1 tracks remaining/);
 s.waits[1].reject(new Error('Catalog unavailable'));await tick();await tick();
 assert.match(s.elements.get('albumDownloadStatus').textContent,/1 downloads failed/);
 assert.equal(vm.runInContext('libraryDownloadErrors.get("c")',c),'Catalog unavailable');
 assert.equal(s.calls.filter(x=>x.body.title==='B').length,0,'saved track is skipped');
 assert.match(s.messages.at(-1),/1 tracks could not/);
 c.updateAlbumLibraryStatuses([tracks[2]],[{in_library:true,download_satisfied:true}]);
 assert.equal(s.elements.get('albumDownloadStatus').textContent,'');
 c.bindAlbumHeaderControls({spotify_id:'other',album:'Other'},[{title:'D'},{title:'E'}]);
 await s.elements.get('albumDownloadAll').onclick();await tick();
 await s.elements.get('albumDownloadAll').onclick();
 assert.equal(s.calls.at(-1).path,'/api/service/cancel');assert.equal(s.calls.at(-1).body.job_id,'D');
 s.waits[2].resolve(null);await tick();await tick();
 assert.ok(!s.calls.some(x=>x.body.title==='E'),'cancelling drops the remaining queue');
 // Resume only the unprocessed suffix after a page/app reload.
 const restored=setup('{bad json',{updated_at:10,batches:[{key:'resume',name:'Resume',status:'running',total:2,completed:1,failed:0,nextIndex:1,
   items:[{track:{title:'Done'},payload:{title:'Done',engine:'monochrome'}},{track:{title:'Remaining'},payload:{title:'Remaining',engine:'monochrome'}}]}]});
 restored.context.restoreAlbumDownloadQueue();await tick();
 assert.equal(restored.calls.length,1);assert.equal(restored.calls[0].body.title,'Remaining');
 restored.waits[0].resolve({in_library:true,download_satisfied:true});await tick();await tick();
 assert.equal(JSON.parse(restored.saved.get('queue')).batches.length,0);
 const joined=setup();joined.context.joinExisting=true;
 joined.context.bindAlbumHeaderControls({spotify_id:'joined',album:'Joined'},[{title:'Existing'}]);
 await joined.elements.get('albumDownloadAll').onclick();await tick();
 await joined.elements.get('albumDownloadAll').onclick();
 assert.ok(!joined.calls.some(call=>call.path==='/api/service/cancel'),'album cancellation leaves an existing job alone');
 joined.waits[0].resolve(null);await tick();
 console.log('Album play/order, serial existing download action, saved-track skip, engine snapshot, remaining-track pie, failures, cancellation and reload resume passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
