const API_BASE = "";
const CATALOG_REFRESH_MS = 15 * 60 * 1000;
const ARTIST_TRACK_PREVIEW_COUNT = 5;
const ARTIST_ALBUM_PREVIEW_COUNT = 6;
const ARTIST_RELATED_PREVIEW_COUNT = 6;
const PREFETCH_AHEAD_COUNT = 5;

const state = {
  viewStack: [],
  catalog: { artists: [], albums: [], top_tracks: [], personal_tracks: [], recent_tracks: [] },
  settings: {},
  playlists: [],
  currentTrack: null,
  activeJobId: null,
  prefetchJobs: new Map(),
  isShuffle: false,
  isRepeat: false,
  queue: [],
  originalQueue: [],
  queueContext: null,
  dockRecentItems: [],
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
  manualPauseRequested: false,
  currentPlayableReady: false,
  playerStatus: "Choose a track to stream",
  activeJobPhase: "",
  playbackRequestId: 0,
  listeningSession: null,
  sidebarRequestId: 0,
  tourPageRequestId: 0,
  sidebarTrackKey: null,
  currentStreamUrl: "",
  currentLibraryPath: "",
  pendingNativeStartAt: 0,
  nativeAudio: { active: false, playing: false, position: 0, duration: 0, path: "", ended: false },
  nativeAudioPollTimer: null,
  prefetchedForRequestId: -1,
  preMuteVolume: 1,
  catalogRefreshTimer: null,
  cacheLogTimer: null,
  progressLogOpen: false,
  progressLogTimer: null,
  progressLogTippy: null,
  progressLogEl: null,
  statusHintTippy: null,
  statusHintRef: null,
  tourLocation: null,
  tourLocationSearchTimer: null,
  tourEventLocationCache: new Map(),
  playlistRecommendationSessions: {},
  playlistRecommendationState: {},
  activePlaylistId: null,
  activeLibraryPill: "home",
  statsPeriod: "month",
  playlistContinuationLoads: new Set(),
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
    { value: "LOSSLESS", label: "ALAC" },
  ],
};

const ENGINE_PROVIDERS = {
  "ytp-dl": [],
  torrent: [
    { value: "all",           label: "All Trackers (Parallel)" },
    { value: "torlock",       label: "TorLock" },
    { value: "torrentdownloads", label: "TorrentDownloads" },
    { value: "limetorrents",  label: "LimeTorrents" },
    { value: "piratebay",     label: "The Pirate Bay" },
    { value: "1337x",         label: "1337x" },
    { value: "kickass",       label: "KickassTorrents" },
    { value: "yts",           label: "YTS" },
  ],
  spotiflac: [
    { value: "tidal",       label: "Tidal" },
    { value: "deezer",      label: "Deezer" },
    { value: "qobuz",       label: "Qobuz" },
    { value: "amazon",      label: "Amazon Music" },
    { value: "apple_music", label: "Apple Music" },
    { value: "soundcloud",  label: "SoundCloud" },
    { value: "youtube",     label: "YouTube" },
  ],
};

const ENGINE_QUALITIES = {
  "ytp-dl": [
    { value: "best", label: "Best available" },
    { value: "m4a",  label: "M4A / AAC" },
    { value: "mp3",  label: "MP3" },
  ],
  torrent: [
    { value: "LOSSLESS", label: "FLAC / Lossless" },
    { value: "MP3",      label: "MP3 / Lossy" },
  ],
  spotiflac: null,
};

function updateQualityOptions(service, currentQuality) {
  const sel = $("defaultQuality");
  if (!sel) return;
  const opts = SERVICE_QUALITIES[service] || SERVICE_QUALITIES.tidal;
  sel.innerHTML = opts.map(o => `<option value="${o.value}">${o.label}</option>`).join("");
  if (currentQuality && opts.some(o => o.value === currentQuality)) {
    sel.value = currentQuality;
  } else {
    sel.value = opts[0].value;
  }
}

function updateEngineControls(engine, currentService, currentQuality) {
  const serviceRow = $("serviceRow");
  const retriesRow = $("retriesRow");
  const serviceSel = $("downloadService");
  const qualitySel = $("defaultQuality");
  if (!serviceRow || !serviceSel || !qualitySel) return;

  const providers = ENGINE_PROVIDERS[engine] || ENGINE_PROVIDERS.spotiflac;
  const engineQualities = ENGINE_QUALITIES[engine];

  // Show/hide service row
  serviceRow.style.display = providers.length > 0 ? "" : "none";

  // Show/hide duckModel row (candidate-ranking engines only)
  const duckModelRow = $("duckModelRow");
  if (duckModelRow) {
    duckModelRow.style.display = engine === "torrent" || engine === "ytp-dl" ? "" : "none";
  }

  // Show/hide retries row (Tor is SpotiFLAC-only)
  if (retriesRow) retriesRow.style.display = engine === "spotiflac" ? "" : "none";

  // Populate service options
  serviceSel.innerHTML = providers.map(p => `<option value="${p.value}">${p.label}</option>`).join("");
  if (providers.length > 0) {
    if (currentService && providers.some(p => p.value === currentService)) {
      serviceSel.value = currentService;
    } else {
      serviceSel.value = providers[0].value;
    }
  }

  // Populate quality options
  if (engineQualities) {
    qualitySel.innerHTML = engineQualities.map(o => `<option value="${o.value}">${o.label}</option>`).join("");
    if (currentQuality && engineQualities.some(o => o.value === currentQuality)) {
      qualitySel.value = currentQuality;
    } else {
      qualitySel.value = engineQualities[0].value;
    }
  } else {
    // spotiflac: quality depends on selected service
    updateQualityOptions(serviceSel.value, currentQuality);
    serviceSel.onchange = () => updateQualityOptions(serviceSel.value, $("defaultQuality").value);
  }
}

const STORAGE_KEYS = {
  volume: "streambox.volume",
  dockRecents: "mindinguflac.dockRecents",
};

async function api(path, options = {}) {
  const { timeout = 15000, ...fetchOptions } = options;
  const controller = timeout > 0 ? new AbortController() : null;
  const id = controller ? setTimeout(() => controller.abort(), timeout) : null;
  try {
    const resp = await fetch(`${API_BASE}${path}`, {
      ...fetchOptions,
      signal: controller ? controller.signal : undefined,
    });
    if (id) clearTimeout(id);
    if (!resp.ok) {
      const error = await resp.json().catch(() => ({ error: resp.statusText }));
      throw new Error(error.error || "API call failed");
    }
    return resp.json();
  } catch (err) {
    if (id) clearTimeout(id);
    throw err;
  }
}

function $(id) { return document.getElementById(id); }

// ---------------------------------------------------------------------------
// DuckDuckGo duck.ai client (free, no API key). DDG gates every request behind
// `x-vqd-hash-1`, a per-request anti-bot token produced by EXECUTING an
// obfuscated JS challenge in a real browser DOM. This frontend IS a real browser
// (WKWebView on macOS, Edge WebView2 on Windows), so we solve the challenge here;
// the Python backend only relays the solved request to DDG (CORS forbids the
// browser calling duckduckgo.com directly).
// ---------------------------------------------------------------------------
async function _sha256Base64(text) {
  const data = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", data);
  let bin = "";
  for (const b of new Uint8Array(digest)) bin += String.fromCharCode(b);
  return btoa(bin);
}

async function duckChatAsk(messages, model = "gpt-5-mini") {
  // The backend now completely handles the anti-bot bypass.
  // We just fetch the VQD token and pass it to the chat endpoint.
  const status = await api("/api/ddg/status");
  if (!status || !status.vqd_hash_1) throw new Error("DDG token unavailable: " + ((status && status.error) || "no token"));

  return api("/api/ddg/chat", {
    method: "POST",
    body: JSON.stringify({
      vqd_hash_1: status.vqd_hash_1,
      model,
      messages
    }),
  });
}

window.testDuck = async function (query) {
  query = query || "Reply with exactly one word: pong";
  console.log("%c[Duck] Running Hardcoded Bypass...", "color: #00ffff; font-weight: bold;");
  try {
    const st = await api("/api/ddg/status");
    if (!st || !st.vqd_hash_1) {
      console.error("[Duck] ❌ Failed to get token:", st.error);
      return;
    }
    console.log("[Duck] Token obtained:", st.vqd_hash_1.substring(0, 15) + "...");

    const res = await api("/api/ddg/chat", {
      method: "POST",
      body: JSON.stringify({ vqd_hash_1: st.vqd_hash_1, model: "gpt-5-mini", messages: [{ role: "user", content: query }] }),
    });

    if (res && res.ok) {
      console.log("%c[Duck] ✅ SUCCESS! -> " + res.text, "color: #00ff00; font-weight: bold;");
    } else {
      console.warn(`%c[Duck] ❌ FAILED -> ${res.status} ${res.error}`, "color: #ff0000;");
      console.log("[Duck] Error Body:", res.body);
    }
  } catch (e) {
    console.error("[Duck] ❌ error:", e);
  }
};

function dockRecentKey(entry) {
  const data = entry.data || {};
  if (entry.kind === "playlist") return `playlist:${data.id || entry.title}`;
  return `track:${data.spotify_id || (data.metadata || {}).spotify_id || `${data.title || ""}:${data.artist || ""}`}`;
}

function storedDockRecentItems() {
  try {
    const entries = JSON.parse(localStorage.getItem(STORAGE_KEYS.dockRecents) || "[]");
    return Array.isArray(entries) ? entries.filter(entry => entry && entry.title && entry.data).slice(0, 3) : [];
  } catch (e) {
    return [];
  }
}

function publishDockRecentItems() {
  localStorage.setItem(STORAGE_KEYS.dockRecents, JSON.stringify(state.dockRecentItems.slice(0, 3)));
  api("/api/dock/recent", {
    method: "POST",
    body: JSON.stringify({ entries: state.dockRecentItems.slice(0, 3) }),
  }).catch(() => {});
}

function addDockRecentItems(entries) {
  const combined = [...entries, ...state.dockRecentItems];
  const seen = new Set();
  state.dockRecentItems = combined.filter(entry => {
    const key = dockRecentKey(entry);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).slice(0, 3);
  publishDockRecentItems();
}

function recordDockRecentSelection(track, playbackContext = null) {
  const entries = [];
  if (playbackContext && playbackContext.kind === "playlist") {
    entries.push({
      kind: "playlist",
      title: playbackContext.name,
      data: { id: playbackContext.id, name: playbackContext.name },
    });
  }
  entries.push({ kind: "track", title: track.title || track.name || "Unknown Track", data: track });
  addDockRecentItems(entries);
}

function seedDockRecentTracks() {
  const catalogEntries = (state.catalog.recent_tracks || []).map(track => ({
    kind: "track",
    title: track.title || track.name || "Unknown Track",
    data: track,
  }));
  addDockRecentItems([...state.dockRecentItems, ...catalogEntries]);
}

window.openDockRecentItem = function openDockRecentItem(entry) {
  if (!entry || !entry.data) return;
  if (entry.kind === "playlist") {
    const playlist = state.playlists.find(item => item.id === entry.data.id);
    if (playlist) pushPage(() => renderPlaylistPage(playlist));
    return;
  }
  selectMusicItem(entry.data, "stream", [entry.data]);
};

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
  const isArtist = item.type === "artist";
  const name = isArtist
    ? (item.name || item.artist || "")
    : (primaryArtistName(item) || item.artist || item.name || "");
  const artistId = item.artist_id || item.spotify_artist_id || (isArtist ? item.spotify_id : "") || item.musicbrainz_artist_id || "";
  return {
    name,
    artist: name,
    artwork_url: item.artist_artwork_url || (item.type === "artist" ? item.artwork_url : ""),
    artist_id: artistId,
    spotify_artist_id: artistId,
    spotify_id: item.spotify_id || artistId,
    spotify_url: item.spotify_url || (item.external_urls && item.external_urls.spotify) || "",
    external_urls: item.external_urls || {},
  };
}

function albumTarget(item = {}) {
  const album = item.album || item.title || "";
  const artist = item.artist || item.name || "";
  const artistId = item.spotify_artist_id || item.artist_id || "";
  const albumId = item.album_spotify_id || item.spotify_album_id || (item.type === "album" ? item.spotify_id : "") || (item.metadata && (item.metadata.album_spotify_id || item.metadata.spotify_album_id || item.metadata.spotify_id)) || "";
  return {
    type: "album",
    title: album,
    album,
    artist,
    artwork_url: item.album_artwork_url || item.artwork_url || "",
    artist_artwork_url: item.artist_artwork_url || "",
    artist_id: artistId,
    spotify_artist_id: artistId,
    year: item.year || "",
    musicbrainz_release_id: item.musicbrainz_release_id || item.release_id || (item.metadata && (item.metadata.musicbrainz_release_id || item.metadata.release_id)) || "",
    spotify_id: albumId,
    spotify_url: item.spotify_url || (item.external_urls && item.external_urls.spotify) || "",
    external_urls: item.external_urls || {},
  };
}

function spotifyAlbumId(album = {}) {
  const value = album.spotify_id || album.album_spotify_id || album.spotify_album_id || (album.metadata && (album.metadata.album_spotify_id || album.metadata.spotify_album_id || album.metadata.spotify_id)) || "";
  const match = String(value).match(/(?:open\.spotify\.com\/album\/|spotify:album:)([A-Za-z0-9]+)/);
  return match ? match[1] : String(value).trim();
}

function spotifyAlbumUrl(album = {}) {
  const url = album.spotify_url || album.external_url || (album.external_urls && album.external_urls.spotify) || "";
  if (url && /open\.spotify\.com\/album\//.test(url)) return url;
  const id = spotifyAlbumId(albumTarget(album));
  return id ? `https://open.spotify.com/album/${id}` : "";
}

function musicBrainzReleaseId(album = {}) {
  const value = album.musicbrainz_release_id || album.release_id || (album.metadata && (album.metadata.musicbrainz_release_id || album.metadata.release_id)) || "";
  const match = String(value).match(/musicbrainz\.org\/release\/([0-9a-f-]+)/i);
  return match ? match[1] : String(value).trim();
}

function musicBrainzReleaseUrl(album = {}) {
  const id = musicBrainzReleaseId(albumTarget(album));
  return id ? `https://musicbrainz.org/release/${id}` : "";
}

async function fetchAlbumTracks(album = {}) {
  const target = albumTarget(album);
  const params = new URLSearchParams({
    artist: target.artist || "",
    album: target.album || target.title || "",
    release_id: musicBrainzReleaseId(target),
    spotify_id: spotifyAlbumId(target),
  });
  const full = await api(`/api/music/album_tracks?${params.toString()}`);
  return full.tracks || [];
}

function artistLinkHtml(item, text = null, className = "") {
  const target = artistTarget(item || {});
  const label = text || target.artist || target.name || (item && item.artist) || (item && item.name) || "";
  if (!label) return "";
  return `<button class="inline-entity-link artist-link ${className}" type="button" title="${esc(label)}" data-open-artist='${attrJson(target)}'>${esc(label)}</button>`;
}

function albumLinkHtml(item, text = null, className = "") {
  const label = text || (item && item.title) || (item && item.name) || "";
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

function normalizeLibraryPill(pill) {
  const value = String(pill || "").trim().toLowerCase();
  return ["home", "stats", "tracks", "albums", "artists"].includes(value) ? value : "home";
}

function setActiveLibraryPill(pill) {
  state.activeLibraryPill = normalizeLibraryPill(pill);
  document.querySelectorAll(".library-pill").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.libraryPill === state.activeLibraryPill);
  });
}

function renderSidebarLibraryPills() {
  document.querySelectorAll(".library-pill").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.libraryPill === state.activeLibraryPill);
  });
}

function setActiveView(id) {
  if (id !== "settings") stopCacheLogPolling();
  if (window.artistEvtSource) {
    window.artistEvtSource.close();
    window.artistEvtSource = null;
  }
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  document.querySelectorAll(".sidebar-playlist-item").forEach(el => el.classList.remove("active"));
  const view = $(id);
  if (view) view.classList.add("active");
}

