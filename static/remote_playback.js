/* Paired Wi-Fi playback control. Bluetooth continues to select audio outputs. */
window.MindinguflacRemote = (() => {
  let route = null, local = null, receiving = null, timer = null, polling = false;
  let initialized = false, acks = [], applied = new Set(), lastError = '';
  let volumeTarget=null, volumeSending=false, nativeVolumeState=null, volumeHudTimer=null;
  let offlineTab='local', offlineConnection='', offlineCache=null, offlinePending=null;
  let layoutObserver=null, layoutMeasureQueued=false;
  const post = (path, body = {}) => api(`/api/remote/${path}`, {method:'POST', body:JSON.stringify(body), timeout:12000});
  const controlling = () => !!route;
  const portable = item => item ? trackIdentitySnapshot(item) : null;
  const publicTracks = tracks => (tracks || []).filter(playableQueueItem).map(portable);
  const displayCache = new Map();
  const displayKey = track => `${trackKey(track || {})}|${track?.album_context?.spotify_id || track?.album_spotify_id || track?.album || ''}`;
  function localArtwork(value) {
    if (!value) return '';
    try {
      const parsed = new URL(String(value),window.location.origin);
      if (parsed.pathname === '/api/image') {
        const source = parsed.searchParams.get('url');
        return source && /^https?:\/\//i.test(source) ? `${API_BASE}/api/image?url=${encodeURIComponent(source)}` : '';
      }
      if (String(value).startsWith('/api/')) return `${API_BASE}${value}`;
      if (parsed.origin === window.location.origin) return parsed.href;
      if (['localhost','127.0.0.1','::1','[::1]'].includes(parsed.hostname)) return '';
      return /^https?:$/.test(parsed.protocol) ? `${API_BASE}/api/image?url=${encodeURIComponent(parsed.href)}` : '';
    } catch (_) { return ''; }
  }
  function cachedDisplayArtwork(track) {
    const albumId=track.album_context?.spotify_id || track.album_spotify_id;
    for (const playlist of state.playlists || []) for (const saved of playlist.tracks || []) {
      if (trackKey(saved)!==trackKey(track)) continue;
      const savedAlbum=saved.album_context?.spotify_id || saved.album_spotify_id || playlist.album_spotify_id;
      if (albumId && albumId!==savedAlbum) continue;
      const art=localArtwork(saved.artwork_url || playlist.artwork_url);
      if (art) return art;
    }
    return '';
  }
  async function resolveDisplayArtwork(track,key,entry) {
    try {
      let albumId=track.album_context?.spotify_id || track.album_spotify_id;
      if (!albumId && /^[A-Za-z0-9]{22}$/.test(track.spotify_id || '')) {
        const result=await api(`/api/music/track_album?spotify_id=${encodeURIComponent(track.spotify_id)}`,{timeout:20000}).catch(()=>({}));
        albumId=result.album_spotify_id || result.spotify_id;
        entry.artwork=localArtwork(result.artwork_url);
      }
      if (!entry.artwork && /^[A-Za-z0-9]{22}$/.test(albumId || '')) {
        const query=new URLSearchParams({spotify_id:albumId,artist:track.album_artist || track.artist || '',album:track.album || '',details:'0'});
        const result=await api(`/api/music/album_tracks?${query}`,{timeout:30000}).catch(()=>({}));
        entry.artwork=localArtwork(result.artwork_url || result.tracks?.find(t=>t.artwork_url)?.artwork_url);
      }
      if (!entry.artwork) {
        const result=await api('/api/music/track_metadata',{method:'POST',body:JSON.stringify({track:portable(track)}),timeout:30000});
        entry.artwork=localArtwork(result.track?.artwork_url);
      }
    } catch (_) {} finally {
      entry.pending=false;entry.retryAt=Date.now()+30000;
      if (entry.artwork && route && displayKey(route.snapshot?.track)===key) renderRemotePlayer();
      if (entry.artwork && !route && displayKey(state.currentTrack)===key && !localArtwork(state.currentTrack.artwork_url)) {
        state.currentTrack.artwork_url=entry.artwork;renderSideCover(state.currentTrack);
      }
    }
  }
  function displayTrack(track) {
    if (!track) return null;
    const key=displayKey(track);
    let entry=displayCache.get(key);
    const supplied=localArtwork(track.artwork_url) || cachedDisplayArtwork(track);
    if (supplied) return {...track,artwork_url:supplied};
    // This path always belongs to this device, never to its remote peer.
    if (!route && state.currentLibraryPath && trackKey(track)===trackKey(state.currentTrack))
      return {...track,artwork_url:`${API_BASE}/api/library/artwork?path=${encodeURIComponent(state.currentLibraryPath)}`};
    if (!entry) {
      entry={artwork:'',pending:false,retryAt:0};displayCache.set(key,entry);
      if(displayCache.size>200)displayCache.delete(displayCache.keys().next().value);
    }
    if (!entry.artwork && !entry.pending && Date.now()>=entry.retryAt) {
      entry.pending=true;resolveDisplayArtwork(track,key,entry);
    }
    return {...track,artwork_url:entry.artwork || ''};
  }
  const position = () => route ? Number(route.snapshot?.position || 0) : currentPlaybackSeconds();
  function playerSnapshot() {
    const audio = $('audioPlayer');
    const current=displayTrack(state.currentTrack);
    if (current?.artwork_url && !localArtwork(state.currentTrack?.artwork_url)) {
      state.currentTrack.artwork_url=current.artwork_url;renderSideCover(state.currentTrack);
    }
    return {track:portable(state.currentTrack), queue:publicTracks(state.queue), queue_index:state.queueIndex,
      position:state.restoredPlaybackPending ? Number(state.pendingResumePosition || 0) : currentPlaybackSeconds() || 0,
      duration:state.nativeAudio.active ? state.nativeAudio.duration || knownTrackDurationSeconds(state.currentTrack) :
        (Number.isFinite(audio.duration) ? audio.duration : knownTrackDurationSeconds(state.currentTrack)) || 0,
      playing:isPlaybackVisiblyActive(), buffering:playbackTransportBusy(), volume:audio.volume,
      shuffle:state.isShuffle, repeat:state.isRepeat, error:lastError,
      status:$('playerMeta')?.textContent || state.playerStatus || '',
      status_mode:state.audioBuffering && state.playerStatusIconMode==='ready'?'buffering':state.playerStatusIconMode || 'ready',
      progress:Math.max(0,Math.min(100,Number(state.playerStatusIconPct)||0)),
      quality_label:state.currentTrack ? qualityLabelForTrack(state.currentTrack) : '',
      queue_title:state.queueContext?.title || state.queueContext?.name || ''};
  }
  const offlineConnected=()=>route?.status==='active';
  function offlinePlaylists(playlists) {
    const result=(playlists || []).filter(pl=>!pl.remote_placeholder);
    if(offlineConnected() && !result.some(pl=>pl.id==='__offline__'))
      result.unshift({id:'__offline__',name:'Offline',playlist_origin:'offline',read_only:true,remote_placeholder:true,tracks:[],artwork_urls:[],metadata_fetched:true});
    return result;
  }
  function offlineView(localPlaylist) {
    if(offlineTab!=='remote' || !offlineConnected())return localPlaylist;
    const tracks=offlineCache?.device_id===route.device_id ? offlineCache.tracks : [];
    return {...localPlaylist,tracks,artwork_urls:[...new Set(tracks.map(t=>t.artwork_url).filter(Boolean))].slice(0,4),
      description:`Downloaded on ${route.name}`,offline_message:offlinePending?'Loading downloaded songs…':offlineCache?.error || 'No songs downloaded on this device.'};
  }
  function offlineTabs() {
    if(!offlineConnected())return '';
    return `<div class="offline-device-tabs" role="tablist" aria-label="Offline music location"><button type="button" role="tab" data-offline-device="local" aria-selected="${offlineTab==='local'}">This phone</button><button type="button" role="tab" title="${esc(route.name)}" aria-label="${esc(route.name)} (connected device)" data-offline-device="remote" aria-selected="${offlineTab==='remote'}">Connected device</button></div>`;
  }
  function redrawOffline() {
    if(state.activePlaylistId!=='__offline__' || !$('pageContent')?.querySelector('[data-playlist-page="__offline__"]'))return;
    const playlist=state.playlists.find(pl=>pl.id==='__offline__');
    if(!playlist)return;
    const top=$('pageContent').querySelector('.scroll-area')?.scrollTop || 0;
    _renderPlaylistContent(playlist);
    const scroll=$('pageContent').querySelector('.scroll-area');if(scroll)scroll.scrollTop=top;
  }
  async function fetchOffline() {
    if(!offlineConnected() || offlinePending)return offlinePending;
    const current=route;
    offlinePending=(async()=>{
      try {
        const result=await api('/api/remote/offline',{timeout:20000});
        if(route!==current || !offlineConnected())return;
        if(!result.ok || !result.route)throw Error(result.error || 'The connected device is unavailable');
        const tracks=(result.tracks || []).map(item=>({...item,remote_device_id:current.device_id,
          artwork_url:localArtwork(item.artwork_url) || cachedDisplayArtwork(item)}));
        offlineCache={device_id:current.device_id,tracks,updated:Date.now()};
        hydrateOfflineArtwork(current,offlineCache).catch(()=>{});
      } catch(error) {
        if(route===current)offlineCache={device_id:current.device_id,tracks:[],updated:Date.now(),error:error.message};
      } finally {offlinePending=null;redrawOffline();}
    })();
    redrawOffline();return offlinePending;
  }
  async function hydrateOfflineArtwork(current,cache) {
    const groups=new Map();
    for(const track of cache.tracks) {
      if(track.artwork_url)continue;
      const key=track.album_context?.spotify_id || track.album_spotify_id || displayKey(track);
      if(!groups.has(key))groups.set(key,[]);groups.get(key).push(track);
    }
    const tasks=[...groups.values()];
    const worker=async()=>{
      while(tasks.length && route===current && offlineCache===cache && offlineTab==='remote' && offlineConnected()) {
        const group=tasks.shift(),track=group[0],key=displayKey(track);
        let entry=displayCache.get(key);
        if(!entry){entry={artwork:'',pending:false,retryAt:0};displayCache.set(key,entry);}
        if(!entry.artwork && !entry.pending && Date.now()>=entry.retryAt){entry.pending=true;await resolveDisplayArtwork(track,key,entry);}
        if(entry.artwork && offlineCache===cache){group.forEach(t=>t.artwork_url=entry.artwork);redrawOffline();}
      }
    };
    await Promise.all([worker(),worker()]);
  }
  function bindOfflineTabs(localPlaylist) {
    $('pageContent').querySelectorAll('[data-offline-device]').forEach(button=>{
      button.onclick=()=>{
        offlineTab=button.dataset.offlineDevice;
        if(offlineTab==='remote' && (!offlineCache || Date.now()-offlineCache.updated>15000))fetchOffline();
        _renderPlaylistContent(localPlaylist);
      };
    });
  }
  function syncOfflineConnection() {
    const key=offlineConnected()?route.device_id:'';
    if(key!==offlineConnection) {
      offlineConnection=key;offlineTab='local';offlineCache=null;
      state.playlists=offlinePlaylists(state.playlists);
      renderSidebarPlaylists();
      if(state.activePlaylistId==='__offline__' && !state.playlists.some(pl=>pl.id==='__offline__')) {
        state.activePlaylistId=null;replacePage(window.matchMedia('(max-width: 900px)').matches?renderMobileLibraryPage:renderHomePage);
      } else redrawOffline();
    }
    if(key && offlineTab==='remote' && state.activePlaylistId==='__offline__' && (!offlineCache || Date.now()-offlineCache.updated>15000))fetchOffline();
  }
  function syncNativeRemoteVolume() {
    if (!IS_ANDROID || !window.MindinguflacAndroid?.setRemotePlayback) return;
    const enabled=route?.status==='active';
    if (!enabled && nativeVolumeState===null) return;
    const volume=Math.round(Math.max(0,Math.min(1,Number(volumeTarget ?? route?.snapshot?.volume ?? 1)))*100);
    const key=`${enabled}:${enabled?volume:0}`;
    if(key===nativeVolumeState)return;
    nativeVolumeState=key;
    window.MindinguflacAndroid.setRemotePlayback(enabled,volume);
  }
  function updateVolumeHud(volume) {
    const hud=$('remoteVolumeHud');if(!hud || !route)return;
    const percent=Math.round(Math.max(0,Math.min(1,volume))*100);
    $('remoteVolumeHudDevice').textContent=route.name;
    $('remoteVolumeHudPercent').textContent=`${percent}%`;
    $('remoteVolumeHudBar').style.width=`${percent}%`;
    $('remoteVolumeHudIcon').className=percent===0?'bi bi-volume-mute-fill':percent<50?'bi bi-volume-down-fill':'bi bi-volume-up-fill';
    hud.setAttribute('aria-label',`${route.name} volume ${percent}%`);
    hud.setAttribute('aria-busy',String(volumeTarget!==null));
  }
  function showVolumeHud(volume) {
    if(!IS_ANDROID || !offlineConnected())return;
    let hud=$('remoteVolumeHud');
    if(!hud) {
      hud=document.createElement('div');hud.id='remoteVolumeHud';hud.className='remote-volume-hud';
      hud.setAttribute('role','status');hud.setAttribute('aria-live','polite');
      hud.innerHTML='<i id="remoteVolumeHudIcon" class="bi bi-volume-up-fill"></i><div class="remote-volume-hud-info"><span id="remoteVolumeHudDevice"></span><div class="remote-volume-hud-track"><span id="remoteVolumeHudBar"></span></div></div><strong id="remoteVolumeHudPercent"></strong>';
      document.body.appendChild(hud);
    }
    hud.hidden=false;updateVolumeHud(volume);hud.classList.toggle('visible',true);
    clearTimeout(volumeHudTimer);volumeHudTimer=setTimeout(()=>hud.classList.toggle('visible',false),1800);
  }
  function renderRemoteVolume() {
    if (!route) return;
    const volume=Number(volumeTarget ?? route.snapshot?.volume ?? 0);
    $('volumeBar').value=volume;$('volumeBar').style.backgroundSize=`${volume*100}% 100%`;
    const icon=$('muteToggle')?.querySelector('i');
    if(icon)icon.className=volume<=.0001?'bi bi-volume-mute':volume<.5?'bi bi-volume-down':'bi bi-volume-up';
    updateVolumeHud(volume);syncNativeRemoteVolume();
  }
  async function setRemoteVolume(value) {
    if (!route || !Number.isFinite(Number(value))) return;
    if (route.status!=='active') {report(new Error('Reconnect the selected device to change its volume'));return;}
    volumeTarget=Math.max(0,Math.min(1,Number(value)));renderRemoteVolume();showVolumeHud(volumeTarget);
    if(volumeSending)return;
    const current=route;volumeSending=true;
    try {
      while(route===current && current.status==='active' && volumeTarget!==null) {
        const target=volumeTarget;
        await command('volume',{volume:target});
        if(volumeTarget===target)volumeTarget=null;
      }
    } catch(error) {volumeTarget=null;report(error);}
    finally {volumeSending=false;if(route)renderRemoteVolume();}
  }
  const adjustVolumeBy=delta=>setRemoteVolume(Number(volumeTarget ?? route?.snapshot?.volume ?? 0)+Number(delta));
  function observeRemoteLayout(el) {
    if (!layoutObserver && typeof ResizeObserver === 'function') {
      layoutObserver = new ResizeObserver(() => {
        if (layoutMeasureQueued) return;
        layoutMeasureQueued = true;
        requestAnimationFrame(() => {
          layoutMeasureQueued = false;
          const banner = $('remotePlaybackBanner'), player = document.querySelector('.player');
          if (banner && !banner.hidden) document.body.style.setProperty('--remote-playback-banner-height', `${Math.ceil(banner.getBoundingClientRect().height)}px`);
          if (player) document.body.style.setProperty('--player-controls-height', `${Math.ceil(player.getBoundingClientRect().height)}px`);
        });
      });
    }
    if (!layoutObserver || !el || el.dataset.remoteLayoutObserved) return;
    el.dataset.remoteLayoutObserved='true';layoutObserver.observe(el);
  }
  function banner() {
    syncNativeRemoteVolume();syncOfflineConnection();
    if(!offlineConnected())$('remoteVolumeHud')?.classList.toggle('visible',false);
    let el = $('remotePlaybackBanner');
    if (!el) {
      el = document.createElement('div'); el.id = 'remotePlaybackBanner'; el.className = 'remote-playback-banner';
      el.setAttribute('role','button'); el.tabIndex=0; el.setAttribute('aria-live','polite');
      el.onclick=()=>openConnectPanel();
      el.onkeydown=event=>{if(event.key==='Enter' || event.key===' '){event.preventDefault();openConnectPanel();}};
      document.body.appendChild(el);
    }
    observeRemoteLayout(el);
    observeRemoteLayout(document.querySelector('.player'));
    el.replaceChildren(); el.hidden = !route && !receiving;
    document.body.classList.toggle('has-remote-playback', !el.hidden);
    if (el.hidden) return;
    const label = document.createElement('span');
    label.textContent = route ? `${route.status === 'connecting' ? 'Connecting to' : 'Listening on'} ${route.name}${route.status === 'disconnected' ? ' · Disconnected' : ''}${route.status === 'failed' ? ' · Connection failed' : ''}`
      : `Controlled by ${receiving.controller_name}`;
    el.appendChild(label);
    el.setAttribute('aria-label',`${label.textContent}. Open Devices`);
  }
  function report(error) { showToast(error.message || String(error), 6000); }
  function renderRemotePlayer() {
    if (!route) return;
    const s = route.snapshot || {}, track = displayTrack(s.track);
    const artChanged=String(state.currentTrack?.artwork_url || '')!==String(track?.artwork_url || '');
    const changed = trackKey(state.currentTrack || {}) !== trackKey(track || {});
    state.currentTrack = track || null; state.queue = s.queue || []; state.originalQueue = [...state.queue];
    state.queueIndex = Number.isInteger(s.queue_index) ? s.queue_index : -1; state.queueContext = s.queue_title ? {title:s.queue_title} : null;
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
      if (track) renderDetailsSidebar(track,null,requestId,s.quality_label || '');
      else $('sideRichContent').replaceChildren();
    }
    if (artChanged && !changed) renderSideCover(track || {});
    $('sideMeta').innerHTML=(track ? artistLinkHtml(track) : '')+(s.quality_label ? `<span class="quality-pill">${esc(s.quality_label)}</span>` : '');
    state.playerStatus=route.error || s.status || (s.buffering ? 'Buffering on receiving device' : s.playing ? 'Playing' : 'Paused');
    $('playerMeta').textContent=state.playerStatus;
    const statusMode=route.error || s.error ? 'error' : s.buffering && (!s.status_mode || s.status_mode==='ready') ? 'buffering' : s.status_mode || 'ready';
    setPlayerStatusIcon(statusMode,Number(s.progress)||0);
    const videoSwitch=$('sideVideoSwitch');if(videoSwitch)videoSwitch.hidden=true;
    const duration = Number(s.duration || 0), pos = Number(s.position || 0);
    $('currentTime').textContent = formatTime(pos); $('durationTime').textContent = formatTime(duration);
    $('seekBar').value = duration > 0 ? pos / duration * 1000 : 0;
    $('seekBar').style.backgroundSize = `${duration > 0 ? pos / duration * 100 : 0}% 100%`;
    renderRemoteVolume();
    $('btnShuffle')?.classList.toggle('active', !!s.shuffle); $('btnRepeat')?.classList.toggle('active', !!s.repeat);
    $('albumShuffle')?.classList.toggle('active', !!s.shuffle);
    $('albumShuffle')?.setAttribute('aria-pressed',String(!!s.shuffle));
    syncPlayPauseButton(); syncActiveTrackRows(); updateSidebarNextQueue();
    if (!$('queuePanel').hidden) refreshQueuePanel();
    if (changed && state.lyrics.open && track) loadLyricsForTrack(track, {force:true}).catch(() => {});
    updateLyricsPosition(pos);
    if (track) pushAndroidNowPlaying({...track,artwork_url:absoluteUrl(track.artwork_url || ''),position:pos,duration}, route.status==='active' && !!s.playing);
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
    route = null; local = null; volumeTarget=null; banner();
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
    setPlayerStatusIcon('ready');
    renderSideVideoButton();
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
      if(item?.remote_device_id && (!offlineConnected() || route.device_id!==item.remote_device_id)){report(new Error('Reconnect the device that downloaded this song'));return Promise.resolve();}
      if (!route || mode !== 'stream' || !playableQueueItem(item)) return localSelect(item,mode,tracks,context);
      return send('select',{track:portable(item),queue:publicTracks(tracks || state.queue.length && state.queue || [item])});
    };
    playQueueOffset=wrap('next',playQueueOffset,delta => send(delta>0?'next':'previous'));
    seekBy=wrap('seek',seekBy,seconds => send('seek',{position:Math.max(0,position()+seconds)}));
    setPlayerVolume=wrap('volume',setPlayerVolume,setRemoteVolume);
    changeVolumeBy=wrap('adjustVolume',changeVolumeBy,adjustVolumeBy);
    syncVolumeBar=wrap('volumeUi',syncVolumeBar,renderRemoteVolume);
    reorderQueueTrack=wrap('reorder',reorderQueueTrack,(from,to)=>send('queue_reorder',{from_index:from,to_index:to}));
    appendTracksToPlaybackQueue=wrap('append',appendTracksToPlaybackQueue,tracks=>send('queue_append',{tracks:publicTracks(tracks)}));
    currentPlaybackSeconds=wrap('clock',currentPlaybackSeconds,position);
    audiblePlaybackSeconds=wrap('audibleClock',audiblePlaybackSeconds,position);
    isPlaybackVisiblyActive=wrap('playing',isPlaybackVisiblyActive,()=>route.status==='active' && !!route.snapshot?.playing);
    playbackTransportBusy=wrap('busy',playbackTransportBusy,()=>route.status!=='active' || !!route.pending || !!route.snapshot?.buffering);
    persistPlaybackSnapshot=wrap('persist',persistPlaybackSnapshot,()=>{});
    // Remote control must never start a local stream, audio/video download or
    // stale prefetch timer. Metadata lookup above remains available locally.
    prefetchOneTrack=wrap('prefetch',prefetchOneTrack,()=>Promise.resolve());
    prefetchNextTracks=wrap('prefetchNext',prefetchNextTracks,()=>Promise.resolve());
    prefetchNextVideos=wrap('prefetchVideos',prefetchNextVideos,()=>{});
    _triggerVideoFetchForTrack=wrap('videoPrefetch',_triggerVideoFetchForTrack,()=>{});
    fetchVideoForTrack=wrap('video',fetchVideoForTrack,()=>Promise.resolve());
    startServiceDownload=wrap('download',startServiceDownload,()=>Promise.resolve());
    playFromLibraryPath=wrap('libraryPlay',playFromLibraryPath,()=>Promise.resolve());
    startNativeAudio=wrap('nativeStart',startNativeAudio,()=>Promise.resolve(false));
    const localSync=syncPlayPauseButton;
    syncPlayPauseButton=function() {
      if (!route) return localSync();
      const busy=playbackTransportBusy(),button=$('playPause');button.disabled=busy;
      button.setAttribute('aria-label',busy?(route.status!=='active'?'Connecting':route.snapshot?.status_mode==='downloading'?'Loading':'Buffering'):route.snapshot?.playing?'Pause':'Play');
      button.setAttribute('aria-busy',String(busy));
      button.querySelector('i').className=route.snapshot?.playing?'bi bi-pause-fill':'bi bi-play-fill';
    };
    const localPlay=$('playPause').onclick,localSeek=$('seekBar').oninput,localMute=$('muteToggle').onclick;
    $('playPause').onclick=()=>route?send(route.snapshot?.playing?'pause':'play'):localPlay();
    $('seekBar').oninput=()=>route?send('seek',{position:Number($('seekBar').value)/1000*Number(route.snapshot?.duration || 0)}):localSeek();
    $('muteToggle').onclick=()=>{
      if(!route)return localMute();
      const current=Number(volumeTarget ?? route.snapshot?.volume ?? 0);
      if(current>0){route.preMuteVolume=current;return setRemoteVolume(0);}
      return setRemoteVolume(route.preMuteVolume || 1);
    };
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
    });
  }
  return {initialize,renderDevices,connect,disconnect,command,isController:controlling,poll,applyCommand,setVolume:setRemoteVolume,adjustVolumeBy,backgroundHeartbeat:()=>{if(offlineConnected())return poll();},offlinePlaylists,offlineView,offlineTabs,bindOfflineTabs,fetchOffline};
})();
