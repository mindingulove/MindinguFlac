const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map(),storage=new Map(),clickListeners=[];
function el(id='') {const classes=new Set();return {id,dataset:{},hidden:true,style:{},textContent:'',innerHTML:'',value:'',
 classList:{toggle:(k,on)=>on?classes.add(k):classes.delete(k),contains:k=>classes.has(k)},
 setAttribute(k,v){this[k]=v;},querySelectorAll:()=>[],querySelector:()=>el(),getBoundingClientRect:()=>({left:10,bottom:30}),
 appendChild(){},append(){},replaceChildren(){},showModal(){this.open=true;},close(){this.open=false;}};}
const $=id=>{if(!nodes.has(id))nodes.set(id,el(id));return nodes.get(id);};
const listOption=el(),compactOption=el();listOption.dataset.albumView='list';compactOption.dataset.albumView='compact';
$('albumViewMenu').querySelectorAll=()=>[compactOption,listOption];
const called=[],text=[];
const context=vm.createContext({window:{matchMedia:()=>({matches:false})},IS_ANDROID:false,Map,Set,JSON,console,
 document:{querySelector:selector=>$('.album-track-header'),querySelectorAll:()=>[compactOption,listOption],addEventListener:(...a)=>clickListeners.push(a)},
 $,localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},
 albumTarget:a=>a,spotifyAlbumUrl:a=>a.spotify_id?`https://open.spotify.com/album/${a.spotify_id}`:'',musicBrainzReleaseUrl:()=>'',
 showAlbumContextMenu:(...args)=>called.push(args),savedAlbumPlaylist:()=>null,navigator:{clipboard:{writeText:async s=>text.push(s)}},
 showToast(){},saveAlbumToLibrary:async a=>called.push(['save',a]),renderAlbumLibraryControl(){},deletePlaylist:async()=>{},
 albumControlKey:a=>a.spotify_id,queueAlbumDownloads:async v=>called.push(['download',v]),visibleAlbumControls:null,fetchAlbumTracks:async()=>[],
});
vm.runInContext(fs.readFileSync('static/album_controls.js','utf8'),context);
const api=context.window.MindinguflacAlbums,album={spotify_id:'ExactDeluxeRelease',album:'Album',artist:'Artist',tracks:[{title:'Song'}]};
(async()=>{
 api.bind(album,album.tracks,{});assert.equal($('albumViewLabel').textContent,'List');
 $('albumViewToggle').onclick();assert.equal($('albumViewMenu').hidden,false);
 compactOption.onclick();assert.equal($('albumViewLabel').textContent,'Compact');assert.ok($('albumTrackList').classList.contains('album-compact'));
 assert.equal(compactOption['aria-checked'],'true');assert.equal(listOption['aria-checked'],'false');
 api.bind(album,album.tracks,{});assert.equal($('albumViewLabel').textContent,'Compact','view survives reopening');
 listOption.onclick();assert.equal($('albumTrackList').classList.contains('album-compact'),false);
 $('albumMore').onclick({screenX:0,screenY:0,preventDefault(){},stopPropagation(){}});assert.equal(called[0][1],album);
 api.configureMenu(album);await $('ctxAlbumCopySpotify').onclick();assert.equal(text[0],'https://open.spotify.com/album/ExactDeluxeRelease');
 await $('ctxAlbumDownload').onclick();assert.equal(called.at(-1)[0],'download');assert.equal(called.at(-1)[1].tracks[0].title,'Song');
 await $('ctxAlbumSaveLibrary').onclick();assert.equal(called.at(-1)[0],'save');
 const operations=[],ctx=new Proxy({measureText:s=>({width:String(s).length*15}),createLinearGradient:()=>({addColorStop(){}})},
  {get:(target,key)=>key in target?target[key]:(...args)=>operations.push([key,...args])});
 const canvas={getContext:()=>ctx};api.drawCard(canvas,album,null,'#214b38');
 assert.equal(canvas.width,720);assert.equal(canvas.height,1080);
 assert.ok(operations.some(o=>o[0]==='fillText' && o[1]==='Album'));
 assert.ok(operations.some(o=>o[0]==='fillText' && o[1]==='Artist'));
 assert.ok(operations.some(o=>o[0]==='fillText' && o[1].includes('Mindinguflac')));
 console.log('Desktop List/Compact persistence, overflow reuse, exact album sharing, queue action and share-card dimensions/content passed');
})().catch(e=>{console.error(e);process.exitCode=1;});

// The share dialog uses the same tested downward-dismiss gesture as other panels.
const appSource=fs.readFileSync('static/app.js','utf8');
const swipeSource=appSource.slice(appSource.indexOf('function attachPanelSwipeClose('),appSource.indexOf('function attachQueueTabSwipe('));
const touchHandlers={},timeouts=[];let dismissed=0;
const swipePanel={dataset:{},style:{},scrollTop:0,addEventListener:(name,handler)=>touchHandlers[name]=handler};
const swipeContext=vm.createContext({setTimeout:fn=>timeouts.push(fn)});vm.runInContext(swipeSource,swipeContext);
swipeContext.attachPanelSwipeClose(swipePanel,swipePanel,()=>dismissed++);
const touch=y=>({touches:[{clientY:y}],target:{closest:()=>null},preventDefault(){}});
touchHandlers.touchstart(touch(100));touchHandlers.touchmove(touch(145));touchHandlers.touchend();
assert.equal(dismissed,0);assert.equal(swipePanel.style.transform,'');
touchHandlers.touchstart(touch(100));touchHandlers.touchmove(touch(215));touchHandlers.touchend();timeouts.shift()();
assert.equal(dismissed,1);assert.equal(swipePanel.style.transform,'');
swipePanel.scrollTop=50;touchHandlers.touchstart(touch(100));touchHandlers.touchmove(touch(250));touchHandlers.touchend();
assert.equal(timeouts.length,0,'scrolling share content does not dismiss it');
assert.ok(fs.readFileSync('static/album_controls.js','utf8').includes('attachPanelSwipeClose(dialog,dialog,()=>dialog.close())'));