function pushPage(renderFn) {
  if (state.viewStack.length > 0) {
    const activeScrollArea = document.querySelector(".active .scroll-area");
    state.viewStack[state.viewStack.length - 1].scroll = activeScrollArea ? activeScrollArea.scrollTop : 0;
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

  if (!$("queuePanel").hidden && typeof refreshQueuePanel === "function") {
    refreshQueuePanel();
  }
}

// ---------------------------------------------------------------------------
// Home & Cards Restoration
// ---------------------------------------------------------------------------

function catalogSignature(catalog) {
  return JSON.stringify(["personal_tracks", "recent_tracks", "top_tracks", "artists", "albums"].map((section) => (
    (catalog[section] || []).map((item) => ({
      id: item.spotify_id || item.id || "",
      title: item.title || item.name || "",
      artist: item.artist || "",
      artwork: item.artwork_url || "",
    }))
  )));
}

function redrawCatalogPage() {
  const current = state.viewStack[state.viewStack.length - 1];
  if (!current) {
    replacePage(renderHomePage);
    return;
  }
  if ([renderHomePage, renderArtistsPage, renderAlbumsPage, renderPersonalTracksPage, renderRecentTracksPage, renderGlobalTracksPage].includes(current.render)) {
    const activeScrollArea = document.querySelector(".active .scroll-area");
    const scrollTop = activeScrollArea ? activeScrollArea.scrollTop : 0;
    current.render();
    const refreshedScrollArea = document.querySelector(".active .scroll-area");
    if (refreshedScrollArea) refreshedScrollArea.scrollTop = scrollTop;
  }
}

function applyCatalog(catalog) {
  const changed = catalogSignature(state.catalog) !== catalogSignature(catalog);
  state.catalog = catalog;
  if (changed || state.viewStack.length === 0) {
    redrawCatalogPage();
  }
}

async function refreshCatalog() {
  try {
    applyCatalog(await api("/api/discover?refresh=1", { timeout: 60000 }));
  } catch (e) {
    console.error("Refresh catalog failed", e);
  }
}

async function loadCatalog() {
  try {
    applyCatalog(await api("/api/discover?refresh=0"));
  } catch (e) {
    console.error("Load cached catalog failed", e);
  }
  refreshCatalog();
  if (state.catalogRefreshTimer) clearInterval(state.catalogRefreshTimer);
  state.catalogRefreshTimer = setInterval(refreshCatalog, CATALOG_REFRESH_MS);
}

async function enrichBatch(items, containerId) {
  const toEnrich = items.filter(t => (!t.artwork_url || t.artwork_url === "") || (t.type === "artist" && !t.monthly_listeners));
  if (toEnrich.length === 0) return;
  
  // High-performance individual streaming with concurrency control (max 5 at once)
  let active = 0;
  let index = 0;

  const next = async () => {
    if (index >= toEnrich.length) return;
    const item = toEnrich[index++];
    active++;
    
    try {
      const res = await api("/api/music/enrich", { method: "POST", body: JSON.stringify({ tracks: [item] }), timeout: 30000 });
      if (res && res.tracks && res.tracks[0]) {
        const enriched = res.tracks[0];
        
        // Update global state catalog
        ["recent_tracks", "personal_tracks", "top_tracks", "artists", "albums"].forEach(key => {
          if (!state.catalog[key]) return;
          const idx = state.catalog[key].findIndex(t => (t.id && t.id === enriched.id) || (t.name === enriched.name && t.artist === enriched.artist));
          if (idx !== -1) {
            state.catalog[key][idx] = { ...state.catalog[key][idx], ...enriched };
            
            // Progressive UI update: find and update the specific card immediately
            const container = $(containerId);
            if (container) {
               // Robust selector using name/title to find the correct card
               const nameAttr = enriched.name ? enriched.name.replace(/"/g, "\\\"") : (enriched.title || "").replace(/"/g, "\\\"");
               const card = container.querySelector(`[data-card-data*='"name":"${nameAttr}"']`) || 
                            container.querySelector(`[data-card-data*='"title":"${nameAttr}"']`);
               if (card) {
                  const artEl = card.querySelector(".card-art");
                  if (artEl && enriched.artwork_url) {
                    artEl.style.backgroundImage = `url('${enriched.artwork_url}')`;
                  }
                  card.dataset.cardData = JSON.stringify(state.catalog[key][idx]);
               }
            }
          }
        });
        
        // Re-sync standard track list rows if applicable
        const listContainer = $(containerId);
        if (listContainer && listContainer.classList.contains("track-list")) {
          renderTrackList(containerId, items);
        }
      }
    } catch (e) {
      console.error("Single item enrichment failed:", e);
    } finally {
      active--;
      next();
    }
  };

  // Launch initial concurrent workers
  for (let i = 0; i < Math.min(5, toEnrich.length); i++) {
    next();
  }
}

function renderHomePage() {
  if (!state.catalog) {
    $("pageContent").innerHTML = '<div class="loading"><div class="spinner"></div><span>Loading library...</span></div>';
    return;
  }
  setActiveLibraryPill("home");
  setActiveView("home");
  
  const personalTracks = (state.catalog.personal_tracks || []).slice(0, 6);
  const recentTracks = uniqueRecentTracks(state.catalog.recent_tracks || []).slice(0, 6);
  const globalTracks = (state.catalog.top_tracks || []).slice(0, 6);
  const topArtists = (state.catalog.artists || []).slice(0, 6);
  const topAlbums = (state.catalog.albums || []).slice(0, 6);

  let html = `
    <div class="library-hero compact-hero">
      <div>
        <span class="eyebrow">Personal Music Discovery</span>
        <h1>Welcome Home</h1>
      </div>
    </div>

    <div class="scroll-area">`;

  if (recentTracks.length) {
    html += `
        <div class="section-head sticky-head">
          <h2>Recently Played</h2>
          <button class="see-more" id="seeMoreRecent">See all <i class="bi bi-chevron-right"></i></button>
        </div>
        <div id="recentTracksGrid" class="grid"></div>
    `;
  }

  if (personalTracks.length) {
    html += `
        <div class="section-head sticky-head">
          <h2>Your Most Listened</h2>
          <button class="see-more" id="seeMorePersonal">See all <i class="bi bi-chevron-right"></i></button>
        </div>
        <div id="personalTracksGrid" class="grid"></div>
    `;
  }

  html += `
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

  $("pageContent").innerHTML = html;

  if (recentTracks.length) {
    renderCards("recentTracksGrid", recentTracks, "track", state.catalog.recent_tracks);
    $("seeMoreRecent").onclick = () => pushPage(renderRecentTracksPage);
  }

  if (personalTracks.length) {
    renderCards("personalTracksGrid", personalTracks, "track", state.catalog.personal_tracks);
    $("seeMorePersonal").onclick = () => pushPage(renderPersonalTracksPage);
  }

  renderCards("topTracksGrid", globalTracks, "track", state.catalog.top_tracks);
  renderCards("topArtistsGrid", topArtists, "artist");
  renderCards("topAlbumsGrid", topAlbums, "album");

  $("seeMoreGlobalTracks").onclick = () => pushPage(renderGlobalTracksPage);
  $("seeMoreArtists").onclick = () => pushPage(renderArtistsPage);
  $("seeMoreAlbums").onclick = () => pushPage(renderAlbumsPage);
  
  syncActiveTrackRows();
}

function renderCards(containerId, items, kind, contextItems = null) {
  const container = $(containerId);
  if (!container) return;
  container.innerHTML = cardsHtml(items, kind, 0);
  bindCardClicks(container, items, contextItems || items);
}

function cardsHtml(items, kind, offset = 0) {
  const current = state.currentTrack;
  return items.map((item, index) => {
    const title = item.title || item.name || item.artist || item.album;
    const year = item.year ? ` (${item.year})` : "";
    const sub = kind === "artist" ? (item.monthly_listeners ? `${formatCount(item.monthly_listeners)} monthly listeners` : "Artist") : `${artistLinkHtml(item)}${year}`;
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

function bindCardClicks(container, items, contextItems) {
  container.querySelectorAll("[data-card]").forEach((button) => {
    const item = items[Number(button.dataset.card)];
    button.onclick = () => {
        if (item.type === "album") pushPage(() => renderAlbumPage(albumTarget(item)));
        else if (item.type === "artist") pushPage(() => renderArtistPage(artistTarget(item)));
        else selectMusicItem(item, "stream", contextItems);
    };
    button.onkeydown = (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        if (item.type === "album") pushPage(() => renderAlbumPage(albumTarget(item)));
        else if (item.type === "artist") pushPage(() => renderArtistPage(artistTarget(item)));
        else selectMusicItem(item, "stream", contextItems);
      }
    };
    button.oncontextmenu = (event) => {
      event.preventDefault();
      if (playableQueueItem(item)) {
        showTrackContextMenu(event, item);
      } else if (item.type === "album") {
        showAlbumContextMenu(event, item);
      }
    };
  });
  bindEntityLinks(container);
}

// ---------------------------------------------------------------------------
// Other Discovery Pages
// ---------------------------------------------------------------------------

function renderArtistsPage() {
  setActiveLibraryPill("artists");
  setActiveView("home");
  $("pageContent").innerHTML = `
    <div class="section-head sticky-head">
      <h1>Top Artists</h1>
      <span>Discovery index</span>
    </div>
    <div class="scroll-area"><div id="fullArtistsGrid" class="grid"></div></div>
  `;
  const artists = state.catalog.artists || [];
  renderCards("fullArtistsGrid", artists, "artist");
}

function renderAlbumsPage() {
  setActiveLibraryPill("albums");
  setActiveView("home");
  $("pageContent").innerHTML = `
    <div class="section-head sticky-head">
      <h1>Top Albums</h1>
      <span>Grouped by artist</span>
    </div>
    <div class="scroll-area"><div id="fullAlbumsGrid" class="grid"></div></div>
  `;
  const albums = state.catalog.albums || [];
  renderCards("fullAlbumsGrid", albums, "album");
}

async function renderRelatedArtistsPage(artist) {
  setActiveView("home");
  const artistName = artist.name || artist.artist;
  const artistId = artist.artist_id || artist.spotify_id || "";
  
  $("pageContent").innerHTML = `
    <div class="section-head sticky-head">
      <h1>Fans also like</h1>
      <span>Artists similar to ${esc(artistName)}</span>
    </div>
    <div class="scroll-area"><div id="fullRelatedArtistsGrid" class="grid round-grid"></div></div>
    <div id="fullRelatedLoading" class="loading"><div class="spinner"></div><span>Fetching more artists…</span></div>
  `;

  try {
    const data = await api("/api/artist/related", {
      method: "POST",
      body: JSON.stringify({ artist_id: artistId, name: artistName, limit: 20 }),
    });
    if ($("fullRelatedLoading")) $("fullRelatedLoading").remove();
    const artists = data.artists || [];
    renderCards("fullRelatedArtistsGrid", artists, "artist");
  } catch (e) {
    if ($("fullRelatedLoading")) $("fullRelatedLoading").innerHTML = "<span>Failed to load related artists.</span>";
  }
}

function renderPersonalTracksPage() {
  setActiveLibraryPill("tracks");
  setActiveView("home");
  const personalTracks = state.catalog.personal_tracks || [];
  const tracks = personalTracks.length ? personalTracks : (state.catalog.top_tracks || []);
  const eyebrow = personalTracks.length ? "Personal" : "Discovery";
  const title = personalTracks.length ? "Top Tracks" : "Global Top Songs";
  $("pageContent").innerHTML = `
    <div class="scroll-area">
      <div class="library-hero compact-hero">
        <div>
          <span class="eyebrow">${eyebrow}</span>
          <h1>${title}</h1>
        </div>
      </div>
      <div class="track-list-header" style="margin-top: 24px">
        <div>#</div>
        <div>Title</div>
        <div></div>
        <div>Album</div>
        <div class="time-column"><i class="bi bi-clock"></i></div>
        <div></div>
      </div>
      <div id="fullPersonalTracks" class="track-list"></div>
    </div>
  `;
  renderTrackList("fullPersonalTracks", tracks);
}

function renderRecentTracksPage() {
  setActiveLibraryPill("home");
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
  const tracks = uniqueRecentTracks(state.catalog.recent_tracks || []);
  renderTrackList("fullRecentTracks", tracks);
}

function renderGlobalTracksPage() {
  setActiveLibraryPill("home");
  setActiveView("home");
  $("pageContent").innerHTML = `
    <div class="scroll-area">
      <div class="library-hero compact-hero">
        <div>
          <span class="eyebrow">Discovery</span>
          <h1>Global Top Songs</h1>
        </div>
      </div>
      <div class="track-list-header" style="margin-top: 24px">
        <div>#</div>
        <div>Title</div>
        <div></div>
        <div>Album</div>
        <div class="time-column"><i class="bi bi-clock"></i></div>
        <div></div>
      </div>
      <div id="fullGlobalTracks" class="track-list"></div>
    </div>
  `;
  const tracks = state.catalog.top_tracks || [];
  renderTrackList("fullGlobalTracks", tracks);
}

const STATS_PERIODS = [
  { key: "today", label: "Today" },
  { key: "week", label: "This Week" },
  { key: "month", label: "This Month" },
  { key: "year", label: "This Year" },
  { key: "all", label: "All Time" },
];

function normalizeStatsPeriod(period) {
  const value = String(period || "").trim().toLowerCase();
  if (value === "custom") return "custom";
  return STATS_PERIODS.some(p => p.key === value) ? value : "month";
}

function statsMsLabel(ms = 0) {
  const totalMinutes = Math.max(0, Math.floor(Number(ms || 0) / 60000));
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours ? `${hours}h ${minutes}m` : `${minutes}m`;
}

function availableStatsYears() {
  const now = new Date().getFullYear();
  const years = new Set([now, now - 1, now - 2, now - 3, now - 4]);
  (state.catalog.recent_tracks || []).forEach(item => {
    const year = Number(item.year || item.release_year || 0);
    if (year >= 1970 && year <= now + 1) years.add(year);
  });
  return [...years].sort((a, b) => b - a);
}

const MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

function _statsMonthsLabel() {
  const sel = state.statsMonths || [];
  if (!sel.length) return "All Months";
  if (sel.length === 1) return MONTH_NAMES[sel[0] - 1];
  if (sel.length === 12) return "All Months";
  return `${sel.length} months`;
}

function renderStatsRangePill(activeYear) {
  const years = availableStatsYears();
  const selected = new Set(state.statsMonths || []);
  return `
    <div class="stats-range-pill" title="Pick a specific year and months">
      <select id="statsYearSelect" class="stats-select">
        <option value="">All Years</option>
        ${years.map(y => `<option value="${y}" ${String(y) === String(activeYear) ? "selected" : ""}>${y}</option>`).join("")}
      </select>
      <div class="stats-month-picker" id="statsMonthPicker">
        <button class="stats-month-btn" id="statsMonthBtn" type="button">${_statsMonthsLabel()}</button>
        <div class="stats-month-dropdown" id="statsMonthDropdown" hidden>
          <button class="stats-month-opt ${!selected.size ? "active" : ""}" data-month="0" type="button">All Months</button>
          ${MONTH_NAMES.map((name, i) => `<button class="stats-month-opt ${selected.has(i+1) ? "active" : ""}" data-month="${i+1}" type="button">${name}</button>`).join("")}
        </div>
      </div>
    </div>
  `;
}

function _bindStatsMonthPicker(onChangeCallback) {
  const btn = $("statsMonthBtn");
  const dropdown = $("statsMonthDropdown");
  if (!btn || !dropdown) return;

  // Portal pattern: move dropdown to body so overflow:hidden ancestors don't clip it
  const _placeDropdown = () => {
    const rect = btn.getBoundingClientRect();
    dropdown.style.top = (rect.bottom + 6) + "px";
    dropdown.style.right = (window.innerWidth - rect.right) + "px";
  };
  const _openDropdown = () => {
    document.body.appendChild(dropdown);
    _placeDropdown();
    dropdown.hidden = false;
    document.querySelector(".scroll-area")?.addEventListener("scroll", _closeDropdown, { passive: true, once: true });
  };
  const _closeDropdown = () => {
    dropdown.hidden = true;
  };

  btn.onclick = (e) => {
    e.stopPropagation();
    if (dropdown.hidden) { _openDropdown(); } else { _closeDropdown(); }
  };

  dropdown.querySelectorAll("[data-month]").forEach(opt => {
    opt.onclick = (e) => {
      e.stopPropagation();
      const m = parseInt(opt.dataset.month, 10);
      if (m === 0) {
        state.statsMonths = [];
      } else {
        const cur = new Set(state.statsMonths || []);
        if (cur.has(m)) { cur.delete(m); } else { cur.add(m); }
        state.statsMonths = [...cur].sort((a, b) => a - b);
      }
      dropdown.querySelectorAll("[data-month]").forEach(o => {
        const om = parseInt(o.dataset.month, 10);
        o.classList.toggle("active", om === 0 ? !(state.statsMonths || []).length : (state.statsMonths || []).includes(om));
      });
      btn.textContent = _statsMonthsLabel();
      if (onChangeCallback) onChangeCallback();
    };
  });

  // Close on outside click (dropdown is now in body, so check btn separately)
  document.addEventListener("click", function closeOnOutside(e) {
    if (!document.body.contains(dropdown)) { document.removeEventListener("click", closeOnOutside); return; }
    if (e.target !== btn && !btn.contains(e.target) && !dropdown.contains(e.target)) {
      _closeDropdown();
    }
  });
}

function renderStatsDateFilters(activeYear) {
  return renderStatsRangePill(activeYear);
}

function getStatsFilterState() {
  return {
    year: state.statsYear || "",
    months: state.statsMonths || [],
    period: state.statsPeriod || "month",
  };
}

function statsQueryParams(extra = {}) {
  const stateFilters = getStatsFilterState();
  const params = new URLSearchParams({
    period: extra.period || stateFilters.period || "month",
  });
  const year = extra.year ?? stateFilters.year;
  const months = extra.months ?? stateFilters.months;
  if (year) params.set("year", year);
  if (months && months.length) params.set("months", months.join(","));
  return params;
}

function renderStatsPeriodPills(activePeriod, activeYear = "") {
  return `
    <div class="stats-period-row">
      ${STATS_PERIODS.map(p => `<button class="library-pill stats-period-pill ${p.key === activePeriod ? "active" : ""}" data-stats-period="${p.key}" type="button">${p.label}</button>`).join("")}
      ${renderStatsRangePill(activeYear)}
    </div>
  `;
}

function statsPeriodLabel(period) {
  const value = String(period || "").trim().toLowerCase();
  if (value === "custom") return "Custom range";
  return STATS_PERIODS.find(p => p.key === value)?.label || "This Month";
}

function statsSummaryCards(summary = {}) {
  const cards = [
    { label: "Total listened", value: statsMsLabel(summary.total_listened_ms || 0) },
    { label: "Tracks played", value: Number(summary.tracks_played || 0).toLocaleString() },
    { label: "Artists heard", value: Number(summary.artists_heard || 0).toLocaleString() },
    { label: "Albums heard", value: Number(summary.albums_heard || 0).toLocaleString() },
  ];
  return cards.map(card => `
    <div class="stats-card">
      <span>${esc(card.label)}</span>
      <strong>${esc(card.value)}</strong>
    </div>
  `).join("");
}

function renderStatsTrackRows(items = []) {
  const rows = items.map((item, idx) => `
    <button class="stats-track-row" type="button" data-item-idx="${idx}" data-item-data='${JSON.stringify(item).replace(/'/g, "&apos;")}'>
      <span class="stats-track-rank">${idx + 1}</span>
      <span class="stats-track-title">
        <span class="track-art" ${item.artwork_url ? `style="background-image: url('${item.artwork_url}')" ` : ""}></span>
        <span class="stats-track-title-text">
          <strong>${esc(item.title || "Unknown")}</strong>
          <span>${esc(item.artist || "")}</span>
        </span>
      </span>
      <span class="stats-track-artist">${esc(item.artist || "")}</span>
      <span class="stats-track-album">${esc(item.album || "")}</span>
      <span class="stats-track-plays">${Number(item.plays || 0).toLocaleString()}</span>
      <span class="stats-track-time">${statsMsLabel(item.listened_ms || 0)}</span>
    </button>
  `).join("");
  return `
    <div class="stats-track-table">
      <div class="stats-track-header">
        <span>#</span>
        <span>Title</span>
        <span>Artist</span>
        <span>Album</span>
        <span>Plays</span>
        <span>Listened time</span>
      </div>
      ${rows}
    </div>
  `;
}

function bindStatsTrackRows(containerId, items = []) {
  const container = $(containerId);
  if (!container) return;
  container.querySelectorAll(".stats-track-row").forEach(el => {
    const item = items[Number(el.dataset.itemIdx)];
    if (!item) return;
    el.onclick = () => selectMusicItem(item, "stream", items);
    if (playableQueueItem(item)) {
      el.oncontextmenu = (event) => {
        event.preventDefault();
        showTrackContextMenu(event, item);
      };
    }
  });
  bindEntityLinks(container);
}

function renderStatsTimeline(items = []) {
  const clean = (items || []).map(item => ({
    label: String(item.label || ""),
    listened_ms: Number(item.listened_ms || 0),
    plays: Number(item.plays || 0),
  })).filter(item => item.label);
  if (!clean.length) {
    return `<div class="stats-empty">No listening activity in this period.</div>`;
  }
  const maxValue = Math.max(...clean.map(item => item.listened_ms || item.plays || 0), 1);
  const BAR_MAX_PX = 140;
  return `
    <div class="stats-chart">
      ${clean.map(item => {
        const value = item.listened_ms || item.plays || 0;
        const barPx = Math.max(6, Math.round((value / maxValue) * BAR_MAX_PX));
        return `
          <div class="stats-chart-bar-wrap" title="${esc(statsMsLabel(item.listened_ms || 0))} — ${esc(item.label)}">
            <div class="stats-chart-bar-area">
              <div class="stats-chart-bar" style="height:${barPx}px"></div>
            </div>
            <span class="stats-chart-value">${statsMsLabel(item.listened_ms || 0)}</span>
            <span class="stats-chart-label">${esc(item.label)}</span>
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function renderStatsGenres(items = []) {
  const clean = (items || []).filter(item => item && (item.genre || item.genre_key));
  if (!clean.length) {
    return `<div class="stats-empty">No genre data in this period.</div>`;
  }
  const maxValue = Math.max(...clean.map(item => Number(item.listened_ms || 0)), 1);
  return `
    <div class="stats-genre-list">
      ${clean.map(item => {
        const width = Math.max(6, Math.round((Number(item.listened_ms || 0) / maxValue) * 100));
        return `
          <div class="stats-genre-row">
            <div class="stats-genre-head">
              <strong>${esc(item.genre || item.genre_key || "Unknown")}</strong>
              <span>${statsMsLabel(item.listened_ms || 0)}</span>
            </div>
            <div class="stats-genre-bar"><div style="width:${width}%"></div></div>
          </div>
        `;
      }).join("")}
    </div>
  `;
}

// Stats cache: keyed by statsQueryParams string → { summary, tracks, artists, albums, timeline, genres, fetchedAt }
if (!state.statsCache) state.statsCache = {};

function _statsPageKey(period) {
  return statsQueryParams({ period }).toString();
}

// Apply a single stats section immediately when its fetch resolves.
// Progressive rendering: each section appears as it arrives, not all at once.
function _applyStatsSummary(summary, activePeriod) {
  if ($("statsSummary")) $("statsSummary").innerHTML = statsSummaryCards(summary || {});
}
function _applyStatsTracks(tracks, activePeriod) {
  const items = (tracks && tracks.items) || [];
  if ($("statsTracks")) { $("statsTracks").innerHTML = renderStatsTrackRows(items); bindStatsTrackRows("statsTracks", items); }
  if ($("statsSeeAllTracks")) $("statsSeeAllTracks").onclick = () => pushPage(() => renderStatsTracksPage(activePeriod));
}
function _applyStatsArtists(artists, activePeriod) {
  const items = (artists && artists.items) || [];
  if ($("statsArtists")) renderCards("statsArtists", items, "artist");
  if ($("statsSeeAllArtists")) $("statsSeeAllArtists").onclick = () => pushPage(() => renderStatsArtistsPage(activePeriod));
}
function _applyStatsAlbums(albums, activePeriod) {
  const items = (albums && albums.items) || [];
  if ($("statsAlbums")) renderCards("statsAlbums", items, "album");
  if ($("statsSeeAllAlbums")) $("statsSeeAllAlbums").onclick = () => pushPage(() => renderStatsAlbumsPage(activePeriod));
}
function _applyStatsTimeline(timeline) {
  const items = (timeline && timeline.items) || [];
  if ($("statsTimeline")) $("statsTimeline").innerHTML = renderStatsTimeline(items);
}
function _applyStatsGenres(genres) {
  const items = (genres && genres.items) || [];
  if ($("statsGenres")) $("statsGenres").innerHTML = renderStatsGenres(items);
}

// Re-apply all sections from cache (used when cache hit or background refresh finishes).
function _applyStatsData(data, activePeriod) {
  _applyStatsSummary(data.summary, activePeriod);
  _applyStatsTracks(data.tracks, activePeriod);
  _applyStatsArtists(data.artists, activePeriod);
  _applyStatsAlbums(data.albums, activePeriod);
  _applyStatsTimeline(data.timeline);
  _applyStatsGenres(data.genres);
}

// Fire all 6 stat fetches independently; each section renders as its fetch resolves.
// Updates state.statsCache[cacheKey] incrementally so cache is always as fresh as possible.
// Returns a Promise that resolves when all 6 are done.
function _fetchStatsDataProgressive(activePeriod, cacheKey) {
  const q = statsQueryParams({ period: activePeriod }).toString();
  const partial = state.statsCache[cacheKey] || { summary: {}, tracks: { items: [] }, artists: { items: [] }, albums: { items: [] }, timeline: { items: [] }, genres: { items: [] }, fetchedAt: 0 };

  const run = (url, key, applyFn) =>
    api(url, { timeout: 30000 }).then(data => {
      partial[key] = data;
      partial.fetchedAt = Date.now();
      state.statsCache[cacheKey] = { ...partial };
      if ($("statsTimeline")) applyFn(data, activePeriod); // only apply if page still active
    }).catch(() => {});

  return Promise.all([
    run(`/api/stats/summary?${q}`, "summary", _applyStatsSummary),
    run(`/api/stats/top-listened-tracks?${q}&limit=6&offset=0`, "tracks", _applyStatsTracks),
    run(`/api/stats/top-listened-artists?${q}&limit=6&offset=0`, "artists", _applyStatsArtists),
    run(`/api/stats/top-listened-albums?${q}&limit=6&offset=0`, "albums", _applyStatsAlbums),
    run(`/api/stats/listening-over-time?${q}`, "timeline", (d) => _applyStatsTimeline(d)),
    run(`/api/stats/top-genres?${q}&limit=6&offset=0`, "genres", (d) => _applyStatsGenres(d)),
  ]);
}

async function renderStatsPage(period = "month") {
  setActiveLibraryPill("stats");
  setActiveView("home");
  const activePeriod = String(period || "").trim().toLowerCase() === "custom" ? "custom" : normalizeStatsPeriod(period);
  state.statsPeriod = activePeriod;

  const isFirstRender = !$("statsTimeline");
  if (isFirstRender) {
    $("pageContent").innerHTML = `
      <div class="scroll-area">
        <div class="library-hero compact-hero">
          <div>
            <span class="eyebrow">Personal Music Discovery</span>
            <h1>Your Listening Stats</h1>
          </div>
        </div>
        ${renderStatsPeriodPills(activePeriod, state.statsYear)}
        <div id="statsSummary" class="stats-summary-grid"></div>
        <div class="section-head sticky-head">
          <h2>Listening over time</h2>
          <span>How your listening changed over the selected period</span>
        </div>
        <div id="statsTimeline" class="stats-timeline"></div>
        <div class="section-head sticky-head">
          <h2>Top listened tracks</h2>
          <button class="see-more" id="statsSeeAllTracks" type="button">See all <i class="bi bi-chevron-right"></i></button>
        </div>
        <div class="stats-table-wrap"><div id="statsTracks" class="track-list stats-track-list"></div></div>
        <div class="section-head sticky-head">
          <h2>Top listened artists</h2>
          <button class="see-more" id="statsSeeAllArtists" type="button">See all <i class="bi bi-chevron-right"></i></button>
        </div>
        <div id="statsArtists" class="grid round-grid stats-artist-grid"></div>
        <div class="section-head sticky-head">
          <h2>Top listened albums</h2>
          <button class="see-more" id="statsSeeAllAlbums" type="button">See all <i class="bi bi-chevron-right"></i></button>
        </div>
        <div id="statsAlbums" class="grid stats-album-grid"></div>
        <div class="section-head sticky-head">
          <h2>Top genres</h2>
          <span>What you listened to most in this period</span>
        </div>
        <div id="statsGenres" class="stats-genre-panel"></div>
      </div>
    `;
  } else {
    // Page already rendered — just update the period pills without full re-render
    const pillRow = document.querySelector(".stats-period-row");
    if (pillRow) pillRow.outerHTML = renderStatsPeriodPills(activePeriod, state.statsYear);
    _bindStatsMonthPicker(() => { state.statsPeriod = "custom"; renderStatsPage("custom"); });
  }

  // Wire period pills
  document.querySelectorAll("[data-stats-period]").forEach(btn => {
    btn.onclick = () => {
      state.statsYear = "";
      state.statsMonths = [];
      state.statsPeriod = btn.dataset.statsPeriod;
      renderStatsPage(btn.dataset.statsPeriod);
    };
  });
  const yearSelect = $("statsYearSelect");
  if (yearSelect) yearSelect.onchange = () => {
    state.statsYear = yearSelect.value;
    if (!yearSelect.value) state.statsMonths = [];
    state.statsPeriod = "custom";
    renderStatsPage("custom");
  };
  _bindStatsMonthPicker(() => {
    if ((state.statsMonths || []).length && !state.statsYear) state.statsYear = String(new Date().getFullYear());
    state.statsPeriod = "custom";
    renderStatsPage("custom");
  });

  const cacheKey = _statsPageKey(activePeriod);
  const cached = state.statsCache[cacheKey];
  const CACHE_TTL_MS = 60 * 1000; // 60 seconds

  if (cached && cached.fetchedAt > 0) {
    // Render immediately from cache so sections appear at once
    _applyStatsData(cached, activePeriod);
    // Refresh in background if stale — updates each section progressively as it arrives
    if (Date.now() - cached.fetchedAt > CACHE_TTL_MS) {
      _fetchStatsDataProgressive(activePeriod, cacheKey);
    }
  } else {
    // First load — fire all 6 fetches independently; each section renders as it resolves
    await _fetchStatsDataProgressive(activePeriod, cacheKey);
  }
}

async function renderStatsTracksPage(period = "month") {
  setActiveLibraryPill("stats");
  setActiveView("home");
  const activePeriod = String(period || "").trim().toLowerCase() === "custom" ? "custom" : normalizeStatsPeriod(period);
  state.statsPeriod = activePeriod;
  $("pageContent").innerHTML = `
    <div class="scroll-area">
      <div class="section-head sticky-head">
        <h1>Top listened tracks</h1>
        <span>Period: ${statsPeriodLabel(activePeriod)}</span>
      </div>
      ${renderStatsPeriodPills(activePeriod, state.statsYear)}
      <div id="statsTracksFull" class="track-list"><div class="stats-loading">Loading…</div></div>
    </div>
  `;
  document.querySelectorAll("[data-stats-period]").forEach(btn => btn.onclick = () => { state.statsYear = ""; state.statsMonths = []; replacePage(() => renderStatsTracksPage(btn.dataset.statsPeriod)); });
  const yearSelect = $("statsYearSelect");
  const reloadStats = () => replacePage(() => renderStatsTracksPage("custom"));
  if (yearSelect) yearSelect.onchange = () => { state.statsYear = yearSelect.value; if (!yearSelect.value) state.statsMonths = []; state.statsPeriod = "custom"; reloadStats(); };
  _bindStatsMonthPicker(() => { if ((state.statsMonths||[]).length && !state.statsYear) state.statsYear = String(new Date().getFullYear()); state.statsPeriod = "custom"; reloadStats(); });
  // Progressive loading: first 10, then remainder in chunks
  const allItems = [];
  const container = $("statsTracksFull");
  const q = () => statsQueryParams({ period: activePeriod }).toString();
  const first = await api(`/api/stats/top-listened-tracks?${q()}&limit=10&offset=0`).catch(() => ({ items: [], total: 0 }));
  allItems.push(...(first.items || []));
  if (container) { container.innerHTML = renderStatsTrackRows(allItems); bindStatsTrackRows("statsTracksFull", allItems); }
  const total = first.total || 0;
  for (let offset = 10; offset < Math.min(total, 200); offset += 20) {
    if (!$("statsTracksFull")) break;
    const chunk = await api(`/api/stats/top-listened-tracks?${q()}&limit=20&offset=${offset}`).catch(() => ({ items: [] }));
    allItems.push(...(chunk.items || []));
    if ($("statsTracksFull")) { $("statsTracksFull").innerHTML = renderStatsTrackRows(allItems); bindStatsTrackRows("statsTracksFull", allItems); }
    if (!(chunk.items || []).length) break;
  }
}

async function renderStatsArtistsPage(period = "month") {
  setActiveLibraryPill("stats");
  setActiveView("home");
  const activePeriod = String(period || "").trim().toLowerCase() === "custom" ? "custom" : normalizeStatsPeriod(period);
  state.statsPeriod = activePeriod;
  $("pageContent").innerHTML = `
    <div class="scroll-area">
      <div class="section-head sticky-head">
        <h1>Top listened artists</h1>
        <span>Period: ${statsPeriodLabel(activePeriod)}</span>
      </div>
      ${renderStatsPeriodPills(activePeriod, state.statsYear)}
      <div id="statsArtistsFull" class="grid round-grid"><div class="stats-loading">Loading…</div></div>
    </div>
  `;
  document.querySelectorAll("[data-stats-period]").forEach(btn => btn.onclick = () => { state.statsYear = ""; state.statsMonths = []; replacePage(() => renderStatsArtistsPage(btn.dataset.statsPeriod)); });
  const yearSelect = $("statsYearSelect");
  const reloadStats = () => replacePage(() => renderStatsArtistsPage("custom"));
  if (yearSelect) yearSelect.onchange = () => { state.statsYear = yearSelect.value; if (!yearSelect.value) state.statsMonths = []; state.statsPeriod = "custom"; reloadStats(); };
  _bindStatsMonthPicker(() => { if ((state.statsMonths||[]).length && !state.statsYear) state.statsYear = String(new Date().getFullYear()); state.statsPeriod = "custom"; reloadStats(); });
  // Progressive loading
  const allItems = [];
  const q = () => statsQueryParams({ period: activePeriod }).toString();
  const first = await api(`/api/stats/top-listened-artists?${q()}&limit=10&offset=0`).catch(() => ({ items: [], total: 0 }));
  allItems.push(...(first.items || []));
  if ($("statsArtistsFull")) { renderCards("statsArtistsFull", allItems, "artist"); bindEntityLinks($("pageContent")); }
  const total = first.total || 0;
  for (let offset = 10; offset < Math.min(total, 200); offset += 20) {
    if (!$("statsArtistsFull")) break;
    const chunk = await api(`/api/stats/top-listened-artists?${q()}&limit=20&offset=${offset}`).catch(() => ({ items: [] }));
    allItems.push(...(chunk.items || []));
    if ($("statsArtistsFull")) { renderCards("statsArtistsFull", allItems, "artist"); bindEntityLinks($("pageContent")); }
    if (!(chunk.items || []).length) break;
  }
}

async function renderStatsAlbumsPage(period = "month") {
  setActiveLibraryPill("stats");
  setActiveView("home");
  const activePeriod = String(period || "").trim().toLowerCase() === "custom" ? "custom" : normalizeStatsPeriod(period);
  state.statsPeriod = activePeriod;
  $("pageContent").innerHTML = `
    <div class="scroll-area">
      <div class="section-head sticky-head">
        <h1>Top listened albums</h1>
        <span>Period: ${statsPeriodLabel(activePeriod)}</span>
      </div>
      ${renderStatsPeriodPills(activePeriod, state.statsYear)}
      <div id="statsAlbumsFull" class="grid"><div class="stats-loading">Loading…</div></div>
    </div>
  `;
  document.querySelectorAll("[data-stats-period]").forEach(btn => btn.onclick = () => { state.statsYear = ""; state.statsMonths = []; replacePage(() => renderStatsAlbumsPage(btn.dataset.statsPeriod)); });
  const yearSelect = $("statsYearSelect");
  const reloadStats = () => replacePage(() => renderStatsAlbumsPage("custom"));
  if (yearSelect) yearSelect.onchange = () => { state.statsYear = yearSelect.value; if (!yearSelect.value) state.statsMonths = []; state.statsPeriod = "custom"; reloadStats(); };
  _bindStatsMonthPicker(() => { if ((state.statsMonths||[]).length && !state.statsYear) state.statsYear = String(new Date().getFullYear()); state.statsPeriod = "custom"; reloadStats(); });
  // Progressive loading
  const allItems = [];
  const q = () => statsQueryParams({ period: activePeriod }).toString();
  const first = await api(`/api/stats/top-listened-albums?${q()}&limit=10&offset=0`).catch(() => ({ items: [], total: 0 }));
  allItems.push(...(first.items || []));
  if ($("statsAlbumsFull")) { renderCards("statsAlbumsFull", allItems, "album"); bindEntityLinks($("pageContent")); }
  const total = first.total || 0;
  for (let offset = 10; offset < Math.min(total, 200); offset += 20) {
    if (!$("statsAlbumsFull")) break;
    const chunk = await api(`/api/stats/top-listened-albums?${q()}&limit=20&offset=${offset}`).catch(() => ({ items: [] }));
    allItems.push(...(chunk.items || []));
    if ($("statsAlbumsFull")) { renderCards("statsAlbumsFull", allItems, "album"); bindEntityLinks($("pageContent")); }
    if (!(chunk.items || []).length) break;
  }
}

function renderTrackList(containerId, items, context = "general", playbackContext = null, queueItems = null) {
  const container = $(containerId);
  if (!container) return;
  const current = state.currentTrack;
  const playbackQueueItems = Array.isArray(queueItems) && queueItems.length ? queueItems : items;

  function makeLibraryBtn(idx, status) {
    const isDownloaded = !!(status && status.in_library);
    const isBusy = !!(status && status.library_requested);
    const label = isDownloaded ? "Remove from library" : (isBusy ? "Cancel library download" : "Add to library");
    let iconHtml;
    if (!status) {
      iconHtml = `<i class="bi bi-arrow-down-circle"></i>`;
    } else if (isBusy) {
      iconHtml = progressButtonMarkup(status);
    } else {
      iconHtml = `<i class="bi ${isDownloaded ? "bi-arrow-down-circle-fill downloaded" : "bi-arrow-down-circle"}"></i>`;
    }
    return `<button class="track-library-btn${isDownloaded ? " downloaded" : ""}${isBusy ? " progress" : ""}" type="button" aria-label="${label}" title="${label}" data-library-action="${idx}" data-active-job-id="${(status && status.active_job_id) || ""}">${iconHtml}</button>`;
  }

  // Phase 1: render immediately with placeholder download icons (no network wait).
  container.innerHTML = items.map((item, idx) => {
    const art = item.artwork_url || "";
    const isTrack = isTrackItem(item);
    const isActive = isTrack && current &&
                     ((item.spotify_id && item.spotify_id === current.spotify_id) ||
                      (item.title === current.title && item.artist === current.artist));
    const typeLabel = { track: "Song", artist: "Artist", album: "Album" }[item.type] || (item.type || "Song");
    const col6 = isTrack ? makeLibraryBtn(idx, null) : "";
    const playsValue = trackPlaysValue(item);

    let col2 = `<strong>${isTrack ? albumLinkHtml(item, item.title || item.name || item.artist) : esc(item.title || item.name || item.artist)}</strong>`;
    let col3 = "", col4 = "";
    
    // Ensure duration is always formatted if missing but duration_ms is present
    let col5 = item.duration || "";
    if (!col5 && item.duration_ms) {
      const totalSeconds = Math.floor(item.duration_ms / 1000);
      const min = Math.floor(totalSeconds / 60);
      const sec = totalSeconds % 60;
      col5 = `${min}:${sec.toString().padStart(2, "0")}`;
    }

    if (context === "search") {
      col2 += `<span>${artistLinkHtml(item)}</span>`;
      col3 = `<span class="pill">${esc(typeLabel)}</span>`;
      col4 = isTrack ? albumLinkHtml(item, item.album || "", "album-link") : "";
    } else if (context === "artist") {
      col3 = playsValue ? `<span class="views-count">${playsValue.toLocaleString()}</span>` : "";
      col4 = albumLinkHtml(item, item.album || "", "album-link");
    } else if (context === "album") {
      col2 += `<span>${artistLinkHtml(item)}</span>`;
      col3 = `<span class="views-count unavailable">${playsValue ? playsValue.toLocaleString() : "-"}</span>`;
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

  function bindLibraryButtons() {
    container.querySelectorAll("[data-library-action]").forEach(button => {
      button.onclick = (event) => {
        event.preventDefault();
        event.stopPropagation();
        toggleTrackLibrary(items[Number(button.dataset.libraryAction)], button, () => renderTrackList(containerId, items, context, playbackContext, playbackQueueItems));
      };
    });
  }

  syncActiveTrackRows();
  container.querySelectorAll(".track-row").forEach(el => {
    const item = items[Number(el.dataset.itemIdx)];
    el.onclick = (event) => {
      if (event.target.closest("[data-library-action]")) return;
      selectMusicItem(item, "stream", playbackQueueItems, playbackContext);
    };
    if (playableQueueItem(item)) {
      el.oncontextmenu = (event) => {
        event.preventDefault();
        if (typeof showTrackContextMenu === "function") {
          showTrackContextMenu(event, item, playbackContext || {});
        }
      };
    }
  });
  bindLibraryButtons();
  bindEntityLinks(container);

  // Phase 2: single batch request → update download icons in-place.
  const trackIdxs = items.reduce((acc, item, idx) => {
    if (isTrackItem(item)) acc.push(idx);
    return acc;
  }, []);
  if (!trackIdxs.length) return;

  api("/api/library/status/batch", {
    method: "POST",
    body: JSON.stringify({ tracks: trackIdxs.map(idx => serviceDownloadPayload(items[idx], "download")) }),
  }).then(statuses => {
    if (!container.isConnected) return;
    trackIdxs.forEach((itemIdx, i) => {
      const btn = container.querySelector(`[data-library-action="${itemIdx}"]`);
      if (!btn) return;
      const status = statuses[i] || {};
      const temp = document.createElement("div");
      temp.innerHTML = makeLibraryBtn(itemIdx, status);
      const newBtn = temp.firstElementChild;
      btn.replaceWith(newBtn);
      // Re-attach a progress poller for downloads still in flight. The backend
      // job keeps running across tab switches; without this the re-rendered
      // button freezes on a static pie and never finalizes to "downloaded".
      if (status.library_requested && !status.in_library) {
        newBtn.dataset.activeJobId = status.active_job_id || "";
        waitForLibraryToggle(items[itemIdx], status.active_job_id || "", newBtn).catch(() => {});
      }
    });
    bindLibraryButtons();
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
        <div class="section-head sticky-head">
          <h2>Popular Tracks</h2>
          <button class="see-more hidden" id="artistTracksToggle" type="button"></button>
        </div>
        <div id="artistTopTracks" class="track-list"></div>
      </div>

      <div id="artistAlbumsSection" class="hidden">
        <div class="section-head sticky-head">
          <h2>Albums</h2>
          <button class="see-more hidden" id="artistAlbumsToggle" type="button"></button>
        </div>
        <div id="artistAlbumsGrid" class="grid"></div>
      </div>

      <div id="artistTourSection" class="hidden">
        <div class="section-head sticky-head">
          <h2>On Tour</h2>
          <button class="tour-link hidden" id="artistTourShowAll" type="button"></button>
        </div>
        <div id="artistTourGrid" class="grid tour-tile-grid"></div>
      </div>

      <div id="artistAboutSection" class="hidden"></div>

      <div id="artistRelatedSection" class="hidden">
        <div class="section-head sticky-head">
          <h2>Fans also like</h2>
          <button class="see-more" id="artistRelatedToggle" type="button">Show all</button>
        </div>
        <div id="artistRelatedGrid" class="grid round-grid"></div>
      </div>
      
      <div id="artistLoading" class="loading"><div class="spinner"></div><span>Loading discovery data…</span></div>
    </div>
  `;

  if (window.artistEvtSource) {
    window.artistEvtSource.close();
  }

  const artistName = artist.name || artist.artist;
  const artistId = artist.artist_id || artist.spotify_id || "";
  let artistTracks = [];
  let artistAlbums = [];
  let artistRelated = [];
  let artistArtwork = artist.artwork_url || "";
  let resolvedArtistId = artistId;
  let tracksExpanded = false;
  let albumsExpanded = false;

  function artistPlaybackContext() {
    return {
      kind: "artist",
      title: artistName || "Artist",
      name: artistName || "Artist",
      id: resolvedArtistId || artistName || "",
    };
  }

  function updateSectionToggle(buttonId, expanded, hasMore, onClick) {
    const button = $(buttonId);
    if (!button) return;
    button.classList.toggle("hidden", !hasMore);
    if (!hasMore) return;
    button.innerHTML = expanded ? 'See less <i class="bi bi-chevron-up"></i>' : 'See all <i class="bi bi-chevron-right"></i>';
    button.onclick = onClick;
  }

  function redrawArtistTracks() {
    renderTrackList(
      "artistTopTracks",
      tracksExpanded ? artistTracks : artistTracks.slice(0, ARTIST_TRACK_PREVIEW_COUNT),
      "artist",
      artistPlaybackContext(),
      artistTracks
    );
    updateSectionToggle("artistTracksToggle", tracksExpanded, artistTracks.length > ARTIST_TRACK_PREVIEW_COUNT, () => {
      tracksExpanded = !tracksExpanded;
      redrawArtistTracks();
    });
  }

  function redrawArtistAlbums() {
    const shownAlbums = albumsExpanded ? artistAlbums : artistAlbums.slice(0, ARTIST_ALBUM_PREVIEW_COUNT);
    renderCards("artistAlbumsGrid", shownAlbums.map(al => ({
      ...al,
      type: "album",
      artist_artwork_url: artistArtwork,
      spotify_artist_id: resolvedArtistId,
    })), "album");
    updateSectionToggle("artistAlbumsToggle", albumsExpanded, artistAlbums.length > ARTIST_ALBUM_PREVIEW_COUNT, () => {
      albumsExpanded = !albumsExpanded;
      redrawArtistAlbums();
    });
  }

  function redrawArtistRelated() {
    const shownRelated = artistRelated.slice(0, ARTIST_RELATED_PREVIEW_COUNT);
    renderCards("artistRelatedGrid", shownRelated.map(a => ({
      ...a,
      type: "artist",
    })), "artist");
    
    const toggle = $("artistRelatedToggle");
    if (toggle) {
      toggle.classList.toggle("hidden", artistRelated.length === 0);
      toggle.onclick = () => pushPage(() => renderRelatedArtistsPage({
        name: artistName,
        artist: artistName,
        artist_id: resolvedArtistId,
        spotify_id: resolvedArtistId
      }));
    }
  }

  function redrawArtistTour(events = [], source = "") {
    const section = $("artistTourSection");
    const grid = $("artistTourGrid");
    if (!section || !grid) return;
    if (!events.length) {
      section.classList.add("hidden");
      return;
    }
    section.classList.remove("hidden");
    // Show top 6 events in the main artist page
    grid.innerHTML = events.slice(0, 6).map(ev => tourEventHtml(ev)).join("");
    section.querySelector(".tour-source-footer")?.remove();
    if (source) {
      grid.insertAdjacentHTML("afterend", `<div class="tour-source-footer">Sourced live via ${esc(source)}</div>`);
    }
    bindExternalUrlButtons(grid);
    
    const toggle = $("artistTourShowAll");
    if (toggle) {
      toggle.textContent = `View all upcoming concerts (${events.length})`;
      toggle.classList.remove("hidden");
      toggle.onclick = () => openTourPage({ name: artistName, artist_id: resolvedArtistId, image: artistArtwork });
    }
  }

  async function loadArtistTour() {
    try {
      const tour = await api("/api/artist/tour", {
        method: "POST",
        body: JSON.stringify({ artist_id: resolvedArtistId, name: artistName, live: false }),
      });
      if (tour.events?.length) {
        redrawArtistTour(tour.events, tour.source);
      }
      if (tour.pending || tour.refresh_needed || tour.stale) {
        api("/api/artist/tour", {
          method: "POST",
          body: JSON.stringify({ artist_id: resolvedArtistId, name: artistName, live: true }),
        }).then(liveTour => {
          if (liveTour.events?.length) redrawArtistTour(liveTour.events, liveTour.source);
        }).catch(() => {});
      }
    } catch (e) {}
  }

  async function loadArtistAbout() {
    if (!resolvedArtistId) return;
    try {
      const about = await api("/api/artist/about", {
        method: "POST",
        timeout: 60000,
        body: JSON.stringify({ artist_id: resolvedArtistId, name: artistName })
      });
      if (!about || !about.monthly_listeners) return;

      const aboutSection = $("artistAboutSection");
      aboutSection.classList.remove("hidden");
      
      const format = (n) => new Intl.NumberFormat().format(n);
      const firstGalleryImg = about.gallery && about.gallery[0] ? about.gallery[0].url : artistArtwork;

      const bioHtml = formatBiographyHtml(about.biography || "No biography available.", {
        name: artistName,
        artist: artistName,
        artist_id: resolvedArtistId,
      });

      aboutSection.innerHTML = `
        <h2 style="margin: 48px 0 24px">About</h2>
        <div class="artist-about-preview" id="artistAboutTrigger">
          <img src="${firstGalleryImg}" class="artist-about-img">
          ${about.global_chart_position ? `
            <div class="rank-badge">
              <span class="rank-label">World</span>
              <span class="rank-num">#${about.global_chart_position}</span>
            </div>
          ` : ""}
          <div class="artist-about-overlay">
          <div class="about-listeners">${format(about.monthly_listeners)} monthly listeners</div>
          <div class="about-bio-preview">${about.biography ? about.biography.replace(/<[^>]*>/g, "") : ""}</div>
          </div>
          </div>

          <dialog class="about-modal" id="artistAboutModal">
          <button class="about-close" id="artistAboutClose"><i class="bi bi-x-lg"></i></button>
          <div class="about-modal-content">
          ${about.gallery && about.gallery.length > 0 ? `
            <div class="about-gallery">
              ${about.gallery.map(img => `<img src="${img.url}" loading="lazy">`).join("")}
            </div>
          ` : ""}

          <div class="about-modal-grid">
            <div>
              <div class="about-stat-row">
                <div class="about-stat-item">
                  <b>${format(about.followers)}</b>
                  <span>Followers</span>
                </div>
                <div class="about-stat-item">
                  <b>${format(about.monthly_listeners)}</b>
                  <span>Monthly Listeners</span>
                </div>
              </div>
              <div class="about-bio-full">${bioHtml}</div>

              <div class="posted-by-row">
                 <div class="mini-art" style="background-image: url('${artistArtwork}')"></div>
                 <span>Posted By <b class="artist-link-inline" data-open-artist='${attrJson(artistTarget({ artist: artistName, name: artistName, artist_id: resolvedArtistId }))}'>${esc(artistName)}</b></span>
              </div>

              <div style="margin-top: 24px; font-size: 12px; color: var(--muted)">Source: ${about.bio_source || "Spotify"}</div>
            </div>
              <div>
                <h3 style="margin-bottom: 24px">Where people listen</h3>
                <ul class="top-cities-list">
                  ${(about.top_cities || []).map(c => `
                    <li>
                      <b>${esc(c.city)}, ${esc(c.country)}</b>
                      <span>${format(c.count)} listeners</span>
                    </li>
                  `).join("")}
                </ul>
              </div>
            </div>
          </div>
        </dialog>
      `;

      const modal = $("artistAboutModal");
      $("artistAboutTrigger").onclick = () => modal.showModal();
      $("artistAboutClose").onclick = () => modal.close();
      modal.onclick = (e) => { if (e.target === modal) modal.close(); };
      modal.addEventListener("keydown", (event) => {
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.stopPropagation();
          event.preventDefault();
          const content = modal.querySelector(".about-modal-content");
          if (content) content.scrollBy({ top: event.key === "ArrowDown" ? 80 : -80, behavior: "smooth" });
        }
      });

      bindArtistInlineLinks(aboutSection, modal);

    } catch (e) {
      console.error("Failed to load artist about:", e);
    }
  }

  const es = new EventSource(`/api/music/artist?artist=${encodeURIComponent(artistName)}&artist_id=${artistId}`);
  window.artistEvtSource = es;

  const timeout = setTimeout(() => {
    if ($("artistLoading")) {
      $("artistLoading").innerHTML = '<span>No discovery data available for this artist.</span>';
      setTimeout(() => { if ($("artistLoading")) $("artistLoading").remove(); }, 3000);
    }
    es.close();
  }, 30000);

  es.onmessage = (e) => {
    clearTimeout(timeout);
    try {
      const part = JSON.parse(e.data);
      if (part.type === "artist_info") {
        resolvedArtistId = part.artist_id || resolvedArtistId;
        artistArtwork = part.artwork_url || artistArtwork;
        $("artistHeroName").textContent = part.artist;
        if (part.artwork_url) {
          $("artistHeroArt").style.backgroundImage = `url('${part.artwork_url}')`;
        }
        // Force attempt to load about info for every artist
        if (resolvedArtistId) {
          loadArtistAbout();
          loadArtistTour();
        } else {
          // If no ID, attempt to fetch it via quick search
          api("/api/music/suggest", { q: artistName }).then(res => {
            const match = (res.results || []).find(r => r.type === "artist" && r.name.toLowerCase() === artistName.toLowerCase());
            if (match && match.id) {
              resolvedArtistId = match.id;
              loadArtistAbout();
              loadArtistTour();
            }
          }).catch(() => {});
        }
      }
      if (part.type === "top_tracks") {
        artistTracks = part.tracks || [];
        $("artistTopTracksSection").classList.remove("hidden");
        redrawArtistTracks();
      }
      if (part.type === "albums") {
        if (part.albums && part.albums.length) {
            artistAlbums = part.albums;
            $("artistAlbumsSection").classList.remove("hidden");
            redrawArtistAlbums();
        }
      }
      if (part.type === "related_artists") {
        if (part.artists && part.artists.length) {
            artistRelated = part.artists;
            $("artistRelatedSection").classList.remove("hidden");
            redrawArtistRelated();
        }
      }
    } catch (err) {}
  };

  es.addEventListener("done", () => { if ($("artistLoading")) $("artistLoading").remove(); es.close(); });
  es.onerror = (err) => { if ($("artistLoading")) $("artistLoading").remove(); es.close(); };
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
    const artistArtwork = data.artist_artwork_url || album.artist_artwork_url || "";
    const year = data.year || album.year || "";
    const albumMeta = [
      year,
      `${data.track_count} tracks`,
      data.total_duration,
    ].filter(Boolean);
    const metadataHtml = albumMeta.map((value) => `<span class="dot">•</span><span>${esc(value)}</span>`).join("");
    const spotifyArtwork = data.artwork_url || album.artwork_url || "";
    const galleryImages = (data.gallery_images || []).length
      ? data.gallery_images
      : (spotifyArtwork ? [{ url: spotifyArtwork, source: "Spotify", label: "Cover" }] : []);
    const hasMultipleImages = galleryImages.length > 1;
    const firstImage = galleryImages[0] || { url: "", source: "Spotify", label: "Cover" };
    
    content.innerHTML = `
      <div class="scroll-area">
        <div class="entity-hero">
          <div class="album-gallery-wrap">
            <div class="entity-art album-gallery${hasMultipleImages ? " has-slides" : ""}" id="albumGallery">
              <button class="gallery-enlarge" id="albumGalleryEnlarge" type="button" aria-label="View ${esc(data.album)} artwork larger">
                <img id="albumGalleryImage" src="${esc(firstImage.url)}" alt="${esc(data.album)} artwork">
              </button>
              ${hasMultipleImages ? `
                <button class="gallery-arrow previous" id="albumGalleryPrevious" type="button" aria-label="Previous album image"><i class="bi bi-chevron-left"></i></button>
                <button class="gallery-arrow next" id="albumGalleryNext" type="button" aria-label="Next album image"><i class="bi bi-chevron-right"></i></button>
                <span class="gallery-position" id="albumGalleryPosition">1 / ${galleryImages.length}</span>
              ` : ""}
            </div>
            ${data.discogs_release_url ? `
              <div class="discogs-attribution ${firstImage.source === "Discogs" ? "" : "hidden"}" id="discogsAttribution">
                <a href="${esc(data.discogs_release_url)}" target="_blank" rel="noopener">Data provided by Discogs</a>
                <span>This application uses Discogs' API but is not affiliated with, sponsored or endorsed by Discogs.</span>
              </div>
            ` : ""}
          </div>
          <div>
            <span class="eyebrow">Album</span>
            <h1>${esc(data.album)}</h1>
            <div class="hero-meta-row">
              <button class="hero-artist-link" id="heroArtistLink" title="${esc(data.artist)}">
                ${artistArtwork ? `<div class="mini-art" style="background-image: url('${artistArtwork}')"></div>` : ""}
                ${esc(data.artist)}
              </button>
              ${metadataHtml}
            </div>
          </div>
        </div>

        <div class="track-list-header" style="margin-top: 24px">
          <div>#</div>
          <div>Title</div>
          <div class="plays-column">Plays</div>
          <div></div>
          <div class="time-column"><i class="bi bi-clock"></i></div>
          <div></div>
        </div>

        <div id="albumTrackList" class="track-list"></div>
        <dialog class="album-image-modal" id="albumImageModal" aria-label="${esc(data.album)} artwork preview">
          <button class="album-image-modal-close" id="albumImageModalClose" type="button" aria-label="Close enlarged artwork"><i class="bi bi-x-lg"></i></button>
          <button class="album-image-modal-zoom" id="albumImageModalZoom" type="button" aria-label="Toggle zoom view"><i class="bi bi-zoom-in"></i></button>
          ${hasMultipleImages ? `
            <button class="album-image-modal-arrow previous" id="albumImageModalPrevious" type="button" aria-label="Previous enlarged album image"><i class="bi bi-chevron-left"></i></button>
            <button class="album-image-modal-arrow next" id="albumImageModalNext" type="button" aria-label="Next enlarged album image"><i class="bi bi-chevron-right"></i></button>
          ` : ""}
          <img id="albumImageModalImage" src="${esc(firstImage.url)}" alt="${esc(data.album)} artwork enlarged">
        </dialog>
      </div>
    `;
    
    $("heroArtistLink").onclick = () => openArtistLink({
      name: data.artist,
      artwork_url: artistArtwork,
      artist_id: album.spotify_artist_id || "",
    });
    const albumImageModal = $("albumImageModal");
    const albumImageModalImage = $("albumImageModalImage");
    const galleryImage = $("albumGalleryImage");
    const galleryPosition = $("albumGalleryPosition");
    const discogsAttribution = $("discogsAttribution");
    let galleryIndex = 0;
    let modalZoom = { scale: 1, x: 0, y: 0, isPanning: false, startX: 0, startY: 0 };
    
    const updateModalTransform = () => {
      albumImageModalImage.style.transform = `translate(${modalZoom.x}px, ${modalZoom.y}px) scale(${modalZoom.scale})`;
      const zoomBtn = $("albumImageModalZoom");
      if (zoomBtn) {
        const icon = zoomBtn.querySelector("i");
        if (icon) {
          icon.className = modalZoom.scale > 1.1 ? "bi bi-zoom-out" : "bi bi-zoom-in";
        }
      }
    };

    const resetModalZoom = () => {
      modalZoom = { scale: 1, x: 0, y: 0, isPanning: false, startX: 0, startY: 0 };
      updateModalTransform();
    };

    const showGalleryImage = (nextIndex) => {
      galleryIndex = (nextIndex + galleryImages.length) % galleryImages.length;
      const image = galleryImages[galleryIndex];
      galleryImage.src = image.url;
      galleryImage.alt = `${data.album} ${image.label || "artwork"}`;
      albumImageModalImage.src = image.full_url || image.url;
      albumImageModalImage.alt = `${galleryImage.alt} enlarged`;
      resetModalZoom();
      if (galleryPosition) {
        galleryPosition.textContent = `${galleryIndex + 1} / ${galleryImages.length}`;
      }
      if (discogsAttribution) {
        discogsAttribution.classList.toggle("hidden", image.source !== "Discogs");
      }
    };

    albumImageModal.onwheel = (event) => {
      event.preventDefault();
      const delta = -event.deltaY;
      const factor = delta > 0 ? 1.1 : 0.9;
      const nextScale = Math.min(Math.max(modalZoom.scale * factor, 1), 10);
      
      // If we are at scale 1, reset position
      if (nextScale === 1) {
        modalZoom.x = 0;
        modalZoom.y = 0;
      }
      
      modalZoom.scale = nextScale;
      updateModalTransform();
    };

    albumImageModal.onmousedown = (event) => {
      if (modalZoom.scale > 1) {
        modalZoom.isPanning = true;
        modalZoom.startX = event.clientX - modalZoom.x;
        modalZoom.startY = event.clientY - modalZoom.y;
      }
    };

    window.addEventListener("mousemove", (event) => {
      if (modalZoom.isPanning) {
        modalZoom.x = event.clientX - modalZoom.startX;
        modalZoom.y = event.clientY - modalZoom.startY;
        updateModalTransform();
      }
    });

    window.addEventListener("mouseup", () => {
      modalZoom.isPanning = false;
    });

    $("albumGalleryEnlarge").onclick = () => {
      showGalleryImage(galleryIndex);
      albumImageModal.showModal();
    };
    $("albumImageModalZoom").onclick = () => {
      if (modalZoom.scale > 1.1) {
        resetModalZoom();
      } else {
        modalZoom.scale = 2.5;
        modalZoom.x = 0;
        modalZoom.y = 0;
        updateModalTransform();
      }
    };
    $("albumImageModalClose").onclick = () => albumImageModal.close();
    albumImageModal.onclick = (event) => {
      // Only close on backdrop click if we are NOT zoomed in
      if (event.target === albumImageModal && modalZoom.scale <= 1.1) {
        albumImageModal.close();
      }
    };
    albumImageModal.addEventListener("keydown", (event) => {
      if (event.key === "ArrowLeft") { event.stopPropagation(); event.preventDefault(); showGalleryImage(galleryIndex - 1); }
      else if (event.key === "ArrowRight") { event.stopPropagation(); event.preventDefault(); showGalleryImage(galleryIndex + 1); }
    });
    if (hasMultipleImages) {
      $("albumGalleryPrevious").onclick = (event) => {
        event.stopPropagation();
        showGalleryImage(galleryIndex - 1);
      };
      $("albumGalleryNext").onclick = (event) => {
        event.stopPropagation();
        showGalleryImage(galleryIndex + 1);
      };
      $("albumImageModalPrevious").onclick = () => showGalleryImage(galleryIndex - 1);
      $("albumImageModalNext").onclick = () => showGalleryImage(galleryIndex + 1);
    }
    renderTrackList("albumTrackList", data.tracks || [], "album");
  } catch (e) {
    content.innerHTML = `<div class="error-state">Failed to load album: ${e.message}</div>`;
  }
}

