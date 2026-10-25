/* Album toolbar, view options and user-initiated album-card sharing. */
window.MindinguflacAlbums = (() => {
  let shareRevision=0;
  const VIEW_KEY='mindinguflac.albumView.v1';
  const mobile=()=>IS_ANDROID || window.matchMedia('(max-width:900px)').matches;
  const publicLink=album=>spotifyAlbumUrl(albumTarget(album)) || musicBrainzReleaseUrl(albumTarget(album));
  const fail=error=>showToast(error.message || String(error),6000);
  function viewMode() { try { return localStorage.getItem(VIEW_KEY)==='compact'?'compact':'list'; } catch(_) { return 'list'; } }
  function applyView(mode,persist=true) {
    mode=mode==='compact'?'compact':'list';
    const list=$('albumTrackList');list?.classList.toggle('album-compact',mode==='compact');
    document.querySelector('.album-track-header')?.classList.toggle('album-compact',mode==='compact');
    const label=$('albumViewLabel');if(label)label.textContent=mode==='compact'?'Compact':'List';
    $('albumViewToggle')?.setAttribute('aria-label',`View as ${mode==='compact'?'Compact':'List'}`);
    const icon=$('albumViewToggle')?.querySelector('i');if(icon)icon.className=mode==='compact'?'bi bi-list':'bi bi-list-ul';
    for(const option of document.querySelectorAll('[data-album-view]')) {
      option.setAttribute('aria-checked',String(option.dataset.albumView===mode));
      option.classList.toggle('active',option.dataset.albumView===mode);
    }
    if(persist)try {localStorage.setItem(VIEW_KEY,mode);}catch(_){}
  }
  function bind(album,tracks,downloadView) {
    applyView(viewMode(),false);
    const more=$('albumMore');
    if(more)more.onclick=event=>{
      event.preventDefault();event.stopPropagation();
      const rect=more.getBoundingClientRect();
      showAlbumContextMenu({preventDefault(){},clientX:rect.left,clientY:rect.bottom+5,screenX:event.screenX,screenY:event.screenY},album);
    };
    const toggle=$('albumViewToggle'),menu=$('albumViewMenu');
    if(toggle && menu) {
      toggle.onclick=()=>{menu.hidden=!menu.hidden;toggle.setAttribute('aria-expanded',String(!menu.hidden));};
      menu.querySelectorAll('[data-album-view]').forEach(option=>option.onclick=()=>{
        applyView(option.dataset.albumView);menu.hidden=true;toggle.setAttribute('aria-expanded','false');
      });
    }
    const share=$('albumShare');if(share)share.onclick=()=>shareCard(album).catch(fail);
    // The overflow and header reuse the same queue and saved-album actions.
    if(downloadView)downloadView.album=album;
  }
  function configureMenu(album) {
    const save=$('ctxAlbumSaveLibrary'),existing=savedAlbumPlaylist(album);
    if(save) {
      save.innerHTML=`<i class="bi ${existing?'bi-check-circle-fill':'bi-plus-circle'}"></i> ${existing?'Remove from Your Library':'Add to Your Library'}`;
      save.onclick=async()=>{ $('albumContextMenu').hidden=true;try {
        if(existing)await deletePlaylist(existing.id);else await saveAlbumToLibrary(album);
        renderAlbumLibraryControl(album);
      }catch(error){fail(error);} };
    }
    $('ctxAlbumDownload').onclick=async()=>{
      $('albumContextMenu').hidden=true;
      try {
        const tracks=album.tracks?.length?album.tracks:await fetchAlbumTracks(album);
        const key=albumControlKey(album,tracks);
        const view=visibleAlbumControls?.key===key?visibleAlbumControls:{key,name:album.album||album.title||'Album',tracks,statuses:new Map()};
        await queueAlbumDownloads(view);
      }catch(error){fail(error);}
    };
    $('ctxAlbumRadio').onclick=()=>{ $('albumContextMenu').hidden=true;artistRadio(album).catch(fail); };
    const link=publicLink(album),copy=$('ctxAlbumCopySpotify');
    copy?.classList.toggle('hidden',!link);
    if(copy)copy.onclick=async()=>{ $('albumContextMenu').hidden=true;try{await navigator.clipboard.writeText(link);showToast('Album link copied');}catch(error){fail(error);} };
    const embed=$('ctxAlbumEmbed');
    const id=spotifyAlbumUrl(albumTarget(album)).match(/\/album\/([A-Za-z0-9]+)/)?.[1] || '';
    embed?.classList.toggle('hidden',!id);
    if(embed)embed.onclick=async()=>{
      $('albumContextMenu').hidden=true;
      // Spotify's documented Embed format; copy only, without loading third-party content.
      const code=`<iframe title="Spotify album" src="https://open.spotify.com/embed/album/${id}" width="100%" height="352" frameborder="0" allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture" loading="lazy"></iframe>`;
      let dialog=$('albumEmbedDialog');
      if(!dialog) {
        dialog=document.createElement('dialog');dialog.id='albumEmbedDialog';dialog.className='album-embed-dialog';
        dialog.setAttribute('aria-label','Embed album');
        dialog.innerHTML='<h2>Embed album</h2><p>Copy this code into your website.</p><textarea readonly aria-label="Album embed code"></textarea><div class="album-embed-actions"><button type="button" data-close>Close</button><button type="button" data-copy>Copy code</button></div>';
        document.body.appendChild(dialog);dialog.querySelector('[data-close]').onclick=()=>dialog.close();
        dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close();});
      }
      dialog.querySelector('textarea').value=code;
      dialog.querySelector('[data-copy]').onclick=async()=>{try{await navigator.clipboard.writeText(code);showToast('Album embed code copied');}catch(error){fail(error);}};
      dialog.showModal();
    };
    $('ctxAlbumCopyMusicBrainz')?.classList.toggle('hidden',!!spotifyAlbumUrl(albumTarget(album)) || !musicBrainzReleaseUrl(albumTarget(album)));
  }
  async function albumPlaylistPicker(album) {
    const tracks=album.tracks?.length?album.tracks:await fetchAlbumTracks(album);
    if(!tracks.length)throw Error('No album songs available');
    const dialog=$('playlistPickerDialog'),search=$('playlistPickerSearch');
    function render() {
      const list=$('playlistPickerBody'),query=search.value.trim().toLowerCase();
      const playlists=(state.playlists || []).filter(p=>!isReadOnlyPlaylist(p) && inferPlaylistOrigin(p)!=='album' && (!query||p.name.toLowerCase().includes(query)));
      list.innerHTML='<button class="playlist-picker-new" id="albumNewPlaylist">New playlist</button>'+
        playlists.map(p=>pickerRowHtml(p,tracks.every(t=>trackInPlaylist(p,t)))).join('');
      list.querySelectorAll('[data-picker-playlist]').forEach(button=>button.onclick=async()=>{
        button.disabled=true;
        try {
          await api('/api/playlists/tracks/add',{method:'POST',body:JSON.stringify({id:button.dataset.pickerPlaylist,tracks})});
          await loadPlaylists();dialog.close();showToast('Album added to playlist');
        }catch(error){button.disabled=false;fail(error);}
      });
      $('albumNewPlaylist').onclick=()=>{dialog.close();openCreatePlaylistDialog(tracks);};
    }
    search.value='';search.oninput=render;render();dialog.showModal();
  }
  async function artistRadio(album) {
    const artist=artistTarget(album),name=artist.name||artist.artist||album.artist;
    showToast(`Loading ${name} radio…`);
    const [seed,related]=await Promise.all([
      fetchArtistTopTracks(artist),
      api('/api/artist/related',{method:'POST',body:JSON.stringify({artist_id:artist.artist_id||'',name,limit:4}),timeout:25000}).catch(()=>({artists:[]})),
    ]);
    const others=await Promise.all((related.artists||[]).slice(0,4).map(a=>fetchArtistTopTracks(a)));
    const sources=[seed,...others].filter(a=>a.length),seen=new Set(),mix=[];
    // Interleave the seed and related artists, preserving each provider's ranking.
    for(let i=0;i<10;i++)for(const source of sources) {
      const item=source[i];if(!item||seen.has(trackKey(item)))continue;
      seen.add(trackKey(item));mix.push(item);
    }
    if(!mix.length)throw Error('No artist radio songs are available');
    state.pendingResumePosition=0;
    await selectMusicItem(mix[0],'stream',mix,{title:`${name} Radio`});
    openQueuePanel();
  }
  function round(ctx,x,y,w,h,r) {
    ctx.beginPath();ctx.moveTo(x+r,y);ctx.arcTo(x+w,y,x+w,y+h,r);ctx.arcTo(x+w,y+h,x,y+h,r);
    ctx.arcTo(x,y+h,x,y,r);ctx.arcTo(x,y,x+w,y,r);ctx.closePath();
  }
  function fitText(ctx,text,x,y,width,size,maxLines=1) {
    ctx.font=`700 ${size}px system-ui,sans-serif`;
    const words=String(text||'').split(/\s+/),lines=[];let line='';
    for(const word of words) {const next=line?`${line} ${word}`:word;if(ctx.measureText(next).width>width && line){lines.push(line);line=word;}else line=next;}
    if(line)lines.push(line);
    for(let i=0;i<Math.min(maxLines,lines.length);i++) {
      let value=lines[i];if(i===maxLines-1 && lines.length>maxLines)value+='…';
      while(ctx.measureText(value).width>width && value.length>1)value=value.slice(0,-2)+'…';
      ctx.fillText(value,x,y+i*size*1.2);
    }
  }
  async function imageFor(album) {
    const source=album.artwork_url||album.tracks?.find(t=>t.artwork_url)?.artwork_url;
    if(!source)return null;
    let url=source;
    if(/^https?:\/\//i.test(source) && !source.startsWith(window.location.origin))url=`${API_BASE}/api/image?url=${encodeURIComponent(source)}`;
    return new Promise(resolve=>{
      const image=new Image();const timeout=setTimeout(()=>resolve(null),12000);
      image.onload=()=>{clearTimeout(timeout);resolve(image);};image.onerror=()=>{clearTimeout(timeout);resolve(null);};image.src=url;
    });
  }
  function dominant(image) {
    if(!image)return '#214b38';
    try {
      const canvas=document.createElement('canvas');canvas.width=16;canvas.height=16;const ctx=canvas.getContext('2d');ctx.drawImage(image,0,0,16,16);
      const pixels=ctx.getImageData(0,0,16,16).data;let r=0,g=0,b=0,count=0;
      for(let i=0;i<pixels.length;i+=4){if(pixels[i+3]<128)continue;r+=pixels[i];g+=pixels[i+1];b+=pixels[i+2];count++;}
      return count?`rgb(${Math.round(r/count*.65)},${Math.round(g/count*.65)},${Math.round(b/count*.65)})`:'#214b38';
    }catch(_){return '#214b38';}
  }
  function drawCard(canvas,album,image,color,gradient=false) {
    const ctx=canvas.getContext('2d');canvas.width=720;canvas.height=1080;
    let fill=color;
    if(gradient){fill=ctx.createLinearGradient(0,0,720,1080);fill.addColorStop(0,color);fill.addColorStop(1,'#090b0a');}
    ctx.fillStyle=fill;ctx.fillRect(0,0,720,1080);
    ctx.fillStyle='rgba(0,0,0,.62)';round(ctx,64,130,592,830,22);ctx.fill();
    if(image){ctx.save();round(ctx,96,162,528,528,12);ctx.clip();const edge=Math.min(image.width,image.height);ctx.drawImage(image,(image.width-edge)/2,(image.height-edge)/2,edge,edge,96,162,528,528);ctx.restore();}
    else {ctx.fillStyle='#262b28';ctx.fillRect(96,162,528,528);ctx.fillStyle='#fff';ctx.font='160px sans-serif';ctx.fillText('♫',270,475);}
    ctx.fillStyle='#fff';fitText(ctx,album.album||album.title||'Album',96,756,528,39,2);
    ctx.fillStyle='#ddd';ctx.font='28px system-ui,sans-serif';let artist=String(album.artist||'');
    while(ctx.measureText(artist).width>528 && artist.length>1)artist=artist.slice(0,-2)+'…';ctx.fillText(artist,96,865);
    ctx.fillStyle='#20d466';ctx.font='700 27px system-ui,sans-serif';ctx.fillText('♫ Mindinguflac',96,923);
    return canvas;
  }
  async function shareCard(album) {
    if(!mobile()) {await navigator.clipboard.writeText(publicLink(album));showToast('Album link copied');return;}
    const revision=++shareRevision;
    const link=publicLink(album);if(!link)throw Error('This album has no public link to share');
    let dialog=$('albumShareDialog');
    if(!dialog) {
      dialog=document.createElement('dialog');dialog.id='albumShareDialog';dialog.className='album-share-dialog';
      dialog.setAttribute('aria-label','Share album');
      dialog.innerHTML=`<div class="album-share-sheet"><div class="share-sheet-handle"></div><button class="album-share-close" aria-label="Close sharing"><i class="bi bi-x-lg"></i></button>
        <canvas width="720" height="1080" id="albumShareCanvas" aria-label="Album share card"></canvas><div class="album-share-colors" role="group" aria-label="Card background"></div>
        <div class="album-share-buttons"><button type="button" id="albumShareCopy"><i class="bi bi-link-45deg"></i><span>Copy link</span></button><button type="button" id="albumShareNative"><i class="bi bi-share"></i><span>Share card</span></button></div><p id="albumShareNotice" role="status"></p></div>`;
      document.body.appendChild(dialog);dialog.querySelector('.album-share-close').onclick=()=>dialog.close();
      dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close();});
    }
    const canvas=$('albumShareCanvas'),colors=dialog.querySelector('.album-share-colors');
    colors.replaceChildren();$('albumShareNotice').textContent='Loading artwork…';$('albumShareNative').disabled=true;
    drawCard(canvas,album,null,'#214b38');dialog.showModal();
    $('albumShareCopy').onclick=async()=>{try{await navigator.clipboard.writeText(link);$('albumShareNotice').textContent='Album link copied';}catch(error){fail(error);}};
    const image=await imageFor(album);if(!dialog.open || revision!==shareRevision)return;
    $('albumShareNotice').textContent='';$('albumShareNative').disabled=false;
    const palette=[{color:dominant(image)},{color:dominant(image),gradient:true},{color:'#101211'}];
    palette.forEach((theme,index)=>{
      const button=document.createElement('button');button.type='button';button.style.background=theme.gradient?`linear-gradient(135deg,${theme.color},#090b0a)`:theme.color;
      button.setAttribute('aria-label',['Artwork color','Dark gradient','Black'][index]);button.setAttribute('aria-pressed',String(index===0));
      button.onclick=()=>{colors.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));drawCard(canvas,album,image,theme.color,theme.gradient);};colors.appendChild(button);
    });
    drawCard(canvas,album,image,palette[0].color);
    $('albumShareNative').onclick=async()=>{
      try {
        const title=album.album||album.title||'Album',png=canvas.toDataURL('image/png');
        if(window.MindinguflacAndroid?.shareAlbumCard)window.MindinguflacAndroid.shareAlbumCard(title,link,png);
        else {
          const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png')),file=new File([blob],'album-card.png',{type:'image/png'});
          if(navigator.canShare?.({files:[file]}) && navigator.share)await navigator.share({title,text:link,files:[file]});
          else if(navigator.share)await navigator.share({title,url:link});
          else {await navigator.clipboard.writeText(link);$('albumShareNotice').textContent='Album link copied';}
        }
      }catch(error){if(error.name!=='AbortError')fail(error);}
    };
  }
  document.addEventListener('click',event=>{
    if(!event.target.closest?.('.album-view-control')){$('albumViewMenu')?.setAttribute('hidden','');$('albumViewToggle')?.setAttribute('aria-expanded','false');}
  });
  return {bind,configureMenu,albumPlaylistPicker,shareCard,applyView,viewMode,drawCard,publicLink,artistRadio};
})();
