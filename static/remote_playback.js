/* Paired Wi-Fi playback control. Bluetooth continues to select audio outputs. */
window.MindinguflacRemote = (() => {
  let route = null, local = null, receiving = null, timer = null, polling = false;
  let initialized = false, acks = [], applied = new Set(), lastError = '';
  const post = (path, body = {}) => api(`/api/remote/${path}`, {method:'POST', body:JSON.stringify(body), timeout:12000});
  const controlling = () => !!route;
  const portable = item => item ? trackIdentitySnapshot(item) : null;
  const publicTracks = tracks => (tracks || []).filter(playableQueueItem).map(portable);
  const position = () => route ? Number(route.snapshot?.position || 0) : currentPlaybackSeconds();
  function playerSnapshot() {
    const audio = $('audioPlayer');
    return {track:portable(state.currentTrack), queue:publicTracks(state.queue), queue_index:state.queueIndex,
      position:state.restoredPlaybackPending ? Number(state.pendingResumePosition || 0) : currentPlaybackSeconds() || 0,
      duration:state.nativeAudio.active ? state.nativeAudio.duration || knownTrackDurationSeconds(state.currentTrack) :
        (Number.isFinite(audio.duration) ? audio.duration : knownTrackDurationSeconds(state.currentTrack)) || 0,
      playing:isPlaybackVisiblyActive(), buffering:playbackTransportBusy(), volume:audio.volume,
      shuffle:state.isShuffle, repeat:state.isRepeat, error:lastError};
  }
  function banner() {
    let el = $('remotePlaybackBanner');
    if (!el) {
      el = document.createElement('div'); el.id = 'remotePlaybackBanner'; el.className = 'remote-playback-banner';
      el.setAttribute('role','status'); el.setAttribute('aria-live','polite');
      document.body.appendChild(el);
    }
    el.replaceChildren(); el.hidden = !route && !receiving;
    document.body.classList.toggle('has-remote-playback', !el.hidden);
    if (el.hidden) return;
    const label = document.createElement('span');
    label.textContent = route ? `${route.status === 'connecting' ? 'Connecting to' : 'Listening on'} ${route.name}${route.status === 'disconnected' ? ' · Disconnected' : ''}${route.status === 'failed' ? ' · Connection failed' : ''}`
      : `Controlled by ${receiving.controller_name}`;
    el.appendChild(label);
    if (route) {
      const exit = document.createElement('button'); exit.type = 'button'; exit.textContent = 'This device';
      exit.onclick = () => disconnect().catch(report); el.appendChild(exit);
    }
  }
  function report(error) { showToast(error.message || String(error), 6000); }
  function renderRemotePlayer() {
    if (!route) return;
    const s = route.snapshot || {}, track = s.track;
    const changed = trackKey(state.currentTrack || {}) !== trackKey(track || {});
    state.currentTrack = track || null; state.queue = s.queue || []; state.originalQueue = [...state.queue];
    state.queueIndex = Number.isInteger(s.queue_index) ? s.queue_index : -1; state.queueContext = null;
    state.isShuffle = !!s.shuffle; state.isRepeat = !!s.repeat;
    if (changed) {
      $('playerTitle').innerHTML = track ? albumLinkHtml(track, track.title) : 'Nothing playing';
      $('playerArtist').innerHTML = track ? artistLinkHtml(track) : '';
      bindEntityLinks($('playerTitle').parentElement);
      state.videoMode = false; state.currentLibraryPath = ''; state.videoFetch = {status:'',path:'',trackKey:''};
      renderSideCover(track || {});
      $('sideTitle').innerHTML = track ? albumLinkHtml(track,track.title) : 'No track selected';
      $('sideMeta').innerHTML = track ? artistLinkHtml(track) : '';
      bindEntityLinks(document.querySelector('.details-head'));
      const requestId = ++state.sidebarRequestId;
      state.sidebarTrackKey = track ? trackKey(track) : '';
      if (track) renderDetailsSidebar(track,null,requestId,'');
      else $('sideRichContent').replaceChildren();
    }
    $('playerMeta').textContent = route.error || (s.buffering ? 'Buffering on receiving device' : s.playing ? 'Playing' : 'Paused');
    const duration = Number(s.duration || 0), pos = Number(s.position || 0);
    $('currentTime').textContent = formatTime(pos); $('durationTime').textContent = formatTime(duration);
    $('seekBar').value = duration > 0 ? pos / duration * 1000 : 0;
    $('seekBar').style.backgroundSize = `${duration > 0 ? pos / duration * 100 : 0}% 100%`;
    $('volumeBar').value = Number(s.volume || 0);
    $('volumeBar').style.backgroundSize = `${Number(s.volume || 0) * 100}% 100%`;
    $('btnShuffle')?.classList.toggle('active', !!s.shuffle); $('btnRepeat')?.classList.toggle('active', !!s.repeat);
    $('albumShuffle')?.classList.toggle('active', !!s.shuffle);
    $('albumShuffle')?.setAttribute('aria-pressed',String(!!s.shuffle));
    syncPlayPauseButton(); syncActiveTrackRows(); updateSidebarNextQueue();
    if (!$('queuePanel').hidden) refreshQueuePanel();
    if (changed && state.lyrics.open && track) loadLyricsForTrack(track, {force:true}).catch(() => {});
    updateLyricsPosition(pos);
    if (track) pushAndroidNowPlaying({...track,position:pos,duration}, route.status==='active' && !!s.playing);
  }
  async function command(action, payload = {}) {
    if (!route || route.status !== 'active') throw new Error('Select the paired computer again to reconnect');
    const current = route;
    current.pending = true; syncPlayPauseButton();
    try {
      const result = await post('command', {action,payload});
      if (current !== route) return;
      if (!result.ok) throw new Error(result.error || 'Remote command failed');
      current.snapshot = result.snapshot; current.error = ''; renderRemotePlayer();
    } catch (error) { current.error = error.message; throw error; }
    finally { current.pending = false; if (route === current) renderRemotePlayer(); }
  }
  const send = (action, payload = {}) => command(action,payload).catch(report);
  async function quiesceLocal() {
    local = {track:state.currentTrack, queue:state.queue, originalQueue:state.originalQueue,
      queueContext:state.queueContext, queueIndex:state.queueIndex, position:currentPlaybackSeconds() || 0,
      shuffle:state.isShuffle, repeat:state.isRepeat};
    ++state.playbackRequestId;
    state.manualPauseRequested = true; state.autoplayWanted = false;
    state.restoredPlaybackPending = false;
    cancelAllPrefetchJobs('remote device selected');
    if (state.activeJobId) await api('/api/service/cancel', {method:'DELETE',body:JSON.stringify({job_id:state.activeJobId})}).catch(() => {});
    state.activeJobId = null;
    const audio = $('audioPlayer'); audio.pause(); audio.removeAttribute('src'); audio.load();
    $('sideVideoPlayer')?.pause?.();
    const pending = state.nativeAudioStart?.promise;
    if (pending) await pending.catch(() => {});
    await stopNativeAudio();
    state.audioBuffering = false; state.currentStreamUrl = '';
  }
  async function connect(device) {
    if (route) await disconnect();
    await quiesceLocal();
    route = {name:device.name || 'Computer',device_id:device.device_id,status:'connecting',snapshot:{},pending:true};
    const current = route; banner(); syncPlayPauseButton();
    try {
      const result = await post('connect',{device_id:device.device_id});
      if (route !== current) return;
      if (!result.ok || !result.session) throw new Error(result.error || 'Receiving player did not acknowledge the connection');
      Object.assign(current,{status:'active',pending:false,snapshot:result.snapshot,error:''});
      renderRemotePlayer(); banner(); await _refreshConnectPanel();
    } catch (error) {
      if (route === current) { current.status='failed';current.pending=false;current.error=error.message;banner();syncPlayPauseButton(); }
      throw error;
    }
  }
  async function disconnect() {
    const saved = local;
    route = null; local = null; banner();
    // Clear the controller route first; an unreachable receiver must never
    // trap the user in remote mode. The receiver lease clears its banner.
    post('disconnect').catch(() => {});
    if (saved) {
      state.currentTrack=saved.track;state.queue=saved.queue;state.originalQueue=saved.originalQueue;
      state.queueContext=saved.queueContext;state.queueIndex=saved.queueIndex;
      state.isShuffle=saved.shuffle;state.isRepeat=saved.repeat;
      state.pendingResumePosition=saved.position;state.restoredPlaybackPending=!!saved.track;
      state.manualPauseRequested=true;state.autoplayWanted=false;
      if (saved.track) prepareSelectedTrackUi(saved.track,`Paused at ${formatTime(saved.position)}`);
      else { $('playerTitle').textContent='Nothing playing';$('playerArtist').textContent='';$('playerMeta').textContent='';resetSeekUi();renderSideCover({});clearMediaSession(); }
    }
    syncPlayPauseButton(); if (!$('connectPanel').hidden) await _refreshConnectPanel();
  }
  async function applyCommand(entry) {
    const p = entry.payload || {};
    switch (entry.action) {
      case 'connect': break;
      case 'select':
        lastError='';
        state.pendingResumePosition=0;
        // Acknowledgement means accepted by the actual player. Playback is
        // reported separately, after its resolver/decoder starts producing it.
        selectMusicItem(p.track,'stream',p.queue.length ? p.queue : [p.track],null).catch(error => { lastError=error.message; });
        break;
      case 'play':
        if (!state.currentTrack) throw new Error('Choose a song first');
        if (!isPlaybackVisiblyActive() && !playbackTransportBusy()) $('playPause').onclick();
        break;
      case 'pause':
        state.manualPauseRequested=true;state.autoplayWanted=false;state.nativeAudioPauseAfterStart=true;
        if (state.nativeAudio.active) {
          const result=await api('/api/native_audio/pause',{method:'POST',body:'{}'});
          if (result.ok === false) throw new Error(result.error || 'Receiver could not pause');
          state.nativeAudio.playing=!!result.playing;
        }
        $('audioPlayer').pause();state.audioBuffering=false;syncPlayPauseButton();break;
      case 'next': playQueueOffset(1); break;
      case 'previous': playQueueOffset(-1); break;
      case 'seek':
        if (state.restoredPlaybackPending) {
          state.pendingResumePosition = Math.min(playerSnapshot().duration || p.position,p.position);
          $('currentTime').textContent = formatTime(state.pendingResumePosition);
          $('seekBar').value = state.pendingResumePosition/Math.max(.001,playerSnapshot().duration)*1000;
        } else { $('seekBar').value=Number(p.position)/Math.max(.001,playerSnapshot().duration)*1000;$('seekBar').oninput(); }
        break;
      case 'volume': setPlayerVolume(p.volume);break;
      case 'shuffle': if (state.isShuffle !== p.enabled) $('btnShuffle').onclick();break;
      case 'repeat': if (state.isRepeat !== p.enabled) $('btnRepeat').onclick();break;
      case 'queue_append': appendTracksToPlaybackQueue(p.tracks);break;
      case 'queue_reorder':
        if (!reorderQueueTrack(p.from_index,p.to_index)) throw new Error('Queue changed. Try again.');break;
      case 'queue_remove':
        if (p.index === state.queueIndex || !state.queue[p.index]) throw new Error('That song cannot be removed from the queue');
        state.queue.splice(p.index,1);if(p.index<state.queueIndex)state.queueIndex--;
        state.originalQueue=[...state.queue];refreshQueuePanel();updateSidebarNextQueue();break;
      default: throw new Error('Unsupported playback command');
    }
  }
  async function poll() {
    if (polling) return;
    polling=true;
    try {
      if (IS_ANDROID) {
        if (!route || route.status === 'connecting' || route.status === 'failed') return;
        if (route.pending) return;
        const current=route, result=await api('/api/remote/status',{timeout:12000});
        if (current !== route || current.pending) return;
        if (result.route === null) { await disconnect(); return; }
        if (!result.ok || !result.route || !result.session) {
          current.status='disconnected';current.error=result.error || 'Remote session ended';
        } else { current.status='active';current.snapshot=result.snapshot;current.error=''; }
        renderRemotePlayer();banner();
      } else {
        const batch=acks;acks=[];
        let result;
        try { result=await post('local',{snapshot:playerSnapshot(),acks:batch}); }
        catch(error) { acks.unshift(...batch);throw error; }
        receiving=result.session;banner();
        for (const entry of result.commands || []) {
          if (applied.has(entry.id)) continue;
          applied.add(entry.id);if(applied.size>1000)applied.delete(applied.values().next().value);
          try { await applyCommand(entry);acks.push({id:entry.id}); }
          catch(error) { acks.push({id:entry.id,error:error.message}); }
        }
      }
    } catch(error) {
      if (!IS_ANDROID) { receiving=null;banner(); }
      if (route) { route.status='disconnected';route.error=error.message;renderRemotePlayer();banner(); }
    } finally { polling=false; }
  }
  async function renderDevices(list) {
    if (!IS_ANDROID) return;
    const data=await api('/api/pairing/status').catch(() => null);
    if (!data) return;
    const heading=document.createElement('li');heading.className='connect-section-label';heading.textContent='Paired computers · Wi-Fi';list.appendChild(heading);
    if (!data.paired || !data.pair?.device_id) {
      const item=document.createElement('li');item.className='connect-device-item';
      const text=document.createElement('span');text.textContent='Pair a computer in Settings';item.appendChild(text);
      item.onclick=() => {closeConnectPanel();pushPage(renderSettings);};list.appendChild(item);return;
    }
    const device=data.pair;
    if(route)for(const physical of list.querySelectorAll('[data-audio-output]'))physical.classList.remove('active');
    const row=document.createElement('li');row.className='connect-device-item';
    row.classList.toggle('active',route?.device_id===device.device_id && route.status==='active');
    const icon=document.createElement('i');icon.className='bi bi-laptop connect-device-icon';
    const info=document.createElement('div');info.className='connect-device-info';
    const name=document.createElement('span');name.className='connect-device-name';name.textContent=device.name || 'Paired computer';
    const sub=document.createElement('span');sub.className='connect-device-sub';
    sub.textContent=route?.status==='active'?'Listening here':'Play and control music over Wi-Fi';
    info.append(name,sub);row.append(icon,info);
    row.onclick=() => connect(device).catch(report);list.appendChild(row);
  }
  function wrap(name, localFunction, remoteFunction) {
    return function(...args) { return route ? remoteFunction(...args) : localFunction.apply(this,args); };
  }
  async function initialize() {
    if (initialized) return; initialized=true;
    const localSelect=selectMusicItem;
    selectMusicItem=function(item,mode='stream',tracks=null,context=null) {
      if (!route || mode !== 'stream' || !playableQueueItem(item)) return localSelect(item,mode,tracks,context);
      return send('select',{track:portable(item),queue:publicTracks(tracks || state.queue.length && state.queue || [item])});
    };
    playQueueOffset=wrap('next',playQueueOffset,delta => send(delta>0?'next':'previous'));
    seekBy=wrap('seek',seekBy,seconds => send('seek',{position:Math.max(0,position()+seconds)}));
    setPlayerVolume=wrap('volume',setPlayerVolume,volume => send('volume',{volume}));
    reorderQueueTrack=wrap('reorder',reorderQueueTrack,(from,to)=>send('queue_reorder',{from_index:from,to_index:to}));
    appendTracksToPlaybackQueue=wrap('append',appendTracksToPlaybackQueue,tracks=>send('queue_append',{tracks:publicTracks(tracks)}));
    currentPlaybackSeconds=wrap('clock',currentPlaybackSeconds,position);
    audiblePlaybackSeconds=wrap('audibleClock',audiblePlaybackSeconds,position);
    isPlaybackVisiblyActive=wrap('playing',isPlaybackVisiblyActive,()=>route.status==='active' && !!route.snapshot?.playing);
    playbackTransportBusy=wrap('busy',playbackTransportBusy,()=>route.status!=='active' || !!route.pending || !!route.snapshot?.buffering);
    persistPlaybackSnapshot=wrap('persist',persistPlaybackSnapshot,()=>{});
    const localSync=syncPlayPauseButton;
    syncPlayPauseButton=function() {
      if (!route) return localSync();
      const busy=playbackTransportBusy(),button=$('playPause');button.disabled=busy;
      button.setAttribute('aria-label',busy?'Connecting':route.snapshot?.playing?'Pause':'Play');
      button.setAttribute('aria-busy',String(busy));
      button.querySelector('i').className=route.snapshot?.playing?'bi bi-pause-fill':'bi bi-play-fill';
    };
    const localPlay=$('playPause').onclick,localSeek=$('seekBar').oninput,localMute=$('muteToggle').onclick;
    $('playPause').onclick=()=>route?send(route.snapshot?.playing?'pause':'play'):localPlay();
    $('seekBar').oninput=()=>route?send('seek',{position:Number($('seekBar').value)/1000*Number(route.snapshot?.duration || 0)}):localSeek();
    $('muteToggle').onclick=()=>route?send('volume',{volume:route.snapshot?.volume>0?0:1}):localMute();
    for (const [id,action,key] of [['btnShuffle','shuffle','shuffle'],['btnRepeat','repeat','repeat']]) {
      const el=$(id),handler=el.onclick;el.onclick=()=>route?send(action,{enabled:!route.snapshot?.[key]}):handler();
    }
    // This phone and physical audio outputs both explicitly leave remote mode.
    document.addEventListener('click',event=>{
      if (!route) return;
      const target=event.target.closest('#ctxAddQueue,#ctxRemoveQueue,#ctxAlbumAddQueue,#ctxArtistAddQueue');
      if (!target) return;
      event.preventDefault();event.stopImmediatePropagation();
      const action=async()=>{
        let tracks=[];
        if(target.id==='ctxAddQueue') tracks=[contextMenuTargetTrack];
        else if(target.id==='ctxRemoveQueue') {
          const index=state.queue.findIndex((t,i)=>i>state.queueIndex && trackKey(t)===trackKey(contextMenuTargetTrack));
          await command('queue_remove',{index});return;
        } else if(target.id==='ctxAlbumAddQueue') tracks=contextMenuTargetAlbum?.tracks?.length?contextMenuTargetAlbum.tracks:await fetchAlbumTracks(contextMenuTargetAlbum);
        else tracks=await fetchArtistTopTracks(contextMenuTargetArtist);
        await command('queue_append',{tracks:publicTracks(tracks)});
      };
      action().catch(report);for(const id of ['trackContextMenu','albumContextMenu','artistContextMenu'])$(id).hidden=true;
    },true);
    await poll();timer=setInterval(poll,750);
    window.addEventListener('pagehide',()=>{
      if(!IS_ANDROID) post('local',{snapshot:playerSnapshot(),acks,closing:true}).catch(()=>{});
      else if(route)post('disconnect').catch(()=>{});
    });
  }
  return {initialize,renderDevices,connect,disconnect,command,isController:controlling,poll,applyCommand};
})();