// ---------------------------------------------------------------------------
// Selection & Playback (SpotiFLAC Only)
// ---------------------------------------------------------------------------
async function selectMusicItem(item, mode = "stream", contextList = null, playbackContext = null) {
  if (!item) return;
  const incomingKey = trackKey(item);
  if (state.listeningSession && state.listeningSession.track_key && state.listeningSession.track_key !== incomingKey) {
    finalizeListeningSession("skip", "track_replaced").catch(() => {});
  }
  if (item.type === "artist") {
    pushPage(() => renderArtistPage(item));
    return;
  }
  if (item.type === "album") {
    pushPage(() => renderAlbumPage(item));
    return;
  }

  // Cancel the active stream job immediately.
  if (state.activeJobId) {
    api("/api/service/cancel", { method: "DELETE", body: JSON.stringify({ job_id: state.activeJobId }) }).catch(() => {});
    state.activeJobId = null;
  }
  adoptPrefetchJobForTrack(item);

  
  const requestId = ++state.playbackRequestId;
  state.manualPauseRequested = false;
  state.activeJobId = null;
  state.currentTrack = item;
  state.currentLibraryPath = ""; // Clear path for new selection
  startListeningSession(item, playbackContext);
  recordDockRecentSelection(item, playbackContext);
  
  prepareSelectedTrackUi(item, "Loading...");
  syncActiveTrackRows();

  // Optimistically update recent tracks
  if (state.catalog && state.catalog.recent_tracks) {
    const incomingKey = recentTrackKey(item);
    state.catalog.recent_tracks = [
      { ...item, source: "Recently Played" },
      ...state.catalog.recent_tracks.filter(t => recentTrackKey(t) !== incomingKey)
    ].slice(0, 100);
  }

  if (contextList && contextList.length) {
    const playable = [...contextList].filter(playableQueueItem);
    const seen = new Set();
    state.originalQueue = [];
    for (const t of playable) {
      const k = trackKey(t);
      if (!seen.has(k)) {
        seen.add(k);
        state.originalQueue.push(t);
      }
    }
    state.queueContext = playbackContext;
    if (state.isShuffle) {
        state.queue = [...state.originalQueue].sort(() => Math.random() - 0.5);
    } else {
        state.queue = [...state.originalQueue];
    }
    state.queueIndex = state.queue.findIndex(t => trackKey(t) === trackKey(item));
    // The sidebar is rendered above (prepareSelectedTrackUi) BEFORE this queue is
    // built, so its "Next in queue" slot was computed against the old/empty queue.
    // Refresh just that slot now that the queue exists, otherwise the card only
    // appears once the user transitions to the next track.
    updateSidebarNextQueue();
  }
  cancelPrefetchJobs("outside current queue window", currentPrefetchWindowKeys(), currentQueueOrderKey());

  if (!$("queuePanel").hidden) {
    refreshQueuePanel();
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
      if (existing.status === "running" || existing.status === "starting") {
        state.activeJobId = existing.id;
        // This may be a prefetch job we're now adopting as the active track.
        // Promote it so the backend torrent prefetch gate stops throttling it;
        // otherwise it could sit queued behind the prefetch limit and never play.
        api("/api/service/promote", { method: "POST", body: JSON.stringify({ job_id: existing.id }) }).catch(() => {});
        await startServiceDownload(item, mode, requestId, existing.id);
        return;
      }
    }
  } catch (e) {}

  await startServiceDownload(item, mode, requestId);
}

function isActiveJobStreamUrl(url) {
  return !!url && url.includes("/api/library/stream_active_job");
}

function isLibraryStreamUrl(url) {
  if (!url || isActiveJobStreamUrl(url)) return false;
  try {
    return new URL(url, window.location.origin).pathname === "/api/library/stream";
  } catch (e) {
    return url.includes("/api/library/stream?") && !url.includes("/api/library/stream_active_job");
  }
}

function seekAfterMetadata(audio, position) {
  const target = Number(position);
  if (!Number.isFinite(target) || target <= 0) return;

  const apply = () => {
    const duration = Number(audio.duration);
    if (!Number.isFinite(duration) || duration <= 0) return;
    try {
      audio.currentTime = Math.max(0, Math.min(target, Math.max(0, duration - 0.25)));
    } catch (e) {}
    audio.removeEventListener("loadedmetadata", apply);
    audio.removeEventListener("canplay", apply);
  };

  audio.addEventListener("loadedmetadata", apply);
  audio.addEventListener("canplay", apply);
  apply();
}

async function playFromLibraryPath(filePath, track, requestId, jobId, statusText = "Playing from library", startAt = 0) {
  if (requestId !== state.playbackRequestId) return;
  state.currentLibraryPath = filePath;
  state.pendingNativeStartAt = 0;
  const streamUrl = `${API_BASE}/api/library/stream?path=${encodeURIComponent(filePath)}&t=${Date.now()}`;
  state.currentStreamUrl = streamUrl;
  const audio = $("audioPlayer");
  if (isNativeAudioSelected()) {
    audio.pause();
    audio.removeAttribute("src");
    audio.load();
    state.currentPlayableReady = true;
    state.autoplayWanted = false;
    setPlayerStatusIcon("ready");
    setPlayerStatus(statusText, track);
    try {
      await startNativeAudio(filePath, track, requestId, startAt);
      return;
    } catch (error) {
      // The native path (NSSound/CoreAudio on macOS) can't decode some formats,
      // notably the webm/opus that YouTube downloads produce. Rather than hang
      // at 0:00, fall back to browser playback (which handles webm) on the
      // default output and tell the user app-only routing isn't available here.
      console.warn("[NativeAudio] playback failed, falling back to browser:", error);
      await stopNativeAudio();
      setPlayerStatus("App-only output unavailable for this file — playing on default", track);
      // fall through to the browser playback path below
    }
  } else {
    await stopNativeAudio();
  }
  audio.src = streamUrl;
  state.currentPlayableReady = true;
  state.autoplayWanted = true;
  
  setPlayerStatusIcon("ready");
  setPlayerStatus(statusText, track);
  audio.load();
  seekAfterMetadata(audio, startAt);
  syncPlayPauseButton();
  tryStartAudio(audio, track, requestId, jobId);
}

async function resumeBrowserAudioFromStableSource(audio) {
  if (!audio) return;
  state.manualPauseRequested = false;
  const hasMissingSource = !audio.src || audio.src === window.location.href;
  const shouldUseFinishedFile = state.currentLibraryPath && (
    hasMissingSource ||
    isActiveJobStreamUrl(audio.src) ||
    isActiveJobStreamUrl(state.currentStreamUrl)
  );

  if (shouldUseFinishedFile) {
    const resumeAt = Number.isFinite(audio.currentTime) ? audio.currentTime : 0;
    await playFromLibraryPath(
      state.currentLibraryPath,
      state.currentTrack,
      state.playbackRequestId,
      state.activeJobId,
      "Playing from cache",
      resumeAt
    );
    return;
  }

  state.autoplayWanted = true;
  audio.play().catch((error) => {
    console.error("[Player] Play failed:", error);
    if (state.currentTrack && error.name !== "NotAllowedError" && error.name !== "AbortError") {
      console.log("[Player] Attempting to re-resolve track after play failure...");
      selectMusicItem(state.currentTrack, "stream", null, state.queueContext);
    } else if (state.currentTrack) {
      setPlayerStatus(error.message || "Playback failed", state.currentTrack);
    }
  });
}

function pauseBrowserAudio(audio) {
  state.manualPauseRequested = true;
  state.autoplayWanted = false;
  if (audio) audio.pause();
}

function syncPlayerStatusTooltip() {
  const icon = $("playerStatusIcon");
  if (!icon) return;
  const title = state.playerStatus || "";
  icon.title = title;
  icon.setAttribute("aria-label", title);
  if (window.tippy) {
    const ref = icon.querySelector(".player-status-content") || icon;
    if (state.statusHintTippy && state.statusHintRef !== ref) {
      state.statusHintTippy.destroy();
      state.statusHintTippy = null;
    }
    if (!state.statusHintTippy) {
      state.statusHintTippy = tippy(ref, {
        content: title || "No status",
        trigger: "mouseenter focus",
        placement: "top",
        theme: "mindingu-status",
        appendTo: () => document.body,
      });
      state.statusHintRef = ref;
    } else {
      state.statusHintTippy.setContent(title || "No status");
    }
    if (state.progressLogOpen) {
      state.statusHintTippy.disable();
    }
  }
}

function setPlayerStatusIcon(mode, pct) {
  const icon = $("playerStatusIcon");
  icon.className = "player-status " + (mode === "ready" ? "ready" : mode === "error" ? "error" : "downloading");
  if (mode === "ready") {
    icon.innerHTML = '<span class="player-status-content"><i class="bi bi-check-circle-fill"></i></span>';
  } else if (mode === "error") {
    icon.innerHTML = '<span class="player-status-content"><i class="bi bi-exclamation-circle"></i></span>';
  } else {
    const p = Math.max(0, Math.min(100, Math.round(pct || 0)));
    icon.innerHTML = `<span class="player-status-content"><span class="player-pie${p > 0 ? "" : " indeterminate"}" style="--pct:${p}"></span></span>`;
  }
  syncPlayerStatusTooltip();
}

function updatePlayerPie(pct) {
  const playerStatusIcon = $("playerStatusIcon");
  const pie = playerStatusIcon ? playerStatusIcon.querySelector(".player-pie") : null;
  if (!pie) return;
  const p = Math.max(0, Math.min(100, Math.round(pct || 0)));
  pie.style.setProperty("--pct", p);
  if (p > 0) pie.classList.remove("indeterminate");
}

function ensureProgressLogPopover() {
  if (state.progressLogEl) return state.progressLogEl;
  const body = document.createElement("pre");
  body.id = "playerProgressPopover";
  body.className = "progress-tippy-body";
  body.textContent = "Loading...";
  state.progressLogEl = body;

  const icon = $("playerStatusIcon");
  if (window.tippy && icon) {
    state.progressLogTippy = tippy(icon, {
      content: body,
      trigger: "manual",
      interactive: true,
      placement: "top",
      maxWidth: 520,
      theme: "mindingu-progress",
      appendTo: () => document.body,
      onHide() {
        if (state.progressLogOpen) {
          state.progressLogOpen = false;
          if (state.progressLogTimer) {
            clearInterval(state.progressLogTimer);
            state.progressLogTimer = null;
          }
        }
      },
    });
  } else {
    body.classList.add("progress-popover");
    document.body.appendChild(body);
  }
  return body;
}

function positionProgressLogPopover() {
  if (state.progressLogTippy) {
    state.progressLogTippy.popperInstance?.update();
    return;
  }
  const popover = state.progressLogEl;
  const icon = $("playerStatusIcon");
  if (!popover || !icon || !state.progressLogOpen) return;
  const rect = icon.getBoundingClientRect();
  const margin = 12;
  const width = popover.offsetWidth || 420;
  const left = Math.max(margin, Math.min(window.innerWidth - width - margin, rect.left + rect.width / 2 - width / 2));
  const top = Math.max(margin, rect.top - popover.offsetHeight - 14);
  popover.style.left = `${left}px`;
  popover.style.top = `${top}px`;
}

function progressLogText(events) {
  const currentTitle = (state.currentTrack?.title || "").toLowerCase();
  let rows = Array.isArray(events) ? events : [];
  if (currentTitle) {
    const matching = rows.filter(event => String(event.title || "").toLowerCase() === currentTitle);
    if (matching.length) rows = matching;
  }
  // Keep up to 50 lines so scrolling is actually useful
  rows = rows.slice(-50);
  if (!rows.length) return state.playerStatus || "Waiting for progress...";
  return rows.map((event) => {
    const clock = new Date((event.timestamp || 0) * 1000).toLocaleTimeString();
    const track = event.title ? `[${event.title}] ` : "";
    return `[${clock}] ${track}${event.message || ""}`;
  }).join("\n");
}

async function refreshProgressLogPopover() {
  if (!state.progressLogOpen) return;
  const body = ensureProgressLogPopover();
  
  // Check if we are currently scrolled to the bottom (within a 15px tolerance)
  // We do this BEFORE updating the content.
  const isScrolledToBottom = Math.abs((body.scrollHeight - body.scrollTop) - body.clientHeight) <= 15;

  try {
    const data = await api("/api/cache/logs");
    body.textContent = progressLogText(data.events || []);
  } catch (error) {
    body.textContent = state.playerStatus || "Unable to read progress log.";
  }
  
  // If we were at the bottom before the update, stay at the bottom
  if (isScrolledToBottom) {
    body.scrollTop = body.scrollHeight;
  }
  
  positionProgressLogPopover();
}

function hideProgressLogPopover() {
  state.progressLogOpen = false;
  if (state.progressLogTimer) {
    clearInterval(state.progressLogTimer);
    state.progressLogTimer = null;
  }
  state.statusHintTippy?.enable();
  if (state.progressLogTippy) {
    state.progressLogTippy.hide();
  } else if (state.progressLogEl) {
    state.progressLogEl.classList.remove("open");
  }
}

function toggleProgressLogPopover() {
  if (state.progressLogOpen) {
    hideProgressLogPopover();
    return;
  }
  state.progressLogOpen = true;
  const popover = ensureProgressLogPopover();
  state.statusHintTippy?.hide();
  state.statusHintTippy?.disable();
  if (state.progressLogTippy) {
    state.progressLogTippy.show();
  } else {
    popover.classList.add("open");
  }
  
  // Await the first refresh so we can snap to bottom immediately
  refreshProgressLogPopover().then(() => {
    popover.scrollTop = popover.scrollHeight;
  });
  
  state.progressLogTimer = setInterval(refreshProgressLogPopover, 1000);
}

function prepareSelectedTrackUi(track, status = "Opening stream...") {
  const audio = $("audioPlayer");
  audio.pause();
  audio.removeAttribute("src");
  audio.src = "";
  try {
    audio.load();
  } catch (e) {}
  stopNativeAudio().catch(() => {});
  try {
    audio.currentTime = 0;
  } catch (e) {}
  resetSeekUi();
  state.currentLibraryPath = "";
  state.currentPlayableReady = false;
  state.activeJobPhase = "";
  state.autoplayWanted = false;
  setPlayerStatusIcon("downloading", 0);
  setPlayerStatus(status, track);
  syncActiveTrackRows();
}

function setPlayerStatus(msg, track, job = null) {
  state.playerStatus = msg;
  const meta = $("playerMeta");
  if (meta && meta.textContent !== msg) {
    meta.classList.remove("fade-in");
    void meta.offsetWidth;
    meta.textContent = msg;
    meta.classList.add("fade-in");
  }
  syncPlayerStatusTooltip();
  if (track) {
    $("playerTitle").innerHTML = albumLinkHtml(track, track.title || "Unknown");
    $("playerArtist").innerHTML = artistLinkHtml(track);
    updateDetailsPanel(track, job);
    updateMediaSession(track);
    bindEntityLinks($("playerTitle").parentElement);
  }
}

function playerStatusForJob(job, fallback = "Loading...") {
  const engine = String(job?.engine || "").toLowerCase();
  const last = String(job?.last_status || "");
  const hasActiveAudio = !!job?.active_audio_path || Number(job?.active_audio_ready_bytes || 0) > 0;
  const isTorrentSearch = engine === "torrent" && !hasActiveAudio && (
    !last ||
    last === "Starting..." ||
    /searching|probing|top candidates|no matching torrents|first pass|artist inventory|clicked album|track fallback|musicbrainz/i.test(last)
  );
  if (isTorrentSearch) return "Searching...";
  if (/^Streaming:/i.test(last)) return "Buffering...";
  return fallback;
}

function activeJobHasPlayableAudio(job) {
  return Number(job?.active_audio_ready_bytes || 0) > 512 * 1024;
}

function updateDetailsPanel(track, job = null) {
  const url = track.artwork_url || "";
  const containers = [document.querySelector(".player-cover"), $("sideCover")];
  containers.forEach(c => {
    if (c) {
      c.style.backgroundImage = url ? `url('${url}')` : "";
      c.innerHTML = url ? "" : `<i class="bi bi-music-note"></i>`;
    }
  });
  $("sideTitle").innerHTML = albumLinkHtml(track, track.title || "No track selected");
  const qualityLabel = qualityLabelForTrack(track, job);
  const qualityHtml = qualityLabel ? `<span class="quality-pill">${qualityLabel}</span>` : "";

  $("sideMeta").innerHTML = `
    <div style="display: flex; align-items: center; justify-content: space-between; width: 100%; min-width: 0;">
      <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0;">
        ${artistLinkHtml(track) || "Search or choose from library"}
      </span>
      ${qualityHtml}
    </div>
  `;
  bindEntityLinks(document.querySelector(".details-head"));

  // Only rebuild the rich sidebar content (related/artist/credits/tour) when the
  // track actually changes. setPlayerStatus() fires on every status tick while a
  // song loads ("Opening stream..." -> "Searching..." -> "Buffering..."), and
  // wiping sideRichContent each time was resetting the user's scroll to the top.
  const key = trackKey(track);
  if (key !== state.sidebarTrackKey) {
    state.sidebarTrackKey = key;
    const requestId = ++state.sidebarRequestId;
    renderDetailsSidebar(track, job, requestId, qualityLabel);
  }
}

function qualityLabelForTrack(track, job = null) {
  const currentPath = state.currentLibraryPath || job?.active_audio_path || "";
  if (currentPath) {
    const ext = currentPath.split(".").pop().split("?")[0].toUpperCase();
    if (["FLAC", "ALAC", "WAV"].includes(ext)) return "HI-RES";
    if (["MP3", "M4A", "AAC", "WEBM", "OPUS", "OGG"].includes(ext)) return "HQ";
  }
  const metaQual = String(track.quality || job?.quality || state.settings.default_quality || "").toUpperCase();
  if (["LOSSLESS", "FLAC", "HI_RES", "HIRES", "HI_RES_LOSSLESS", "SQ"].some(q => metaQual.includes(q))) return "HI-RES";
  if (["MP3", "HQ", "HIGH", "320", "256", "M4A", "AAC"].some(q => metaQual.includes(q))) return "HQ";
  return "";
}

function formatCount(value) {
  const number = Number(value || 0);
  return number ? new Intl.NumberFormat().format(number) : "0";
}

function stripHtml(value = "") {
  const div = document.createElement("div");
  div.innerHTML = String(value || "");
  return div.textContent || div.innerText || "";
}

function biographyLinkTargets() {
  const artists = new Map();
  const albums = new Map();

  const addArtist = (name, data = {}) => {
    const label = String(name || "").trim();
    if (label.length < 3) return;
    const key = label.toLowerCase();
    if (!artists.has(key)) artists.set(key, { ...data, name: label, artist: label });
  };
  const addAlbum = (title, data = {}) => {
    const label = String(title || "").trim();
    if (label.length < 3) return;
    const key = label.toLowerCase();
    if (!albums.has(key)) albums.set(key, { ...data, title: label, album: label });
  };

  (state.catalog.artists || []).forEach(artist => addArtist(artist.name || artist.artist, artist));
  (state.catalog.albums || []).forEach(album => {
    addAlbum(album.title || album.name || album.album, album);
    addArtist(album.artist, album);
  });
  ["top_tracks", "recent_tracks", "personal_tracks"].forEach(section => {
    (state.catalog[section] || []).forEach(track => {
      addArtist(track.artist, track);
      addAlbum(track.album, track);
    });
  });

  return {
    artists: [...artists.values()].sort((a, b) => String(b.name || "").length - String(a.name || "").length),
    albums: [...albums.values()].sort((a, b) => String(b.title || "").length - String(a.title || "").length),
  };
}

