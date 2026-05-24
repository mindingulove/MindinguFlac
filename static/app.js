const API_BASE = "";

const state = {
  viewStack: [],
  catalog: { artists: [], albums: [], top_tracks: [], personal_tracks: [], recent_tracks: [] },
  settings: {},
  playlists: [],
  currentTrack: null,
  activeJobId: null,
  isShuffle: false,
  isRepeat: false,
  queue: [],
  originalQueue: [],
  queueIndex: -1,
  seekHoldTimer: null,
  seekHoldDirection: 0,
  volumeHoldTimer: null,
  volumeHoldDirection: 0,
  suggestTimer: null,
  suggestionResults: [],
  suggestionAllResults: [],
  suggestionVisibleCount: 0,
  forwardHistory: [],
  autoplayWanted: false,
  currentPlayableReady: false,
  playerStatus: "Choose a track to stream",
  playbackRequestId: 0,
  currentStreamUrl: "",
  prefetchedForRequestId: -1,
};

const SERVICE_LABELS = {
  tidal: "Tidal",
  deezer: "Deezer",
  qobuz: "Qobuz",
  amazon: "Amazon Music",
  apple_music: "Apple Music",
  soundcloud: "SoundCloud",
  youtube: "YouTube",
};

const SERVICE_QUALITIES = {
  tidal: [
    { value: "DOLBY_ATMOS",    label: "Dolby Atmos" },
    { value: "HI_RES_LOSSLESS",label: "Hi-Res Lossless" },
    { value: "LOSSLESS",       label: "Lossless (FLAC/CD)" },
    { value: "HIGH",           label: "High (320kbps)" },
    { value: "LOW",            label: "Low (96-128kbps)" },
  ],
  deezer: [
    { value: "LOSSLESS", label: "Lossless (FLAC)" },
    { value: "HIGH",     label: "High (320kbps)" },
    { value: "256",      label: "256kbps" },
    { value: "192",      label: "192kbps" },
    { value: "128",      label: "128kbps" },
  ],
  qobuz: [
    { value: "27", label: "Hi-Res Max" },
    { value: "7",  label: "Hi-Res" },
    { value: "6",  label: "CD (FLAC)" },
  ],
  amazon: [
    { value: "LOSSLESS", label: "FLAC / ALAC" },
  ],
  apple_music: [
    { value: "256", label: "256kbps AAC" },
    { value: "192", label: "192kbps AAC" },
    { value: "128", label: "128kbps AAC" },
  ],
  soundcloud: [
    { value: "HIGH", label: "High (256kbps)" },
    { value: "LOW",  label: "Low (128kbps)" },
  ],
  youtube: [
    { value: "HIGH", label: "High (256kbps)" },
    { value: "LOW",  label: "Low (128kbps)" },
  ],
};

function updateQualityOptions(service, currentQuality) {
  const sel = $("defaultQuality");
  if (!sel) return;
  const opts = SERVICE_QUALITIES[service] || SERVICE_QUALITIES.tidal;
  sel.innerHTML = opts.map(o => `<option value="${o.value}">${o.label}</option>`).join("");
  // Keep current quality if valid for this service, else default to first
  if (currentQuality && opts.some(o => o.value === currentQuality)) {
    sel.value = currentQuality;
  } else {
    sel.value = opts[0].value;
  }
}

const STORAGE_KEYS = {
  volume: "streambox.volume",
};

async function api(path, options = {}) {
  const resp = await fetch(`${API_BASE}${path}`, options);
  if (!resp.ok) {
    const error = await resp.json().catch(() => ({ error: resp.statusText }));
    throw new Error(error.error || "API call failed");
  }
  return resp.json();
}