function linkifyPlainBiographyText(text = "", currentArtist = {}) {
  const container = document.createElement("span");
  container.textContent = String(text || "");
  const { artists, albums } = biographyLinkTargets();
  const replacements = [];

  const addReplacement = (label, html) => {
    const clean = String(label || "").trim();
    if (clean.length < 3 || !String(text || "").toLowerCase().includes(clean.toLowerCase())) return;
    replacements.push({ label: clean, html });
  };

  const currentArtistName = String(currentArtist.name || currentArtist.artist || "").trim();
  const currentArtistId = currentArtist.artist_id || currentArtist.id || "";
  if (currentArtistName) {
    addReplacement(currentArtistName, `<span class="artist-link-inline" data-open-artist='${attrJson(artistTarget({ artist: currentArtistName, name: currentArtistName, artist_id: currentArtistId }))}'>${esc(currentArtistName)}</span>`);
  }
  artists.forEach(artist => {
    const name = artist.name || artist.artist;
    addReplacement(name, `<span class="artist-link-inline" data-open-artist='${attrJson(artistTarget(artist))}'>${esc(name)}</span>`);
  });
  const candidateNames = [
    ...(String(text || "").match(/\b[A-Z][A-Za-z]+(?:\s+[‘'"][A-Z][A-Za-z]+[’'"])?\s+[A-Z][A-Za-z]+\b/g) || []),
    ...(String(text || "").match(/\b[A-Z][A-Za-z]+\s+[A-Z][A-Za-z]+\b/g) || []),
  ];
  const ignoredNames = new Set(["New York", "Los Angeles", "São Paulo", "Mexico City", "Monthly Listeners"]);
  candidateNames.forEach(name => {
    const clean = name.replace(/\s+/g, " ").trim();
    if (ignoredNames.has(clean) || /^\d/.test(clean)) return;
    addReplacement(clean, `<span class="artist-link-inline" data-open-artist='${attrJson(artistTarget({ artist: clean, name: clean }))}'>${esc(clean)}</span>`);
  });
  albums.forEach(album => {
    const title = album.title || album.name || album.album;
    addReplacement(title, `<span class="album-link-inline" data-open-album='${attrJson(albumTarget(album))}'>${esc(title)}</span>`);
  });
  const albumMentionPattern = /\b(?:album|record|single)\s+([A-Z][^,.]{2,80}?)(?=\s+(?:changed|became|was|is|won|sold|topped|reached|defined|arrived|followed)|[,.])/gi;
  let albumMention;
  while ((albumMention = albumMentionPattern.exec(String(text || ""))) !== null) {
    const title = albumMention[1].replace(/\s+/g, " ").trim();
    addReplacement(title, `<span class="album-link-inline" data-open-album='${attrJson(albumTarget({ title, album: title, artist: currentArtist.name || currentArtist.artist || "" }))}'>${esc(title)}</span>`);
  }

  const sorted = replacements.sort((a, b) => b.label.length - a.label.length);
  const isBoundary = (value, index) => {
    if (index <= 0 || index >= value.length) return true;
    return !/[A-Za-z0-9_]/.test(value[index]);
  };
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  const textNodes = [];
  while (walker.nextNode()) textNodes.push(walker.currentNode);
  textNodes.forEach(node => {
    const source = node.nodeValue || "";
    const lower = source.toLowerCase();
    let cursor = 0;
    const fragment = document.createDocumentFragment();
    while (cursor < source.length) {
      let match = null;
      for (const replacement of sorted) {
        const needle = replacement.label.toLowerCase();
        const idx = lower.indexOf(needle, cursor);
        if (idx < 0 || !isBoundary(source, idx) || !isBoundary(source, idx + replacement.label.length)) continue;
        if (!match || idx < match.idx || (idx === match.idx && replacement.label.length > match.label.length)) {
          match = { ...replacement, idx };
        }
      }
      if (!match) {
        fragment.append(document.createTextNode(source.slice(cursor)));
        break;
      }
      if (match.idx > cursor) fragment.append(document.createTextNode(source.slice(cursor, match.idx)));
      const span = document.createElement("span");
      span.innerHTML = match.html;
      fragment.append(...Array.from(span.childNodes));
      cursor = match.idx + match.label.length;
    }
    node.replaceWith(fragment);
  });

  return container.innerHTML;
}

function formatBiographyHtml(text = "", currentArtist = {}) {
  const normalized = String(text || "No biography available.")
    .replace(/<a href="spotify:artist:([^"]+)">([^<]+)<\/a>/g, (match, id, name) => {
      return `<span class="artist-link-inline" data-open-artist='${attrJson(artistTarget({ artist: name, name, artist_id: id }))}'>${esc(name)}</span>`;
    });
  const wrapper = document.createElement("div");
  wrapper.innerHTML = normalized;
  const plain = wrapper.textContent || wrapper.innerText || "";
  const hasExplicitLinks = normalized.includes("artist-link-inline");
  const paragraphs = plain
    .split(/\n{2,}/)
    .map(part => part.replace(/\s+/g, " ").trim())
    .filter(Boolean);

  if (!paragraphs.length) return "";
  return paragraphs.map(paragraph => {
    if (hasExplicitLinks && plain.trim() === paragraph) return `<p>${normalized}</p>`;
    return `<p>${linkifyPlainBiographyText(paragraph, currentArtist)}</p>`;
  }).join("");
}

function formatArtistBioLinks(text) {
  return formatBiographyHtml(text);
}

// Sanitize backend-provided biography HTML (e.g. a Wikipedia lead section whose
// inline article links we want to keep). Rebuilds only whitelisted tags with
// only safe attributes and https hrefs, so untrusted markup can't inject script.
function sanitizeBioFragment(html = "") {
  const ALLOWED = new Set(["P", "A", "B", "I", "EM", "STRONG", "BR"]);
  const src = document.createElement("template");
  src.innerHTML = String(html || "");
  const clean = (srcNode, destParent) => {
    srcNode.childNodes.forEach((node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        destParent.appendChild(document.createTextNode(node.nodeValue));
      } else if (node.nodeType === Node.ELEMENT_NODE && ALLOWED.has(node.tagName)) {
        const el = document.createElement(node.tagName.toLowerCase());
        if (node.tagName === "A") {
          const href = node.getAttribute("href") || "";
          if (/^https:\/\//i.test(href)) {
            el.setAttribute("href", href);
            el.setAttribute("target", "_blank");
            el.setAttribute("rel", "noopener noreferrer");
          }
        }
        clean(node, el);
        destParent.appendChild(el);
      } else if (node.nodeType === Node.ELEMENT_NODE) {
        clean(node, destParent); // unwrap disallowed element, keep its content
      }
    });
  };
  const out = document.createElement("div");
  clean(src.content, out);
  return out.innerHTML;
}

function primaryArtistName(track = {}) {
  return String(track.artist || track.metadata?.artist || "").split(/,\s*|\s+&\s+|\s+feat\.?\s+/i)[0].trim();
}

function primaryArtistId(track = {}) {
  return track.spotify_artist_id || track.artist_id || track.metadata?.spotify_artist_id || track.metadata?.artist_id || "";
}

function relatedTracksFor(track, limit = 4) {
  const artist = primaryArtistName(track).toLowerCase();
  if (!artist) return [];
  const pools = [
    ...(state.catalog.personal_tracks || []),
    ...(state.catalog.recent_tracks || []),
    ...(state.catalog.top_tracks || []),
  ];
  const seen = new Set([trackKey(track)]);
  const related = [];
  for (const candidate of pools) {
    if (!playableQueueItem(candidate)) continue;
    if (trackKey(candidate) && seen.has(trackKey(candidate))) continue;
    if (!String(candidate.artist || "").toLowerCase().includes(artist)) continue;
    seen.add(trackKey(candidate));
    related.push(candidate);
    if (related.length >= limit) break;
  }
  return related;
}

function nextQueueTrack() {
  restoreLinearOriginalQueue();
  if (!state.queue.length) return null;
  const idx = getQueueIndex();
  if (idx < 0 || state.queue.length < 2) return null;
  return state.queue[(idx + 1) % state.queue.length];
}

function sidebarTrackRow(track, cls = "") {
  const art = track.artwork_url ? `style="background-image:url('${track.artwork_url}')"` : "";
  return `
    <button class="side-track-row ${cls}" type="button" data-side-track='${attrJson(track)}'>
      <span class="side-track-art" ${art}>${track.artwork_url ? "" : '<i class="bi bi-music-note"></i>'}</span>
      <span class="side-track-copy">
        <strong>${esc(track.title || track.name || "Unknown")}</strong>
        <span>${esc(track.artist || "")}</span>
      </span>
    </button>
  `;
}

// Builds the right-rail "Next in queue" card (or empty string when there is no
// next track). Kept separate so queue mutations can refresh just this card in
// place via updateSidebarNextQueue() without re-running the whole sidebar (which
// would re-trigger the artist/credits/tour network loads).
function nextQueueCardHtml() {
  const next = nextQueueTrack();
  if (!next) return "";
  return `
    <section class="side-card">
      <div class="side-section-head">
        <h3>Next in queue</h3>
        <button class="side-text-btn" id="sideOpenQueue" type="button">Open queue</button>
      </div>
      ${sidebarTrackRow(next, "side-next-track")}
    </section>
  `;
}

// Refresh the sidebar "Next in queue" card to match the current queue order.
// Called (ungated) from every queue-mutation site so the preview stays correct
// even when the queue panel is closed but the sidebar is visible.
function updateSidebarNextQueue() {
  const slot = $("sideNextQueueSlot");
  if (!slot) return;
  slot.innerHTML = nextQueueCardHtml();
  $("sideOpenQueue")?.addEventListener("click", openQueuePanel);
  bindSidebarTrackRows(slot);
}

function renderDetailsSidebar(track, job, requestId, qualityLabel = "") {
  const content = $("sideRichContent");
  if (!content) return;
  const artistName = primaryArtistName(track) || track.artist || "";

  content.innerHTML = `
    <section class="side-card" id="sideRelatedArtistsCard">
      <div class="side-card-loading">Loading related music...</div>
    </section>
    <section class="side-card side-artist-card" id="sideArtistCard">
      <div class="side-card-loading">Loading artist info...</div>
    </section>
    <section class="side-card" id="sideCreditsCard">
      <div class="side-section-head">
        <h3>Credits</h3>
        <button class="side-text-btn" id="sideCreditsShowAll" type="button">Show all</button>
      </div>
      <div class="side-card-loading">Loading credits...</div>
    </section>
    <section class="side-card" id="sideTourCard">
      <div class="side-section-head">
        <h3>On tour</h3>
        <button class="side-text-btn" id="sideTourShowAll" type="button">Show all</button>
      </div>
      <div class="side-card-loading">Loading tour dates...</div>
    </section>
    <div id="sideNextQueueSlot">${nextQueueCardHtml()}</div>
  `;

  bindSidebarTrackRows(content);
  $("sideOpenQueue")?.addEventListener("click", openQueuePanel);
  $("sideTourShowAll")?.addEventListener("click", () => openTourPage({
    name: track.artist || primaryArtistName(track),
    artist_id: primaryArtistId(track),
    image: state.sidebarArtist?.tourImage || state.sidebarArtist?.image || track.artist_artwork_url || track.artwork_url || "",
  }));

  const artistCard = $("sideArtistCard");
  if (artistCard) {
    const artistName = primaryArtistName(track) || track.artist || "Artist";
    const image = state.sidebarArtist?.image || track.artist_artwork_url || track.artwork_url || "";
    artistCard.innerHTML = `
      <button class="side-artist-trigger" id="sideArtistTrigger" type="button">
        <span class="side-artist-image" style="${image ? `background-image:url('${image}')` : ""}">
          <span>About the artist</span>
        </span>
        <span class="side-artist-info">
          <strong>${esc(artistName)}</strong>
          <span>Loading artist info...</span>
        </span>
      </button>
    `;
    $("sideArtistTrigger")?.addEventListener("click", () => {
      if (state.sidebarArtist?.name || state.sidebarArtist?.image) {
        showArtistAboutModal({
          biography: "",
          monthly_listeners: 0,
        }, state.sidebarArtist.name || artistName, state.sidebarArtist.id || "", state.sidebarArtist.image || image);
      }
    });
  }

  loadSidebarArtistInfo(track, requestId, qualityLabel).catch(() => {});
  loadSidebarRelatedArtists(track, requestId).catch(() => {});
  loadSidebarCredits(track, requestId).catch(() => {});
  loadSidebarTour(track, requestId).catch(() => {});
}

// Wire a sidebar carousel's prev/next arrows and toggle their visibility based
// on scroll position (Spotify-style horizontal rail).
function wireSideCarousel(root) {
  const track = root.querySelector(".side-carousel-track");
  const prev = root.querySelector(".side-carousel-nav.prev");
  const next = root.querySelector(".side-carousel-nav.next");
  if (!track || !prev || !next) return;
  const update = () => {
    const max = track.scrollWidth - track.clientWidth - 1;
    prev.classList.toggle("is-hidden", track.scrollLeft <= 0);
    next.classList.toggle("is-hidden", track.scrollLeft >= max);
  };
  const step = () => Math.max(160, Math.round(track.clientWidth * 0.8));
  prev.addEventListener("click", () => track.scrollBy({ left: -step(), behavior: "smooth" }));
  next.addEventListener("click", () => track.scrollBy({ left: step(), behavior: "smooth" }));
  track.addEventListener("scroll", update, { passive: true });
  requestAnimationFrame(update);
}

// "Related music" — real related artists fetched from the backend (Spotify
// "fans also like", or MusicBrainz relationships as a fallback). Replaces the
// old purely-local "Related music" card, which went blank whenever the artist
// had nothing else in the user's local catalog.
async function loadSidebarRelatedArtists(track, requestId) {
  const card = $("sideRelatedArtistsCard");
  if (!card) return;
  try {
    const data = await api("/api/artist/top_tracks", {
      method: "POST",
      timeout: 20000,
      body: JSON.stringify({ artist_id: primaryArtistId(track), name: track.artist || primaryArtistName(track) }),
    });
    if (requestId !== state.sidebarRequestId) return;
    const currentTitle = track.title || "";
    const currentArtist = track.artist || "";
    const tracks = (data.tracks || []).filter(t => (t.title || t.name) !== currentTitle).slice(0, 10);
    if (!tracks.length) { card.remove(); return; }
    card.innerHTML = `
      <div class="side-section-head"><h3>Related music</h3></div>
      <div class="side-carousel">
        <button class="side-carousel-nav prev is-hidden" type="button" aria-label="Scroll left"><i class="bi bi-chevron-left"></i></button>
        <div class="side-carousel-track">
          ${tracks.map(t => `
            <button class="side-carousel-card" type="button" data-side-track='${attrJson(t)}'>
              <span class="side-carousel-art" ${t.artwork_url ? `style="background-image:url('${t.artwork_url}')"` : ""}>${t.artwork_url ? "" : '<i class="bi bi-music-note"></i>'}</span>
              <strong>${esc(t.title || t.name)}</strong>
              <span>Track</span>
            </button>
          `).join("")}
        </div>
        <button class="side-carousel-nav next" type="button" aria-label="Scroll right"><i class="bi bi-chevron-right"></i></button>
      </div>
    `;
    bindSidebarTrackRows(card);
    wireSideCarousel(card);
  } catch (error) {
    if (requestId !== state.sidebarRequestId) return;
    card.remove();
  }
}

function bindSidebarTrackRows(root) {
  root.querySelectorAll("[data-side-track]").forEach((button) => {
    button.onclick = () => {
      const track = JSON.parse(button.dataset.sideTrack || "{}");
      selectMusicItem(track, "stream", null, state.queueContext);
    };
  });
}

async function loadSidebarArtistInfo(track, requestId, qualityLabel) {
  const artistName = primaryArtistName(track);
    const artistId = primaryArtistId(track);
    const card = $("sideArtistCard");
    if (!card) return;
    try {
      const about = await api("/api/artist/about", {
        method: "POST",
        timeout: 60000,
        // Send the full (untruncated) artist name so the backend can resolve the
        // correct artist when the track carries no spotify_artist_id.
        body: JSON.stringify({ artist_id: artistId, name: track.artist || artistName }),
      });
    if (requestId !== state.sidebarRequestId) return;
    const image = about.hero_image || about.avatar || (about.gallery && about.gallery[0] && about.gallery[0].url) || track.artist_artwork_url || track.artwork_url || "";
    const tourImage = pickTourHeroArtistImage(about) || image;
    // Remember the resolved artist image so the full tour page can use it as a hero.
    state.sidebarArtist = { name: artistName || track.artist || "", image, tourImage, id: artistId };
    const bio = stripHtml(about.biography || "");
    card.innerHTML = `
      <button class="side-artist-trigger" id="sideArtistTrigger" type="button">
        <span class="side-artist-image" style="${image ? `background-image:url('${image}')` : ""}">
          <span>About the artist</span>
        </span>
        <span class="side-artist-info">
          <strong>${esc(artistName || track.artist || "Artist")}${about.verified ? ' <i class="bi bi-patch-check-fill"></i>' : ""}</strong>
          ${about.monthly_listeners ? `<span>${formatCount(about.monthly_listeners)} monthly listeners</span>` : ""}
          ${bio ? `<span class="side-artist-bio">${esc(bio)}</span>` : ""}
        </span>
      </button>
    `;
    $("sideArtistTrigger")?.addEventListener("click", () => showArtistAboutModal(about, artistName || track.artist, artistId, image));
  } catch (error) {
    if (requestId !== state.sidebarRequestId) return;
    const image = track.artist_artwork_url || track.artwork_url || state.sidebarArtist?.image || "";
    card.innerHTML = `
      <button class="side-artist-trigger" id="sideArtistTrigger" type="button">
        <span class="side-artist-image" style="${image ? `background-image:url('${image}')` : ""}">
          <span>About the artist</span>
        </span>
        <span class="side-artist-info">
          <strong>${esc(artistName || track.artist || "Artist")}</strong>
          <span>${esc(String(error?.message || error || "Artist info unavailable"))}</span>
        </span>
      </button>
    `;
  }
}

async function loadSidebarCredits(track, requestId) {
  const card = $("sideCreditsCard");
  if (!card) return;
  try {
    const credits = await api("/api/track/credits", {
      method: "POST",
      body: JSON.stringify({ track }),
      timeout: 45000,
    });
    if (requestId !== state.sidebarRequestId) return;
    const rows = (credits.sections || []).flatMap(section => (section.rows || []).map(row => ({ ...row, section: section.title }))).slice(0, 3);
    card.querySelector(".side-card-loading")?.remove();
    card.insertAdjacentHTML("beforeend", `
      <div class="side-credit-list">
        ${rows.map(row => `
          <div class="side-credit-row">
            <span>${esc(row.name)}</span>
            <small>${esc(row.role || row.section || "")}</small>
          </div>
        `).join("") || '<div class="side-empty">No credits available.</div>'}
      </div>
    `);
    $("sideCreditsShowAll")?.addEventListener("click", () => showCreditsModal(credits));
  } catch (error) {
    if (requestId !== state.sidebarRequestId) return;
    card.querySelector(".side-card-loading")?.remove();
    card.insertAdjacentHTML("beforeend", `
      <div class="side-empty">${esc(String(error?.message || error || "Credits lookup failed"))}</div>
    `);
  }
}

async function loadSidebarTour(track, requestId) {
  const artistName = primaryArtistName(track);
  const artistId = primaryArtistId(track);
  const card = $("sideTourCard");
  if (!card) return;
  const fullName = track.artist || artistName;

  // Fast path: render any cached preview immediately.
  const tour = await api("/api/artist/tour", {
    method: "POST",
    body: JSON.stringify({ artist_id: artistId, name: artistName, live: false }),
  });
  if (requestId !== state.sidebarRequestId) return;
  const events = tour.events || [];
  card.querySelector(".side-card-loading")?.remove();

  const renderSidebarTourCard = (rows, statusText = "", showButton = false) => {
    card.querySelector(".side-tour-list")?.remove();
    card.querySelector(".side-tour-find")?.remove();
    card.querySelector(".side-tour-status")?.remove();
    card.querySelector(".side-tour-empty")?.remove();
    if (rows.length) {
      card.insertAdjacentHTML("beforeend", `
        <div class="side-tour-list">
          ${rows.slice(0, 3).map(event => tourEventHtml(event)).join("")}
        </div>
      `);
    } else if (statusText || showButton) {
      const message = statusText || "No upcoming tour dates.";
      card.insertAdjacentHTML("beforeend", `
        <div class="side-tour-status">${esc(message)}</div>
      `);
    }
    if (showButton) {
      card.insertAdjacentHTML("beforeend", `
        <button class="side-tour-find" id="sideTourFind" type="button">
          <i class="bi bi-globe2"></i> Find tour dates
        </button>
      `);
      $("sideTourFind")?.addEventListener("click", () => openTourPage({ name: fullName, artist_id: artistId, image: track.artist_artwork_url || track.artwork_url || "" }));
    }
    bindExternalUrlButtons(card);
    $("sideTourShowAll")?.addEventListener("click", () => openTourPage({ name: fullName, artist_id: artistId, image: track.artist_artwork_url || track.artwork_url || "" }));
  };

  const shouldRefreshTour = Boolean(tour.pending || tour.refresh_needed || tour.stale);
  renderSidebarTourCard(
    events,
    events.length ? "" : (shouldRefreshTour ? "Loading tour dates..." : (tour.message || tour.error || "No upcoming tour dates.")),
    !events.length && !shouldRefreshTour,
  );

  if (!shouldRefreshTour) return;

  // Background live fetch: update the preview when the live worker returns.
  api("/api/artist/tour", {
      method: "POST",
      body: JSON.stringify({ artist_id: artistId, name: artistName, live: true }),
      timeout: 0,
  }).then((liveTour) => {
    if (requestId !== state.sidebarRequestId) return;
    const liveEvents = liveTour?.events || [];
    const loadingGone = card.querySelector(".side-tour-status");
    if (loadingGone) loadingGone.remove();
    renderSidebarTourCard(liveEvents, liveEvents.length ? "" : (liveTour?.message || ""), !liveEvents.length);
    if (liveTour?.source && liveEvents.length) {
      card.insertAdjacentHTML("beforeend", `<div class="tour-source">Sourced live via ${esc(liveTour.source)}</div>`);
    }
  }).catch((error) => {
    if (requestId !== state.sidebarRequestId) return;
    if (/abort/i.test(String(error?.message || error || ""))) return;
    renderSidebarTourCard(events, String(error?.message || error || "Tour lookup failed"), !events.length);
  });
}

function openTourPage(artist = {}) {
  const artistName = typeof artist === "string" ? artist : (artist.name || artist.artist || "Artist");
  const artistId = typeof artist === "string" ? "" : (artist.artist_id || artist.spotify_id || "");
  const artistImage = typeof artist === "string" ? "" : (artist.image || artist.artwork_url || "");
  const ctx = state.sidebarArtist || {};
  const image = artistImage || ((ctx.name && ctx.name.toLowerCase() === String(artistName).toLowerCase()) ? (ctx.tourImage || ctx.image) : "");
  pushPage(() => renderArtistTourPage({ name: artistName, artist_id: artistId, image }));
}

function pickTourHeroArtistImage(about = {}) {
  const gallery = Array.isArray(about.gallery) ? about.gallery : [];
  const withSize = gallery
    .filter(item => item && item.url && Number(item.width) > 0 && Number(item.height) > 0)
    .map(item => ({
      ...item,
      width: Number(item.width) || 0,
      height: Number(item.height) || 0,
    }));
  if (!withSize.length) return about.hero_image || "";

  const score = (item) => {
    const aspect = item.width / item.height;
    const area = item.width * item.height;
    const landscapeBias = aspect >= 1.35 ? 10_000_000 : 0;
    const portraitPenalty = aspect < 1 ? 10_000_000 : 0;
    const shapeScore = Math.min(aspect, 3) * 1_000_000;
    return landscapeBias + shapeScore + area - portraitPenalty;
  };
  const picked = withSize.sort((a, b) => score(b) - score(a))[0];
  return picked?.url || about.hero_image || "";
}

function tourEventHtml(event = {}) {
  const date = event.date || event.datetime || "";
  const month = event.month || (date ? new Date(date).toLocaleString(undefined, { month: "short" }) : "");
  const day = event.day || (date ? String(new Date(date).getDate()) : "");
  const sub = event.location || event.venue || event.info || event.artist || "";
  return `
    <button class="side-tour-row" type="button" ${event.url ? `data-open-url="${esc(event.url)}"` : ""}>
      <span class="side-tour-date"><b>${esc(month || "--")}</b><strong>${esc(day || "--")}</strong></span>
      <span class="side-tour-copy">
        <strong>${esc(event.place || event.city || event.location || event.name || "Event")}</strong>
        <span>${esc(sub)}</span>
      </span>
    </button>
  `;
}

function bindExternalUrlButtons(root = document) {
  root.querySelectorAll("[data-open-url]").forEach(button => {
    if (button.dataset.urlBound) return;
    button.dataset.urlBound = "1";
    button.addEventListener("click", () => {
      const url = button.dataset.openUrl || "";
      if (url) window.open(url, "_blank", "noopener");
    });
  });
}

function bindArtistInlineLinks(root, modal = null) {
  root.querySelectorAll(".artist-link-inline, .album-link-inline").forEach(el => {
    el.onclick = (event) => {
      event.preventDefault();
      if (modal) modal.close();
      if (el.dataset.openArtist) {
        pushPage(() => renderArtistPage(JSON.parse(el.dataset.openArtist || "{}")));
      } else if (el.dataset.openAlbum) {
        pushPage(() => renderAlbumPage(JSON.parse(el.dataset.openAlbum || "{}")));
      }
    };
  });
}

function showArtistAboutModal(about = {}, artistName = "Artist", artistId = "", image = "") {
  document.getElementById("sidebarArtistAboutModal")?.remove();
  // Wikipedia-sourced bios carry their own inline links in biography_html; render
  // those (sanitized) directly. Spotify/plain bios go through the catalog linker.
  const bioHtml = about.biography_html
    ? sanitizeBioFragment(about.biography_html)
    : formatBiographyHtml(about.biography || "No biography available.", {
        name: artistName,
        artist: artistName,
        artist_id: artistId,
      });
  const gallery = about.gallery || [];
  const heroImage = image || about.hero_image || (gallery[0] && gallery[0].url) || "";
  const dialog = document.createElement("dialog");
  dialog.className = "about-modal sidebar-about-modal";
  dialog.id = "sidebarArtistAboutModal";
  dialog.innerHTML = `
    <button class="about-close" type="button" aria-label="Close"><i class="bi bi-x-lg"></i></button>
    <div class="sidebar-about-modal-content">
      ${heroImage ? `<div class="sidebar-about-hero" style="background-image:url('${heroImage}')"></div>` : ""}
      <div class="sidebar-about-body">
        <div class="about-stat-row">
          <div class="about-stat-item"><b>${formatCount(about.followers)}</b><span>Followers</span></div>
          <div class="about-stat-item"><b>${formatCount(about.monthly_listeners)}</b><span>Monthly Listeners</span></div>
        </div>
        <div class="about-bio-full">${bioHtml}</div>
        ${about.top_cities && about.top_cities.length ? `
          <h3>Where people listen</h3>
          <ul class="top-cities-list">
            ${about.top_cities.slice(0, 8).map(c => `
              <li><b>${esc(c.city)}, ${esc(c.country)}</b><span>${formatCount(c.count)} listeners</span></li>
            `).join("")}
          </ul>
        ` : ""}
      </div>
    </div>
  `;
  document.body.appendChild(dialog);
  dialog.querySelector(".about-close").onclick = () => dialog.close();
  dialog.onclick = (event) => { if (event.target === dialog) dialog.close(); };
  dialog.addEventListener("close", () => dialog.remove());
  bindArtistInlineLinks(dialog, dialog);
  dialog.showModal();
}

function showCreditsModal(credits = {}) {
  document.getElementById("sidebarCreditsModal")?.remove();
  const dialog = document.createElement("dialog");
  dialog.className = "side-modal credits-modal";
  dialog.id = "sidebarCreditsModal";
  dialog.innerHTML = `
    <div class="side-modal-head">
      <div>
        <h2>Credits</h2>
        <strong>${esc(credits.title || "Track")}</strong>
      </div>
      <button class="side-modal-close" type="button" aria-label="Close"><i class="bi bi-x-lg"></i></button>
    </div>
    <div class="side-modal-body">
      ${(credits.sections || []).map(section => `
        <section class="credits-modal-section">
          <h3>${esc(section.title)}</h3>
          ${(section.rows || []).map(row => `
            <div class="credits-modal-row">
              <span>${esc(row.name)}</span>
              <small>${esc(row.role || "")}</small>
            </div>
          `).join("") || '<div class="side-empty">No entries.</div>'}
        </section>
      `).join("")}
    </div>
  `;
  document.body.appendChild(dialog);
  dialog.querySelector(".side-modal-close").onclick = () => dialog.close();
  dialog.onclick = (event) => { if (event.target === dialog) dialog.close(); };
  dialog.addEventListener("close", () => dialog.remove());
  dialog.showModal();
}

async function renderArtistTourPage(artist = {}) {
  const artistName = typeof artist === "string" ? artist : (artist.name || artist.artist || "Artist");
  const artistId = typeof artist === "string" ? "" : (artist.artist_id || artist.spotify_id || "");
  const artistImage = typeof artist === "string" ? "" : (artist.image || "");
  const requestId = ++state.tourPageRequestId;
  setActiveView("home");
  setActiveLibraryPill("artists");
  const tourLocation = await resolveTourLocation();
  if (requestId !== state.tourPageRequestId) return;
  const localLabel = formatTourLocationLabel(tourLocation);
  const browseUrl = `https://www.songkick.com/search?query=${encodeURIComponent(artistName)}`;

  $("pageContent").innerHTML = `
    <div class="scroll-area tour-scroll">
      <div class="tour-events-page">
        <div class="tour-hero" id="tourHero">
          ${artistImage ? `<div class="tour-hero-art" style="background-image:url('${esc(artistImage)}')"></div>` : ""}
          <div class="tour-hero-overlay">
            <span class="tour-eyebrow">All events</span>
            <h1 class="tour-hero-name">${esc(artistName)}</h1>
          </div>
        </div>
        <div class="tour-hero-actions">
          <span class="tour-loc-pill"><i class="bi bi-geo-alt-fill"></i> ${esc(localLabel)}</span>
          <a class="tour-share" href="${esc(browseUrl)}" target="_blank" rel="noopener" aria-label="Browse all events"><i class="bi bi-box-arrow-up"></i></a>
        </div>
        <div class="tour-body" id="tourBody">
          <div class="tour-loading"><div class="spinner"></div><span>Finding tour dates…</span></div>
        </div>
      </div>
    </div>
  `;

  const body = $("tourBody");
  if (!body) return;

  const rowHtml = (event) => {
    const sub = [event.location || event.venue, event.info].filter(Boolean).join(" · ") || artistName;
    return `
      <div class="tour-event-row" ${event.url ? `data-open-url="${esc(event.url)}"` : ""}>
        <div class="tour-event-date">
          <span>${esc(event.month || "")}</span>
          <strong>${esc(event.day || "")}</strong>
        </div>
        <div class="tour-event-copy">
          <strong>${esc(event.place || event.city || "Event")}</strong>
          <span>${esc(sub)}</span>
          ${event.price ? `<span class="tour-event-price"><i class="bi bi-tag"></i> ${esc(event.price)}</span>` : ""}
        </div>
        <time class="tour-event-time">${esc(event.time || "")}</time>
      </div>`;
  };

  const renderTourBody = async (tour = {}, options = {}) => {
    if (requestId !== state.tourPageRequestId) return;
    const { showEmptyState = true } = options;
    const events = tour.events || [];
    const todayIso = new Date().toISOString().slice(0, 10);
    const upcomingEvents = events.filter(event => !event.date || String(event.date).slice(0, 10) >= todayIso);
    const groupedEvents = groupTourEvents(upcomingEvents, tourLocation);
    const nearEvents = await sortNearTourEvents(groupedEvents, tourLocation);
    if (requestId !== state.tourPageRequestId) return;
    const emptyMessage = tour.message || tour.error || "No upcoming tour dates found for this artist.";
    const emptyStateHtml = showEmptyState ? `
      <section class="tour-other">
        <div class="tour-empty-state">${esc(emptyMessage)}</div>
      </section>
    ` : `
      <div class="tour-loading"><div class="spinner"></div><span>Finding tour dates…</span></div>
    `;
    body.innerHTML = `
      <section class="tour-near">
        <h2>Near ${esc(localLabel)}</h2>
        ${nearEvents.length ? `
          <div class="tour-event-list">${nearEvents.map(rowHtml).join("")}</div>
        ` : `
          <div class="tour-near-empty">
            <p>No upcoming events.</p>
            <a class="tour-browse-btn" href="${esc(browseUrl)}" target="_blank" rel="noopener">Browse all events</a>
          </div>
        `}
      </section>
      ${groupedEvents.otherCountries.length ? `
        <section class="tour-other">
          <h2>Other countries</h2>
          <div class="tour-event-list">${groupedEvents.otherCountries.map(rowHtml).join("")}</div>
          ${tour.source ? `<div class="tour-source">Sourced live via ${esc(tour.source)}</div>` : ""}
        </section>
      ` : ""}
      ${!upcomingEvents.length ? emptyStateHtml : ""}
    `;
    bindExternalUrlButtons(body);
  };

  let shouldFetchLiveTour = true;
  try {
    const cachedTour = await api("/api/artist/tour", {
      method: "POST",
      body: JSON.stringify({ artist_id: artistId, name: artistName, live: false }),
      timeout: 12000,
    });
    if (requestId !== state.tourPageRequestId) return;
    shouldFetchLiveTour = Boolean(cachedTour?.pending || cachedTour?.refresh_needed || cachedTour?.stale);
    await renderTourBody(cachedTour || {}, { showEmptyState: !shouldFetchLiveTour });
  } catch (e) {
    if (requestId !== state.tourPageRequestId) return;
    await renderTourBody({ events: [] }, { showEmptyState: false });
  }

  if (!shouldFetchLiveTour) return;

  api("/api/artist/tour", {
      method: "POST",
      body: JSON.stringify({ artist_id: artistId, name: artistName, live: true }),
      timeout: 0,
    }).then((tour) => {
      if (!body.isConnected || requestId !== state.tourPageRequestId) return;
      renderTourBody(tour || {});
    }).catch((e) => {
      if (!body.isConnected || requestId !== state.tourPageRequestId) return;
      if (/abort/i.test(String(e?.message || e || ""))) return;
      renderTourBody({ events: [], error: String((e && e.message) || e) });
    });
  if (!artistImage) {
    const hero = $("tourHero");
    if (hero && !hero.querySelector(".tour-hero-art")) {
      api("/api/artist/about", {
        method: "POST",
        timeout: 60000,
        body: JSON.stringify({ name: artistName }),
      }).then((about) => {
        const image = about?.hero_image || about?.avatar || (about?.gallery && about.gallery[0] && about.gallery[0].url) || "";
        if (!image) return;
        if (!hero.isConnected) return;
        const art = document.createElement("div");
        art.className = "tour-hero-art";
        art.style.backgroundImage = `url("${String(image).replaceAll('"', '\\"')}")`;
        hero.prepend(art);
      }).catch(() => {});
    }
  }
}

function normalizePlaceKey(value = "") {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function formatTourLocationLabel(location = {}) {
  return location.label || [location.city, location.state, location.country].filter(Boolean).join(", ") || "you";
}

function tourLocationFromSettings() {
  const settings = state.settings || {};
  return {
    label: String(settings.tour_city || "").trim(),
    lat: String(settings.tour_lat || "").trim(),
    lon: String(settings.tour_lon || "").trim(),
    city: String(settings.tour_city || "").trim(),
    state: String(settings.tour_state || "").trim(),
    country: String(settings.tour_country || "").trim(),
    country_code: String(settings.tour_country_code || "").trim().toUpperCase(),
  };
}

async function resolveTourLocation() {
  if (state.tourLocation) return state.tourLocation;
  const override = tourLocationFromSettings();
  if (override.lat && override.lon) {
    try {
      const resolved = await api(`/api/location/reverse?lat=${encodeURIComponent(override.lat)}&lon=${encodeURIComponent(override.lon)}`);
      const location = {
        label: override.label || resolved?.city || "",
        city: String(resolved?.city || override.label || "").trim(),
        state: String(resolved?.state || "").trim(),
        country: String(resolved?.country || "").trim(),
        country_code: String(resolved?.country_code || "").trim().toUpperCase(),
        lat: override.lat,
        lon: override.lon,
      };
      state.tourLocation = location;
      return location;
    } catch (e) {}
  }
  if (override.label) {
    try {
      const geo = await api(`/api/location/search?term=${encodeURIComponent(override.label)}`);
      const first = (geo?.results || [])[0];
      if (first) {
        const location = {
          label: first.label || override.label,
          city: String(first.city || override.label || "").trim(),
          state: String(first.state || "").trim(),
          country: String(first.country || "").trim(),
          country_code: String(first.country_code || "").trim().toUpperCase(),
          lat: String(first.lat || "").trim(),
          lon: String(first.lon || "").trim(),
        };
        state.tourLocation = location;
        return location;
      }
    } catch (e) {}
  }
  const fallback = {
    label: "",
    city: "",
    state: "",
    country: "",
    country_code: "",
  };

  const geo = await new Promise((resolve) => {
    if (!navigator.geolocation) {
      resolve(null);
      return;
    }
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      resolve(value);
    };
    const timer = setTimeout(() => finish(null), 6000);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        clearTimeout(timer);
        finish({ lat: position.coords.latitude, lon: position.coords.longitude });
      },
      () => {
        clearTimeout(timer);
        finish(null);
      },
      { enableHighAccuracy: true, timeout: 5000, maximumAge: 60 * 1000 }
    );
  });

  if (geo && Number.isFinite(geo.lat) && Number.isFinite(geo.lon)) {
    try {
      const resolved = await api(`/api/location/reverse?lat=${encodeURIComponent(geo.lat)}&lon=${encodeURIComponent(geo.lon)}`);
      const location = {
        label: resolved?.city || "",
        city: String(resolved?.city || "").trim(),
        state: String(resolved?.state || "").trim(),
        country: String(resolved?.country || "").trim(),
        country_code: String(resolved?.country_code || "").trim().toUpperCase(),
        lat: String(geo.lat),
        lon: String(geo.lon),
      };
      state.tourLocation = location;
      return location;
    } catch (e) {}
  }

  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  fallback.label = (tz.split("/").pop() || "").replace(/_/g, " ") || "";
  fallback.city = fallback.label;
  state.tourLocation = fallback;
  return fallback;
}

async function hydrateTourLocationInputs() {
  const cityInput = $("tourCity");
  const latInput = $("tourLat");
  const lonInput = $("tourLon");
  if (!cityInput || !latInput || !lonInput) return;

  const settings = state.settings || {};
  latInput.value = String(settings.tour_lat || "").trim();
  lonInput.value = String(settings.tour_lon || "").trim();
  cityInput.value = String(settings.tour_city || "").trim();

  if ((!cityInput.value || !cityInput.value.trim()) && latInput.value && lonInput.value) {
    try {
      const resolved = await api(`/api/location/reverse?lat=${encodeURIComponent(latInput.value)}&lon=${encodeURIComponent(lonInput.value)}`);
      cityInput.value = String(resolved?.city || "").trim();
    } catch (e) {}
  }
  if (cityInput.value.trim() && (!latInput.value || !lonInput.value)) {
    try {
      const data = await api(`/api/location/search?term=${encodeURIComponent(cityInput.value.trim())}`);
      const first = (data?.results || [])[0];
      if (first) {
        latInput.value = String(first.lat || "").trim();
        lonInput.value = String(first.lon || "").trim();
      }
    } catch (e) {}
  }
}

function setTourLocationSelection(item = {}) {
  const cityInput = $("tourCity");
  const latInput = $("tourLat");
  const lonInput = $("tourLon");
  if (!cityInput || !latInput || !lonInput) return;
  cityInput.value = String(item.label || item.city || "").trim();
  latInput.value = String(item.lat || "").trim();
  lonInput.value = String(item.lon || "").trim();
  state.tourLocation = {
    label: cityInput.value,
    city: String(item.city || item.label || "").trim(),
    state: String(item.state || "").trim(),
    country: String(item.country || "").trim(),
    country_code: String(item.country_code || "").trim().toUpperCase(),
    lat: latInput.value,
    lon: lonInput.value,
  };
  hideTourLocationSuggestions();
}

function showTourLocationSuggestions(items = []) {
  const box = $("tourLocationSuggestions");
  if (!box) return;
  if (!items.length) {
    box.innerHTML = "";
    box.classList.add("hidden");
    return;
  }
  box.innerHTML = items.map((item, index) => `
    <button class="tour-location-suggestion" type="button" data-tour-location="${index}">
      <strong>${esc(item.label || item.city || "Location")}</strong>
      <span>${esc(item.subtitle || [item.state, item.country].filter(Boolean).join(", "))}</span>
    </button>
  `).join("");
  box.classList.remove("hidden");
  box.querySelectorAll("[data-tour-location]").forEach((button) => {
    button.addEventListener("click", () => {
      const item = items[Number(button.dataset.tourLocation)];
      if (item) setTourLocationSelection(item);
    });
  });
}

function hideTourLocationSuggestions() {
  const box = $("tourLocationSuggestions");
  if (!box) return;
  box.classList.add("hidden");
  box.innerHTML = "";
}

function setupTourLocationPicker() {
  const input = $("tourCity");
  const box = $("tourLocationSuggestions");
  if (!input || !box) return;

  const doSearch = async () => {
    const term = input.value.trim();
    if (!term) {
      hideTourLocationSuggestions();
      return;
    }
    const countryCode = String((state.tourLocation && state.tourLocation.country_code) || "").trim();
    try {
      const data = await api(`/api/location/search?term=${encodeURIComponent(term)}&country_code=${encodeURIComponent(countryCode)}`);
      if (input.value.trim() !== term) return;
      showTourLocationSuggestions(data.results || []);
    } catch (e) {
      hideTourLocationSuggestions();
    }
  };

  input.oninput = () => {
    clearTimeout(state.tourLocationSearchTimer);
    state.tourLocationSearchTimer = setTimeout(doSearch, 200);
  };
  input.onfocus = () => {
    if (input.value.trim()) input.oninput();
  };
  input.onblur = () => {
    setTimeout(() => hideTourLocationSuggestions(), 120);
  };
  box.onmousedown = (event) => event.preventDefault();
}

function extractEventLocationParts(event = {}) {
  const place = String(event.place || event.city || "").trim();
  const location = String(event.location || "").trim();
  const country = String(event.country || "").trim();
  const state = String(event.state || event.region || "").trim();
  let city = place;
  let derivedState = state;
  let derivedCountry = country;

  if (location) {
    const parts = location.split(",").map(part => part.trim()).filter(Boolean);
    const venueish = /(arena|stadium|theatre|theater|park|hall|club|center|centre|dome|auditorium|festival|pavilion|ground|amphitheater|amphitheatre)/i;
    if (!city) {
      if (parts.length >= 3) city = venueish.test(parts[0]) ? parts[1] : parts[0];
      else if (parts.length === 2) city = venueish.test(parts[0]) ? parts[1] : parts[0];
      else if (parts.length === 1) city = parts[0];
    }
    if (!derivedState && parts.length >= 3) derivedState = parts[1];
    if (!derivedCountry && parts.length >= 2) derivedCountry = parts[parts.length - 1];
  }

  return {
    city,
    state: derivedState,
    country: derivedCountry,
    cityKey: normalizePlaceKey(city),
    stateKey: normalizePlaceKey(derivedState),
    countryKey: normalizePlaceKey(derivedCountry),
  };
}

function groupTourEvents(events, location) {
  const targetCityKey = normalizePlaceKey(location.city);
  const targetStateKey = normalizePlaceKey(location.state);
  const targetCountryKey = normalizePlaceKey(location.country);
  const out = {
    sameCity: [],
    sameState: [],
    sameCountry: [],
    otherCountries: [],
  };

  for (const event of events) {
    const place = extractEventLocationParts(event);
    if (targetCityKey && place.cityKey && place.cityKey === targetCityKey) {
      out.sameCity.push(event);
      continue;
    }
    if (targetStateKey && place.stateKey && place.stateKey === targetStateKey && (!targetCountryKey || !place.countryKey || place.countryKey === targetCountryKey)) {
      out.sameState.push(event);
      continue;
    }
    if (targetCountryKey && place.countryKey && place.countryKey === targetCountryKey) {
      out.sameCountry.push(event);
      continue;
    }
    out.otherCountries.push(event);
  }

  return out;
}

function tourEventDateValue(event = {}) {
  const value = String(event.date || event.datetime || "");
  const parsed = value ? Date.parse(value) : NaN;
  return Number.isFinite(parsed) ? parsed : Number.MAX_SAFE_INTEGER;
}

function numericCoordinate(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function haversineKm(aLat, aLon, bLat, bLon) {
  const toRad = (value) => value * Math.PI / 180;
  const earthKm = 6371;
  const dLat = toRad(bLat - aLat);
  const dLon = toRad(bLon - aLon);
  const startLat = toRad(aLat);
  const endLat = toRad(bLat);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(startLat) * Math.cos(endLat) * Math.sin(dLon / 2) ** 2;
  return 2 * earthKm * Math.asin(Math.min(1, Math.sqrt(h)));
}

async function coordinatesForTourEvent(event = {}, location = {}) {
  const place = extractEventLocationParts(event);
  const city = place.city || event.city || event.place || "";
  if (!city) return null;
  const countryCode = String(location.country_code || "").trim().toUpperCase();
  const country = place.country || location.country || "";
  const key = normalizePlaceKey([city, place.state, countryCode || country].filter(Boolean).join("|"));
  if (!key) return null;
  if (state.tourEventLocationCache.has(key)) return state.tourEventLocationCache.get(key);

  const query = [city, place.state, country].filter(Boolean).join(", ");
  try {
    const data = await api(`/api/location/search?term=${encodeURIComponent(query)}&country_code=${encodeURIComponent(countryCode)}`, { timeout: 10000 });
    const first = (data?.results || [])[0];
    const coords = first ? {
      lat: numericCoordinate(first.lat),
      lon: numericCoordinate(first.lon),
    } : null;
    const resolved = coords && coords.lat !== null && coords.lon !== null ? coords : null;
    state.tourEventLocationCache.set(key, resolved);
    return resolved;
  } catch (e) {
    state.tourEventLocationCache.set(key, null);
    return null;
  }
}

async function sortNearTourEvents(groupedEvents, location = {}) {
  const targetLat = numericCoordinate(location.lat);
  const targetLon = numericCoordinate(location.lon);
  const nearEvents = [
    ...groupedEvents.sameCity,
    ...groupedEvents.sameState,
    ...groupedEvents.sameCountry,
  ];
  if (targetLat === null || targetLon === null || nearEvents.length < 2) {
    return nearEvents.sort((a, b) => tourEventDateValue(a) - tourEventDateValue(b));
  }

  const ranked = await Promise.all(nearEvents.map(async (event, index) => {
    const place = extractEventLocationParts(event);
    let distance = Number.POSITIVE_INFINITY;
    if (normalizePlaceKey(location.city) && place.cityKey === normalizePlaceKey(location.city)) {
      distance = 0;
    } else {
      const coords = await coordinatesForTourEvent(event, location);
      if (coords) distance = haversineKm(targetLat, targetLon, coords.lat, coords.lon);
    }
    return { event, index, distance };
  }));

  ranked.sort((a, b) => {
    if (a.distance !== b.distance) return a.distance - b.distance;
    const dateDiff = tourEventDateValue(a.event) - tourEventDateValue(b.event);
    return dateDiff || a.index - b.index;
  });
  return ranked.map(item => item.event);
}

function serviceDownloadPayload(track, mode = "stream", prefetch = false) {
  return {
    kind: "track",
    mode,
    prefetch,
    artist: track.artist || "",
    album: track.album || "",
    title: track.title || "",
    quality: state.settings.default_quality || "LOSSLESS",
    service: state.settings.download_service || "tidal",
    engine: state.settings.download_engine || "spotiflac",
    track,
    metadata: track.metadata || track,
  };
}

function trackIdentityValue(item, key) {
  return item?.[key] || item?.metadata?.[key] || "";
}

function trackKey(item) {
  for (const key of ["spotify_id", "isrc", "musicbrainz_recording_id", "musicbrainz_track_id", "deezer_id", "tidal_id"]) {
    const value = String(trackIdentityValue(item, key) || "").trim();
    if (value) return `${key}:${value}`;
  }
  return [
    item?.title || item?.metadata?.title || "",
    item?.artist || item?.metadata?.artist || "",
    item?.album || item?.metadata?.album || "",
  ].map(value => String(value).trim().toLowerCase()).join("||");
}

function recentTrackKey(item) {
  return trackKey(item) || [
    item?.title || item?.metadata?.title || "",
    item?.artist || item?.metadata?.artist || "",
    item?.album || item?.metadata?.album || "",
  ].map(value => String(value).trim().toLowerCase()).join("||");
}

function listeningTrackPayload(track) {
  const sourceEngine = track?.source_engine || track?.metadata?.source_engine || track?.source || state.settings.download_engine || "";
  const sourceService = track?.source_service || track?.metadata?.source_service || track?.source || state.settings.download_service || "";
  const resolvedUrl = track?.resolved_url || track?.metadata?.resolved_url || track?.spotify_url || track?.url || "";
  return {
    track_key: trackKey(track),
    title: track?.title || track?.name || "",
    artist: track?.artist || "",
    album: track?.album || "",
    duration_ms: Number(track?.duration_ms || track?.metadata?.duration_ms || 0),
    source_engine: sourceEngine,
    source_service: sourceService,
    resolved_url: resolvedUrl,
    metadata: track?.metadata || track || {},
  };
}

function startListeningSession(track, playbackContext = null) {
  if (!track) return;
  const sourceEngine = track?.source_engine || track?.metadata?.source_engine || track?.source || state.settings.download_engine || "";
  const sourceService = track?.source_service || track?.metadata?.source_service || track?.source || state.settings.download_service || "";
  const resolvedUrl = track?.resolved_url || track?.metadata?.resolved_url || track?.spotify_url || track?.url || "";
  state.listeningSession = {
    event_id: crypto.randomUUID(),
    started_at: Date.now() / 1000,
    track_key: trackKey(track),
    title: track.title || track.name || "",
    artist: track.artist || "",
    album: track.album || "",
    duration_ms: Number(track.duration_ms || track.metadata?.duration_ms || 0),
    source_engine: sourceEngine,
    source_service: sourceService,
    resolved_url: resolvedUrl,
    listened_ms: 0,
    max_position_ms: 0,
    metadata: track.metadata || track || {},
    playbackContext,
  };
}

function updateListeningSessionPosition(positionSeconds = 0, durationSeconds = 0) {
  const session = state.listeningSession;
  if (!session) return;
  const listenedMs = Math.max(0, Math.round(Number(positionSeconds || 0) * 1000));
  session.max_position_ms = Math.max(session.max_position_ms || 0, listenedMs);
  if (!session.duration_ms && durationSeconds > 0) {
    session.duration_ms = Math.round(Number(durationSeconds) * 1000);
  }
}

async function finalizeListeningSession(eventType = "", reason = "") {
  const session = state.listeningSession;
  if (!session || !session.track_key) return null;
  const durationMs = Number(session.duration_ms || 0) || 0;
  const listenedMs = Math.max(0, Number(session.max_position_ms || 0));
  const listenedPercent = durationMs > 0 ? Math.min(100, (listenedMs / durationMs) * 100) : 0;
  const payload = {
    event_id: session.event_id,
    track_key: session.track_key,
    title: session.title,
    artist: session.artist,
    album: session.album,
    source_engine: session.source_engine || "",
    source_service: session.source_service || "",
    resolved_url: session.resolved_url || "",
    duration_ms: durationMs,
    listened_ms: listenedMs,
    listened_percent: listenedPercent,
    started_at: session.started_at,
    ended_at: Date.now() / 1000,
    event_type: eventType || (listenedPercent >= 95 ? "complete" : listenedPercent >= 30 ? "play" : "skip"),
    reason,
    metadata: session.metadata || {},
  };
  state.listeningSession = null;
  try {
    return await api("/api/listening/event", {
      method: "POST",
      timeout: 10000,
      body: JSON.stringify(payload),
    });
  } catch (error) {
    return null;
  }
}

function beaconListeningSession(eventType = "", reason = "") {
  const session = state.listeningSession;
  if (!session || !session.track_key || !navigator.sendBeacon) return false;
  const durationMs = Number(session.duration_ms || 0) || 0;
  const listenedMs = Math.max(0, Number(session.max_position_ms || 0));
  const listenedPercent = durationMs > 0 ? Math.min(100, (listenedMs / durationMs) * 100) : 0;
  const payload = {
    event_id: session.event_id,
    track_key: session.track_key,
    title: session.title,
    artist: session.artist,
    album: session.album,
    source_engine: session.source_engine || "",
    source_service: session.source_service || "",
    resolved_url: session.resolved_url || "",
    duration_ms: durationMs,
    listened_ms: listenedMs,
    listened_percent: listenedPercent,
    started_at: session.started_at,
    ended_at: Date.now() / 1000,
    event_type: eventType || (listenedPercent >= 95 ? "complete" : listenedPercent >= 30 ? "play" : "skip"),
    reason,
    metadata: session.metadata || {},
  };
  state.listeningSession = null;
  try {
    return navigator.sendBeacon("/api/listening/event", new Blob([JSON.stringify(payload)], { type: "application/json" }));
  } catch (error) {
    return false;
  }
}

function uniqueRecentTracks(items = []) {
  const seen = new Set();
  const out = [];
  for (const item of items) {
    const key = recentTrackKey(item);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push(item);
  }
  return out;
}

function playableQueueItem(item) {
  return item && item.type !== "artist" && item.type !== "album";
}

function getQueueIndex() {
  let idx = state.queueIndex;
  if (idx < 0 && state.currentTrack) {
    const currentKey = trackKey(state.currentTrack);
    idx = state.queue.findIndex(t => trackKey(t) === currentKey);
    if (idx >= 0) state.queueIndex = idx;
  }
  return idx;
}

function currentQueueOrderKey() {
  return `${state.isShuffle ? "shuffle" : "linear"}|${state.queue.map(trackKey).join(">")}`;
}

function restoreLinearOriginalQueue() {
  if (state.isShuffle || !state.currentTrack || state.originalQueue.length <= state.queue.length) return;
  state.queue = [...state.originalQueue];
  state.queueIndex = state.queue.findIndex(t => trackKey(t) === trackKey(state.currentTrack));
}

function upcomingPrefetchTracks(limit = PREFETCH_AHEAD_COUNT) {
  if (state.isRepeat || !state.queue.length) return [];
  const idx = getQueueIndex();
  if (idx < 0) return [];
  const max = Math.min(limit, Math.max(0, state.queue.length - 1));
  const tracks = [];
  const seen = new Set([state.currentTrack ? trackKey(state.currentTrack) : ""]);
  for (let offset = 1; offset <= max; offset++) {
    const item = state.queue[(idx + offset) % state.queue.length];
    const key = trackKey(item);
    if (!playableQueueItem(item) || seen.has(key)) continue;
    seen.add(key);
    tracks.push(item);
  }
  return tracks;
}

function currentPrefetchWindowKeys() {
  return new Set(upcomingPrefetchTracks().map(trackKey));
}

function cancelPrefetchJob(key, entry, reason = "stale") {
  if (!entry || !entry.jobId) return;
  console.log("[Prefetch] Cancelling", entry.jobId, reason);
  api("/api/service/cancel", {
    method: "DELETE",
    body: JSON.stringify({ job_id: entry.jobId }),
  }).catch(() => {});
  state.prefetchJobs.delete(key);
}

function cancelPrefetchJobs(reason = "stale", keepKeys = new Set(), orderKey = currentQueueOrderKey()) {
  for (const [key, entry] of Array.from(state.prefetchJobs.entries())) {
    if (keepKeys.has(key) && entry.orderKey === orderKey) continue;
    cancelPrefetchJob(key, entry, reason);
  }
}

function cancelAllPrefetchJobs(reason = "queue changed") {
  cancelPrefetchJobs(reason, new Set(), "");
}

function adoptPrefetchJobForTrack(track) {
  const key = trackKey(track);
  const entry = state.prefetchJobs.get(key);
  if (entry) {
    console.log("[Prefetch] Reusing prefetched job:", entry.jobId);
    state.prefetchJobs.delete(key);
  }
  return entry || null;
}

function playQueueOffset(delta) {
  if (!state.queue.length && !state.originalQueue.length) return;
  restoreLinearOriginalQueue();
  if (!state.queue.length) return;
  const idx = getQueueIndex();
  const playlistCtx = currentPlaylistContext();
  if (delta > 0 && playlistCtx && idx >= state.queue.length - 1) {
    continuePlaylistWithRecommendations("manual_next").then((advanced) => {
      if (advanced && state.queue.length > idx + 1) {
        state.queueIndex = idx + 1;
        selectMusicItem(state.queue[state.queueIndex], "stream", null, state.queueContext);
      }
    }).catch(() => {});
    return;
  }
  state.queueIndex = ((idx < 0 ? 0 : idx) + delta + state.queue.length) % state.queue.length;
  selectMusicItem(state.queue[state.queueIndex], "stream", null, state.queueContext);
}

async function prefetchOneTrack(next, orderKey) {
  const key = trackKey(next);
  if (state.prefetchJobs.has(key)) return;
  try {
    const source = await api("/api/playback/source", { method: "POST", body: JSON.stringify(serviceDownloadPayload(next, "stream")) });
    if (source.path) {
      console.log("[Prefetch] Already cached:", next.title);
      return;
    }
  } catch (e) {}
  try {
    if (currentQueueOrderKey() !== orderKey || !currentPrefetchWindowKeys().has(key)) return;
    const job = await api("/api/service/download", { method: "POST", body: JSON.stringify(serviceDownloadPayload(next, "stream", true)) });
    if (job && job.id) {
      if (currentQueueOrderKey() !== orderKey || !currentPrefetchWindowKeys().has(key)) {
        api("/api/service/cancel", { method: "DELETE", body: JSON.stringify({ job_id: job.id }) }).catch(() => {});
        return;
      }
      console.log("[Prefetch] Job started:", job.id, "for", next.title);
      state.prefetchJobs.set(key, { jobId: job.id, orderKey });
    }
  } catch (e) {
    console.error("[Prefetch] Failed to start:", e);
  }
}

async function prefetchNextTracks() {
  if (state.isRepeat) { console.log("[Prefetch] skipped: repeat on"); return; }
  restoreLinearOriginalQueue();
  if (!state.queue.length) { console.log("[Prefetch] skipped: empty queue"); return; }
  const targets = upcomingPrefetchTracks();
  if (!targets.length) { console.log("[Prefetch] skipped: no upcoming tracks"); return; }
  const orderKey = currentQueueOrderKey();
  cancelPrefetchJobs("outside current queue window", new Set(targets.map(trackKey)), orderKey);
  console.log(`[Prefetch] Starting batch of ${targets.length}:`, targets.map(track => track.title).join(", "));
  await Promise.all(targets.map(track => prefetchOneTrack(track, orderKey)));
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
    const activeJobId = (result.job && result.job.id) || result.active_job_id || "";
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
    jobId = (status && status.active_job_id) ? status.active_job_id : "";
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
  button.innerHTML = '<i class="bi bi-arrow-down-circle"></i>';
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
    if (button && button.dataset.cancelled === "1") return null;
    // Stop polling a button that has been removed from the DOM (e.g. the tab
    // was re-rendered); a fresh poller is attached to the replacement button.
    if (button && !button.isConnected) return null;
    await new Promise(resolve => setTimeout(resolve, 1000));
    if (button && (button.dataset.cancelled === "1" || !button.isConnected)) return null;
    const status = await api("/api/library/status", {
      method: "POST",
      body: JSON.stringify(serviceDownloadPayload(track, "download")),
    }).catch(() => null);
    if (status && status.active_job_id && button) button.dataset.activeJobId = status.active_job_id;
    if (status && typeof status.progress !== "undefined") {
      updateLibraryProgressButton(button, status);
    }
    if (status && status.active_job_status === "error") throw new Error("Download cancelled");
    if (status && status.in_library) {
      if (button) {
        button.classList.remove("progress");
        button.classList.add("downloaded");
        button.innerHTML = '<i class="bi bi-arrow-down-circle-fill downloaded"></i>';
      }
      return status;
    }
    if (jobId) {
      const data = await api("/api/service/downloads").catch(() => ({ jobs: [] }));
      const job = (data.jobs || []).find(item => item.id === jobId);
      if (job && job.status === "error") throw new Error(job.error || "Download failed");
      if (job && job.status === "finished") {
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
        await playFromLibraryPath(job.library_path, track, requestId, job.id, "Playing from cache");
      } else if (isNativeAudioSelected()) {
        // Skip browser playback for live jobs if native is selected.
        // NSSound doesn't support streaming URLs, so we wait for the file to finish.
        state.currentPlayableReady = false;
        state.activeJobPhase = playerStatusForJob(job);
        state.autoplayWanted = false;
        setPlayerStatusIcon("downloading", job.progress || 0);
        setPlayerStatus(state.activeJobPhase, track, job);
      } else {
        const audio = $("audioPlayer");
        state.activeJobPhase = playerStatusForJob(job);
        state.autoplayWanted = !state.manualPauseRequested;
        if (activeJobHasPlayableAudio(job)) {
          const streamUrl = `${API_BASE}/api/library/stream_active_job?job_id=${job.id}&t=${Date.now()}`;
          state.currentStreamUrl = streamUrl;
          audio.src = streamUrl;
          state.currentPlayableReady = true;
          audio.load();
        } else {
          state.currentPlayableReady = false;
          setPlayerStatusIcon("downloading", job.progress || 0);
          setPlayerStatus(state.activeJobPhase, track, job);
        }
        syncPlayPauseButton();
        if (state.currentPlayableReady) tryStartAudio(audio, track, requestId, job.id);
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
        if (mode === "stream") {
          const source = await api("/api/playback/source", {
            method: "POST",
            body: JSON.stringify(serviceDownloadPayload(track, "stream")),
          }).catch(() => null);
          if (source && source.path) {
            await playFromLibraryPath(source.path, track, requestId, source.active_job_id || null, "Playing from cache");
            return;
          }
        }
        setPlayerStatusIcon("error");
        setPlayerStatus(job.error || "Service download failed", track, job);
        return;
      }
      const pct = job.progress ? Math.max(0, Math.min(99, Math.round(job.progress))) : 0;
      if (job.status === "finished") {
        if (mode === "stream" && job.library_path) {
          state.currentLibraryPath = job.library_path;
          state.currentPlayableReady = true;
        }
        setPlayerStatusIcon("ready");
        setPlayerStatus(mode === "stream" ? "Playing from cache" : "Saved to library", track, job);
        if (!switchedToFinal && mode === "stream" && job.library_path) {
          switchedToFinal = true;
          const audio = $("audioPlayer");
          const shouldSwitchToNative = isNativeAudioSelected() && !state.manualPauseRequested;
          // Don't interrupt active browser stream playback unless the user
          // explicitly selected native app-only output, where no browser route exists.
          const shouldSwitchActiveJobToCache = isActiveJobStreamUrl(state.currentStreamUrl);
          if (shouldSwitchToNative || (!state.manualPauseRequested && (shouldSwitchActiveJobToCache || !audio || audio.paused || audio.currentTime < 2))) {
            try {
              const resumeAt = shouldSwitchToNative && state.pendingNativeStartAt
                ? state.pendingNativeStartAt
                : (audio && Number.isFinite(audio.currentTime) ? audio.currentTime : 0);
              await playFromLibraryPath(job.library_path, track, requestId, jobId, "Playing from cache", resumeAt);
            } catch (error) {
              setPlayerStatusIcon("error");
              setPlayerStatus(error.message || "Native audio failed", track);
            }
          }
        }
        state.activeJobId = null;
        return;
      }
      if (mode === "stream" && !state.currentPlayableReady && activeJobHasPlayableAudio(job) && !isNativeAudioSelected()) {
        const audio = $("audioPlayer");
        const streamUrl = `${API_BASE}/api/library/stream_active_job?job_id=${job.id}&t=${Date.now()}`;
        state.currentStreamUrl = streamUrl;
        audio.src = streamUrl;
        state.currentPlayableReady = true;
        if (!state.manualPauseRequested) {
          state.autoplayWanted = true;
          audio.load();
          tryStartAudio(audio, track, requestId, job.id);
        }
      }
      if (mode === "stream" && $("playerStatusIcon")?.classList.contains("error")) {
        setPlayerStatusIcon("downloading", pct);
      }
      updatePlayerPie(pct);
      state.activeJobPhase = playerStatusForJob(job);
      setPlayerStatus(state.activeJobPhase, track, job);
    } catch (error) {}
  }
}