function $(id) { return document.getElementById(id); }
function esc(str) {
  if (!str) return "";
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function isTrackItem(item) {
  if (!item) return false;
  if (item.type === "track") return true;
  if (item.type === "artist" || item.type === "album") return false;
  return !!(item.title || item.duration);
}

function progressButtonMarkup(status = {}) {
  const progress = Math.max(0, Math.min(95, Math.round(Number(status.progress || 0))));
  const hasProgress = progress > 0;
  const label = hasProgress ? `Downloading ${progress}%` : "Preparing download";
  return `<span class="track-progress-ring ${hasProgress ? "determinate" : "indeterminate"}" style="--pct: ${progress}" aria-label="${label}">
    <span class="track-progress-core"><span class="track-progress-stop"></span></span>
  </span>`;
}

function attrJson(value) {
  return JSON.stringify(value || {}).replace(/'/g, "&apos;");
}

function artistTarget(item = {}) {
  const name = item.artist || item.name || "";
  return {
    name,
    artist: name,
    artwork_url: item.artist_artwork_url || (item.type === "artist" ? item.artwork_url : ""),
    artist_id: item.artist_id || item.spotify_artist_id || item.musicbrainz_artist_id || "",
  };
}

function albumTarget(item = {}) {
  const album = item.album || item.title || "";
  return {
    type: "album",
    title: album,
    album,
    artist: item.artist || "",
    artwork_url: item.album_artwork_url || item.artwork_url || "",
    musicbrainz_release_id: item.musicbrainz_release_id || "",
    spotify_id: item.album_spotify_id || item.spotify_album_id || "",
  };
}

function artistLinkHtml(item, text = null, className = "") {
  const label = text || item?.artist || item?.name || "";
  if (!label) return "";
  return `<button class="inline-entity-link artist-link ${className}" type="button" title="${esc(label)}" data-open-artist='${attrJson(artistTarget({ ...item, artist: label }))}'>${esc(label)}</button>`;
}

function albumLinkHtml(item, text = null, className = "") {
  const label = text || item?.title || item?.name || "";
  if (!label) return "";
  return `<button class="inline-entity-link track-title-link ${className}" type="button" title="${esc(label)}" data-open-album='${attrJson(albumTarget(item))}'>${esc(label)}</button>`;
}

function openArtistLink(item) {
  pushPage(() => renderArtistPage(item));
}

function openAlbumLink(item) {
  pushPage(() => renderAlbumPage(item));
}

function bindEntityLinks(root = document) {
  root.querySelectorAll("[data-open-artist]").forEach((button) => {
    if (button.dataset.entityBound) return;
    button.dataset.entityBound = "1";
    button.onclick = (event) => {
      event.preventDefault();
      event.stopPropagation();
      openArtistLink(JSON.parse(button.dataset.openArtist || "{}"));
    };
  });
  root.querySelectorAll("[data-open-album]").forEach((button) => {
    if (button.dataset.entityBound) return;
    button.dataset.entityBound = "1";
    button.onclick = (event) => {
      event.preventDefault();
      event.stopPropagation();
      openAlbumLink(JSON.parse(button.dataset.openAlbum || "{}"));
    };
  });
}

function resetSeekUi() {
  const seek = $("seekBar");
  if (seek) {
    seek.value = 0;
    seek.style.backgroundSize = "0% 100%";
  }
  const current = $("currentTime");
  if (current) current.textContent = "0:00";
  const duration = $("durationTime");
  if (duration) duration.textContent = "0:00";
}

function isTypingTarget(target) {
  if (!target) return false;
  const tag = target.tagName;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT", "BUTTON"].includes(tag);
}

// ---------------------------------------------------------------------------
// Views & Navigation
// ---------------------------------------------------------------------------

function setActiveView(id) {
  if (window.artistEvtSource) {
    window.artistEvtSource.close();
    window.artistEvtSource = null;
  }
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  document.querySelectorAll(".nav").forEach((b) => b.classList.remove("active"));
  document.querySelectorAll(".sidebar-playlist-item").forEach(el => el.classList.remove("active"));
  const view = $(id);
  if (view) view.classList.add("active");
  const nav = document.querySelector(`.nav[data-view="${id}"]`);
  if (nav) nav.classList.add("active");
}

function pushPage(renderFn) {
  if (state.viewStack.length > 0) {
    state.viewStack[state.viewStack.length - 1].scroll = document.querySelector(".active .scroll-area")?.scrollTop || 0;
  }
  state.viewStack.push({ render: renderFn, scroll: 0 });
  state.forwardHistory = [];
  renderFn();
  updateHistoryButtons();
}

function popPage() {
  if (state.viewStack.length <= 1) return;
  const page = state.viewStack.pop();
  state.forwardHistory.push(page);
  const prev = state.viewStack[state.viewStack.length - 1];
  prev.render();
  if (prev.scroll) {
    setTimeout(() => {
      const area = document.querySelector(".active .scroll-area");
      if (area) area.scrollTop = prev.scroll;
    }, 0);
  }
  updateHistoryButtons();
}

function forwardPage() {
  if (state.forwardHistory.length === 0) return;
  const page = state.forwardHistory.pop();
  state.viewStack.push(page);
  page.render();
  updateHistoryButtons();
}

function replacePage(renderFn) {
  state.viewStack = [{ render: renderFn, scroll: 0 }];
  state.forwardHistory = [];
  renderFn();
  updateHistoryButtons();
}

function updateHistoryButtons() {
  const back = $("backButton");
  const forward = $("forwardButton");
  if (back) back.disabled = state.viewStack.length <= 1;
  if (forward) forward.disabled = state.forwardHistory.length === 0;
}

function syncActiveTrackRows() {
  const current = state.currentTrack;
  if (!current) return;
  
  const currentTitle = (current.title || "").toLowerCase().trim();
  const currentArtist = (current.artist || "").toLowerCase().trim();
  const currentSpotifyId = current.spotify_id;
  const currentMBId = current.musicbrainz_recording_id || current.musicbrainz_track_id;

  document.querySelectorAll(".track-row, .music-card").forEach(el => {
    let itemData = null;
    try {
      if (el.dataset.track) itemData = JSON.parse(el.dataset.track);
      else if (el.dataset.cardData) itemData = JSON.parse(el.dataset.cardData);
      else if (el.dataset.itemData) itemData = JSON.parse(el.dataset.itemData);
    } catch(e) {}

    if (itemData) {
      const itemTitle = (itemData.title || itemData.name || "").toLowerCase().trim();
      const itemArtist = (itemData.artist || "").toLowerCase().trim();
      const itemSpotifyId = itemData.spotify_id;
      const itemMBId = itemData.musicbrainz_recording_id || itemData.musicbrainz_track_id;
      
      let match = false;
      if (currentSpotifyId && itemSpotifyId) match = (currentSpotifyId === itemSpotifyId);
      else if (currentMBId && itemMBId) match = (currentMBId === itemMBId);
      else match = (itemTitle === currentTitle && (itemArtist === currentArtist || !itemArtist || !currentArtist));
      
      el.classList.toggle("active-track", match);
    }
  });
}

// ---------------------------------------------------------------------------
// Home & Cards Restoration
// ---------------------------------------------------------------------------

async function loadCatalog() {
  try {
    state.catalog = await api("/api/discover");
    if (state.viewStack.length === 0 || state.viewStack[0].render === renderHomePage) {
      replacePage(renderHomePage);
    }
  } catch (e) {
    console.error("Load catalog failed", e);
  }
}

function renderHomePage() {
  if (!state.catalog) {
    $("pageContent").innerHTML = '<div class="loading"><div class="spinner"></div><span>Loading library...</span></div>';
    return;
  }
  setActiveView("home");
  
  const personalTracks = (state.catalog.personal_tracks || []).slice(0, 6);
  const recentTracks = (state.catalog.recent_tracks || []).slice(0, 6);
  const globalTracks = (state.catalog.top_tracks || []).slice(0, 6);
  const topArtists = (state.catalog.artists || []).slice(0, 6);
  const topAlbums = (state.catalog.albums || []).slice(0, 6);

  $("pageContent").innerHTML = `
    <div class="library-hero compact-hero">
      <div>
        <span class="eyebrow">Personal Music Discovery</span>
        <h1>Welcome Home</h1>
      </div>
    </div>

    <div class="scroll-area">
      ${recentTracks.length ? `
        <div class="section-head sticky-head">
          <h2>Recently Played</h2>
          <button class="see-more" id="seeMoreRecent">See all <i class="bi bi-chevron-right"></i></button>
        </div>
        <div id="recentTracksGrid" class="grid"></div>
      ` : ""}

      ${personalTracks.length ? `
        <div class="section-head sticky-head">
          <h2>Your Most Listened</h2>
          <button class="see-more" id="seeMorePersonal">See all <i class="bi bi-chevron-right"></i></button>
        </div>
        <div id="personalTracksGrid" class="grid"></div>
      ` : ""}

      <div class="section-head sticky-head">
        <h2>Top Songs (Global)</h2>
        <button class="see-more" id="seeMoreGlobalTracks">See all <i class="bi bi-chevron-right"></i></button>
      </div>
      <div id="topTracksGrid" class="grid"></div>

      <div class="section-head sticky-head">
        <h2>Top Artists (Global)</h2>
        <button class="see-more" id="seeMoreArtists">See all <i class="bi bi-chevron-right"></i></button>
      </div>
      <div id="topArtistsGrid" class="grid"></div>

      <div class="section-head sticky-head">
        <h2>Top Albums (Global)</h2>
        <button class="see-more" id="seeMoreAlbums">See all <i class="bi bi-chevron-right"></i></button>
      </div>
      <div id="topAlbumsGrid" class="grid"></div>
    </div>
  `;

  if (recentTracks.length) {
    renderCards("recentTracksGrid", recentTracks, "track");
    $("seeMoreRecent").onclick = () => pushPage(renderRecentTracksPage);
  }

  if (personalTracks.length) {
    renderCards("personalTracksGrid", personalTracks, "track");
    $("seeMorePersonal").onclick = () => pushPage(renderPersonalTracksPage);
  }

  renderCards("topTracksGrid", globalTracks, "track");
  renderCards("topArtistsGrid", topArtists, "artist");
  renderCards("topAlbumsGrid", topAlbums, "album");

  $("seeMoreGlobalTracks").onclick = () => pushPage(renderGlobalTracksPage);
  $("seeMoreArtists").onclick = () => pushPage(renderArtistsPage);
  $("seeMoreAlbums").onclick = () => pushPage(renderAlbumsPage);
  
  syncActiveTrackRows();
}

function renderCards(containerId, items, kind) {
  const container = $(containerId);
  if (!container) return;
  container.innerHTML = cardsHtml(items, kind, 0);
  bindCardClicks(container, items);
}

function cardsHtml(items, kind, offset = 0) {
  const current = state.currentTrack;
  return items.map((item, index) => {
    const title = item.title || item.name || item.artist || item.album;
    const year = item.year ? ` (${item.year})` : "";
    const sub = kind === "artist" ? "Artist" : `${artistLinkHtml(item)}${year}`;
    const artUrl = item.artwork_url || "";
    const isActive = current && (item.title === current.title && item.artist === current.artist);
    const titleHtml = kind === "track" ? albumLinkHtml(item, title) : (kind === "artist" ? artistLinkHtml(item, title) : esc(title));
    
    return `
      <div class="music-card ${kind === "artist" ? "artist-card" : ""} ${isActive ? "active-track" : ""}"
              role="button"
              tabindex="0"
              data-card="${offset + index}" 
              data-card-data='${JSON.stringify(item).replace(/'/g, "&apos;")}'>
        <div class="card-art ${kind === "artist" ? "round" : ""}" style="background-image: url('${artUrl}')">
          <div class="card-play-overlay"><i class="bi bi-play-fill"></i></div>
        </div>
        <strong>${titleHtml}</strong>
        <span>${sub}</span>
      </div>
    `;
  }).join("");
}

function bindCardClicks(container, items) {
  container.querySelectorAll("[data-card]").forEach((button) => {
    button.onclick = () => selectMusicItem(items[Number(button.dataset.card)], "stream", items);
    button.onkeydown = (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectMusicItem(items[Number(button.dataset.card)], "stream", items);
      }
    };
  });
  bindEntityLinks(container);
}

// ---------------------------------------------------------------------------
// Other Discovery Pages
// ---------------------------------------------------------------------------

function renderArtistsPage() {
  setActiveView("home");
  document.querySelectorAll(".nav").forEach(b => b.classList.remove("active"));
  document.querySelector('.nav[data-view="artists"]')?.classList.add("active");
  $("pageContent").innerHTML = `
    <div class="section-head sticky-head">
      <h1>Top Artists</h1>
      <span>Discovery index</span>
    </div>
    <div class="scroll-area"><div id="fullArtistsGrid" class="grid"></div></div>
  `;
  renderCards("fullArtistsGrid", state.catalog.artists || [], "artist");
}

function renderAlbumsPage() {
  setActiveView("home");
  document.querySelectorAll(".nav").forEach(b => b.classList.remove("active"));
  document.querySelector('.nav[data-view="albums"]')?.classList.add("active");
  $("pageContent").innerHTML = `
    <div class="section-head sticky-head">
      <h1>Top Albums</h1>
      <span>Grouped by artist</span>
    </div>
    <div class="scroll-area"><div id="fullAlbumsGrid" class="grid"></div></div>
  `;
  renderCards("fullAlbumsGrid", state.catalog.albums || [], "album");
}

function renderPersonalTracksPage() {
  setActiveView("home");
  $("pageContent").innerHTML = `
    <div class="scroll-area">
      <div class="library-hero compact-hero">
        <div>
          <span class="eyebrow">Personal</span>
          <h1>Your Most Listened</h1>
        </div>
      </div>
      <div id="fullPersonalTracks" class="track-list"></div>
    </div>
  `;
  renderTrackList("fullPersonalTracks", state.catalog.personal_tracks || []);
}

function renderRecentTracksPage() {
  setActiveView("home");
  $("pageContent").innerHTML = `
    <div class="scroll-area">
      <div class="library-hero compact-hero">
        <div>
          <span class="eyebrow">History</span>
          <h1>Recently Played</h1>
        </div>
      </div>
      <div id="fullRecentTracks" class="track-list"></div>
    </div>
  `;
  renderTrackList("fullRecentTracks", state.catalog.recent_tracks || []);
}

function renderGlobalTracksPage() {
  setActiveView("home");
  $("pageContent").innerHTML = `
    <div class="scroll-area">
      <div class="library-hero compact-hero">
        <div>
          <span class="eyebrow">Discovery</span>
          <h1>Global Top Songs</h1>
        </div>
      </div>
      <div id="fullGlobalTracks" class="track-list"></div>
    </div>
  `;
  renderTrackList("fullGlobalTracks", state.catalog.top_tracks || []);
}

function renderTrackList(containerId, items, context = "general") {
  const container = $(containerId);
  if (!container) return;
  const current = state.currentTrack;
  
  Promise.all(items.map(item => {
    if (!isTrackItem(item)) return Promise.resolve(null);
    return api("/api/library/status", { method: "POST", body: JSON.stringify(serviceDownloadPayload(item, "download")) }).catch(() => null);
  })).then((statuses) => {
    container.innerHTML = items.map((item, idx) => {
      const art = item.artwork_url || "";
      const isTrack = isTrackItem(item);
      const isActive = isTrack && current &&
                       ((item.spotify_id && item.spotify_id === current.spotify_id) || 
                        (item.title === current.title && item.artist === current.artist));
      
      const status = statuses[idx] || {};
      const isDownloaded = isTrack && status.in_library;
      const isBusy = isTrack && !!status.library_requested;

      const typeLabel = { track: "Song", artist: "Artist", album: "Album" }[item.type] || (item.type || "Song");
      
      let col6 = ""; // Status column (Far Right)
      if (isTrack) {
        const label = isDownloaded ? "Remove from library" : (isBusy ? "Cancel library download" : "Add to library");
        let iconHtml = `<i class="bi ${isDownloaded ? "bi-check-circle-fill downloaded" : "bi-check-circle"}"></i>`;
        if (isBusy) {
           iconHtml = progressButtonMarkup(status);
        }
        col6 = `<button class="track-library-btn ${isDownloaded ? "downloaded" : ""} ${isBusy ? "progress" : ""}" type="button" aria-label="${label}" title="${label}" data-library-action="${idx}" data-active-job-id="${status.active_job_id || ""}">
          ${iconHtml}
        </button>`;
      }

      let col2 = `<strong>${isTrack ? albumLinkHtml(item, item.title || item.name || item.artist) : esc(item.title || item.name || item.artist)}</strong>`;
      let col3 = ""; // Center column
      let col4 = ""; // Extra column
      let col5 = item.duration || "";

      if (context === "search") {
        col2 += `<span>${artistLinkHtml(item)}</span>`;
        col3 = `<span class="pill">${esc(typeLabel)}</span>`;
        col4 = isTrack ? albumLinkHtml(item, item.album || "", "album-link") : "";
      } else if (context === "artist") {
        col3 = item.plays ? `<span class="views-count">${item.plays.toLocaleString()}</span>` : "";
        col4 = albumLinkHtml(item, item.album || "", "album-link");
      } else if (context === "album") {
        col2 += `<span>${artistLinkHtml(item)}</span>`;
        col3 = "";
        col4 = "";
      } else {
        col2 += `<span>${artistLinkHtml(item)}</span>`;
        col4 = albumLinkHtml(item, item.album || "", "album-link");
      }

      return `
        <div class="track-row ${isActive ? "active-track" : ""}" data-item-idx="${idx}" data-item-data='${JSON.stringify(item).replace(/'/g, "&apos;")}'>
          <div class="track-art ${item.type === "artist" ? "round" : ""}" style="background-image: url('${art}')"></div>
          <div class="track-main">${col2}</div>
          <div class="track-center">${col3}</div>
          <div class="track-extra">${col4}</div>
          <div class="track-time">${col5}</div>
          <div class="track-status-icon">${col6}</div>
        </div>
      `;
    }).join("");
    
    syncActiveTrackRows();
    container.querySelectorAll(".track-row").forEach(el => {
      el.onclick = (event) => {
        if (event.target.closest("[data-library-action]")) return;
        selectMusicItem(items[Number(el.dataset.itemIdx)], "stream", items);
      };
    });
    container.querySelectorAll("[data-library-action]").forEach(button => {
      button.onclick = (event) => {
        event.preventDefault();
        event.stopPropagation();
        toggleTrackLibrary(items[Number(button.dataset.libraryAction)], button, () => renderTrackList(containerId, items, context));
      };
    });
    bindEntityLinks(container);
  }).catch(() => {});
}

// ---------------------------------------------------------------------------
// Artist & Album Individual Pages
// ---------------------------------------------------------------------------

async function renderArtistPage(artist) {
  setActiveView("home");
  const content = $("pageContent");
  
  content.innerHTML = `
    <div class="scroll-area">
      <div class="entity-hero">
        <div id="artistHeroArt" class="entity-art round" style="background-image: url('${artist.artwork_url || ""}')"></div>
        <div>
          <span class="eyebrow">Artist</span>
          <h1 id="artistHeroName">${esc(artist.name || artist.artist)}</h1>
        </div>
      </div>
      
      <div id="artistTopTracksSection" class="hidden">
        <div class="section-head sticky-head"><h2>Popular Tracks</h2></div>
        <div id="artistTopTracks" class="track-list"></div>
      </div>

      <div id="artistAlbumsSection" class="hidden">
        <div class="section-head sticky-head"><h2>Albums</h2></div>
        <div id="artistAlbumsGrid" class="grid"></div>
      </div>
      
      <div id="artistLoading" class="loading"><div class="spinner"></div><span>Loading discovery data…</span></div>
    </div>
  `;

  if (window.artistEvtSource) {
    window.artistEvtSource.close();
  }

  const artistName = artist.name || artist.artist;
  const artistId = artist.artist_id || "";
  const es = new EventSource(`/api/music/artist?artist=${encodeURIComponent(artistName)}&artist_id=${artistId}`);
  window.artistEvtSource = es;

  es.onmessage = (e) => {
    try {
      const part = JSON.parse(e.data);
      if (part.type === "artist_info") {
        $("artistHeroName").textContent = part.artist;
        if (part.artwork_url) {
          $("artistHeroArt").style.backgroundImage = `url('${part.artwork_url}')`;
        }
      }
      if (part.type === "top_tracks") {
        $("artistTopTracksSection").classList.remove("hidden");
        renderTrackList("artistTopTracks", part.tracks || [], "artist");
      }
      if (part.type === "albums") {
        if (part.albums && part.albums.length) {
            $("artistAlbumsSection").classList.remove("hidden");
            renderCards("artistAlbumsGrid", part.albums.map(al => ({...al, type:"album"})), "album");
        }
      }
    } catch (err) {}
  };

  es.addEventListener("done", () => { $("artistLoading")?.remove(); es.close(); });
  es.onerror = (err) => { $("artistLoading")?.remove(); es.close(); };
}

async function renderAlbumPage(album) {
  setActiveView("home");
  const content = $("pageContent");
  content.innerHTML = `<div class="loading"><div class="spinner"></div><span>Loading ${esc(album.title || album.album)}…</span></div>`;

  try {
    const artistName = album.artist || "";
    const albumTitle = album.title || album.album || "";
    const releaseId = album.musicbrainz_release_id || "";
    const spotifyId = album.spotify_id || "";
    
    const data = await api(`/api/music/album_tracks?artist=${encodeURIComponent(artistName)}&album=${encodeURIComponent(albumTitle)}&release_id=${releaseId}&spotify_id=${spotifyId}`);
    
    content.innerHTML = `
      <div class="scroll-area">
        <div class="entity-hero">
          <div class="entity-art" style="background-image: url('${data.artwork_url || album.artwork_url || ""}')"></div>
          <div>
            <span class="eyebrow">Album</span>
            <h1>${esc(data.album)}</h1>
            <div class="hero-meta-row">
              <button class="hero-artist-link" id="heroArtistLink" title="${esc(data.artist)}">
                <div class="mini-art" style="background-image: url('${data.artist_artwork_url || ""}')"></div>
                ${esc(data.artist)}
              </button>
              <span class="dot">•</span>
              <span>${data.year}</span>
              <span class="dot">•</span>
              <span>${data.track_count} tracks</span>
              <span class="dot">•</span>
              <span>${data.total_duration}</span>
            </div>
          </div>
        </div>
        <div id="albumTrackList" class="track-list" style="margin-top: 24px"></div>
      </div>
    `;
    
    $("heroArtistLink").onclick = () => openArtistLink({ name: data.artist, artwork_url: data.artist_artwork_url });
    renderTrackList("albumTrackList", data.tracks || [], "album");
  } catch (e) {
    content.innerHTML = `<div class="error-state">Failed to load album: ${e.message}</div>`;
  }
}

// ---------------------------------------------------------------------------
// Selection & Playback (SpotiFLAC Only)
// ---------------------------------------------------------------------------

async function selectMusicItem(item, mode = "stream", contextList = null) {
  if (item.type === "artist") {
    pushPage(() => renderArtistPage(item));
    return;
  }
  if (item.type === "album") {
    pushPage(() => renderAlbumPage(item));
    return;
  }
  
  const requestId = ++state.playbackRequestId;
  state.activeJobId = null;
  state.currentTrack = item;
  
  prepareSelectedTrackUi(item, "Loading...");
  syncActiveTrackRows();
  
  if (contextList && contextList.length) {
    state.originalQueue = [...contextList].filter(t => t.type !== "artist");
    if (state.isShuffle) {
        state.queue = [...state.originalQueue].sort(() => Math.random() - 0.5);
    } else {
        state.queue = [...state.originalQueue];
    }
    state.queueIndex = state.queue.findIndex(t => t.title === item.title && t.artist === item.artist);
  }
  
  try {
    const source = await api("/api/playback/source", { method: "POST", body: JSON.stringify(serviceDownloadPayload(item, "stream")) });
    if (requestId !== state.playbackRequestId) return;
    if (source.path) {
      state.activeJobId = source.active_job_id || null;
      await playFromLibraryPath(source.path, item, requestId, source.active_job_id || null, source.source === "cache" ? "Playing from cache" : "Playing from library");
      return;
    }
  } catch (e) {}

  try {
    const { jobs } = await api("/api/service/downloads");
    if (requestId !== state.playbackRequestId) return;
    
    const existing = jobs.find(j =>
        j.mode === "stream" && (
          (item.spotify_id && j.spotify_id === item.spotify_id) ||
          (item.musicbrainz_recording_id && j.musicbrainz_recording_id === item.musicbrainz_recording_id) ||
          (j.title === item.title && j.artist === item.artist)
        )
    );
    
    if (existing) {
      state.activeJobId = existing.id;
      if (existing.status === "finished" && existing.library_path) {
        await playFromLibraryPath(existing.library_path, item, requestId, existing.id);
        return;
      } else if (existing.status === "running" || existing.status === "starting") {
        await startServiceDownload(item, mode, requestId, existing.id);
        return;
      }
    }
  } catch (e) {}

  await startServiceDownload(item, mode, requestId);
}

async function playFromLibraryPath(filePath, track, requestId, jobId, statusText = "Playing from library") {
  if (requestId !== state.playbackRequestId) return;
  const streamUrl = `${API_BASE}/api/library/stream?path=${encodeURIComponent(filePath)}&t=${Date.now()}`;
  state.currentStreamUrl = streamUrl;
  const audio = $("audioPlayer");
  audio.src = streamUrl;
  state.currentPlayableReady = true;
  state.autoplayWanted = true;
  
  setPlayerStatusIcon("ready");
  setPlayerStatus(statusText, track);
  audio.load();
  syncPlayPauseButton();
  tryStartAudio(audio, track, requestId, jobId);
}

function setPlayerStatusIcon(mode, pct) {
  const icon = $("playerStatusIcon");
  icon.className = "player-status " + (mode === "ready" ? "ready" : mode === "error" ? "error" : "downloading");
  if (mode === "ready") {
    icon.innerHTML = '<i class="bi bi-check-circle-fill"></i>';
  } else if (mode === "error") {
    icon.innerHTML = '<i class="bi bi-exclamation-circle"></i>';
  } else {
    const p = Math.max(0, Math.min(100, Math.round(pct || 0)));
    icon.innerHTML = `<span class="player-pie${p > 0 ? "" : " indeterminate"}" style="--pct:${p}"></span>`;
  }
}

function updatePlayerPie(pct) {
  const pie = $("playerStatusIcon")?.querySelector(".player-pie");
  if (!pie) return;
  const p = Math.max(0, Math.min(100, Math.round(pct || 0)));
  pie.style.setProperty("--pct", p);
  if (p > 0) pie.classList.remove("indeterminate");
}

function prepareSelectedTrackUi(track, status = "Opening stream...") {
  const audio = $("audioPlayer");
  audio.pause();
  try {
    audio.currentTime = 0;
  } catch (e) {}
  resetSeekUi();
  state.currentPlayableReady = false;
  state.autoplayWanted = false;
  setPlayerStatusIcon("downloading", 0);
  setPlayerStatus(status, track);
  syncActiveTrackRows();
}

function setPlayerStatus(msg, track) {
  state.playerStatus = msg;
  const meta = $("playerMeta");
  if (meta && meta.textContent !== msg) {
    meta.classList.remove("fade-in");
    void meta.offsetWidth;
    meta.textContent = msg;
    meta.classList.add("fade-in");
  }
  if (track) {
    $("playerTitle").innerHTML = albumLinkHtml(track, track.title || "Unknown");
    $("playerArtist").innerHTML = artistLinkHtml(track);
    updateDetailsPanel(track);
    updateMediaSession(track);
    bindEntityLinks($("playerTitle").parentElement);
  }
}

function updateDetailsPanel(track) {
  const url = track.artwork_url || "";
  const containers = [document.querySelector(".player-cover"), $("sideCover")];
  containers.forEach(c => {
    if (c) {
      c.style.backgroundImage = url ? `url('${url}')` : "";
      c.innerHTML = url ? "" : `<i class="bi bi-music-note"></i>`;
    }
  });
  $("sideTitle").innerHTML = albumLinkHtml(track, track.title || "No track selected");
  $("sideMeta").innerHTML = artistLinkHtml(track) || "Search or choose from library";
  bindEntityLinks(document.querySelector(".details-head"));
}

function serviceDownloadPayload(track, mode = "stream") {
  return {
    kind: "track",
    mode,
    artist: track.artist || "",
    album: track.album || "",
    title: track.title || "",
    quality: state.settings.default_quality || "LOSSLESS",
    service: state.settings.download_service || "tidal",
    track,
    metadata: track.metadata || track,
  };
}

async function prefetchNextTrack() {
  if (state.isRepeat) return;
  if (!state.queue.length || state.queueIndex < 0) return;
  const nextIdx = state.queueIndex + 1;
  if (nextIdx >= state.queue.length) return;
  const next = state.queue[nextIdx];
  if (!next || next.type === "artist" || next.type === "album") return;
  try {
    const source = await api("/api/playback/source", { method: "POST", body: JSON.stringify(serviceDownloadPayload(next, "stream")) });
    if (source.path) return; // already cached, nothing to do
  } catch (e) {}
  try {
    await api("/api/service/download", { method: "POST", body: JSON.stringify(serviceDownloadPayload(next, "stream")) });
  } catch (e) {}
}

async function toggleTrackLibrary(track, button, refresh) {
  if (!isTrackItem(track)) return;
  if (button.classList.contains("progress")) {
    await cancelLibraryDownload(track, button, refresh);
    return;
  }
  button.classList.add("progress");
  button.classList.remove("downloaded");
  button.dataset.cancelled = "";
  button.innerHTML = progressButtonMarkup({ progress: 0 });
  try {
    const result = await api("/api/library/toggle", {
      method: "POST",
      body: JSON.stringify(serviceDownloadPayload(track, "download")),
    });
    const activeJobId = result.job?.id || result.active_job_id || "";
    if (activeJobId) button.dataset.activeJobId = activeJobId;
    if (result.action === "started" || result.action === "queued") {
      await waitForLibraryToggle(track, activeJobId, button);
    }
    if (typeof refresh === "function") refresh();
  } catch (error) {
    if (button.dataset.cancelled !== "1") {
      button.title = error.message || "Library update failed";
    }
  } finally {
    button.classList.remove("progress");
    button.dataset.activeJobId = "";
  }
}

async function cancelLibraryDownload(track, button, refresh) {
  button.dataset.cancelled = "1";
  let jobId = button.dataset.activeJobId || "";
  if (!jobId) {
    const status = await api("/api/library/status", {
      method: "POST",
      body: JSON.stringify(serviceDownloadPayload(track, "download")),
    }).catch(() => null);
    jobId = status?.active_job_id || "";
  }
  if (jobId) {
    await api("/api/service/cancel", {
      method: "DELETE",
      body: JSON.stringify({ job_id: jobId }),
    }).catch(() => null);
  }
  button.classList.remove("progress");
  button.classList.remove("downloaded");
  button.dataset.activeJobId = "";
  button.innerHTML = '<i class="bi bi-check-circle"></i>';
  if (typeof refresh === "function") refresh();
}

function updateLibraryProgressButton(button, status) {
  if (!button) return;
  button.classList.add("progress");
  const s = typeof status === "object" ? status : { progress: status };
  button.innerHTML = progressButtonMarkup(s);
}

async function waitForLibraryToggle(track, jobId = "", button = null) {
  for (let attempt = 0; attempt < 900; attempt++) {
    if (button?.dataset.cancelled === "1") return null;
    await new Promise(resolve => setTimeout(resolve, 1000));
    if (button?.dataset.cancelled === "1") return null;
    const status = await api("/api/library/status", {
      method: "POST",
      body: JSON.stringify(serviceDownloadPayload(track, "download")),
    }).catch(() => null);
    if (status?.active_job_id && button) button.dataset.activeJobId = status.active_job_id;
    if (status && typeof status.progress !== "undefined") {
      updateLibraryProgressButton(button, status);
    }
    if (status?.active_job_status === "error") throw new Error("Download cancelled");
    if (status?.in_library) {
      if (button) {
        button.classList.remove("progress");
        button.classList.add("downloaded");
        button.innerHTML = '<i class="bi bi-check-circle-fill downloaded"></i>';
      }
      return status;
    }
    if (jobId) {
      const data = await api("/api/service/downloads").catch(() => ({ jobs: [] }));
      const job = (data.jobs || []).find(item => item.id === jobId);
      if (job?.status === "error") throw new Error(job.error || "Download failed");
      if (job?.status === "finished") {
        updateLibraryProgressButton(button, { ...job, progress: 100 });
      } else if (job && typeof job.progress !== "undefined") {
        updateLibraryProgressButton(button, job);
      }
    }
  }
  throw new Error("Library update timed out");
}

async function startServiceDownload(track, mode = "stream", requestId = state.playbackRequestId, existingJobId = null) {
  if (requestId !== state.playbackRequestId) return;
  const payload = serviceDownloadPayload(track, mode);
  try {
    let job;
    if (existingJobId) {
      const data = await api("/api/service/downloads");
      job = data.jobs.find(j => j.id === existingJobId);
    } else {
      job = await api("/api/service/download", { method: "POST", body: JSON.stringify(payload) });
    }
    
    if (requestId !== state.playbackRequestId) return;
    state.activeJobId = job.id;
    
    if (mode === "stream") {
      if (job.status === "finished" && job.library_path) {
        playFromLibraryPath(job.library_path, track, requestId, job.id, "Playing from cache");
      } else {
        const streamUrl = `${API_BASE}/api/library/stream_active_job?job_id=${job.id}&t=${Date.now()}`;
        state.currentStreamUrl = streamUrl;
        const audio = $("audioPlayer");
        audio.src = streamUrl;
        state.currentPlayableReady = true;
        state.autoplayWanted = true;
        audio.load();
        syncPlayPauseButton();
        tryStartAudio(audio, track, requestId, job.id);
      }
    }
    watchServiceDownload(job.id, track, mode, requestId);
  } catch (error) {
    setPlayerStatus(error.message || "Download failed", track);
  }
}

async function watchServiceDownload(jobId, track, mode = "stream", requestId = state.playbackRequestId) {
  let switchedToFinal = false;
  for (let attempt = 0; attempt < 600; attempt++) {
    if (requestId !== state.playbackRequestId || state.activeJobId !== jobId) return;
    await new Promise((resolve) => setTimeout(resolve, 1000));
    try {
      if (requestId !== state.playbackRequestId || state.activeJobId !== jobId) return;
      const data = await api("/api/service/downloads");
      const job = (data.jobs || []).find((item) => item.id === jobId);
      if (!job) return;
      if (job.status === "error") {
        setPlayerStatusIcon("error");
        setPlayerStatus(job.error || "Service download failed", track);
        return;
      }
      const pct = job.progress ? Math.max(0, Math.min(99, Math.round(job.progress))) : 0;
      if (job.status === "finished") {
        setPlayerStatusIcon("ready");
        setPlayerStatus(mode === "stream" ? "Playing from cache" : "Saved to library", track);
        if (!switchedToFinal && mode === "stream" && job.library_path) {
          switchedToFinal = true;
          await playFromLibraryPath(job.library_path, track, requestId, jobId, "Playing from cache");
        }
        return;
      }
      updatePlayerPie(pct);
      setPlayerStatus("Loading...", track);
    } catch (error) {}
  }
}

function tryStartAudio(audio, track, requestId, jobId) {
  audio.play().catch((error) => {
    if (requestId !== state.playbackRequestId) return;
    state.autoplayWanted = false;
    if (error && error.name === "NotAllowedError") {
      state.autoplayWanted = true;
      setPlayerStatus("Ready — press play", track);
    }
  });
}

// ---------------------------------------------------------------------------
// Search & Suggestions
// ---------------------------------------------------------------------------

function bindSearch() {
  const input = $("searchInput");
  input.oninput = () => {
    clearTimeout(state.suggestTimer);
    const value = input.value.trim();
    if (value.length < 2) {
      hideSuggestions();
      return;
    }
    state.suggestTimer = setTimeout(async () => {
      try {
        const data = await api(`/api/music/suggest?q=${encodeURIComponent(value)}`);
        state.suggestionAllResults = data.results || [];
        state.suggestionVisibleCount = Math.min(6, state.suggestionAllResults.length);
        state.suggestionResults = state.suggestionAllResults.slice(0, state.suggestionVisibleCount);
        renderSuggestions();
      } catch (e) {}
    }, 300);
  };

  input.onkeydown = (e) => {
    if (e.key === "Enter") {
      const value = input.value.trim();
      if (value) {
        hideSuggestions();
        searchMusic(value);
      }
    }
  };
}

function renderSuggestions() {
  const box = $("suggestions");
  if (!state.suggestionResults.length) {
    hideSuggestions();
    return;
  }
  box.innerHTML = state.suggestionResults.map((item, index) => suggestionMarkup(item, index)).join("");
  box.classList.toggle("has-more", state.suggestionAllResults.length > 6);
  box.classList.remove("hidden");
  bindSuggestionButtons(box);
  appendRemainingAsync();
}

function appendRemainingAsync() {
  const box = $("suggestions");
  let i = state.suggestionVisibleCount;

  function step() {
    if (i >= state.suggestionAllResults.length || box.classList.contains("hidden")) return;
    box.insertAdjacentHTML("beforeend", suggestionMarkup(state.suggestionAllResults[i], i));
    bindSuggestionButtons(box);
    i++;
    state.suggestionVisibleCount = i;
    state.suggestionResults = state.suggestionAllResults.slice(0, i);
    requestAnimationFrame(step);
  }

  requestAnimationFrame(step);
}

function suggestionMarkup(item, index) {
  const art = item.artwork_url || "";
  const name = esc(item.type === "artist" ? item.artist : (item.title || item.artist));
  const typeLabel = { track: "Song", artist: "Artist", album: "Album" }[item.type] || (item.type || "Song");
  const sub = item.type !== "artist" ? `<div class="suggestion-sub"><span class="pill">${esc(typeLabel)}</span> ${esc(item.artist || item.album || "")}</div>` : `<div class="suggestion-sub"><span class="pill">Artist</span></div>`;
  
  return `
    <button class="suggestion" type="button" data-suggestion="${index}">
      <div class="suggestion-art" style="background-image: url('${art}')">
        ${art ? "" : suggestionIcon(item.type)}
      </div>
      <div class="suggestion-info">
        <strong>${name}</strong>
        ${sub}
      </div>
    </button>
  `;
}

function bindSuggestionButtons(root = document) {
  root.querySelectorAll("[data-suggestion]").forEach((button) => {
    if (button.dataset.bound) return;
    button.dataset.bound = "1";
    button.onclick = () => {
      const item = state.suggestionResults[Number(button.dataset.suggestion)];
      $("searchInput").value = item.title || item.artist || "";
      hideSuggestions();
      if (item.type === "artist" || item.type === "album") {
        searchMusic(item.title || item.artist, item.type);
        selectMusicItem(item);
      } else {
        searchMusic(item.title || item.artist, "track");
      }
    };
  });
}

function suggestionIcon(type) {
  if (type === "artist") return '<i class="bi bi-person-circle"></i>';
  if (type === "album") return '<i class="bi bi-disc"></i>';
  return '<i class="bi bi-music-note-beamed"></i>';
}

function hideSuggestions() {
  const box = $("suggestions");
  box.classList.add("hidden");
  box.classList.remove("has-more");
  box.innerHTML = "";
  state.suggestionAllResults = [];
  state.suggestionResults = [];
  state.suggestionVisibleCount = 0;
}

async function searchMusic(q, type = "all") {
  pushPage(() => {
    setActiveView("home");
    $("pageContent").innerHTML = `<div class="loading"><div class="spinner"></div><span>Searching for "${esc(q)}"…</span></div>`;
    api(`/api/music/search?q=${encodeURIComponent(q)}`).then(data => {
      renderSearchPage(data.results, q, type);
    }).catch(e => {
      $("pageContent").innerHTML = `<div class="error-state">Search failed: ${e.message}</div>`;
    });
  });
}

function renderSearchPage(results, query, tab = "all") {
  const filtered = tab === "all" ? results : results.filter(r => r.type === tab);
  
  setActiveView("home");
  $("pageContent").innerHTML = `
    <div class="section-head sticky-head" style="flex-direction: column; align-items: flex-start; gap: 16px">
      <div style="display: flex; justify-content: space-between; align-items: baseline; width: 100%">
        <h1>Results for "${esc(query)}"</h1>
        <span>${results.length} items found</span>
      </div>
      <div class="search-tabs">
        ${["all", "track", "artist", "album"].map(t => `
          <button class="tab ${tab === t ? "active" : ""}" data-search-tab="${t}">${tabLabel(t)}</button>
        `).join("")}
      </div>
    </div>
    <div class="scroll-area">
      <div id="searchGrid" class="${tab === "artist" || tab === "album" ? "grid" : "track-list"}" style="margin-top: 8px"></div>
    </div>
  `;

  document.querySelectorAll("[data-search-tab]").forEach(btn => {
    btn.onclick = () => replacePage(() => renderSearchPage(results, query, btn.dataset.searchTab));
  });

  if (tab === "artist" || tab === "album") {
    renderCards("searchGrid", filtered, tab);
  } else {
    renderTrackList("searchGrid", filtered, "search");
  }
}

function tabLabel(tab) {
  return { all: "All", track: "Songs", artist: "Artists", album: "Albums" }[tab] || tab;
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

async function renderSettings() {
  setActiveView("settings");
  state.settings = await api("/api/settings");
  
  $("cacheDir").value = state.settings.cache_dir || "";
  $("musicDir").value = state.settings.music_dir || "";
  $("downloadService").value = state.settings.download_service || "tidal";
  updateQualityOptions($("downloadService").value, state.settings.default_quality || "LOSSLESS");
  $("downloadService").onchange = () => updateQualityOptions($("downloadService").value, $("defaultQuality").value);
  $("cacheCleanupFrequency").value = state.settings.cache_cleanup_frequency || "never";
  $("demoMusicIndexer").checked = !!state.settings.demo_music_indexer;
  $("strictTitleMatch").checked = !!state.settings.strict_title_match;
  
  $("musicIndexers").innerHTML = "";
  (state.settings.music_indexers || []).forEach(indexer => {
    const row = document.createElement("div");
    row.className = "indexer-row";
    row.innerHTML = `
      <input data-field="name" placeholder="Name" value="${esc(indexer.name)}">
      <select data-field="type"><option value="musicbrainz" selected>MusicBrainz</option></select>
      <label class="check"><input data-field="enabled" type="checkbox" ${indexer.enabled?"checked":""}> Enabled</label>
      <button type="button" class="remove-btn" data-remove><i class="bi bi-trash"></i></button>
    `;
    row.querySelector("[data-remove]").onclick = () => row.remove();
    $("musicIndexers").appendChild(row);
  });
  
  try {
    const stats = await api("/api/cache");
    $("cacheUsage").textContent = `${(stats.bytes / (1024 * 1024)).toFixed(1)} MB used by ${stats.files} files`;
  } catch (e) {}
}

async function saveSettings(e) {
  e.preventDefault();
  const body = {
    ...state.settings,
    cache_dir: $("cacheDir").value,
    music_dir: $("musicDir").value,
    download_service: $("downloadService").value,
    default_quality: $("defaultQuality").value,
    cache_cleanup_frequency: $("cacheCleanupFrequency").value,
    demo_music_indexer: $("demoMusicIndexer").checked,
    strict_title_match: $("strictTitleMatch").checked,
    music_indexers: Array.from(document.querySelectorAll("#musicIndexers .indexer-row")).map(row => ({
      name: row.querySelector("[data-field='name']").value,
      type: row.querySelector("[data-field='type']").value,
      enabled: row.querySelector("[data-field='enabled']").checked,
    }))
  };
  try {
    await api("/api/settings", { method: "POST", body: JSON.stringify(body) });
    state.settings = body;
    alert("Settings saved");
  } catch (e) { alert("Save failed: " + e.message); }
}

// ---------------------------------------------------------------------------
// Player & Boot
// ---------------------------------------------------------------------------

function syncPlayPauseButton() {
  const audio = $("audioPlayer");
  const playPause = $("playPause");
  if (!playPause) return;
  const icon = playPause.querySelector("i");
  if (icon) {
    icon.className = audio.paused ? "bi bi-play-fill" : "bi bi-pause-fill";
  }
}

function syncVolumeBar() {
  const audio = $("audioPlayer");
  const volume = $("volumeBar");
  if (!audio || !volume) return;
  volume.value = audio.volume;
  volume.style.backgroundSize = `${audio.volume * 100}% 100%`;
}

function seekBy(seconds) {
  const audio = $("audioPlayer");
  if (!audio || !Number.isFinite(audio.duration) || audio.duration <= 0) return;
  audio.currentTime = Math.max(0, Math.min(audio.duration, audio.currentTime + seconds));
}

function stopSeekHold() {
  if (state.seekHoldTimer) {
    clearInterval(state.seekHoldTimer);
    state.seekHoldTimer = null;
  }
  state.seekHoldDirection = 0;
}

function changeVolumeBy(delta) {
  const audio = $("audioPlayer");
  if (!audio) return;
  audio.volume = Math.max(0, Math.min(1, audio.volume + delta));
  localStorage.setItem(STORAGE_KEYS.volume, String(audio.volume));
  syncVolumeBar();
}

function stopVolumeHold() {
  if (state.volumeHoldTimer) {
    clearInterval(state.volumeHoldTimer);
    state.volumeHoldTimer = null;
  }
  state.volumeHoldDirection = 0;
}

function startVolumeHold(direction) {
  if (state.volumeHoldDirection === direction && state.volumeHoldTimer) return;
  stopVolumeHold();
  state.volumeHoldDirection = direction;
  changeVolumeBy(direction * 0.05);
  state.volumeHoldTimer = setInterval(() => changeVolumeBy(direction * 0.02), 120);
}

function startSeekHold(direction) {
  if (state.seekHoldDirection === direction && state.seekHoldTimer) return;
  stopSeekHold();
  state.seekHoldDirection = direction;
  seekBy(direction * 1);
  state.seekHoldTimer = setInterval(() => seekBy(direction * 0.35), 120);
}

function bindKeyboardControls() {
  document.addEventListener("keydown", (event) => {
    if (isTypingTarget(event.target)) return;
    if (event.code === "Space") {
      event.preventDefault();
      const audio = $("audioPlayer");
      if (!audio.src && !state.currentStreamUrl) return;
      audio.paused ? audio.play() : audio.pause();
      return;
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      startSeekHold(1);
      return;
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      startSeekHold(-1);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      startVolumeHold(1);
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      startVolumeHold(-1);
    }
  });
  document.addEventListener("keyup", (event) => {
    if (event.key === "ArrowRight" && state.seekHoldDirection === 1) stopSeekHold();
    if (event.key === "ArrowLeft" && state.seekHoldDirection === -1) stopSeekHold();
    if (event.key === "ArrowUp" && state.volumeHoldDirection === 1) stopVolumeHold();
    if (event.key === "ArrowDown" && state.volumeHoldDirection === -1) stopVolumeHold();
  });
  window.addEventListener("blur", () => {
    stopSeekHold();
    stopVolumeHold();
  });
}

function storedVolume() {
  const fromSettings = Number(state.settings?.volume);
  if (Number.isFinite(fromSettings)) return Math.max(0, Math.min(1, fromSettings));
  const local = Number(localStorage.getItem(STORAGE_KEYS.volume));
  return Number.isFinite(local) ? Math.max(0, Math.min(1, local)) : 1;
}

let _volumeSaveTimer = null;
function persistVolume(vol) {
  state.settings.volume = vol;
  clearTimeout(_volumeSaveTimer);
  _volumeSaveTimer = setTimeout(() => {
    api("/api/settings", { method: "POST", body: JSON.stringify(state.settings) }).catch(() => {});
  }, 600);
}

function absoluteUrl(url) {
  if (!url) return "";
  try {
    return new URL(url, window.location.href).href;
  } catch (e) {
    return "";
  }
}

function updateMediaSession(track) {
  if (!("mediaSession" in navigator) || !track) return;
  const art = absoluteUrl(track.artwork_url || "");
  const artwork = art ? [
    { src: art, sizes: "96x96", type: "image/png" },
    { src: art, sizes: "128x128", type: "image/png" },
    { src: art, sizes: "256x256", type: "image/png" },
    { src: art, sizes: "512x512", type: "image/png" },
  ] : [];
  navigator.mediaSession.metadata = new MediaMetadata({
    title: track.title || "Unknown",
    artist: track.artist || "",
    album: track.album || "",
    artwork,
  });
}

function bindMediaSessionActions() {
  if (!("mediaSession" in navigator)) return;
  const audio = $("audioPlayer");
  const handlers = {
    play: () => audio.play(),
    pause: () => audio.pause(),
    previoustrack: () => $("btnPrev").click(),
    nexttrack: () => $("btnNext").click(),
  };
  Object.entries(handlers).forEach(([action, handler]) => {
    try {
      navigator.mediaSession.setActionHandler(action, handler);
    } catch (e) {}
  });
}

function bindPlayer() {
  const audio = $("audioPlayer");
  audio.volume = storedVolume();
  syncVolumeBar();
  $("playPause").onclick = () => audio.paused ? audio.play() : audio.pause();
  audio.onplay = audio.onpause = () => {
    syncPlayPauseButton();
    syncActiveTrackRows();
    if ("mediaSession" in navigator) {
      navigator.mediaSession.playbackState = audio.paused ? "paused" : "playing";
    }
  };
  audio.onended = () => {
    if (state.queue.length) {
      state.queueIndex = (state.queueIndex + 1) % state.queue.length;
      selectMusicItem(state.queue[state.queueIndex], "stream", state.originalQueue);
    }
  };
  audio.ontimeupdate = () => {
    if (!audio.duration) return;
    $("seekBar").value = (audio.currentTime / audio.duration) * 1000;
    $("currentTime").textContent = formatTime(audio.currentTime);
    $("durationTime").textContent = formatTime(audio.duration);
    $("seekBar").style.backgroundSize = `${(audio.currentTime / audio.duration) * 100}% 100%`;
    if (audio.currentTime >= 2 && state.prefetchedForRequestId !== state.playbackRequestId) {
      state.prefetchedForRequestId = state.playbackRequestId;
      prefetchNextTrack().catch(() => {});
    }
  };
  $("seekBar").oninput = () => { if (audio.duration) audio.currentTime = ($("seekBar").value / 1000) * audio.duration; };
  $("volumeBar").oninput = () => {
    audio.volume = Number($("volumeBar").value);
    persistVolume(audio.volume);
    syncVolumeBar();
  };
  $("btnNext").onclick = () => { if (state.queue.length) { state.queueIndex = (state.queueIndex + 1) % state.queue.length; selectMusicItem(state.queue[state.queueIndex], "stream", state.originalQueue); } };
  $("btnPrev").onclick = () => { if (state.queue.length) { state.queueIndex = (state.queueIndex - 1 + state.queue.length) % state.queue.length; selectMusicItem(state.queue[state.queueIndex], "stream", state.originalQueue); } };
  $("btnShuffle").onclick = () => { state.isShuffle = !state.isShuffle; $("btnShuffle").classList.toggle("active", state.isShuffle); };
  $("btnRepeat").onclick = () => { state.isRepeat = !state.isRepeat; $("btnRepeat").classList.toggle("active", state.isRepeat); audio.loop = state.isRepeat; };
  bindMediaSessionActions();
}

function formatTime(s) { const m = Math.floor(s / 60); return `${m}:${Math.floor(s % 60).toString().padStart(2, "0")}`; }

// ---------------------------------------------------------------------------
// Playlists
// ---------------------------------------------------------------------------

async function loadPlaylists() {
  try {
    state.playlists = await api("/api/playlists");
    renderSidebarPlaylists();
  } catch (e) {
    console.error("loadPlaylists failed", e);
  }
}

function trackInPlaylist(playlist, track) {
  if (!track) return false;
  return playlist.tracks.some(t => {
    if (track.spotify_id && t.spotify_id) return t.spotify_id === track.spotify_id;
    return t.title?.toLowerCase() === track.title?.toLowerCase() &&
           t.artist?.toLowerCase() === track.artist?.toLowerCase();
  });
}

function renderSidebarPlaylists() {
  const list = $("sidebarPlaylistList");
  if (!list) return;
  if (!state.playlists.length) {
    list.innerHTML = `<div style="padding: 8px 10px; font-size: 12px; color: var(--muted);">No playlists yet</div>`;
    return;
  }
  list.innerHTML = state.playlists.map(pl => {
    const art = pl.artwork_url || (pl.tracks[0] || {}).artwork_url || "";
    const artStyle = art ? `style="background-image: url('${art}')"` : "";
    const artIcon = art ? "" : `<i class="bi bi-music-note-list"></i>`;
    return `
      <div class="sidebar-playlist-item" data-playlist-id="${pl.id}">
        <div class="sidebar-playlist-art" ${artStyle}>${artIcon}</div>
        <div class="sidebar-playlist-info">
          <div class="sidebar-playlist-name">${esc(pl.name)}</div>
          <div class="sidebar-playlist-count">${pl.tracks.length} song${pl.tracks.length !== 1 ? "s" : ""}</div>
        </div>
        <button class="sidebar-playlist-delete" type="button" data-delete-playlist="${pl.id}" aria-label="Delete playlist" title="Delete playlist"><i class="bi bi-trash3"></i></button>
      </div>
    `;
  }).join("");

  list.querySelectorAll(".sidebar-playlist-item").forEach(el => {
    el.onclick = (event) => {
      if (event.target.closest("[data-delete-playlist]")) return;
      const pl = state.playlists.find(p => p.id === el.dataset.playlistId);
      if (pl) pushPage(() => renderPlaylistPage(pl));
    };
  });
  list.querySelectorAll("[data-delete-playlist]").forEach(btn => {
    btn.onclick = (event) => {
      event.stopPropagation();
      deletePlaylist(btn.dataset.deletePlaylist);
    };
  });
}

async function deletePlaylist(id) {
  if (!confirm("Delete this playlist?")) return;
  try {
    await api("/api/playlists", { method: "DELETE", body: JSON.stringify({ id }) });
    state.playlists = state.playlists.filter(p => p.id !== id);
    renderSidebarPlaylists();
    // If we're viewing this playlist, go back
    if (state.viewStack.length > 1) popPage();
  } catch (e) {
    alert("Failed to delete playlist: " + e.message);
  }
}

function formatDuration(tracks) {
  const ms = tracks.reduce((sum, t) => sum + (t.duration_ms || 0), 0);
  if (!ms) return "";
  const totalMin = Math.floor(ms / 60000);
  const hr = Math.floor(totalMin / 60);
  const min = totalMin % 60;
  return hr ? `${hr} hr ${min} min` : `${min} min`;
}

function renderPlaylistPage(playlist) {
  setActiveView("home");
  document.querySelectorAll(".nav").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".sidebar-playlist-item").forEach(el => {
    el.classList.toggle("active", el.dataset.playlistId === playlist.id);
  });
  const pl = state.playlists.find(p => p.id === playlist.id) || playlist;
  _renderPlaylistContent(pl);

  // Auto-refresh once if imported from Spotify but metadata not yet fetched
  if (pl.spotify_url && !pl.metadata_fetched) {
    api("/api/playlists/refresh", { method: "POST", body: JSON.stringify({ id: pl.id }) })
      .then(updated => {
        const idx = state.playlists.findIndex(p => p.id === pl.id);
        if (idx !== -1) state.playlists[idx] = updated;
        renderSidebarPlaylists();
        _renderPlaylistContent(updated);
        document.querySelectorAll(".sidebar-playlist-item").forEach(el => {
          el.classList.toggle("active", el.dataset.playlistId === pl.id);
        });
      }).catch(() => {});
  }
}

function _renderPlaylistContent(pl) {
  const heroArt = pl.artwork_url || (pl.tracks[0] || {}).artwork_url || "";
  const artStyle = heroArt ? `background-image: url('${heroArt}')` : "";
  const artIcon = artStyle ? "" : `<i class="bi bi-music-note-list"></i>`;
  const duration = formatDuration(pl.tracks);
  const metaParts = [];
  if (pl.owner) metaParts.push(esc(pl.owner));
  if (pl.followers) metaParts.push(`${pl.followers.toLocaleString()} saves`);
  metaParts.push(`${pl.tracks.length} song${pl.tracks.length !== 1 ? "s" : ""}${duration ? ", " + duration : ""}`);

  $("pageContent").innerHTML = `
    <div class="scroll-area">
      <div class="playlist-hero">
        <div class="playlist-hero-art" style="${artStyle}">${artIcon}</div>
        <div class="playlist-hero-info">
          <span class="eyebrow">Playlist</span>
          <h1>${esc(pl.name)}</h1>
          ${pl.description ? `<div class="playlist-hero-desc">${esc(pl.description)}</div>` : ""}
          <div class="playlist-hero-meta">${metaParts.join(" · ")}</div>
        </div>
      </div>
      <div id="playlistTrackList" class="track-list" style="margin-top: 24px"></div>
    </div>
  `;

  if (pl.tracks.length) {
    renderTrackList("playlistTrackList", pl.tracks, "general");
  } else {
    $("playlistTrackList").innerHTML = `<div style="padding: 24px; color: var(--muted); text-align: center;">No songs yet — click the status icon while a track is playing to add it.</div>`;
  }
}

// Open the "Add to playlist" picker for the current track
function openPlaylistPicker(track) {
  if (!track) return;
  const dialog = $("playlistPickerDialog");
  if (!dialog) return;

  let searchVal = "";

  function renderPickerList() {
    const body = $("playlistPickerBody");
    const filtered = state.playlists.filter(pl =>
      !searchVal || pl.name.toLowerCase().includes(searchVal.toLowerCase())
    );

    const sections = [];

    // Saved in (already contains track)
    const saved = filtered.filter(pl => trackInPlaylist(pl, track));
    if (saved.length) {
      sections.push(`<div class="playlist-picker-divider">Saved in</div>`);
      saved.forEach(pl => sections.push(pickerRowHtml(pl, true)));
    }

    // Recently updated (not containing track)
    const recent = filtered.filter(pl => !trackInPlaylist(pl, track));
    if (recent.length) {
      sections.push(`<div class="playlist-picker-divider">Recently updated</div>`);
      recent.forEach(pl => sections.push(pickerRowHtml(pl, false)));
    }

    const newBtn = `
      <button class="playlist-picker-new" id="pickerNewBtn" type="button">
        <div class="playlist-picker-new-icon"><i class="bi bi-plus-lg"></i></div>
        New playlist
      </button>
    `;

    body.innerHTML = newBtn + sections.join("");

    body.querySelectorAll("[data-picker-playlist]").forEach(btn => {
      btn.onclick = async () => {
        const plId = btn.dataset.pickerPlaylist;
        const wasIn = btn.dataset.inPlaylist === "1";
        const pl = state.playlists.find(p => p.id === plId);
        if (!pl) return;
        try {
          const result = await api("/api/playlists/tracks", {
            method: "POST",
            body: JSON.stringify({ playlist_id: plId, track, action: wasIn ? "remove" : "add" }),
          });
          const idx = state.playlists.findIndex(p => p.id === plId);
          if (idx !== -1) {
            if (result.in_playlist) {
              state.playlists[idx].tracks.push(track);
            } else {
              state.playlists[idx].tracks = state.playlists[idx].tracks.filter(t => {
                if (track.spotify_id && t.spotify_id) return t.spotify_id !== track.spotify_id;
                return !(t.title?.toLowerCase() === track.title?.toLowerCase() && t.artist?.toLowerCase() === track.artist?.toLowerCase());
              });
            }
          }
          renderSidebarPlaylists();
          renderPickerList();
        } catch (e) {
          alert("Failed: " + e.message);
        }
      };
    });

    $("pickerNewBtn").onclick = () => {
      dialog.close();
      openCreatePlaylistDialog(track);
    };
  }

  renderPickerList();

  $("playlistPickerSearch").value = "";
  $("playlistPickerSearch").oninput = (e) => {
    searchVal = e.target.value;
    renderPickerList();
  };

  dialog.showModal();
}

function pickerRowHtml(pl, isIn) {
  const art = (pl.tracks[0] || {}).artwork_url || "";
  const artStyle = art ? `style="background-image: url('${art}')"` : "";
  const artIcon = art ? "" : `<i class="bi bi-music-note-list"></i>`;
  return `
    <button class="playlist-picker-row" type="button" data-picker-playlist="${pl.id}" data-in-playlist="${isIn ? "1" : "0"}">
      <div class="playlist-picker-art" ${artStyle}>${artIcon}</div>
      <div class="playlist-picker-info">
        <strong>${esc(pl.name)}</strong>
        <span>${pl.tracks.length} songs</span>
      </div>
      <div class="playlist-picker-check ${isIn ? "checked" : ""}">
        ${isIn ? '<i class="bi bi-check-lg"></i>' : ""}
      </div>
    </button>
  `;
}

function openCreatePlaylistDialog(trackToAdd = null) {
  const dialog = $("createPlaylistDialog");
  if (!dialog) return;
  $("newPlaylistName").value = "";
  $("newPlaylistSpotifyUrl").value = "";
  dialog.showModal();

  $("createPlaylistSubmit").onclick = async () => {
    const name = $("newPlaylistName").value.trim() || "New Playlist";
    const spotifyUrl = $("newPlaylistSpotifyUrl").value.trim();
    $("createPlaylistSubmit").disabled = true;
    $("createPlaylistSubmit").textContent = "Creating…";
    try {
      const result = await api("/api/playlists", {
        method: "POST",
        body: JSON.stringify({ name, spotify_url: spotifyUrl }),
      });
      state.playlists.unshift(result);
      // If a track was queued to be added, add it now
      if (trackToAdd) {
        try {
          await api("/api/playlists/tracks", {
            method: "POST",
            body: JSON.stringify({ playlist_id: result.id, track: trackToAdd, action: "add" }),
          });
          state.playlists[0].tracks.push(trackToAdd);
        } catch (e) {}
      }
      renderSidebarPlaylists();
      dialog.close();
    } catch (e) {
      alert("Failed to create playlist: " + e.message);
    } finally {
      $("createPlaylistSubmit").disabled = false;
      $("createPlaylistSubmit").textContent = "Create";
    }
  };
}

function bindPlaylistDialogs() {
  const picker = $("playlistPickerDialog");
  const creator = $("createPlaylistDialog");

  $("playlistPickerClose").onclick = () => picker.close();
  $("playlistPickerCancel").onclick = () => picker.close();
  $("createPlaylistClose").onclick = () => creator.close();
  $("createPlaylistCancel").onclick = () => creator.close();

  picker.addEventListener("click", (e) => { if (e.target === picker) picker.close(); });
  creator.addEventListener("click", (e) => { if (e.target === creator) creator.close(); });

  $("createPlaylistBtn").onclick = () => openCreatePlaylistDialog();

  $("playerStatusIcon").addEventListener("click", () => {
    if (!state.currentTrack) return;
    loadPlaylists().then(() => openPlaylistPicker(state.currentTrack));
  });
}

async function boot() {
  bindSearch();
  bindPlayer();
  bindKeyboardControls();
  bindPlaylistDialogs();
  state.settings = await api("/api/settings").catch(() => ({}));
  const _audio = $("audioPlayer");
  _audio.volume = storedVolume();
  syncVolumeBar();

  // Hide suggestions when clicking outside
  document.addEventListener("click", (e) => {
    const searchBox = document.querySelector(".search-box");
    if (searchBox && !searchBox.contains(e.target)) {
      hideSuggestions();
    }
  });

  document.querySelectorAll("[data-view]").forEach(el => {
    el.onclick = () => {
       if (el.dataset.view === "settings") pushPage(renderSettings);
       else if (el.dataset.view === "home") replacePage(renderHomePage);
       else if (el.dataset.view === "artists") pushPage(renderArtistsPage);
       else if (el.dataset.view === "albums") pushPage(renderAlbumsPage);
    };
  });
  $("settingsForm").onsubmit = saveSettings;
  $("backButton").onclick = popPage;
  $("forwardButton").onclick = forwardPage;
  $("clearCache").onclick = async () => { await api("/api/cache", { method: "DELETE" }); renderSettings(); };

  await Promise.all([loadCatalog(), loadPlaylists()]);
  replacePage(renderHomePage);
}

boot().catch(console.error);