function tryStartAudio(audio, track, requestId, jobId) {
  audio.play().catch((error) => {
    if (requestId !== state.playbackRequestId) return;
    if (error && error.name === "NotAllowedError") {
      state.autoplayWanted = true;
      setPlayerStatus("Ready — press play", track);
    } else if (error && error.name !== "AbortError") {
      // AbortError means src changed mid-load — keep autoplayWanted so oncanplay retries.
      state.autoplayWanted = false;
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

function openSuggestionItem(item = {}) {
  if (item.type === "artist") {
    pushPage(() => renderArtistPage(artistTarget(item)));
    return;
  }
  if (item.type === "album") {
    pushPage(() => renderAlbumPage(albumTarget(item)));
    return;
  }
  if (item.type === "track") {
    pushPage(() => renderAlbumPage(albumTarget(item)));
  }
}

function bindSuggestionButtons(root = document) {
  root.querySelectorAll("[data-suggestion]").forEach((button) => {
    if (button.dataset.bound) return;
    button.dataset.bound = "1";
    button.onclick = () => {
      const item = state.suggestionResults[Number(button.dataset.suggestion)];
      $("searchInput").value = item.title || item.artist || "";
      hideSuggestions();
      openSuggestionItem(item);
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

function stopCacheLogPolling() {
  if (state.cacheLogTimer) {
    clearInterval(state.cacheLogTimer);
    state.cacheLogTimer = null;
  }
}

async function refreshCacheLogs() {
  const output = $("cacheLiveLog");
  if (!output) return;
  try {
    const data = await api("/api/cache/logs");
    const events = data.events || [];
    const status = $("cacheLiveStatus");
    if (status) status.textContent = data.cache_dir || "Cache folder";
    if (!events.length) {
      output.textContent = "Waiting for cache activity...";
      return;
    }
    output.textContent = events.map((event) => {
      const clock = new Date((event.timestamp || 0) * 1000).toLocaleTimeString();
      const track = event.title ? `[${event.title}] ` : "";
      const msg = event.message || "";
      
      // Auto-play / High-performance transition: upgrade a LIVE active-job
      // stream to the finalized local file. Only do this when we are actually
      // on a live active-job stream — never when already playing the cache file
      // or on native output (re-selecting there just redownloads/loops) and
      // never if the user manually paused (re-selecting restarts from 0).
      if (msg.includes("Ready to play") && state.currentTrack && !state.manualPauseRequested && !state.nativeAudio.playing && $("audioPlayer").paused && isActiveJobStreamUrl(state.currentStreamUrl)) {
        const title = (state.currentTrack.title || "").toLowerCase();
        if (msg.toLowerCase().includes(title)) {
           console.log("[Player] Detected file readiness, forcing high-fidelity stream...");
           // This switches from the live torrent stream to the finalized local file
           selectMusicItem(state.currentTrack, "stream", null, state.queueContext);
        }
      }
      
      return `[${clock}] ${track}${msg}`;
    }).join("\n");
    const autoScroll = $("cacheAutoScroll");
    if (!autoScroll || autoScroll.checked) {
      output.scrollTop = output.scrollHeight;
    }
  } catch (error) {
    output.textContent = "Unable to read cache activity.";
  }
}

function startCacheLogPolling() {
  stopCacheLogPolling();
  refreshCacheLogs();
  state.cacheLogTimer = setInterval(refreshCacheLogs, 1000);
}

async function renderSettings() {
  setActiveView("settings");
  startCacheLogPolling();
  state.settings = await api("/api/settings");

  $("cacheDir").value = state.settings.cache_dir || "";

  $("musicDir").value = state.settings.music_dir || "";

  const engine = state.settings.download_engine || "spotiflac";
  $("downloadEngine").value = engine;
  updateEngineControls(engine, state.settings.download_service || "tidal", state.settings.default_quality || "LOSSLESS");
  $("downloadEngine").onchange = () => {
    const newEngine = $("downloadEngine").value;
    updateEngineControls(newEngine, $("downloadService").value, $("defaultQuality").value);
  };

  if ($("duckModel")) {
    $("duckModel").value = state.settings.duck_model || "1";
  }

  const aiProvider = $("aiProvider");
  if (aiProvider) {
    aiProvider.value = state.settings.ai_provider || "duckai";
    const updateAiRows = () => {
      const provider = aiProvider.value;
      $("duckModelRow")?.classList.toggle("hidden", provider !== "duckai");
      $("geminiModelRow")?.classList.toggle("hidden", provider !== "gemini");
    };
    aiProvider.onchange = updateAiRows;
    updateAiRows();
  }

  if ($("geminiModel")) {
    $("geminiModel").value = state.settings.gemini_model || "gemini-1.5-flash";
  }
  if ($("tourSource")) {
    $("tourSource").value = state.settings.tour_source || "ai";
  }
  await hydrateTourLocationInputs();
  setupTourLocationPicker();

  $("trackMaxRetries").value = (state.settings.track_max_retries !== undefined) ? state.settings.track_max_retries : 1;

  $("cacheCleanupFrequency").value = state.settings.cache_cleanup_frequency || "never";

  const demoMusicIndexer = $("demoMusicIndexer");
  if (demoMusicIndexer) demoMusicIndexer.checked = !!state.settings.demo_music_indexer;
  const strictTitleMatch = $("strictTitleMatch");
  if (strictTitleMatch) strictTitleMatch.checked = !!state.settings.strict_title_match;
  $("qobuzToken").value = state.settings.qobuz_token || "";
  $("discogsToken").value = state.settings.discogs_token || "";

  try {
    const stats = await api("/api/cache");
    const sizeMB = stats.bytes / (1024 * 1024);
    const sizeText = sizeMB >= 1024 ? `${(sizeMB / 1024).toFixed(1)} GB` : `${sizeMB.toFixed(1)} MB`;
    $("cacheUsage").textContent = `${sizeText} used by ${stats.files} files`;
  } catch (e) {}
}

async function saveSettings(e) {
  e.preventDefault();
  const body = {
    ...state.settings,
    cache_dir: $("cacheDir").value,
    music_dir: $("musicDir").value,
    download_engine: $("downloadEngine").value,
    ai_provider: $("aiProvider") ? $("aiProvider").value : "duckai",
    duck_model: $("duckModel") ? $("duckModel").value : "1",
    gemini_model: $("geminiModel") ? $("geminiModel").value : "gemini-1.5-flash",
    tour_source: $("tourSource") ? $("tourSource").value : "ai",
    tour_city: $("tourCity") ? $("tourCity").value.trim() : "",
    tour_lat: $("tourLat") ? $("tourLat").value.trim() : "",
    tour_lon: $("tourLon") ? $("tourLon").value.trim() : "",
    download_service: $("downloadService").value,
    default_quality: $("defaultQuality").value,
    track_max_retries: parseInt($("trackMaxRetries").value),

    cache_cleanup_frequency: $("cacheCleanupFrequency").value,

    demo_music_indexer: $("demoMusicIndexer") ? $("demoMusicIndexer").checked : !!state.settings.demo_music_indexer,
    strict_title_match: $("strictTitleMatch") ? $("strictTitleMatch").checked : !!state.settings.strict_title_match,
    qobuz_token: $("qobuzToken").value.trim(),
    discogs_token: $("discogsToken").value.trim(),
    music_indexers: []
  };
  try {
    await api("/api/settings", { method: "POST", body: JSON.stringify(body) });
    state.settings = body;
    state.tourLocation = null;
    alert("Settings saved");
  } catch (e) { alert("Save failed: " + e.message); }
}

// ---------------------------------------------------------------------------
// Player & Boot
// ---------------------------------------------------------------------------

function isNativeAudioSelected() {
  return typeof _activeSinkId === "string" && _activeSinkId.startsWith("native:") && !!_nativeAudioDeviceUid;
}

function nativeAudioVolume() {
  const audio = $("audioPlayer");
  return audio ? Number(audio.volume || 0) : storedVolume();
}

async function stopNativeAudio() {
  if (state.nativeAudioPollTimer) {
    clearInterval(state.nativeAudioPollTimer);
    state.nativeAudioPollTimer = null;
  }
  if (state.nativeAudio.active) {
    await api("/api/native_audio/stop", { method: "POST", body: "{}" }).catch(() => {});
  }
  state.nativeAudio = { active: false, playing: false, position: 0, duration: 0, path: "", ended: false };
  syncPlayPauseButton();
}

async function startNativeAudio(filePath, track, requestId, position = 0) {
  if (!isNativeAudioSelected()) return false;
  const result = await api("/api/native_audio/play", {
    method: "POST",
    body: JSON.stringify({
      path: filePath,
      device_uid: _nativeAudioDeviceUid,
      volume: nativeAudioVolume(),
      position,
      metadata: track,
    }),
  });
  if (!result.ok) {
    throw new Error(result.error || "Native audio failed");
  }
  state.nativeAudio = {
    active: true,
    playing: !!result.playing,
    position: result.position || 0,
    duration: result.duration || 0,
    path: filePath,
    ended: false,
  };
  updateListeningSessionPosition(state.nativeAudio.position, state.nativeAudio.duration);
  syncPlayPauseButton();
  updateMediaSession(track);
  startNativeAudioPolling(requestId);
  return true;
}

async function fallbackToDefaultOutputAndResume(requestId, position) {
  // The selected app-audio output device (e.g. EDIFIER over Bluetooth) dropped.
  // Hand playback back to the default output ("This computer") and resume from
  // where native left off, instead of leaving the track silently paused.
  if (requestId !== state.playbackRequestId) return;
  const track = state.currentTrack;
  const libraryPath = state.currentLibraryPath;
  await stopNativeAudio();
  _activeSinkId = "";
  _nativeAudioDeviceUid = "";
  const audio = $("audioPlayer");
  if (typeof audio.setSinkId === "function") {
    try { await audio.setSinkId(""); } catch (e) {}
  }
  $("btnConnectDevice").classList.toggle("active", false);
  _refreshConnectPanel().catch(() => {});
  if (libraryPath && track) {
    await playFromLibraryPath(
      libraryPath, track, requestId, state.activeJobId,
      "Output disconnected — playing on this computer", position
    ).catch(() => {});
  } else if (track) {
    setPlayerStatus("Output device disconnected", track);
  }
}

let _deviceChangeListenerAdded = false;
function ensureOutputDisconnectListener() {
  // Event-driven (no polling): the browser fires `devicechange` the moment an
  // audio device connects or disconnects. When routing app audio to a native
  // output device, verify via the backend CoreAudio list whether our device is
  // gone and, if so, fall back to the default output and keep playing.
  if (_deviceChangeListenerAdded) return;
  if (!navigator.mediaDevices || typeof navigator.mediaDevices.addEventListener !== "function") return;
  _deviceChangeListenerAdded = true;
  navigator.mediaDevices.addEventListener("devicechange", async () => {
    if (!state.nativeAudio.active || !_nativeAudioDeviceUid) return;
    const devs = await api("/api/audio/devices").catch(() => null);
    if (devs && Array.isArray(devs.devices) &&
        !devs.devices.some(d => d.uid === _nativeAudioDeviceUid)) {
      await fallbackToDefaultOutputAndResume(state.playbackRequestId, state.nativeAudio.position || 0);
    }
  });
}

function startNativeAudioPolling(requestId) {
  if (state.nativeAudioPollTimer) clearInterval(state.nativeAudioPollTimer);
  ensureOutputDisconnectListener();
  state.nativeAudioPollTimer = setInterval(async () => {
    if (requestId !== state.playbackRequestId || !state.nativeAudio.active) {
      clearInterval(state.nativeAudioPollTimer);
      state.nativeAudioPollTimer = null;
      return;
    }
    const status = await api("/api/native_audio/status").catch(() => null);
    if (!status) return;
    state.nativeAudio = {
      ...state.nativeAudio,
      playing: !!status.playing,
      position: status.position || 0,
      duration: status.duration || 0,
      ended: !!status.ended,
    };
    updateListeningSessionPosition(state.nativeAudio.position, state.nativeAudio.duration);
    syncNativeAudioUi();
    // Prefetch the next track once playback is underway. The <audio> element's
    // ontimeupdate never fires on the native path, so trigger it here too.
    if (state.nativeAudio.position >= 2 && state.prefetchedForRequestId !== state.playbackRequestId) {
      state.prefetchedForRequestId = state.playbackRequestId;
      prefetchNextTracks().catch(() => {});
    }
    if (status.ended && !state.manualPauseRequested) {
      await finalizeListeningSession("complete", "native_audio_ended").catch(() => {});
      await stopNativeAudio();
      clearMediaSession();
      playQueueOffset(1);
    }
  }, 500);
}

function syncNativeAudioUi() {
  if (!state.nativeAudio.active) return;
  const duration = state.nativeAudio.duration || 0;
  const position = state.nativeAudio.position || 0;
  if (duration > 0) {
    $("seekBar").value = (position / duration) * 1000;
    $("currentTime").textContent = formatTime(position);
    $("durationTime").textContent = formatTime(duration);
    $("seekBar").style.backgroundSize = `${(position / duration) * 100}% 100%`;
  }
  syncPlayPauseButton();
  if (state.currentTrack) updateMediaSession(state.currentTrack);
}

async function toggleNativeAudioPlayback() {
  if (!state.nativeAudio.active) return;

  // If it already ended, advance to the next track regardless of pause intent.
  if (state.nativeAudio.ended) {
      playQueueOffset(1);
    return;
  }

  // Decide pause vs resume from the user's explicit pause intent, not from the
  // poll-updated nativeAudio.playing flag. The poll can briefly report
  // playing=false (NSSound isPlaying quirk / status lag); trusting it would
  // misroute a pause click into the resume branch and restart the track from 0.
  if (!state.manualPauseRequested) {
    state.manualPauseRequested = true;
    state.autoplayWanted = false;
    const status = await api("/api/native_audio/pause", { method: "POST", body: "{}" });
    state.nativeAudio.playing = !!status.playing;
    // If it's still playing after a pause request, it might be out of sync
    if (state.nativeAudio.playing) {
        console.warn("[NativeAudio] Pause request did not stop playback, forcing state update");
        const forced = await api("/api/native_audio/status").catch(() => null);
        if (forced) state.nativeAudio.playing = !!forced.playing;
    }
    _callNowPlaying("set_playback_state", 2);
  } else {
    if (!state.currentLibraryPath) {
        console.log("[Player] Native audio has no path to resume, doing nothing.");
        return;
    }
    state.manualPauseRequested = false;
    const status = await api("/api/native_audio/resume", { method: "POST", body: "{}" });
    if (!status.ok) {
        // If resume failed, maybe it's already playing or needs a hard status check
        const forced = await api("/api/native_audio/status").catch(() => null);
        if (forced && forced.playing) {
            state.nativeAudio.playing = true;
        } else {
            console.warn("[Player] Native resume failed:", status.error);
        }
    } else {
        state.nativeAudio.playing = !!status.playing;
    }
    _callNowPlaying("set_playback_state", 1);
  }
  syncPlayPauseButton();
}

function syncPlayPauseButton() {
  const audio = $("audioPlayer");
  const playPause = $("playPause");
  if (!playPause) return;
  const icon = playPause.querySelector("i");
  if (icon) {
    const paused = state.nativeAudio.active
      ? (state.manualPauseRequested || !state.nativeAudio.playing)
      : audio.paused;
    icon.className = paused ? "bi bi-play-fill" : "bi bi-pause-fill";
  }
}

function syncVolumeBar() {
  const audio = $("audioPlayer");
  const volume = $("volumeBar");
  if (!audio || !volume) return;
  volume.value = audio.volume;
  volume.style.backgroundSize = `${audio.volume * 100}% 100%`;
  const icon = document.querySelector("#muteToggle i");
  if (icon) {
    const v = audio.volume;
    icon.className = v <= 0.0001 ? "bi bi-volume-mute"
                   : v < 0.5 ? "bi bi-volume-down"
                   : "bi bi-volume-up";
  }
}

function setPlayerVolume(v) {
  const audio = $("audioPlayer");
  if (!audio) return;
  audio.volume = Math.max(0, Math.min(1, v));
  localStorage.setItem(STORAGE_KEYS.volume, String(audio.volume));
  persistVolume(audio.volume);
  if (state.nativeAudio.active) {
    api("/api/native_audio/volume", { method: "POST", body: JSON.stringify({ volume: audio.volume }) }).catch(() => {});
  }
  syncVolumeBar();
}

function seekBy(seconds) {
  if (state.nativeAudio.active) {
    const duration = state.nativeAudio.duration || 0;
    const target = Math.max(0, Math.min(duration || 0, (state.nativeAudio.position || 0) + seconds));
    api("/api/native_audio/seek", { method: "POST", body: JSON.stringify({ position: target }) }).catch(() => {});
    state.nativeAudio.position = target;
    syncNativeAudioUi();
    return;
  }
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
  if (state.nativeAudio.active) {
    api("/api/native_audio/volume", { method: "POST", body: JSON.stringify({ volume: audio.volume }) }).catch(() => {});
  }
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
      if (state.nativeAudio.active) {
        toggleNativeAudioPlayback().catch(() => {});
        return;
      }
      if (isNativeAudioSelected() && state.currentLibraryPath && state.currentTrack && $("audioPlayer").paused) {
        state.manualPauseRequested = false;
        startNativeAudio(state.currentLibraryPath, state.currentTrack, state.playbackRequestId, state.nativeAudio.position || 0).catch(() => {});
        return;
      }
      const audio = $("audioPlayer");
      if (!audio.src && !state.currentStreamUrl && !state.currentLibraryPath) return;
      if (audio.paused) {
        resumeBrowserAudioFromStableSource(audio).catch((error) => {
          if (state.currentTrack) setPlayerStatus(error.message || "Playback failed", state.currentTrack);
        });
      } else {
        pauseBrowserAudio(audio);
      }
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
    clearMediaSession();
  });
}

function storedVolume() {
  const fromSettings = state.settings && state.settings.volume !== undefined ? Number(state.settings.volume) : NaN;
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

function _callNowPlaying(fnName, arg) {
  if (!state.nativeAudio.active && fnName !== "clear_now_playing") return;
  
  if (fnName === "set_now_playing") {
    api("/api/now_playing", { method: "POST", body: JSON.stringify(arg) }).catch(() => {});
  } else if (fnName === "set_playback_state") {
    api("/api/now_playing/state", { method: "POST", body: JSON.stringify({ state: arg }) }).catch(() => {});
  } else if (fnName === "clear_now_playing") {
    api("/api/now_playing/clear", { method: "POST" }).catch(() => {});
  }
}

function shouldExposeNowPlaying() {
  return !!state.currentTrack;
}

function clearMediaSession() {
  if ("mediaSession" in navigator) {
    navigator.mediaSession.metadata = null;
    navigator.mediaSession.playbackState = "none";
  }
  _callNowPlaying("clear_now_playing");
}

function updateMediaSession(track) {
  if (!track || !shouldExposeNowPlaying()) {
    clearMediaSession();
    return;
  }
  
  const art = absoluteUrl(track.artwork_url || "");
  const durSec = state.nativeAudio.active && state.nativeAudio.duration > 0
    ? state.nativeAudio.duration
    : ($("audioPlayer") && isFinite($("audioPlayer").duration) && $("audioPlayer").duration > 0)
    ? $("audioPlayer").duration
    : (track.duration_ms ? track.duration_ms / 1000 : 300);
  const position = state.nativeAudio.active
    ? state.nativeAudio.position
    : (($("audioPlayer") && isFinite($("audioPlayer").currentTime)) ? $("audioPlayer").currentTime : 0);

  if (state.nativeAudio.active) {
    // Native audio output: use the Swift helper, clear the browser media session
    if ("mediaSession" in navigator) {
      navigator.mediaSession.metadata = null;
      navigator.mediaSession.playbackState = "none";
    }
    _callNowPlaying("set_now_playing", {
      title: track.title || "Unknown",
      artist: track.artist || "",
      album: track.album || "",
      duration: durSec,
      position,
      artwork_url: art,
    });
  } else {
    // Browser audio output: use the browser media session, clear the Swift helper
    _callNowPlaying("clear_now_playing");
    if ("mediaSession" in navigator) {
      navigator.mediaSession.metadata = new MediaMetadata({
        title: track.title || "Unknown",
        artist: track.artist || "",
        album: track.album || "",
        artwork: art ? [
          { src: art, sizes: "96x96", type: "image/png" },
          { src: art, sizes: "128x128", type: "image/png" },
          { src: art, sizes: "256x256", type: "image/png" },
          { src: art, sizes: "512x512", type: "image/png" },
        ] : []
      });
      navigator.mediaSession.setActionHandler('play', () => $("playPause")?.click());
      navigator.mediaSession.setActionHandler('pause', () => $("playPause")?.click());
      navigator.mediaSession.setActionHandler('previoustrack', () => $("btnPrev")?.click());
      navigator.mediaSession.setActionHandler('nexttrack', () => $("btnNext")?.click());
    }
  }
}

function bindMediaSessionActions() {
  // Intentionally do not register global media-session action handlers.
  // macOS should keep using its own control-center routing so the selected app
  // receives play/pause instead of Mindinguflac claiming the session.
}

function bindPlayer() {
  const audio = $("audioPlayer");
  audio.volume = storedVolume();
  syncVolumeBar();
  $("playPause").onclick = () => {
    if (state.nativeAudio.active) {
      toggleNativeAudioPlayback().catch((error) => {
        if (state.currentTrack) setPlayerStatus(error.message || "Native audio failed", state.currentTrack);
      });
      return;
    }
    // Only hand a click to native-start when the browser isn't already playing.
    // If a switch to native output didn't actually move playback (no cache file
    // yet, or native start failed), the browser keeps playing while
    // isNativeAudioSelected() is true; without this guard every click re-fires
    // startNativeAudio and the pause button can never stop the browser audio.
    if (isNativeAudioSelected() && state.currentLibraryPath && state.currentTrack && audio.paused) {
      state.manualPauseRequested = false;
      startNativeAudio(state.currentLibraryPath, state.currentTrack, state.playbackRequestId, state.nativeAudio.position || 0).catch((error) => {
        if (state.currentTrack) setPlayerStatus(error.message || "Native audio failed", state.currentTrack);
      });
      return;
    }
    if (audio.paused) {
      const icon = $("playPause")?.querySelector("i");
      const buttonShowsPause = !!icon && icon.classList.contains("bi-pause-fill");
      if (buttonShowsPause && (state.autoplayWanted || audio.currentTime > 0)) {
        pauseBrowserAudio(audio);
        return;
      }
      if ((!audio.src || audio.src === window.location.href) && !state.currentLibraryPath) {
          // If a download is actively running, ignore the play button so we don't restart it
          if ($("playerStatusIcon") && $("playerStatusIcon").classList.contains("downloading")) {
              console.log("[Player] Download in progress, ignoring play click.");
              return;
          }
          // If it's already "Opening stream..." or "BUFFERING...", ignore the play click
          const status = $("playerMeta")?.textContent || "";
          if (status.includes("...") || status === "BUFFERING...") {
              console.log("[Player] Already resolving or buffering, ignoring play click.");
              return;
          }
          console.log("[Player] Browser audio has no src and not busy, doing nothing.");
          return;
      }
      console.log("[Player] Manual play requested. Current src:", audio.src);
      resumeBrowserAudioFromStableSource(audio).catch((error) => {
        if (state.currentTrack) setPlayerStatus(error.message || "Playback failed", state.currentTrack);
      });
    } else {
      pauseBrowserAudio(audio);
    }
  };
  audio.onplay = audio.onpause = () => {
    syncPlayPauseButton();
    syncActiveTrackRows();
    api("/api/dock/playing-state", { method: "POST", body: JSON.stringify({ playing: !audio.paused }) }).catch(() => {});
    if (audio.paused) {
      if (state.currentTrack) {
        _callNowPlaying("set_now_playing", { position: audio.currentTime });
        _callNowPlaying("set_playback_state", 2);
      } else {
        _callNowPlaying("clear_now_playing");
      }
    } else if (shouldExposeNowPlaying()) {
      _callNowPlaying("set_playback_state", 1);
      if (state.currentTrack) {
        updateMediaSession(state.currentTrack);
      }
    }
  };
  audio.onended = () => {
    // A user-paused stream must never auto-advance. A growing-file active-job
    // stream can fire "ended" when playback reaches the current download head;
    // if the user paused, that would wrap a length-1 queue back onto the same
    // track and replay it from the start.
    if (state.manualPauseRequested) return;
    finalizeListeningSession("complete", "audio_ended").catch(() => {});
    clearMediaSession();
    const playlistCtx = currentPlaylistContext();
    if (playlistCtx && state.queueIndex >= state.queue.length - 1) {
      continuePlaylistWithRecommendations("audio_ended").then((advanced) => {
        if (advanced && state.queue.length > state.queueIndex + 1) {
          playQueueOffset(1);
        }
      }).catch(() => {});
      return;
    }
    playQueueOffset(1);
  };
  audio.ontimeupdate = () => {
    if (!audio.duration) return;
    updateListeningSessionPosition(audio.currentTime, audio.duration);
    if (state.streamRetryCount) state.streamRetryCount = 0; // playback recovered
    $("seekBar").value = (audio.currentTime / audio.duration) * 1000;
    $("currentTime").textContent = formatTime(audio.currentTime);
    $("durationTime").textContent = formatTime(audio.duration);
    $("seekBar").style.backgroundSize = `${(audio.currentTime / audio.duration) * 100}% 100%`;
    if (audio.currentTime >= 2 && state.prefetchedForRequestId !== state.playbackRequestId) {
      state.prefetchedForRequestId = state.playbackRequestId;
      prefetchNextTracks().catch(() => {});
    }
  };
  audio.onloadedmetadata = () => {
    if (state.currentTrack && shouldExposeNowPlaying()) {
      _callNowPlaying("set_now_playing", {
        duration: audio.duration || 0,
        position: audio.currentTime || 0,
      });
    }
    if (audio.duration) {
      updateListeningSessionPosition(audio.currentTime || 0, audio.duration);
    }
  };
  audio.oncanplay = () => {
    if (state.autoplayWanted && !state.manualPauseRequested && audio.paused) {
      audio.play().catch(() => {});
    }
  };
  audio.onwaiting = () => {
    if (state.currentTrack) {
      setPlayerStatus(state.activeJobPhase === "Searching..." ? "Searching..." : "Buffering...", state.currentTrack);
    }
  };
  audio.onplaying = () => {
    // Do NOT clear manualPauseRequested here. This event also fires on buffer
    // recovery; clearing the user's pause intent would let other auto-play
    // triggers (onended, onerror, the job watcher) resume a track the user
    // deliberately paused. The intent is cleared only by an explicit play /
    // new-track action.
    state.autoplayWanted = false;
    state.activeJobPhase = "";
    if (state.currentTrack) {
        const isCache = isLibraryStreamUrl(state.currentStreamUrl);
        setPlayerStatus(isCache ? "Playing from cache" : "Streaming...", state.currentTrack);
    }
  };
  audio.onerror = () => {
    const error = audio.error;
    // Ignore errors if we don't have a source (common when using native output)
    if (!audio.src || audio.src === window.location.href) return;
    if (state.manualPauseRequested) return;

    if (state.currentLibraryPath && isActiveJobStreamUrl(state.currentStreamUrl) && state.currentTrack) {
        const resumeAt = Number.isFinite(audio.currentTime) ? audio.currentTime : 0;
        playFromLibraryPath(
          state.currentLibraryPath,
          state.currentTrack,
          state.playbackRequestId,
          state.activeJobId,
          "Playing from cache",
          resumeAt
        ).catch(() => {});
    } else if (error && error.code === 4 && state.currentStreamUrl && state.currentTrack) {
        // Media error 4 on an active-job stream is often just a transient Safari
        // hiccup — but if the job has errored the server returns 409 forever, and
        // retrying the same URL immediately spins into an infinite loop. Cap the
        // retries, back off, and give up cleanly once the source is clearly dead.
        state.streamRetryCount = (state.streamRetryCount || 0) + 1;
        if (state.streamRetryCount > 4) {
            console.warn("[Player] Stream keeps failing (job likely errored); stopping retries.");
            state.streamRetryCount = 0;
            state.autoplayWanted = false;
            setPlayerStatusIcon("error");
            setPlayerStatus("Source unavailable — press play to try another", state.currentTrack);
            return;
        }
        console.log(`[Player] Media error 4 (Safari/Transient). Retry ${state.streamRetryCount}/4...`);
        const pos = audio.currentTime;
        const requestId = state.playbackRequestId;
        setTimeout(() => {
            if (requestId !== state.playbackRequestId || state.manualPauseRequested) return;
            const url = new URL(state.currentStreamUrl, window.location.origin);
            url.searchParams.set("t", Date.now()); // Bust cache on retry
            audio.src = url.toString();
            audio.load();
            audio.currentTime = pos;
            audio.play().catch(() => {});
        }, 800);
    } else if (error && state.currentTrack) {
        console.error("[Player] Media error:", error.code, error.message);
        // Error codes: 1=ABORTED, 2=NETWORK, 3=DECODE, 4=SRC_NOT_SUPPORTED
        if (error.code === 2 || error.code === 3) {
            console.log("[Player] Fatal media error, attempting to re-resolve track...");
            selectMusicItem(state.currentTrack, "stream", null, state.queueContext);
        } else {
            setPlayerStatus(`Playback error (${error.code})`, state.currentTrack);
        }
    }
  };
  $("seekBar").oninput = () => {
    if (state.nativeAudio.active) {
      const duration = state.nativeAudio.duration || 0;
      if (duration > 0) {
        const position = ($("seekBar").value / 1000) * duration;
        state.nativeAudio.position = position;
        api("/api/native_audio/seek", { method: "POST", body: JSON.stringify({ position }) }).catch(() => {});
        if (shouldExposeNowPlaying()) {
          _callNowPlaying("set_now_playing", { position });
        }
      }
      return;
    }
    if (audio.duration) {
      audio.currentTime = ($("seekBar").value / 1000) * audio.duration;
      if (shouldExposeNowPlaying()) {
        _callNowPlaying("set_now_playing", { position: audio.currentTime });
      }
    }
  };
  $("volumeBar").oninput = () => {
    const v = Number($("volumeBar").value);
    if (v > 0.0001) state.preMuteVolume = v;
    setPlayerVolume(v);
  };
  $("muteToggle").onclick = () => {
    const cur = Number(audio.volume) || 0;
    if (cur > 0.0001) {
      state.preMuteVolume = cur;
      setPlayerVolume(0);
    } else {
      const restore = state.preMuteVolume > 0.0001 ? state.preMuteVolume : (storedVolume() || 1);
      setPlayerVolume(restore);
    }
  };
  window.addEventListener("focus", () => {
    if (state.currentTrack && !audio.paused) {
      _callNowPlaying("set_playback_state", 1);
      updateMediaSession(state.currentTrack);
    }
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && !audio.paused && state.currentTrack) {
      _callNowPlaying("set_playback_state", 1);
      updateMediaSession(state.currentTrack);
    }
  });
  $("btnNext").onclick = () => playQueueOffset(1);
  $("btnPrev").onclick = () => playQueueOffset(-1);
  const btnShuffle = $("btnShuffle");
  if (btnShuffle) {
    btnShuffle.onclick = () => {
      state.isShuffle = !state.isShuffle;
      btnShuffle.classList.toggle("active", state.isShuffle);

      cancelAllPrefetchJobs("queue order changed");
      
      if (state.queue.length > 0 && state.currentTrack) {
        const current = state.currentTrack;
        if (state.isShuffle) {
          const currentKey = trackKey(current);
          const others = state.originalQueue.filter(t => trackKey(t) !== currentKey);
          state.queue = [current, ...others.sort(() => Math.random() - 0.5)];
          state.queueIndex = 0;
        } else {
          state.queue = [...state.originalQueue];
          state.queueIndex = state.queue.findIndex(t => trackKey(t) === trackKey(current));
        }
        
        if (!$("queuePanel").hidden) {
          refreshQueuePanel();
        }
        updateSidebarNextQueue();

        prefetchNextTracks().catch(() => {});
      }
    };
  }

  const btnRepeat = $("btnRepeat");
  if (btnRepeat) {
    btnRepeat.onclick = () => {
      state.isRepeat = !state.isRepeat;
      btnRepeat.classList.toggle("active", state.isRepeat);
      audio.loop = state.isRepeat;
      
      // If repeat is enabled, we don't need the next track prefetch anymore
      if (state.isRepeat) cancelAllPrefetchJobs("repeat enabled");
      else prefetchNextTracks().catch(() => {});
    };
  }
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
  if (!playlist || !playlist.tracks) return false;
  if (!track) return false;
  return playlist.tracks.some(t => {
    if (track.spotify_id && t.spotify_id) return t.spotify_id === track.spotify_id;
    return t.title && track.title && t.artist && track.artist &&
           t.title.toLowerCase() === track.title.toLowerCase() &&
           t.artist.toLowerCase() === track.artist.toLowerCase();
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
    const origin = inferPlaylistOrigin(pl);
    const originLabel = origin === "album" ? "Album" : "Created";
    const isActive = state.activePlaylistId === pl.id;
    return `
      <div class="sidebar-playlist-item${isActive ? " active" : ""}" data-playlist-id="${pl.id}">
        <div class="sidebar-playlist-art" ${artStyle}>${artIcon}</div>
        <div class="sidebar-playlist-info">
          <div class="sidebar-playlist-name">${esc(pl.name)}</div>
          <div class="sidebar-playlist-count">${pl.tracks.length} song${pl.tracks.length !== 1 ? "s" : ""} · ${esc(originLabel)}</div>
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
  document.querySelectorAll(".sidebar-playlist-item").forEach(el => {
    el.classList.toggle("active", el.dataset.playlistId === playlist.id);
  });
  const pl = state.playlists.find(p => p.id === playlist.id) || playlist;
  state.activePlaylistId = pl.id;
  const playlistOrigin = inferPlaylistOrigin(pl);
  const playlistPlaybackContext = {
    kind: "playlist",
    id: pl.id,
    name: pl.name,
    origin: playlistOrigin,
    allow_playlist_continuation: playlistOrigin === "manual",
  };
  _renderPlaylistContent(pl, playlistPlaybackContext);
  if (playlistOrigin === "album") {
    hydrateAlbumPlaylistTracks(pl, playlistPlaybackContext).catch(() => {});
  }
  if (playlistOrigin === "manual") {
    const cached = state.playlistRecommendationState[pl.id]?.items || [];
    if (cached.length >= 10) {
      renderPlaylistRecommendations(pl.id, cached);
    } else {
      loadPlaylistRecommendations(pl, true).catch(() => {});
    }
  }

  // Auto-refresh once if imported from Spotify but metadata not yet fetched
  if (pl.spotify_url && !pl.metadata_fetched) {
    api("/api/playlists/refresh", { method: "POST", body: JSON.stringify({ id: pl.id }) })
      .then(updated => {
        const idx = state.playlists.findIndex(p => p.id === pl.id);
        if (idx !== -1) state.playlists[idx] = updated;
        renderSidebarPlaylists();
        const updatedOrigin = inferPlaylistOrigin(updated);
        _renderPlaylistContent(updated, {
          kind: "playlist",
          id: updated.id,
          name: updated.name,
          origin: updatedOrigin,
          allow_playlist_continuation: updatedOrigin === "manual",
        });
        if (updatedOrigin === "album") {
          hydrateAlbumPlaylistTracks(updated, {
            kind: "playlist",
            id: updated.id,
            name: updated.name,
            origin: updatedOrigin,
            allow_playlist_continuation: false,
          }).catch(() => {});
        }
        if (updatedOrigin === "manual") {
          const cached = state.playlistRecommendationState[updated.id]?.items || [];
          if (cached.length >= 10) renderPlaylistRecommendations(updated.id, cached);
          else loadPlaylistRecommendations(updated, true).catch(() => {});
        }
        state.activePlaylistId = updated.id;
        renderSidebarPlaylists();
      }).catch(() => {});
  }
}

function _renderPlaylistContent(pl, playlistPlaybackContext = null) {
  const heroArt = pl.artwork_url || (pl.tracks[0] || {}).artwork_url || "";
  const artStyle = heroArt ? `background-image: url('${heroArt}')` : "";
  const artIcon = artStyle ? "" : `<i class="bi bi-music-note-list"></i>`;
  const duration = formatDuration(pl.tracks);
  const playlistOrigin = String(pl.playlist_origin || "").trim().toLowerCase();
  const isAlbumPlaylist = playlistOrigin === "album";
  const primaryTrack = (pl.tracks || []).find(track => track && (track.artist || track.album)) || (pl.tracks || [])[0] || {};
  const heroArtist = primaryTrack.artist || pl.owner || "";
  const heroYear = primaryTrack.year || "";
  const heroTrackCount = pl.tracks.length;
  const heroMeta = [];
  if (isAlbumPlaylist) {
    if (heroArtist) heroMeta.push(heroArtist);
    if (heroYear) heroMeta.push(heroYear);
    heroMeta.push(`${heroTrackCount} track${heroTrackCount !== 1 ? "s" : ""}`);
    if (duration) heroMeta.push(duration);
  } else {
    if (pl.owner) heroMeta.push(esc(pl.owner));
    if (pl.followers) heroMeta.push(`${pl.followers.toLocaleString()} saves`);
    heroMeta.push(`${pl.tracks.length} song${pl.tracks.length !== 1 ? "s" : ""}${duration ? ", " + duration : ""}`);
  }

  $("pageContent").innerHTML = `
    <div class="scroll-area">
      <div class="playlist-hero">
        <div class="playlist-hero-art" style="${artStyle}">${artIcon}</div>
        <div class="playlist-hero-info">
          <span class="eyebrow">${isAlbumPlaylist ? "Album" : "Playlist"}</span>
          <h1>${esc(pl.name)}</h1>
          ${isAlbumPlaylist ? `
            <div class="hero-meta-row">
              <button class="hero-artist-link" id="playlistHeroArtistLink" title="${esc(heroArtist)}">
                ${primaryTrack.artwork_url ? `<div class="mini-art" style="background-image: url('${esc(primaryTrack.artwork_url)}')"></div>` : ""}
                ${esc(heroArtist)}
              </button>
              ${heroYear ? `<span class="dot">•</span><span>${esc(heroYear)}</span>` : ""}
              <span class="dot">•</span><span>${heroTrackCount} tracks</span>
              ${duration ? `<span class="dot">•</span><span>${esc(duration)}</span>` : ""}
            </div>
          ` : `
            ${pl.description ? `<div class="playlist-hero-desc">${esc(pl.description)}</div>` : ""}
            <div class="playlist-hero-meta">${heroMeta.join(" · ")}</div>
          `}
        </div>
      </div>

      <div class="track-list-header" style="margin-top: 24px">
        <div>#</div>
        <div>Title</div>
        ${isAlbumPlaylist ? `<div>Plays</div><div></div><div><i class="bi bi-clock"></i></div><div></div>` : `<div></div><div>Album</div><div><i class="bi bi-clock"></i></div><div></div>`}
      </div>

      <div id="playlistTrackList" class="track-list"></div>

      <div class="playlist-recommendations-head" ${isAlbumPlaylist ? 'style="display:none"' : ""}>
        <div>
          <h2>Recommended</h2>
          <p>Based on this playlist and your listening taste</p>
        </div>
      </div>
      <div id="playlistRecommendations" class="playlist-recommendations" ${isAlbumPlaylist ? 'style="display:none"' : ""}></div>
    </div>
  `;

  if (pl.tracks.length) {
    renderTrackList(
      "playlistTrackList",
      pl.tracks,
      isAlbumPlaylist ? "album" : "general",
      playlistPlaybackContext || { kind: "playlist", id: pl.id, name: pl.name, allow_playlist_continuation: false }
    );
  } else {
    $("playlistTrackList").innerHTML = `<div style="padding: 24px; color: var(--muted); text-align: center;">No songs yet — click the status icon while a track is playing to add it.</div>`;
  }
  if (isAlbumPlaylist && heroArtist) {
    const artistBtn = $("playlistHeroArtistLink");
    if (artistBtn) {
      artistBtn.onclick = () => pushPage(() => renderArtistPage(artistTarget({
        name: heroArtist,
        artist: heroArtist,
        artist_id: primaryTrack.artist_id || primaryTrack.spotify_artist_id || "",
        spotify_id: primaryTrack.artist_id || primaryTrack.spotify_artist_id || "",
        artwork_url: primaryTrack.artwork_url || "",
      })));
    }
  }
}

function playlistTrackKeys(playlist = {}) {
  return new Set((playlist.tracks || []).map(trackKey).filter(Boolean));
}

function queueTrackKeys() {
  return new Set((state.queue || []).map(trackKey).filter(Boolean));
}

function inferPlaylistOrigin(pl = {}) {
  const origin = String(pl.playlist_origin || "").trim().toLowerCase();
  return origin === "album" ? "album" : "manual";
}

function trackPlaysValue(item) {
  const direct = Number(item?.plays);
  if (Number.isFinite(direct) && direct > 0) return direct;
  const popularity = Number(item?.spotify_popularity || item?.popularity || 0);
  if (Number.isFinite(popularity) && popularity > 0) return popularity * 10000;
  return null;
}

function mergeAlbumPlaylistTrack(base, hydrated, albumTitle = "") {
  const plays = trackPlaysValue(hydrated) ?? trackPlaysValue(base);
  return {
    ...base,
    ...hydrated,
    album: hydrated?.album || base?.album || albumTitle,
    artist: hydrated?.artist || base?.artist || "",
    title: hydrated?.title || base?.title || "",
    plays: plays || base?.plays || 0,
  };
}

async function hydrateAlbumPlaylistTracks(playlist, playbackContext = null) {
  if (!playlist || inferPlaylistOrigin(playlist) !== "album") return playlist;
  const tracks = Array.isArray(playlist.tracks) ? playlist.tracks : [];
  const seed = tracks.find(track => track && (track.artist || track.album || track.title || track.spotify_id || track.musicbrainz_release_id)) || {};
  const artistName = seed.artist || playlist.owner || "";
  const albumTitle = seed.album || playlist.name || "";
  const releaseId = seed.musicbrainz_release_id || "";
  const spotifyId = seed.spotify_id || "";
  if (!artistName || !albumTitle) return playlist;

  try {
    const params = new URLSearchParams({
      artist: artistName,
      album: albumTitle,
      release_id: releaseId,
      spotify_id: spotifyId,
    });
    const data = await api(`/api/music/album_tracks?${params.toString()}`);
    const hydratedTracks = Array.isArray(data.tracks) ? data.tracks : [];
    if (!hydratedTracks.length) return playlist;

    const mergedTracks = tracks.map(track => {
      const key = trackKey(track);
      const hydrated = hydratedTracks.find(candidate => {
        if (!candidate) return false;
        if (key && trackKey(candidate) === key) return true;
        return (
          String(candidate.title || "").trim().toLowerCase() === String(track.title || "").trim().toLowerCase() &&
          String(candidate.artist || "").trim().toLowerCase() === String(track.artist || "").trim().toLowerCase()
        );
      });
      return hydrated ? mergeAlbumPlaylistTrack(track, hydrated, data.album || albumTitle) : track;
    });

    const updated = {
      ...playlist,
      tracks: mergedTracks,
      artwork_url: data.artwork_url || playlist.artwork_url || "",
      owner: data.artist || playlist.owner || "",
      metadata_fetched: true,
    };

    const idx = state.playlists.findIndex(entry => entry.id === playlist.id);
    if (idx !== -1) state.playlists[idx] = updated;
    renderSidebarPlaylists();
    if (state.activePlaylistId === playlist.id) {
      _renderPlaylistContent(updated, playbackContext || {
        kind: "playlist",
        id: updated.id,
        name: updated.name,
        origin: "album",
        allow_playlist_continuation: false,
      });
    }
    return updated;
  } catch (error) {
    console.warn("Failed to hydrate album playlist tracks", error);
    return playlist;
  }
}

function currentPlaylistContext() {
  return state.queueContext && state.queueContext.kind === "playlist" ? state.queueContext : null;
}

function playlistAllowsContinuation(ctx = null) {
  const context = ctx || currentPlaylistContext();
  if (!context) return false;
  if (context.allow_playlist_continuation === true) return true;
  if (context.allow_playlist_continuation === false) return false;
  return false;
}

function appendTracksToPlaybackQueue(tracks = [], playlistId = "") {
  if (!Array.isArray(tracks) || !tracks.length) return 0;
  const seen = new Set([...(state.queue || []).map(trackKey).filter(Boolean)]);
  let added = 0;
  for (const raw of tracks) {
    const item = { ...raw };
    const key = trackKey(item);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    state.queue.push(item);
    state.originalQueue.push(item);
    added++;
  }
  if (playlistId && state.playlistRecommendationState[playlistId]) {
    const current = state.playlistRecommendationState[playlistId];
    current.items = current.items || [];
    current.itemsByKey = current.itemsByKey || {};
  }
  return added;
}

async function continuePlaylistWithRecommendations(reason = "queue_end") {
  const ctx = currentPlaylistContext();
  if (!ctx || !ctx.id || !playlistAllowsContinuation(ctx) || state.playlistContinuationLoads.has(ctx.id)) return false;
  const playlist = state.playlists.find(p => p.id === ctx.id) || { id: ctx.id, tracks: [] };
  const playlistKeys = [...playlistTrackKeys(playlist)];
  const queueKeys = [...queueTrackKeys()];
  const currentState = state.playlistRecommendationState[ctx.id] || { items: [], itemsByKey: {} };
  const exclude = new Set([...playlistKeys, ...queueKeys, ...Object.keys(currentState.itemsByKey || {})]);
  state.playlistContinuationLoads.add(ctx.id);
  try {
    const previousSession = state.playlistRecommendationSessions[ctx.id] || "";
    const params = new URLSearchParams({
      limit: "10",
      refresh: "0",
      exclude: [...exclude].join(","),
      queue_track_keys: queueKeys.join(","),
    });
    if (previousSession) params.set("session_id", previousSession);
    const data = await api(`/api/playlists/${encodeURIComponent(ctx.id)}/recommendations?${params.toString()}`);
    if (data.session_id) state.playlistRecommendationSessions[ctx.id] = data.session_id;
    const items = Array.isArray(data.items) ? data.items : [];
    if (!items.length) return false;
    const added = appendTracksToPlaybackQueue(items.map(item => ({ ...item, kind: "track", source: "playlist_recommendation" })), ctx.id);
    currentState.items = [...(currentState.items || []), ...items];
    currentState.itemsByKey = Object.fromEntries((currentState.items || []).map(item => [item.track_key, item]));
    state.playlistRecommendationState[ctx.id] = currentState;
    if (state.activePlaylistId === ctx.id) {
      renderPlaylistRecommendations(ctx.id, currentState.items);
    }
    if (added > 0) {
      updateSidebarNextQueue();
      if (!$("queuePanel").hidden) refreshQueuePanel();
    }
    return added > 0;
  } finally {
    state.playlistContinuationLoads.delete(ctx.id);
  }
}

function renderPlaylistRecommendationsLoading() {
  return `
    <div class="playlist-recommendation-loading">
      <div class="spinner"></div>
      <span>Finding recommendations…</span>
    </div>
  `;
}

function sortPlaylistRecommendationItems(items = []) {
  return [...items].sort((a, b) => {
    const byPlays = Number(b?.plays || 0) - Number(a?.plays || 0);
    if (byPlays) return byPlays;
    const byScore = Number(b?.score || 0) - Number(a?.score || 0);
    if (byScore) return byScore;
    return String(a?.title || "").localeCompare(String(b?.title || ""));
  });
}

function renderPlaylistRecommendations(playlistId, items = []) {
  const box = $("playlistRecommendations");
  if (!box) return;
  if (!items.length) {
    box.innerHTML = `<div class="playlist-recommendation-empty">No recommendations right now.</div>`;
    return;
  }
  box.innerHTML = items.map((item, idx) => {
    const artAttr = item.artwork_url ? ` data-art="${esc(item.artwork_url)}"` : "";
    const duration = item.duration_ms ? formatTime(Math.floor(Number(item.duration_ms) / 1000)) : "";
    return `
      <div class="track-row recommendation-track-row" data-item-idx="${idx}" data-item-data='${JSON.stringify(item).replace(/'/g, "&apos;")}'>
        <div class="track-art"${artAttr}></div>
        <div class="track-main">
          <strong>${esc(item.title || "Unknown Track")}</strong>
          <span>${esc(item.artist || "")}</span>
        </div>
        <div class="track-center"></div>
        <div class="track-extra">${item.album ? albumLinkHtml(item, item.album, "album-link") : ""}</div>
        <div class="track-time">${esc(duration)}</div>
        <div class="track-status-icon">
          <button class="track-library-btn recommendation-add" type="button" title="Add to playlist" aria-label="Add to playlist" data-rec-add="${idx}">
            <i class="bi bi-plus-circle"></i>
          </button>
        </div>
      </div>
    `;
  }).join("");
  box.querySelectorAll(".track-art[data-art]").forEach(artEl => {
    const img = new Image();
    img.onload = () => { artEl.style.backgroundImage = `url('${artEl.dataset.art}')`; };
    img.src = artEl.dataset.art;
  });
  box.querySelectorAll(".track-row").forEach(el => {
    const item = items[Number(el.dataset.itemIdx)];
    el.onclick = (event) => {
      if (event.target.closest("[data-rec-add]")) return;
      selectMusicItem(item, "stream", null, { kind: "playlist", id: playlistId, name: "Recommended", allow_playlist_continuation: false });
    };
    if (playableQueueItem(item)) {
      el.oncontextmenu = (event) => {
        event.preventDefault();
        if (typeof showTrackContextMenu === "function") {
          showTrackContextMenu(event, item);
        }
      };
    }
  });
  box.querySelectorAll("[data-rec-add]").forEach((button) => {
    const item = items[Number(button.dataset.recAdd)];
    button.onclick = (event) => {
      event.preventDefault();
      event.stopPropagation();
      addPlaylistRecommendation(playlistId, item, button).catch((error) => {
        alert(error.message || "Failed to add recommendation");
      });
    };
  });
}

async function loadPlaylistRecommendations(playlist, refresh = false) {
  if (!playlist || !playlist.id) return;
  const box = $("playlistRecommendations");
  if (!box) return;
  box.innerHTML = renderPlaylistRecommendationsLoading();
  const previousState = state.playlistRecommendationState[playlist.id] || { items: [], itemsByKey: {} };
  const playlistKeys = [...playlistTrackKeys(playlist)];
  const queueKeys = [...queueTrackKeys()];
  const merged = new Map();
  const seedItems = Array.isArray(previousState.items) ? previousState.items : [];
  seedItems.forEach(item => {
    if (item && item.track_key && !merged.has(item.track_key)) merged.set(item.track_key, item);
  });

  let sessionId = state.playlistRecommendationSessions[playlist.id] || "";
  let firstRequest = true;
  let attempts = 0;
  let grew = true;

  try {
    while (merged.size < 10 && grew && attempts < 6) {
      attempts++;
      const exclude = new Set([...playlistKeys, ...queueKeys, ...merged.keys()]);
      const params = new URLSearchParams({
        limit: "10",
        refresh: firstRequest && refresh ? "1" : "0",
        exclude: [...exclude].join(","),
        queue_track_keys: queueKeys.join(","),
      });
      if (sessionId) params.set("session_id", sessionId);
      const data = await api(`/api/playlists/${encodeURIComponent(playlist.id)}/recommendations?${params.toString()}`);
      sessionId = data.session_id || sessionId || "";
      state.playlistRecommendationSessions[playlist.id] = sessionId;
      const freshItems = Array.isArray(data.items) ? data.items : [];
      const sizeBefore = merged.size;
      freshItems.forEach(item => {
        if (item && item.track_key && !merged.has(item.track_key)) {
          merged.set(item.track_key, item);
        }
      });
      const items = sortPlaylistRecommendationItems([...merged.values()]).slice(0, 10);
      const itemsByKey = {};
      items.forEach(item => { if (item && item.track_key) itemsByKey[item.track_key] = item; });
      state.playlistRecommendationState[playlist.id] = { items, itemsByKey };
      renderPlaylistRecommendations(playlist.id, items);
      grew = merged.size > sizeBefore;
      firstRequest = false;
      if (!freshItems.length) break;
    }
  } catch (err) {
    if ($("playlistRecommendations")) {
      if (merged.size > 0) {
        // Partial results already rendered — leave them
      } else {
        $("playlistRecommendations").innerHTML = `<div class="playlist-recommendation-empty">Couldn't load recommendations right now.</div>`;
      }
    }
    return;
  }

  if (merged.size === 0) {
    state.playlistRecommendationState[playlist.id] = { items: [], itemsByKey: {} };
    renderPlaylistRecommendations(playlist.id, []);
  }
}

async function addPlaylistRecommendation(playlistId, item, button) {
  const playlist = state.playlists.find(p => p.id === playlistId);
  if (!playlist) throw new Error("Playlist not found");
  if (!item) throw new Error("Recommendation not found");
  const recState = state.playlistRecommendationState[playlistId] || { items: [] };
  const row = button.closest(".track-row");
  const parent = row?.parentElement || null;
  const nextSibling = row?.nextElementSibling || null;
  const snapshot = row ? row.cloneNode(true) : null;
  const sessionId = state.playlistRecommendationSessions[playlistId] || "";
  const allPlaylistKeys = new Set([...playlistTrackKeys(playlist), ...queueTrackKeys(), ...Object.keys(recState.itemsByKey || {})]);
  const excludeTrackKeys = [...allPlaylistKeys];
  if (row) row.remove();
  button.disabled = true;
  try {
    const added = await api(`/api/playlists/${encodeURIComponent(playlistId)}/tracks`, {
      method: "POST",
      body: JSON.stringify({
        playlist_id: playlistId,
        track_key: item.track_key,
        title: item.title,
        artist: item.artist,
        album: item.album,
        artwork_url: item.artwork_url,
        duration_ms: item.duration_ms || 0,
        metadata: item.metadata || {},
        source: "recommendation",
        session_id: sessionId,
      }),
    });
    const idx = state.playlists.findIndex(p => p.id === playlistId);
    if (idx !== -1 && added.track && !playlist.tracks.some(t => trackKey(t) === trackKey(added.track))) {
      state.playlists[idx].tracks.push(added.track);
      const trackList = $("playlistTrackList");
      if (trackList) renderTrackList("playlistTrackList", state.playlists[idx].tracks, "general", { kind: "playlist", id: playlistId, name: playlist.name });
      renderSidebarPlaylists();
    }
    const replacement = await api(`/api/playlists/${encodeURIComponent(playlistId)}/recommendations/replacement`, {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        exclude_track_keys: excludeTrackKeys,
        queue_track_keys: [...queueTrackKeys()],
      }),
    });
    const current = state.playlistRecommendationState[playlistId] || { items: [], itemsByKey: {} };
    current.items = (current.items || []).filter(entry => entry.track_key !== item.track_key);
    if (replacement && replacement.item) {
      current.items.push(replacement.item);
    }
    current.items.sort((a, b) => {
      const byPlays = Number(b?.plays || 0) - Number(a?.plays || 0);
      if (byPlays) return byPlays;
      const byScore = Number(b?.score || 0) - Number(a?.score || 0);
      if (byScore) return byScore;
      return String(a?.title || "").localeCompare(String(b?.title || ""));
    });
    if (current.items.length < 10) {
      const refilled = await api(`/api/playlists/${encodeURIComponent(playlistId)}/recommendations?${new URLSearchParams({
        limit: "10",
        refresh: "1",
        exclude: [...new Set([...playlistTrackKeys(playlist), ...queueTrackKeys(), ...current.items.map(entry => entry.track_key)])].join(","),
        queue_track_keys: [...queueTrackKeys()].join(","),
      }).toString()}`);
      const merged = new Map();
      [...(current.items || []), ...((refilled && refilled.items) || [])].forEach(entry => {
        if (entry && entry.track_key && !merged.has(entry.track_key)) merged.set(entry.track_key, entry);
      });
      current.items = sortPlaylistRecommendationItems([...merged.values()]).slice(0, 10);
    }
    current.itemsByKey = Object.fromEntries((current.items || []).map(entry => [entry.track_key, entry]));
    state.playlistRecommendationState[playlistId] = current;
    renderPlaylistRecommendations(playlistId, current.items);
  } catch (error) {
    if (snapshot && parent) parent.insertBefore(snapshot, nextSibling);
    button.disabled = false;
    throw error;
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
                return !(t.title && track.title && t.artist && track.artist &&
                         t.title.toLowerCase() === track.title.toLowerCase() && 
                         t.artist.toLowerCase() === track.artist.toLowerCase());
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
        body: JSON.stringify({ name, spotify_url: spotifyUrl, origin: "manual" }),
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

  $("playerStatusIcon").addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    // Green check (ready) -> add the current track to a playlist.
    // Pie (downloading) or error -> show the progress log.
    const icon = $("playerStatusIcon");
    if (icon.classList.contains("ready")) {
      if (state.progressLogOpen) hideProgressLogPopover();
      if (state.currentTrack) openPlaylistPicker(state.currentTrack);
      return;
    }
    toggleProgressLogPopover();
  });

  document.addEventListener("click", (event) => {
    if (!state.progressLogOpen) return;
    const icon = $("playerStatusIcon");
    const tippyBox = document.querySelector(".tippy-box[data-theme~='mindingu-progress']");
    if (icon?.contains(event.target) || tippyBox?.contains(event.target)) return;
    hideProgressLogPopover();
  });

  window.addEventListener("resize", () => {
    if (state.progressLogOpen) {
      positionProgressLogPopover();
    }
  });
}

async function restorePlaybackState() {
  try {
    const status = await api("/api/native_audio/status");
    if (status && status.metadata && status.path) {
      const track = status.metadata;
      state.currentTrack = track;
      startListeningSession(track);
      state.playbackRequestId++;
      state.nativeAudio = {
        active: true,
        playing: !!status.playing,
        position: status.position || 0,
        duration: status.duration || 0,
        path: status.path,
        ended: !!status.ended,
      };
      updateListeningSessionPosition(state.nativeAudio.position, state.nativeAudio.duration);
      
      // If playing, start polling
      if (status.playing) {
        startNativeAudioPolling(state.playbackRequestId);
      }
      
      syncNativeAudioUi();
      renderNowPlaying();
      updateMediaSession(track);
      
      console.log("[Boot] Restored playback state for:", track.title);
    }
  } catch (e) {
    console.warn("[Boot] Failed to restore playback state:", e);
  }
}

async function boot() {
  state.dockRecentItems = storedDockRecentItems();
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

  document.querySelectorAll("[data-library-pill]").forEach(el => {
    el.onclick = () => {
       const pill = normalizeLibraryPill(el.dataset.libraryPill);
       setActiveLibraryPill(pill);
       if (pill === "home") replacePage(renderHomePage);
       else if (pill === "stats") replacePage(() => renderStatsPage(state.statsPeriod || "month"));
       else if (pill === "tracks") pushPage(renderPersonalTracksPage);
       else if (pill === "artists") pushPage(renderArtistsPage);
       else if (pill === "albums") pushPage(renderAlbumsPage);
    };
  });

  (function _bindPillScrollArrows() {
    const row = $("libraryPillRow");
    if (!row) return;
    const wrap = row.closest(".library-pill-scroll-wrap");
    if (!wrap) return;
    const prev = wrap.querySelector(".pill-scroll-prev");
    const next = wrap.querySelector(".pill-scroll-next");
    if (!prev || !next) return;
    const SCROLL_BY = 160;
    const _update = () => {
      const canScrollLeft = row.scrollLeft > 2;
      const canScrollRight = row.scrollWidth - row.clientWidth - row.scrollLeft > 2;
      prev.classList.toggle("can-scroll", canScrollLeft);
      next.classList.toggle("can-scroll", canScrollRight);
    };
    row.addEventListener("scroll", _update, { passive: true });
    window.addEventListener("resize", _update, { passive: true });
    prev.onclick = () => { row.scrollBy({ left: -SCROLL_BY, behavior: "smooth" }); };
    next.onclick = () => { row.scrollBy({ left: SCROLL_BY, behavior: "smooth" }); };
    requestAnimationFrame(() => requestAnimationFrame(_update));
  })();

  document.querySelectorAll("[data-view-jump]").forEach(el => {
    el.onclick = () => {
       if (el.dataset.viewJump === "settings") pushPage(renderSettings);
    };
  });
  $("settingsForm").onsubmit = saveSettings;
  $("backButton").onclick = popPage;
  $("forwardButton").onclick = forwardPage;
  $("clearCache").onclick = async () => { await api("/api/cache", { method: "DELETE" }); renderSettings(); };

  await Promise.all([loadCatalog(), loadPlaylists()]);
  seedDockRecentTracks();
  
  // Try to restore playback state before showing home page
  await restorePlaybackState();
  
  replacePage(renderHomePage);
}

boot().catch(console.error);

// Global keyboard shortcuts
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    const openModals = document.querySelectorAll("dialog[open]");
    if (openModals.length > 0) {
      event.preventDefault();
      openModals.forEach(modal => modal.close());
    }
  }
});

// ---------------------------------------------------------------------------
// Connect to device (audio output routing via AudioContext.setSinkId)
// ---------------------------------------------------------------------------

let _audioCtx = null;
let _audioSrcNode = null;
let _activeSinkId = "";  // "" = default (this computer)
let _nativeAudioDeviceUid = "";
let _nativeAudioAvailable = false;

function _ensureAudioContext() {
  if (_audioCtx) return _audioCtx;
  _audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  const audio = $("audioPlayer");
  _audioSrcNode = _audioCtx.createMediaElementSource(audio);
  _audioSrcNode.connect(_audioCtx.destination);
  return _audioCtx;
}

async function setAudioOutputDevice(deviceId) {
  _activeSinkId = deviceId;
  const audio = $("audioPlayer");
  
  if (deviceId && deviceId.startsWith("native:")) {
    _nativeAudioDeviceUid = deviceId.slice("native:".length);
    // When already on native output the browser <audio> element has no src
    // (it was cleared when native took over), so its currentTime is 0/stale.
    // Take the resume position from the native player in that case, otherwise
    // switching outputs would restart the track from the beginning.
    const resumeAt = state.nativeAudio.active
      ? (state.nativeAudio.position || 0)
      : (Number.isFinite(audio.currentTime) ? audio.currentTime : 0);
    const shouldKeepPaused = !!state.manualPauseRequested;
    let nativePath = state.currentLibraryPath || "";

    if (!nativePath && state.currentTrack) {
      const source = await api("/api/playback/source", {
        method: "POST",
        body: JSON.stringify(serviceDownloadPayload(state.currentTrack, "stream")),
      }).catch(() => null);
      if (source && source.path) {
        nativePath = source.path;
        state.currentLibraryPath = source.path;
      }
    }

    if (nativePath && state.currentTrack) {
      try {
        await startNativeAudio(nativePath, state.currentTrack, state.playbackRequestId, resumeAt);
        // Stop browser audio only after native playback successfully starts.
        audio.pause();
        audio.removeAttribute("src");
        audio.load();
        if (shouldKeepPaused) {
          await api("/api/native_audio/pause", { method: "POST", body: "{}" }).catch(() => {});
          state.nativeAudio.playing = false;
        }
      } catch (error) {
        setPlayerStatus(error.message || "Native audio failed", state.currentTrack);
      }
    } else if (state.currentTrack) {
      // No completed/cache file exists yet. Native app-only output cannot play
      // the live active-job URL, so stop default-output browser playback and
      // resume native at the same position once the cache file is ready.
      state.pendingNativeStartAt = audio && Number.isFinite(audio.currentTime) ? audio.currentTime : 0;
      if (audio) {
        audio.pause();
        audio.removeAttribute("src");
        audio.load();
      }
      state.currentPlayableReady = false;
      state.autoplayWanted = false;
      setPlayerStatus("Native output will start when cache is ready", state.currentTrack);
    }
    syncPlayPauseButton();
    return;
  }
  _nativeAudioDeviceUid = "";
  // Capture native playback state before stopping it so we can hand playback
  // back to the browser at the same position when switching off a native device.
  const wasNativeActive = state.nativeAudio.active;
  const nativeResumeAt = state.nativeAudio.position || 0;
  const keepPaused = !!state.manualPauseRequested;
  await stopNativeAudio();

  if (typeof audio.setSinkId === "function") {
    try {
      await audio.setSinkId(deviceId);
    } catch (e) {
      console.warn("audio.setSinkId failed:", e);
    }
  } else {
    const sinkSupported = typeof AudioContext !== "undefined" &&
      typeof AudioContext.prototype.setSinkId === "function";
    if (sinkSupported) {
      try {
        const ctx = _ensureAudioContext();
        if (ctx.state === "suspended") await ctx.resume();
        await ctx.setSinkId(deviceId);
      } catch (e) {
        console.warn("setSinkId failed:", e);
      }
    }
  }

  // Coming off a native device, the <audio> element has no src (native took
  // over). Resume browser playback from the cached file at the same position.
  // playFromLibraryPath streams the existing file — it never redownloads.
  if (wasNativeActive && state.currentLibraryPath && state.currentTrack) {
    await playFromLibraryPath(
      state.currentLibraryPath, state.currentTrack, state.playbackRequestId,
      state.activeJobId, "Playing from cache", nativeResumeAt
    ).catch(() => {});
    if (keepPaused) pauseBrowserAudio(audio);
  }
}

async function _getOutputDevices() {
  if (!navigator.mediaDevices?.enumerateDevices) return [];
  let devices = await navigator.mediaDevices.enumerateDevices();
  let outputs = devices.filter(d => d.kind === "audiooutput");
  
  // CRITICAL: macOS/Browsers hide names like "Edifier" until the user grants permission.
  // We check if the first output has a name; if not, we must ask.
  if (outputs.length && (!outputs[0].label || outputs[0].label === "")) {
    try {
      console.log("[Audio] Hardware labels locked. Requesting temporary permission...");
      const s = await navigator.mediaDevices.getUserMedia({ audio: true });
      s.getTracks().forEach(t => t.stop()); // Stop immediately
      devices = await navigator.mediaDevices.enumerateDevices();
      outputs = devices.filter(d => d.kind === "audiooutput");
    } catch (e) {
      console.warn("[Audio] Permission denied, hardware labels will remain generic.", e);
    }
  }
  return outputs;
}

function _audioLabelsMatch(left, right) {
  const a = (left || "").toLowerCase().trim();
  const b = (right || "").toLowerCase().trim();
  return !!a && !!b && (a === b || a.includes(b) || b.includes(a));
}

async function _selectBrowserAudioOutput(label = "") {
  if (typeof navigator.mediaDevices?.selectAudioOutput !== "function") return null;
  try {
    const selected = await navigator.mediaDevices.selectAudioOutput();
    if (!selected) return null;
    if (label && selected.label && !_audioLabelsMatch(selected.label, label)) {
      console.warn("[Audio] User selected a different output:", selected.label);
    }
    return selected;
  } catch (e) {
    console.warn("[Audio] Output chooser failed:", e);
    return null;
  }
}

function _canChooseBrowserAudioOutput() {
  return typeof navigator.mediaDevices?.selectAudioOutput === "function";
}

function _showBrowserAudioRouteUnavailable(name) {
  const msg = `App-only output routing to ${name} is not available in this browser. Use Chrome/Edge for per-app audio output, or select the device as the Mac output.`;
  console.warn("[Audio]", msg);
  alert(msg);
}

function _deviceIcon(name) {
  const n = (name || "").toLowerCase();
  if (n.includes("airpod") || n.includes("headphone") || n.includes("earphone") || n.includes("headset"))
    return "bi-headphones";
  if (n.includes("bluetooth") || n.includes("bt "))
    return "bi-bluetooth";
  if (n.includes("tv") || n.includes("hdmi"))
    return "bi-tv";
  if (n.includes("speaker"))
    return "bi-speaker";
  return "bi-laptop";
}

let _btScanInterval = null;

async function _renderConnectDevices(backendDevices, btState, nativeAvailable = false) {
  const list = $("connectDeviceList");
  list.innerHTML = "";
  _nativeAudioAvailable = !!nativeAvailable;

  const browserOutputs = await _getOutputDevices();

  // Section: available output devices.
  const items = [];
  // "This computer" is our universal "Default" which handles built-in speakers automatically.
  items.push({ name: "This computer", deviceId: "", icon: "bi-laptop", sub: "Default output" });

  const filterKeywords = ["speaker", "internal speaker", "built-in", "microphone", "input", "driver", "background music", "teams", "zoom"];

  for (const bd of backendDevices) {
    if (bd.uid === "default") continue;
    const lname = bd.name.toLowerCase();
    
    // Strictly hide built-in speakers from the list so they don't duplicate "This computer"
    // except for explicitly allowed external ones.
    if (filterKeywords.some(k => lname.includes(k)) && !lname.includes("airplay") && !lname.includes("edifier")) {
        continue;
    }
    
    // Cross-reference to get browser-internal ID
    const match = browserOutputs.find(b =>
        (b.label && _audioLabelsMatch(b.label, bd.name)) ||
        b.deviceId === bd.uid
    );

    const label = bd.name || "Audio Device";
    const isAirPlay = label.toLowerCase().includes("airplay");
    
    const nativeId = bd.uid ? `native:${bd.uid}` : "";
    items.push({
        name: label,
        deviceId: match ? match.deviceId : (nativeAvailable && nativeId ? nativeId : bd.uid),
        backendUid: bd.uid,
        nativeUid: nativeAvailable && bd.uid ? bd.uid : "",
        needsBrowserRoute: !match && !nativeAvailable,
        icon: isAirPlay ? "bi-broadcast-pin" : _deviceIcon(label),
        sub: isAirPlay ? "AirPlay" : (match && !nativeAvailable ? "" : (nativeAvailable ? "App audio only" : (_canChooseBrowserAudioOutput() ? "Choose output" : "Browser unsupported")))
    });
  }

  // PASS 2: Add any browser-discovered external devices we missed (but apply same filters)
  for (const b of browserOutputs) {
    if (b.deviceId === "default" || !b.label) continue;
    const lname = b.label.toLowerCase();
    
    // Apply strict filtering to browser list too
    if (filterKeywords.some(k => lname.includes(k)) && !lname.includes("airplay") && !lname.includes("edifier")) {
        continue;
    }

    if (!items.find(i => i.deviceId === b.deviceId || (i.name && i.name === b.label))) {
        items.push({ name: b.label, deviceId: b.deviceId, backendUid: "", needsBrowserRoute: false, icon: _deviceIcon(b.label), sub: "" });
    }
  }

  if (_canChooseBrowserAudioOutput() && !items.find(i => i.deviceId === "__choose_output__")) {
    items.push({
      name: "Choose audio output...",
      deviceId: "__choose_output__",
      backendUid: "",
      needsBrowserRoute: false,
      icon: "bi-broadcast-pin",
      sub: "Bluetooth / AirPlay",
    });
  }

  for (const item of items) {
    const li = document.createElement("li");
    li.className = "connect-device-item" + (item.deviceId === _activeSinkId ? " active" : "");
    li.innerHTML = `
      <div class="connect-device-icon"><i class="bi ${item.icon}"></i></div>
      <div class="connect-device-info">
        <span class="connect-device-name">${item.name}</span>
        ${item.sub ? `<span class="connect-device-sub">${item.sub}</span>` : ""}
      </div>
      ${item.deviceId === _activeSinkId ? `<i class="bi bi-check-circle-fill connect-active-check"></i>` : ""}
    `;
    li.onclick = async () => {
      let targetId = item.deviceId;
      if (targetId === "__choose_output__") {
        const selected = await _selectBrowserAudioOutput();
        if (!selected) return;
        await setAudioOutputDevice(selected.deviceId);
        _activeSinkId = selected.deviceId;
        await _refreshConnectPanel();
        return;
      }
      
      // Native bridge takes priority in the desktop app (WebKit setSinkId doesn't work)
      if (item.nativeUid) {
          targetId = `native:${item.nativeUid}`;
      } else {
      // Find the browser internal ID by case-insensitive matching
      const freshDevs = await _getOutputDevices();
      const targetName = item.name.toLowerCase();
      const match = freshDevs.find(d => {
        if (!d.label) return false;
        return _audioLabelsMatch(d.label, targetName);
      });

      if (match) {
          console.log("[Audio] Mapped to:", match.label);
          targetId = match.deviceId;
      } else if (item.needsBrowserRoute || (targetId && (targetId.includes(":") || targetId.length > 40))) {
          console.warn("[Audio] No match for:", item.name);
          const selected = await _selectBrowserAudioOutput(item.name);
          if (selected) {
            targetId = selected.deviceId;
          } else if (item.deviceId !== "") {
            _showBrowserAudioRouteUnavailable(item.name);
            return;
          }
      }
      } // end else (browser path)

      console.log("[Audio] Routing to:", item.name, targetId || "Default");
      await setAudioOutputDevice(targetId);
      await _refreshConnectPanel();
    };
    list.appendChild(li);
  }

  // Section: nearby / unpaired Bluetooth devices.
  // We show paired-but-disconnected devices here, AND connected devices that aren't in the top list.
  const matchedNames = new Set(items.map(i => i.name.toLowerCase()));
  const nearby = (btState?.devices || []).filter(d => !d.connected || !matchedNames.has(d.name.toLowerCase()));

  const scanHeader = document.createElement("li");
  scanHeader.className = "connect-section-header";
  const scanning = btState?.scanning;
  scanHeader.innerHTML = `
    <span>Nearby devices</span>
    <button class="connect-scan-btn" id="btScanBtn" type="button">
      ${scanning
        ? `<i class="bi bi-arrow-clockwise connect-spin"></i> Scanning...`
        : `<i class="bi bi-search"></i> Scan`}
    </button>
  `;
  scanHeader.querySelector("#btScanBtn").onclick = async (e) => {
    e.stopPropagation();
    if (scanning) {
      await api("/api/bluetooth/scan/stop", { method: "POST", body: "{}" });
    } else {
      await api("/api/bluetooth/scan/start", { method: "POST", body: "{}" });
      _startBtPoll();
    }
    await _refreshConnectPanel();
  };
  list.appendChild(scanHeader);

  if (btState?.error) {
    const err = document.createElement("li");
    err.className = "connect-bt-error";
    err.textContent = btState.error;
    list.appendChild(err);
  }

  if (nearby.length === 0) {
    const empty = document.createElement("li");
    empty.className = "connect-bt-empty";
    empty.textContent = scanning ? "Looking for devices..." : "No paired devices - press Scan to find new ones";
    list.appendChild(empty);
  }

  for (const dev of nearby) {
    const li = document.createElement("li");
    li.className = "connect-device-item connect-nearby";
    li.dataset.address = dev.address;
    const subtext = dev.connected ? "Connected" : dev.address;
    const btnText = dev.connected ? "Active" : (dev.paired ? "Connect" : "Pair");
    const btnClass = dev.connected ? "connect-pair-btn connected" : "connect-pair-btn";

    li.innerHTML = `
      <div class="connect-device-icon"><i class="bi ${_deviceIcon(dev.name)}"></i></div>
      <div class="connect-device-info">
        <span class="connect-device-name">${dev.name}</span>
        <span class="connect-device-sub">${subtext}</span>
      </div>
      <button class="${btnClass}" type="button" ${dev.connected ? 'disabled' : ''}>${btnText}</button>
    `;
    li.querySelector(".connect-pair-btn").onclick = async (e) => {
      e.stopPropagation();
      const btn = e.currentTarget;
      btn.textContent = dev.paired ? "Connecting..." : "Pairing...";
      btn.disabled = true;
      try {
        const res = await api("/api/bluetooth/pair", { method: "POST", body: JSON.stringify({ address: dev.address }) });
        if (res.error) { btn.textContent = "Failed"; btn.disabled = false; }
      else { btn.textContent = "Done"; setTimeout(() => _refreshConnectPanel(), 2000); }
      } catch { btn.textContent = "Error"; btn.disabled = false; }
    };
    list.appendChild(li);
  }
}

function _startBtPoll() {
  if (_btScanInterval) return;
  _btScanInterval = setInterval(async () => {
    try {
      const st = await api("/api/bluetooth/state");
      await _refreshConnectPanel(st);
      if (!st.scanning) { clearInterval(_btScanInterval); _btScanInterval = null; }
    } catch { clearInterval(_btScanInterval); _btScanInterval = null; }
  }, 1500);
}

async function _refreshConnectPanel(btState) {
  if ($("connectPanel").hidden) return;
  if (!btState) {
    try { btState = await api("/api/bluetooth/state"); } catch { btState = { scanning: false, devices: [], error: "" }; }
  }
  try {
    const data = await api("/api/audio/devices");
    await _renderConnectDevices(data.devices || [], btState, !!data.native_available);
  } catch { await _renderConnectDevices([], btState, false); }
}

function positionDetailsOverlay() {
  const detailsPanel = document.querySelector(".details-panel");
  if (detailsPanel) {
    const rect = detailsPanel.getBoundingClientRect();
    document.documentElement.style.setProperty("--details-overlay-left", `${rect.left}px`);
    document.documentElement.style.setProperty("--details-overlay-width", `${rect.width}px`);
    detailsPanel.classList.add("details-overlay-open");
  }
}

function releaseDetailsOverlay() {
  if ($("queuePanel")?.hidden && $("connectPanel")?.hidden) {
    document.querySelector(".details-panel")?.classList.remove("details-overlay-open");
    document.documentElement.style.removeProperty("--details-overlay-left");
    document.documentElement.style.removeProperty("--details-overlay-width");
  }
}

async function openConnectPanel() {
  positionDetailsOverlay();
  $("connectPanel").hidden = false;
  $("btnConnectDevice").classList.add("active");
  $("connectPanel").style.zIndex = "1000";
  $("queuePanel").style.zIndex = "900";
  const list = $("connectDeviceList");
  list.innerHTML = `<li style="padding:18px;color:var(--muted);font-size:13px">Loading...</li>`;
  await _refreshConnectPanel();
}

function closeConnectPanel() {
  $("connectPanel").hidden = true;
  releaseDetailsOverlay();
  if (_btScanInterval) { clearInterval(_btScanInterval); _btScanInterval = null; }
  api("/api/bluetooth/scan/stop", { method: "POST", body: "{}" }).catch(() => {});
  $("btnConnectDevice").classList.toggle("active", _activeSinkId !== "");
}

$("btnConnectDevice").onclick = () => {
  if ($("connectPanel").hidden) openConnectPanel();
  else closeConnectPanel();
};
$("connectPanelClose").onclick = closeConnectPanel;

// ---------------------------------------------------------------------------
// Queue Panel UI
// ---------------------------------------------------------------------------
function renderQueueTracks(containerId, tracks, isRecent) {
  const container = $(containerId);
  if (!container) return;
  if (!tracks || !tracks.length) {
    container.innerHTML = `<div style="color:var(--muted); font-size:13px;">No tracks.</div>`;
    return;
  }
  container.innerHTML = tracks.map((track, i) => {
    const art = track.artwork_url ? `background-image: url('${track.artwork_url}');` : "";
    const isActive = isRecent && state.currentTrack && trackKey(track) === trackKey(state.currentTrack);
    const isReorderable = !isRecent && Number.isInteger(track._qIdx) && track._qIdx >= 0;
    return `
      <div class="queue-track-item ${isActive ? "active" : ""} ${isReorderable ? "queue-track-reorderable" : ""}" data-q-index="${i}" data-q-abs-index="${track._qIdx ?? ""}" data-q-recent="${isRecent}" ${isReorderable ? 'draggable="true"' : ""}>
        ${isReorderable ? '<i class="bi bi-grip-vertical queue-drag-handle" aria-hidden="true"></i>' : ""}
        <div class="queue-track-art" style="${art}"></div>
        <div class="queue-track-info">
          <div class="queue-track-title" ${isActive ? 'style="color:var(--accent)"' : ""}>${esc(track.title || track.name)}</div>
          <div class="queue-track-artist">${esc(track.artist)}</div>
        </div>
      </div>
    `;
  }).join("");

  container.querySelectorAll(".queue-track-item").forEach(el => {
    const idx = parseInt(el.dataset.qIndex, 10);
    const track = tracks[idx];
    el.onclick = () => {
      if (el.dataset.qRecent === "true") {
        selectMusicItem(track, "stream", tracks, { title: "Recently Played" });
      } else {
        // Use the absolute stable index stored on the track object
        if (track._qIdx !== undefined && track._qIdx >= 0) {
          state.queueIndex = track._qIdx;
          selectMusicItem(state.queue[state.queueIndex], "stream", null, state.queueContext);
        }
      }
    };
    if (playableQueueItem(track)) {
      el.oncontextmenu = (event) => {
        event.preventDefault();
        if (typeof showTrackContextMenu === "function") {
          const cinfo = el.dataset.qRecent === "true" ? {} : { queueIndex: track._qIdx };
          showTrackContextMenu(event, track, cinfo);
        }
      };
    }
  });
  if (!isRecent) bindQueueReorder(container);
}

function reorderQueueTrack(fromIndex, toIndex) {
  if (!Number.isInteger(fromIndex) || !Number.isInteger(toIndex)) return false;
  if (fromIndex < 0 || toIndex < 0 || fromIndex >= state.queue.length || toIndex >= state.queue.length) return false;
  const currentKey = state.currentTrack ? trackKey(state.currentTrack) : "";
  const moving = state.queue[fromIndex];
  if (currentKey && trackKey(moving) === currentKey) return false;

  const [item] = state.queue.splice(fromIndex, 1);
  let insertIndex = toIndex;
  if (fromIndex < toIndex) insertIndex -= 1;
  insertIndex = Math.max(0, Math.min(state.queue.length, insertIndex));
  state.queue.splice(insertIndex, 0, item);
  state.queueIndex = state.queue.findIndex(track => trackKey(track) === currentKey);
  if (state.queueIndex < 0 && currentKey) state.queueIndex = 0;
  state.originalQueue = [...state.queue];
  prefetchNextTracks();
  refreshQueuePanel();
  updateSidebarNextQueue();
  return true;
}

function bindQueueReorder(container) {
  let draggedIndex = -1;
  const clearDropTargets = () => {
    container.querySelectorAll(".queue-drop-before, .queue-drop-after").forEach(el => {
      el.classList.remove("queue-drop-before", "queue-drop-after");
    });
  };
  container.querySelectorAll(".queue-track-reorderable").forEach(row => {
    row.addEventListener("dragstart", (event) => {
      draggedIndex = parseInt(row.dataset.qAbsIndex || "-1", 10);
      row.classList.add("queue-dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", String(draggedIndex));
    });
    row.addEventListener("dragend", () => {
      row.classList.remove("queue-dragging");
      draggedIndex = -1;
      clearDropTargets();
    });
    row.addEventListener("dragover", (event) => {
      const targetIndex = parseInt(row.dataset.qAbsIndex || "-1", 10);
      if (draggedIndex < 0 || targetIndex < 0 || draggedIndex === targetIndex) return;
      event.preventDefault();
      clearDropTargets();
      const rect = row.getBoundingClientRect();
      const after = event.clientY > rect.top + rect.height / 2;
      row.classList.add(after ? "queue-drop-after" : "queue-drop-before");
      event.dataTransfer.dropEffect = "move";
    });
    row.addEventListener("drop", (event) => {
      event.preventDefault();
      const targetIndex = parseInt(row.dataset.qAbsIndex || "-1", 10);
      if (draggedIndex < 0 || targetIndex < 0 || draggedIndex === targetIndex) return;
      const rect = row.getBoundingClientRect();
      const after = event.clientY > rect.top + rect.height / 2;
      reorderQueueTrack(draggedIndex, after ? targetIndex + 1 : targetIndex);
    });
  });
  container.addEventListener("dragover", (event) => {
    if (draggedIndex < 0) return;
    const row = event.target.closest(".queue-track-reorderable");
    if (row) return;
    event.preventDefault();
    clearDropTargets();
    const last = container.querySelector(".queue-track-reorderable:last-child");
    last?.classList.add("queue-drop-after");
  });
  container.addEventListener("drop", (event) => {
    if (draggedIndex < 0 || event.target.closest(".queue-track-reorderable")) return;
    event.preventDefault();
    reorderQueueTrack(draggedIndex, state.queue.length);
  });
}

function refreshQueuePanel() {
  restoreLinearOriginalQueue();
  // Now Playing
  const nowPlayingContainer = $("queueNowPlaying");
  if (state.currentTrack) {
    const art = state.currentTrack.artwork_url ? `background-image: url('${state.currentTrack.artwork_url}');` : "";
    nowPlayingContainer.innerHTML = `
      <div class="queue-track-item active" style="pointer-events:none">
        <div class="queue-track-art" style="${art}"></div>
        <div class="queue-track-info">
          <div class="queue-track-title" style="color:var(--accent)">${esc(state.currentTrack.title || state.currentTrack.name)}</div>
          <div class="queue-track-artist">${esc(state.currentTrack.artist)}</div>
        </div>
      </div>
    `;
  } else {
    nowPlayingContainer.innerHTML = `<div style="color:var(--muted); font-size:13px;">Nothing playing</div>`;
  }

  // Next tracks (up to 100, wrapping around if not shuffling)
  let nextTracks = [];
  if (state.queue && state.queue.length) {
    const qLen = state.queue.length;
    const startIdx = state.queueIndex + 1;
    
    for (let i = 0; i < Math.min(100, qLen - 1); i++) {
        const targetIdx = (startIdx + i) % qLen;
        // Don't include the currently playing track in the 'Next' list
        if (targetIdx === state.queueIndex) break; 
        nextTracks.push({ ...state.queue[targetIdx], _qIdx: targetIdx });
    }
  }
  
  if (state.queueContext) {
    $("queueNextTitle").innerText = `Next from: ${state.queueContext.title || "Queue"}`;
  } else {
    $("queueNextTitle").innerText = "Next";
  }

  renderQueueTracks("queueNextList", nextTracks, false);

  // Recent tracks
  const recentTracks = (state.catalog && state.catalog.recent_tracks) ? state.catalog.recent_tracks : [];
  renderQueueTracks("queueRecentList", recentTracks, true);
}

function openQueuePanel() {
  positionDetailsOverlay();
  $("queuePanel").hidden = false;
  $("btnQueue").classList.add("active");
  $("queuePanel").style.zIndex = "1000";
  $("connectPanel").style.zIndex = "900";
  refreshQueuePanel();
}

function closeQueuePanel() {
  $("queuePanel").hidden = true;
  releaseDetailsOverlay();
  $("btnQueue").classList.remove("active");
}

$("btnQueue").onclick = () => {
  if ($("queuePanel").hidden) openQueuePanel();
  else closeQueuePanel();
};
$("queuePanelClose").onclick = closeQueuePanel;

window.addEventListener("resize", () => {
  if (!$("queuePanel")?.hidden || !$("connectPanel")?.hidden) {
    positionDetailsOverlay();
  }
});

document.querySelectorAll(".queue-tab").forEach(tab => {
  tab.onclick = () => {
    document.querySelectorAll(".queue-tab").forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    const target = tab.dataset.target;
    $("queueContentQueue").hidden = target !== "queue";
    $("queueContentRecent").hidden = target !== "recent";
  };
});

// ---------------------------------------------------------------------------
// Context Menu
// ---------------------------------------------------------------------------
let contextMenuTargetTrack = null;
let contextMenuLibraryReady = false;

function ensureContextMenuLibrary() {
  if (contextMenuLibraryReady) return;
  ["trackContextMenu", "albumContextMenu"].forEach((menuId) => {
    if ($(menuId) && !$(`${menuId}ToggleProxy`)) {
      const proxy = document.createElement("button");
      proxy.id = `${menuId}ToggleProxy`;
      proxy.type = "button";
      proxy.className = "cm-toggle context-menu-toggle-proxy";
      proxy.setAttribute("data-cm-target", `#${menuId}`);
      proxy.tabIndex = -1;
      proxy.setAttribute("aria-hidden", "true");
      document.body.appendChild(proxy);
    }
  });
  const contextMenuLib = window.ContextMenuLib || (typeof ContextMenuLib !== "undefined" ? ContextMenuLib : null);
  if (contextMenuLib && typeof contextMenuLib.init === "function") {
    contextMenuLib.init();
    contextMenuLibraryReady = true;
  }
}

function openContextMenu(event, menu) {
  if (!menu) return;
  event.preventDefault();
  ensureContextMenuLibrary();
  menu.hidden = false;
  menu.style.display = "none";
  const proxy = $(`${menu.id}ToggleProxy`);
  if (!contextMenuLibraryReady || !proxy) {
    menu.style.display = "block";
    menu.style.left = `${Math.max(10, event.clientX)}px`;
    menu.style.top = `${Math.max(10, event.clientY)}px`;
    return;
  }
  proxy.dispatchEvent(new MouseEvent("contextmenu", {
    bubbles: true,
    cancelable: true,
    clientX: event.clientX,
    clientY: event.clientY,
    screenX: event.screenX,
    screenY: event.screenY,
  }));
  requestAnimationFrame(() => positionContextSubmenus(menu));
}

function positionContextSubmenus(menu) {
  if (!menu || menu.hidden) return;
  menu.querySelectorAll(".context-menu-item.has-submenu").forEach((item) => {
    const submenu = item.querySelector(".context-submenu");
    const icon = item.querySelector(".context-submenu-icon");
    if (!submenu) return;
    item.classList.remove("submenu-left");
    submenu.style.display = "block";
    const itemRect = item.getBoundingClientRect();
    const submenuWidth = submenu.offsetWidth || 180;
    submenu.style.display = "";
    const shouldOpenLeft = itemRect.right + submenuWidth > window.innerWidth - 10;
    item.classList.toggle("submenu-left", shouldOpenLeft);
    if (icon) {
      icon.classList.toggle("bi-caret-left-fill", shouldOpenLeft);
      icon.classList.toggle("bi-caret-right-fill", !shouldOpenLeft);
    }
  });
}

$("ctxDownload")?.addEventListener("click", () => {
  if (contextMenuTargetTrack) {
    // Simulate a click on a library button if we can find one, or just trigger toggleTrackLibrary
    // We create a dummy button for the toggle function
    const dummyBtn = document.createElement("button");
    toggleTrackLibrary(contextMenuTargetTrack, dummyBtn, () => {
        // Refresh views if needed
        syncActiveTrackRows();
    });
  }
  $("trackContextMenu").hidden = true;
});

function showTrackContextMenu(event, track, contextInfo = {}) {
  contextMenuTargetTrack = track;
  const menu = $("trackContextMenu");
  if (!menu) return;

  // Header
  const headerArt = $("ctxHeaderArt");
  if (headerArt) {
    headerArt.style.backgroundImage = track.artwork_url ? `url('${track.artwork_url}')` : "";
    headerArt.style.display = track.artwork_url ? "block" : "none";
  }
  const headerTitle = $("ctxHeaderTitle");
  if (headerTitle) headerTitle.textContent = track.title || track.name || "Unknown Track";
  
  const headerArtist = $("ctxHeaderArtist");
  if (headerArtist) {
    let sub = track.artist || "";
    if (track.album) sub += ` • ${track.album}`;
    headerArtist.textContent = sub;
  }

  // Build the artist links
  const artistContainer = $("ctxGoArtistContainer");
  artistContainer.innerHTML = "";
  if (track.artist) {
    const artists = track.artist.split(/,\s*|\s+&\s+/).map(a => a.trim()).filter(Boolean);
    if (artists.length === 1) {
      artistContainer.innerHTML = `<button id="ctxGoArtist" class="context-menu-item"><i class="bi bi-person" style="color:var(--muted);"></i> Go to artist</button>`;
      $("ctxGoArtist").onclick = () => {
        menu.hidden = true;
        pushPage(() => renderArtistPage(artistTarget({ ...track, artist: artists[0], name: artists[0], artist_id: primaryArtistId(track) })));
      };
    } else if (artists.length > 1) {
      const submenuItems = artists.map((a, i) => `<button id="ctxGoArtistSub_${i}" class="context-menu-item">${esc(a)}</button>`).join("");
      artistContainer.innerHTML = `
        <div class="context-menu-item has-submenu">
          <i class="bi bi-person" style="color:var(--muted);"></i> Go to artist
          <i class="bi bi-caret-right-fill context-submenu-icon"></i>
          <div class="context-submenu">${submenuItems}</div>
        </div>
      `;
      artists.forEach((a, i) => {
        $(`ctxGoArtistSub_${i}`).onclick = () => {
          menu.hidden = true;
          pushPage(() => renderArtistPage(artistTarget({ ...track, artist: a, name: a, artist_id: primaryArtistId(track) })));
        };
      });
    }
  }

  $("ctxGoAlbum").style.display = track.album ? "flex" : "none";
  
  // Dynamic Queue logic
  let upcomingIdx = -1;
  if (state.queue && state.queue.length && state.queueIndex >= 0) {
    const targetKey = trackKey(track);
    for (let i = state.queueIndex + 1; i < state.queue.length; i++) {
      if (trackKey(state.queue[i]) === targetKey) {
        upcomingIdx = i;
        break;
      }
    }
  }

  const btnAddQueue = $("ctxAddQueue");
  if (btnAddQueue) btnAddQueue.style.display = upcomingIdx !== -1 ? "none" : "flex";

  const btnDownload = $("ctxDownload");
  if (btnDownload) {
    const inLibrary = track.in_library || (track.metadata && track.metadata.in_library);
    btnDownload.style.display = inLibrary ? "none" : "flex";
  }
  
  const btnRemoveQueue = $("ctxRemoveQueue");
  if (btnRemoveQueue) {
    if (upcomingIdx !== -1) {
      btnRemoveQueue.style.display = "flex";
      btnRemoveQueue.onclick = () => {
        const removed = state.queue.splice(upcomingIdx, 1)[0];
        if (state.originalQueue) {
            const origIdx = state.originalQueue.findIndex(t => t === removed);
            if (origIdx >= 0) state.originalQueue.splice(origIdx, 1);
        }
        if (upcomingIdx <= state.queueIndex) state.queueIndex--;
        if (!$("queuePanel").hidden) refreshQueuePanel();
        updateSidebarNextQueue();
        menu.hidden = true;
      };
    } else {
      btnRemoveQueue.style.display = "none";
    }
  }

  const tastePayload = () => ({
    track_key: trackKey(track),
    title: track.title || track.name || "",
    artist: track.artist || "",
    album: track.album || "",
    resolved_url: track.resolved_url || track.spotify_url || track.url || track.metadata?.resolved_url || track.metadata?.spotify_url || track.metadata?.url || "",
    metadata: track.metadata || track,
  });

  const btnTaste = $("ctxTasteTrack");
  const btnBlacklist = $("ctxBlacklistTrack");

  const applyTasteState = (liked = false, blacklisted = false) => {
    if (btnTaste) {
      btnTaste.innerHTML = liked
        ? '<i class="bi bi-heart-fill" style="color:var(--muted);"></i> Remove from taste profile'
        : '<i class="bi bi-heart" style="color:var(--muted);"></i> Add to taste profile';
    }
    if (btnBlacklist) {
      btnBlacklist.innerHTML = blacklisted
        ? '<i class="bi bi-slash-circle-fill" style="color:var(--muted);"></i> Blacklisted'
        : '<i class="bi bi-slash-circle" style="color:var(--muted);"></i> Blacklist';
    }
  };

  applyTasteState(false, false);

  if (btnTaste) {
    btnTaste.onclick = async () => {
      const affinity = await api(`/api/taste/track?track_key=${encodeURIComponent(trackKey(track))}`).catch(() => ({}));
      const liked = String(affinity.status || "") === "liked";
      const endpoint = liked ? "/api/taste/remove-from-taste-profile" : "/api/taste/manual-like";
      await api(endpoint, { method: "POST", body: JSON.stringify(tastePayload()) });
      menu.hidden = true;
    };
  }

  if (btnBlacklist) {
    btnBlacklist.onclick = async () => {
      await api("/api/taste/manual-hard-blacklist", { method: "POST", body: JSON.stringify(tastePayload()) });
      menu.hidden = true;
    };
  }

  api(`/api/taste/track?track_key=${encodeURIComponent(trackKey(track))}`).then((affinity) => {
    const status = String(affinity?.status || "");
    applyTasteState(status === "liked", status === "hard_blacklisted");
  }).catch(() => {});

  // Remove from playlist
  const btnRemoveFromPlaylist = $("ctxRemoveFromPlaylist");
  if (btnRemoveFromPlaylist) {
    const playlistCtx = contextInfo && contextInfo.kind === "playlist" ? contextInfo : null;
    btnRemoveFromPlaylist.style.display = playlistCtx ? "flex" : "none";
    if (playlistCtx) {
      btnRemoveFromPlaylist.onclick = async () => {
        menu.hidden = true;
        await api("/api/playlists/tracks", {
          method: "POST",
          body: JSON.stringify({ playlist_id: playlistCtx.id, track, action: "remove" }),
        });
        const idx = state.playlists.findIndex(p => p.id === playlistCtx.id);
        if (idx !== -1) {
          const tKey = trackKey(track);
          state.playlists[idx].tracks = state.playlists[idx].tracks.filter(t => trackKey(t) !== tKey);
          renderPlaylistPage(state.playlists[idx]);
        }
      };
    }
  }

  // Share buttons
  const btnCopySpotify = $("ctxCopySpotify");
  if (btnCopySpotify) {
    let spId = trackIdentityValue(track, "spotify_id");
    if (spId && spId.includes(":")) spId = spId.split(":").pop();
    btnCopySpotify.style.display = spId ? "flex" : "none";
    btnCopySpotify.onclick = () => {
      navigator.clipboard.writeText(`https://open.spotify.com/track/${spId}`);
      menu.hidden = true;
    };
  }

  const btnCopyMusicBrainz = $("ctxCopyMusicBrainz");
  if (btnCopyMusicBrainz) {
    let mbId = trackIdentityValue(track, "musicbrainz_recording_id") || 
                 trackIdentityValue(track, "musicbrainz_track_id") ||
                 trackIdentityValue(track, "musicbrainz_id") ||
                 trackIdentityValue(track, "musicbrainz_trackid") ||
                 trackIdentityValue(track, "musicbrainz_recordingid") ||
                 trackIdentityValue(track, "mbid");
    if (mbId && mbId.includes("/")) mbId = mbId.split("/").pop();
    btnCopyMusicBrainz.style.display = mbId ? "flex" : "none";
    btnCopyMusicBrainz.onclick = () => {
      navigator.clipboard.writeText(`https://musicbrainz.org/recording/${mbId}`);
      menu.hidden = true;
    };
  }

  const btnCopyYouTube = $("ctxCopyYouTube");
  if (btnCopyYouTube) {
    let ytUrl = trackIdentityValue(track, "youtube_url") || trackIdentityValue(track, "url") || "";
    // If it's just an ID, format it
    if (ytUrl && !ytUrl.startsWith("http") && ytUrl.length < 15) {
        ytUrl = `https://www.youtube.com/watch?v=${ytUrl}`;
    }
    if (!ytUrl) {
      const ytId = trackIdentityValue(track, "youtube_id") || trackIdentityValue(track, "yt_id");
      if (ytId) ytUrl = `https://www.youtube.com/watch?v=${ytId}`;
    }
    btnCopyYouTube.style.display = ytUrl ? "flex" : "none";
    btnCopyYouTube.onclick = () => {
      navigator.clipboard.writeText(ytUrl);
      menu.hidden = true;
    };
  }

  openContextMenu(event, menu);
}

document.addEventListener("click", (e) => {
  const menu = $("trackContextMenu");
  if (menu && !menu.hidden && !menu.contains(e.target)) {
    menu.hidden = true;
  }
});

$("ctxAddQueue")?.addEventListener("click", () => {
  if (contextMenuTargetTrack) {
    state.queue.push(contextMenuTargetTrack);
    if (state.originalQueue) state.originalQueue.push(contextMenuTargetTrack);
    if (!$("queuePanel").hidden) refreshQueuePanel();
    updateSidebarNextQueue();
  }
  $("trackContextMenu").hidden = true;
});

$("ctxAddPlaylist")?.addEventListener("click", () => {
  if (contextMenuTargetTrack) openPlaylistPicker(contextMenuTargetTrack);
  $("trackContextMenu").hidden = true;
});

$("ctxGoAlbum")?.addEventListener("click", () => {
  if (contextMenuTargetTrack) {
    pushPage(() => renderAlbumPage(albumTarget(contextMenuTargetTrack)));
  }
  $("trackContextMenu").hidden = true;
});

// ---------------------------------------------------------------------------
// Album Context Menu
// ---------------------------------------------------------------------------
let contextMenuTargetAlbum = null;

function showAlbumContextMenu(event, album) {
  contextMenuTargetAlbum = album;
  const menu = $("albumContextMenu");
  if (!menu) return;
  const target = albumTarget(album);

  // Header
  const headerArt = $("ctxAlbumHeaderArt");
  if (headerArt) {
    headerArt.style.backgroundImage = target.artwork_url ? `url('${target.artwork_url}')` : "";
    headerArt.style.display = target.artwork_url ? "block" : "none";
  }
  const headerTitle = $("ctxAlbumHeaderTitle");
  if (headerTitle) headerTitle.textContent = target.title || album.name || "Unknown Album";
  
  const headerArtist = $("ctxAlbumHeaderArtist");
  if (headerArtist) headerArtist.textContent = target.artist || "";

  $("ctxAlbumCopySpotify")?.classList.toggle("hidden", !spotifyAlbumUrl(target));
  $("ctxAlbumCopyMusicBrainz")?.classList.toggle("hidden", !musicBrainzReleaseUrl(target));

  openContextMenu(event, menu);
}
$("ctxAlbumAddQueue")?.addEventListener("click", async () => {
  if (contextMenuTargetAlbum) {
    let tracks = contextMenuTargetAlbum.tracks || [];
    if (!tracks.length) {
      try {
        tracks = await fetchAlbumTracks(contextMenuTargetAlbum);
      } catch (e) {
        console.error("Failed to fetch album tracks:", e);
      }
    }
    if (tracks.length) {
        tracks.forEach(t => {
            const trackItem = { ...t, kind: "track" };
            state.queue.push(trackItem);
            if (state.originalQueue) state.originalQueue.push(trackItem);
        });
        if (!$("queuePanel").hidden) refreshQueuePanel();
        updateSidebarNextQueue();
    }
  }
  $("albumContextMenu").hidden = true;
});

$("ctxAlbumCopySpotify")?.addEventListener("click", () => {
  if (contextMenuTargetAlbum) {
    const url = spotifyAlbumUrl(contextMenuTargetAlbum);
    if (url) navigator.clipboard.writeText(url);
  }
  $("albumContextMenu").hidden = true;
});

$("ctxAlbumCopyMusicBrainz")?.addEventListener("click", () => {
  if (contextMenuTargetAlbum) {
    const url = musicBrainzReleaseUrl(contextMenuTargetAlbum);
    if (url) navigator.clipboard.writeText(url);
  }
  $("albumContextMenu").hidden = true;
});

$("ctxAlbumAddPlaylist")?.addEventListener("click", async () => {
  if (contextMenuTargetAlbum) {
    // 1. Fetch tracks if not present
    let tracks = contextMenuTargetAlbum.tracks || [];
    if (!tracks.length) {
      try {
        tracks = await fetchAlbumTracks(contextMenuTargetAlbum);
      } catch (e) {
        console.error("Failed to fetch album tracks:", e);
      }
    }
    if (!tracks.length) {
        $("albumContextMenu").hidden = true;
        return;
    }

    // 2. Create playlist
    try {
        const target = albumTarget(contextMenuTargetAlbum);
        const pl = await api("/api/playlists", {
          method: "POST",
          body: JSON.stringify({
            name: target.title || contextMenuTargetAlbum.name || "New Playlist",
            spotify_url: spotifyAlbumUrl(target),
            origin: "album",
          }),
        });
        // 3. Add tracks
        await api("/api/playlists/tracks/add", { method: "POST", body: JSON.stringify({ id: pl.id, tracks: tracks.map(t => ({ ...t, kind: "track" })) }) });
        await loadPlaylists();
    } catch (e) {
        alert("Failed to add album to playlist: " + e.message);
    }
  }
  $("albumContextMenu").hidden = true;
});

$("ctxAlbumGoArtist")?.addEventListener("click", () => {
  if (contextMenuTargetAlbum) {
    pushPage(() => renderArtistPage(artistTarget(contextMenuTargetAlbum)));
  }
  $("albumContextMenu").hidden = true;
});

window.addEventListener("beforeunload", () => {
  beaconListeningSession("", "beforeunload");
});

document.addEventListener("click", (e) => {
    const aMenu = $("albumContextMenu");
    if (aMenu && !aMenu.hidden && !aMenu.contains(e.target)) {
        aMenu.hidden = true;
    }
});
