const API_BASE = "";
const IS_ANDROID = /Mindinguflac-Android/i.test(navigator.userAgent) || !!window.MindinguflacAndroid;
if (IS_ANDROID) document.documentElement.classList.add("is-android");
const CATALOG_REFRESH_MS = 15 * 60 * 1000;
const ARTIST_TRACK_PREVIEW_COUNT = 5;
const ARTIST_ALBUM_PREVIEW_COUNT = 6;
const ARTIST_RELATED_PREVIEW_COUNT = 6;
const PREFETCH_AHEAD_COUNT = 5;

const state = {
  viewStack: [],
  runtime: null,
  catalog: { artists: [], albums: [], top_tracks: [], personal_tracks: [], recent_tracks: [] },
  mobileLibraryFilter: "playlists",
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
  playerStatusIconMode: "ready",
  playerStatusIconPct: 0,
  renderedPlayerStatusIcon: "",
  activeJobPhase: "",
  playbackRequestId: 0,
  listeningSession: null,
  sidebarRequestId: 0,
  tourPageRequestId: 0,
  sidebarTrackKey: null,
  currentStreamUrl: "",
  currentLibraryPath: "",
  pendingNativeStartAt: 0,
  pendingResumePosition: 0,
  restoredPlaybackPending: false,
  nativeAudio: { active: false, playing: false, position: 0, duration: 0, path: "", ended: false },
  nativeAudioStart: null,
  nativeAudioStarting: false,
  nativeAudioPauseAfterStart: false,
  nativeAudioPollTimer: null,
  prefetchedForRequestId: -1,
  preMuteVolume: 1,
  catalogRefreshTimer: null,
  cacheLogTimer: null,
  pairingPollTimer: null,
  pairingQrTimer: null,
  pairingInvite: null,
  pairingQrVisible: false,
  pairingBeforeInvite: [],
  pendingPairingInvitation: "",
  pairingPreview: null,
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
  detailsExpanded: false,
  statsPeriod: "month",
  playlistContinuationLoads: new Set(),
  videoMode: false,
  videoSync: { key: "", status: "", offset: 0, manual: 0, attempts: 0, timer: null },
  audioBuffering: false,
  audioHasPlayed: false,
  directStreamReconnectPending: false,
  directStreamReconnectTimer: null,
  directStreamReconnectAttempts: 0,
  directStreamAttemptPosition: 0,
  directStreamResumePending: false,
  directStreamPosition: 0,
  directStreamNativeFallbackAttempted: false,
  sideVideoTrackKey: "",
  videoFetch: {
    trackKey: "",
    status: "",   // ""|"downloading"|"ready"|"not_found"
    path: "",
  },
  lyrics: {
    open: false,
    loading: false,
    trackKey: "",
    source: "",
    provider: "",
    lines: [],
    raw: "",
    synced: true,
    activeIndex: -1,
    programmaticScroll: false,
    lastScrollAt: 0,
    syncOffset: 0.1,  // seconds to delay lyrics display relative to LRC timestamps
  },
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
  "ytp-dl": [
    { value: "youtube", label: "YouTube" },
  ],
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
  monochrome: [
    { value: "monochrome", label: "Monochrome (FLAC)" },
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
  monochrome: [
    { value: "LOSSLESS", label: "FLAC / Lossless" },
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

async function loadRuntimeCapabilities() {
  if (state.runtime) return state.runtime;
  try {
    state.runtime = await api("/api/runtime");
  } catch (_) {
    state.runtime = null;
  }
  return state.runtime;
}

function runtimeEngine(engine) {
  return (state.runtime && state.runtime.engines && state.runtime.engines[engine]) || null;
}

// On Android the engine picker is built from the backend's measured capability
// report, so an engine whose runtime is missing from the APK is never offered.
function androidEngineOptions() {
  const engines = (state.runtime && state.runtime.engines) || {};
  const order = ["ytp-dl", "monochrome", "torrent", "spotiflac"];
  const labels = {
    "torrent": "Torrent (Experimental)",
    "monochrome": "Monochrome (FLAC)",
    "ytp-dl": "YouTube Music",
  };
  return order
    .filter(name => engines[name] && engines[name].available)
    .map(name => ({ value: name, label: labels[name] || engines[name].label || name }));
}

// Say plainly why an engine is missing instead of quietly dropping it from
// the picker, so a user looking for FLAC/BitTorrent learns what is wrong.
function renderAndroidEngineNotes() {
  const row = $("androidEngineNotesRow");
  const list = $("androidEngineNotes");
  if (!row || !list) return;
  const engines = (state.runtime && state.runtime.engines) || {};
  const notes = ["monochrome", "torrent", "ytp-dl", "spotiflac"]
    .filter(name => engines[name] && !engines[name].available)
    .map(name => {
      const entry = engines[name];
      const label = esc(entry.label || name);
      const reason = esc(entry.reason || "Runtime not packaged in this build.");
      return `<li><strong>${label}</strong>${reason}</li>`;
    });
  const missing = ((state.runtime && state.runtime.dependencies) || {}).missing || [];
  if (missing.length) {
    notes.push(`<li><strong>Missing packaged runtimes</strong>${esc(missing.join(", "))}</li>`);
  }
  list.innerHTML = notes.join("");
  row.classList.toggle("hidden", !notes.length);
}

function updateEngineControls(engine, currentService, currentQuality) {
  $("torrentPlaybackCandidatesRow")?.classList.toggle("hidden", engine !== "torrent");
  $("torrentPrefetchCandidatesRow")?.classList.toggle("hidden", engine !== "torrent");
  $("torrentMetadataTimeoutRow")?.classList.toggle("hidden", engine !== "torrent");
  const serviceRow = $("serviceRow");
  const retriesRow = $("retriesRow");
  const serviceSel = $("downloadService");
  const qualitySel = $("defaultQuality");
  if (!serviceRow || !serviceSel || !qualitySel) return;

  let providers = ENGINE_PROVIDERS[engine] || ENGINE_PROVIDERS.spotiflac;
  let engineQualities = ENGINE_QUALITIES[engine];
  const capability = IS_ANDROID ? runtimeEngine(engine) : null;
  if (capability) {
    // Keep only the sources and qualities this engine's Android backend
    // actually implements. Offering the rest would either silently search
    // something else or label lossy output as FLAC.
    providers = providers.filter(option => (capability.services || []).includes(option.value));
    if (engineQualities) {
      engineQualities = engineQualities.filter(option => (capability.qualities || []).includes(option.value));
    }
  } else if (IS_ANDROID && engine === "ytp-dl") {
    engineQualities = ENGINE_QUALITIES[engine].filter(option => option.value !== "mp3");
  }
  if (engineQualities && !engineQualities.length) engineQualities = ENGINE_QUALITIES[engine];

  // Show/hide service row
  serviceRow.style.display = providers.length > 0 ? "" : "none";

  // Show/hide duckModel row (candidate-ranking engines only)
  const duckModelRow = $("duckModelRow");
  if (duckModelRow) {
    duckModelRow.style.display = engine === "torrent" || engine === "ytp-dl" ? "" : "none";
  }

  // Mornye owns provider retries; the former Tor retry setting is obsolete.
  if (retriesRow) retriesRow.style.display = "none";

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
  playbackSession: "mindinguflac.playbackSession.v1",
};

let _lastPlaybackSnapshotWrite = 0;

function localPlaybackSnapshot() {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEYS.playbackSession) || "null");
    if (!value || !value.track || typeof value.track !== "object") return null;
    const position = Number(value.position || 0);
    const duration = Number(value.duration || 0);
    return {
      track: value.track,
      libraryPath: String(value.libraryPath || ""),
      position: Number.isFinite(position) && position >= 0 ? position : 0,
      duration: Number.isFinite(duration) && duration >= 0 ? duration : 0,
      paused: value.paused !== false,
    };
  } catch (error) {
    return null;
  }
}

async function storedPlaybackSnapshot() {
  const persisted = await api("/api/playback/session").catch(() => null);
  if (persisted?.track && typeof persisted.track === "object") return persisted;
  return localPlaybackSnapshot();
}

function persistPlaybackSnapshot(force = false) {
  if (!state.currentTrack) return;
  const now = Date.now();
  if (!force && now - _lastPlaybackSnapshotWrite < 1000) return;
  _lastPlaybackSnapshotWrite = now;
  const audio = $("audioPlayer");
  const position = state.nativeAudio.active
    ? Number(state.nativeAudio.position || 0)
    : Number(audio?.currentTime || state.pendingResumePosition || 0);
  const spotifyDuration = knownTrackDurationSeconds(state.currentTrack);
  const directMonochrome = isMonochromeDirectStreamUrl(state.currentStreamUrl);
  const duration = state.nativeAudio.active
    ? Number(state.nativeAudio.duration || 0)
    : Number((directMonochrome ? spotifyDuration || audio?.duration : audio?.duration || spotifyDuration) || 0);
  const paused = state.nativeAudio.active
    ? (state.manualPauseRequested || !state.nativeAudio.playing)
    : !audio || audio.paused || state.audioBuffering;
  try {
    const snapshot = {
      track: state.currentTrack,
      libraryPath: state.currentLibraryPath || "",
      position: Number.isFinite(position) ? Math.max(0, position) : 0,
      duration: Number.isFinite(duration) ? Math.max(0, duration) : 0,
      paused,
      savedAt: now,
    };
    const serialized = JSON.stringify(snapshot);
    localStorage.setItem(STORAGE_KEYS.playbackSession, serialized);
    if (force && navigator.sendBeacon) {
      navigator.sendBeacon(
        `${API_BASE}/api/playback/session`,
        new Blob([serialized], { type: "application/json" })
      );
    } else {
      api("/api/playback/session", {
        method: "POST",
        body: serialized,
        timeout: 5000,
      }).catch(() => {});
    }
  } catch (error) {}
}

async function api(path, options = {}) {
  const { timeout = path.startsWith("/api/music/album_tracks?") ? 45000 : 15000, ...fetchOptions } = options;
  const controller = timeout > 0 ? new AbortController() : null;
  const id = controller ? setTimeout(() => controller.abort(), timeout) : null;
  try {
    const resp = await fetch(`${API_BASE}${path}`, {
      credentials: "same-origin",
      ...fetchOptions,
      signal: controller ? controller.signal : undefined,
    });
    if (!resp.ok) {
      const error = await resp.json().catch(() => ({ error: resp.statusText }));
      throw new Error(error.error || "API call failed");
    }
    return await resp.json();
  } catch (err) {
    if (controller?.signal.aborted) {
      throw new Error("The request took too long. Please try again.");
    }
    throw err;
  } finally {
    if (id) clearTimeout(id);
  }
}

function $(id) { return document.getElementById(id); }

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
  const releaseContext = item.type !== "album" ? (item.album_context || item.metadata?.album_context || {}) : {};
  // A track's own title is never its album's name: a track without an album
  // name opens its album through its Spotify id instead (track_spotify_id).
  const isTrack = item.type === "track" || (item.type !== "album" && !!(item.duration_ms || item.duration || item.length || item.track_number));
  // "Unknown" / "Unknown Album" are placeholders, not names: searching for
  // them finds nothing, so treat them as no name and locate the album by id.
  const placeholder = (value) => /^unknown(\s+album)?$/i.test(String(value || "").trim());
  const album = releaseContext.album || (placeholder(item.album) ? "" : item.album) || (isTrack || placeholder(item.title) ? "" : item.title) || "";
  const artist = releaseContext.album_artist || item.album_artist || item.metadata?.album_artist || item.artist || item.name || "";
  const sameArtist = String(artist).toLocaleLowerCase() === String(item.artist || item.name || "").toLocaleLowerCase();
  const artistId = item.album_artist_id || (sameArtist ? (item.spotify_artist_id || item.artist_id || "") : "");
  const metadataAlbumId = item.metadata && (
    item.metadata.album_spotify_id || item.metadata.spotify_album_id ||
    (item.type === "album" ? item.metadata.spotify_id : "")
  );
  const albumId = releaseContext.spotify_id || item.album_spotify_id || item.spotify_album_id || (item.type === "album" ? item.spotify_id : "") || metadataAlbumId || "";
  return {
    type: "album",
    title: album,
    album,
    artist,
    artwork_url: releaseContext.artwork_url || item.album_artwork_url || item.artwork_url || "",
    artist_artwork_url: item.artist_artwork_url || "",
    artist_id: artistId,
    spotify_artist_id: artistId,
    year: item.year || "",
    musicbrainz_release_id: item.musicbrainz_release_id || item.release_id || (item.metadata && (item.metadata.musicbrainz_release_id || item.metadata.release_id)) || "",
    spotify_id: albumId,
    // Only an album link is an album's URL; a track's spotify_url is the track.
    spotify_url: /open\.spotify\.com\/album\//.test(item.spotify_url || "") ? item.spotify_url : "",
    external_urls: item.type === "album" ? (item.external_urls || {}) : {},
    // Any non-album item is a track here (player-bar tracks often have no
    // "type" or duration), so its Spotify id locates the exact album.
    track_spotify_id: item.type === "album" ? "" : (item.track_spotify_id || item.spotify_id || (isTrack ? item.id : "") || ""),
  };
}

function savedAlbumSpotifyId(playlist = {}) {
  return playlist.album_spotify_id || playlist.spotify_album_id ||
    (String(playlist.spotify_url || "").match(/(?:\/album\/|spotify:album:)([A-Za-z0-9]+)/)?.[1] || "");
}

function spotifyAlbumId(album = {}) {
  const metadataAlbumId = album.metadata && (
    album.metadata.album_spotify_id || album.metadata.spotify_album_id ||
    (album.type === "album" ? album.metadata.spotify_id : "")
  );
  const value = album.spotify_id || album.album_spotify_id || album.spotify_album_id || metadataAlbumId || "";
  const match = String(value).match(/(?:open\.spotify\.com\/album\/|spotify:album:)([A-Za-z0-9]+)/);
  return match ? match[1] : String(value).trim();
}

function spotifyArtistUrl(artist = {}) {
  const target = artistTarget(artist);
  const url = target.spotify_url || (target.external_urls && target.external_urls.spotify) || "";
  if (url && /open\.spotify\.com\/artist\//.test(url)) return url;
  let id = target.spotify_artist_id || target.spotify_id || target.artist_id || "";
  if (id && id.includes(":")) id = id.split(":").pop();
  return id ? `https://open.spotify.com/artist/${id}` : "";
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
  const full = await api(`/api/music/album_tracks?${params.toString()}&details=0`);
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
  return `<button class="inline-entity-link track-title-link ${className}" type="button" title="${esc(label)}" data-open-album='${attrJson(albumTarget(item))}' data-source-track='${attrJson(item)}'>${esc(label)}</button>`;
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
      const track = JSON.parse(button.dataset.sourceTrack || "{}");
      const album = JSON.parse(button.dataset.openAlbum || "{}");
      // Open the album page at once: it finds the exact album from the
      // track's Spotify id (track_spotify_id) and shows its header while the
      // songs load. Waiting for full track enrichment first (Spotify, Deezer,
      // MusicBrainz) made every title click take ~30 s.
      if (isTrackItem(track) && !album.spotify_id && !album.track_spotify_id && !album.album) {
        // Nothing to locate the album by: only then enrich the track first.
        resolveTrackAlbumLink(track, album).catch(error => {
          console.warn("Could not resolve the track album before opening it:", error);
          openAlbumLink(album);
        });
      } else {
        openAlbumLink(album);
      }
    };
  });
}

async function resolveTrackAlbumLink(track, fallbackAlbum) {
  const response = await api("/api/music/track_metadata", {
    method: "POST",
    body: JSON.stringify({ track }),
    timeout: 45000,
  });
  const enriched = response?.track || {};
  const albumName = String(enriched.album || enriched.album_title || "").trim();
  openAlbumLink(albumName ? albumTarget({ ...track, ...enriched, album: albumName }) : fallbackAlbum);
}

// The collapsed player draws its progress as a gradient stop on .player::before,
// so it needs the same updates the full seek bar gets.
function setMiniPlayerProgress(ratio) {
  const player = document.querySelector(".player");
  if (!player) return;
  const pct = Math.min(100, Math.max(0, (Number(ratio) || 0) * 100));
  player.style.setProperty("--player-progress", `${pct}%`);
}

function resetSeekUi() {
  setMiniPlayerProgress(0);
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

let _nowPlayingCloseTimer = null;
let _nowPlayingRestoreTimer = null;

function syncDetailsExpandButton(expanded) {
  const button = $("detailsExpandBtn");
  if (!button) return;
  const label = expanded ? "Collapse now playing" : "Expand now playing";
  button.setAttribute("aria-pressed", String(expanded));
  button.setAttribute("aria-label", label);
  button.title = label;
  button.querySelector("path")?.setAttribute(
    "d",
    expanded
      ? "M9 4v5H4M15 4v5h5M20 15h-5v5M4 15h5v5"
      : "M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"
  );
}

function setDetailsExpanded(expanded) {
  const wantExpanded = Boolean(expanded);
  const onPhone = window.matchMedia("(max-width: 900px)").matches;
  const body = document.body;
  const panel = document.querySelector(".details-panel");

  clearTimeout(_nowPlayingCloseTimer);
  clearTimeout(_nowPlayingRestoreTimer);
  body.classList.remove("now-playing-closing", "now-playing-restored");
  // The settle() listener below sets this to "none" after the open animation
  // finishes, to stop its lingering transform from leaking into the
  // containing block for fixed children (see the comment there). An inline
  // style always beats a class selector, so without clearing it here every
  // open and close after the first ran with no animation at all — not fast,
  // just silently skipped.
  if (panel) panel.style.animation = "";

  // Closing on a phone plays the sheet back down before the screen is torn
  // apart. The panel and the transport bar are separate fixed elements, so
  // both have to travel together — and the mini bar has to be faded back in
  // afterwards, otherwise it pops into place the instant the classes drop.
  if (!wantExpanded && state.detailsExpanded && onPhone && body.classList.contains("mobile-now-playing")) {
    state.detailsExpanded = false;
    syncDetailsExpandButton(false);
    // See the matching comment below: nothing floating over this screen makes
    // sense once it is gone, and this is the path a swipe or the collapse
    // button actually takes.
    if (state.lyrics?.open) closeLyricsPanel();
    const queue = $("queuePanel");
    if (queue && !queue.hidden) closeQueuePanel();
    const connect = $("connectPanel");
    if (connect && !connect.hidden) closeConnectPanel();
    body.classList.add("now-playing-closing");
    _nowPlayingCloseTimer = setTimeout(() => {
      body.classList.remove("now-playing-closing", "mobile-now-playing", "details-expanded");
      panel?.classList.remove("is-expanded");
      body.classList.add("now-playing-restored");
      _nowPlayingRestoreTimer = setTimeout(
        () => body.classList.remove("now-playing-restored"), 220);
    }, 210);
    return;
  }

  state.detailsExpanded = wantExpanded;
  panel?.classList.toggle("is-expanded", state.detailsExpanded);
  body.classList.toggle("details-expanded", state.detailsExpanded);
  body.classList.toggle("mobile-now-playing", state.detailsExpanded && onPhone);
  syncDetailsExpandButton(state.detailsExpanded);

  // Exiting the fullscreen screen closes whatever was open over it; none of
  // them make sense floating above a screen that is no longer there.
  if (!state.detailsExpanded) {
    if (state.lyrics?.open) closeLyricsPanel();
    const queue = $("queuePanel");
    if (queue && !queue.hidden) closeQueuePanel();
    const connect = $("connectPanel");
    if (connect && !connect.hidden) closeConnectPanel();
  }

  if (state.detailsExpanded && panel) {
    // The open animation uses fill-mode: both, which leaves the panel's
    // computed transform at translateY(0) — not "none" — once it finishes.
    // A non-none transform on an ancestor changes the containing block for any
    // position:fixed descendant, and #queuePanel/#connectPanel live inside
    // .details-panel: that is what made the queue scroll away with the
    // panel's own content instead of staying pinned to the viewport. Dropping
    // the animation once it completes restores "transform: none" (nothing
    // else sets it) without disturbing the slide-in itself.
    panel.addEventListener("animationend", function settle(event) {
      if (event.target !== panel) return;
      panel.removeEventListener("animationend", settle);
      if (state.detailsExpanded) panel.style.animation = "none";
    });
  }
}

function setMobileNavActive(name) {
  document.querySelectorAll("[data-mobile-nav]").forEach(button => {
    button.classList.toggle("active", button.dataset.mobileNav === name);
  });
}

function mobileLibraryItemsHtml(playlists) {
  const filter = state.mobileLibraryFilter || "playlists";
  if (filter === "playlists") {
    if (!playlists.length) return '<div class="mobile-empty-state">Your playlists will appear here.</div>';
    return playlists.map(pl => {
      return `<button class="mobile-library-item" type="button" data-mobile-playlist-id="${esc(pl.id)}">
        ${playlistArtworkHtml(pl, "mobile-library-art")}
        <span><strong>${esc(pl.name)}</strong><small>Playlist · ${pl.tracks?.length || 0} songs</small></span>
      </button>`;
    }).join("");
  }

  const trackKey = track => String(track.spotify_id || track.id || `${track.title || track.name || ""}\u0000${track.artist || ""}`).trim().toLocaleLowerCase();
  const items = new Map();
  for (const playlist of playlists) {
    for (const track of (playlist.tracks || [])) {
      if (!track || typeof track !== "object") continue;
      const primary = primaryArtistName(track);
      if (filter === "artists") {
        const credits = track.artists || track.metadata?.artists || track.artist_names;
        const entries = Array.isArray(credits)
          ? credits.map(value => typeof value === "string" ? { name: value } : (value || {}))
          : String(track.artist || "").split(/,\s+|\s+&\s+|\s+feat(?:uring)?\.?\s+|\s+ft\.?\s+|\s+x\s+/i).map(name => ({ name }));
        for (const credit of entries) {
          const name = String(credit.name || credit.artist || "").trim();
          if (!name) continue;
          const key = name.normalize("NFKC").toLocaleLowerCase();
          const creditId = credit.artist_id || credit.spotify_artist_id || credit.spotify_id || credit.id || (key === primary.normalize("NFKC").toLocaleLowerCase() ? (track.spotify_artist_id || track.artist_id || "") : "");
          if (!items.has(key)) items.set(key, { name, artist: name, type: "artist", artwork_url: credit.artwork_url || credit.image_url || track.artist_artwork_url || "", artist_id: creditId, trackKeys: new Set() });
          const entry = items.get(key);
          entry.trackKeys.add(trackKey(track));
          if (!entry.artwork_url && (credit.artwork_url || credit.image_url || track.artist_artwork_url)) entry.artwork_url = credit.artwork_url || credit.image_url || track.artist_artwork_url;
          if (!entry.artist_id && creditId) entry.artist_id = creditId;
        }
      } else {
        const title = String(track.album || track.album_title || "").trim();
        if (!title) continue;
        const albumArtist = String(track.album_artist || track.metadata?.album_artist || primary).trim();
        const exactAlbumId = track.album_spotify_id || track.spotify_album_id || track.metadata?.album_spotify_id || track.metadata?.spotify_album_id || "";
        const key = exactAlbumId ? `spotify:${exactAlbumId}` : `${title}\u0000${albumArtist}`.normalize("NFKC").toLocaleLowerCase();
        if (!items.has(key)) items.set(key, { title, album: title, artist: albumArtist, type: "album", artwork_url: track.album_artwork_url || track.artwork_url || "", artist_artwork_url: track.artist_artwork_url || "", spotify_id: track.album_spotify_id || track.spotify_album_id || track.metadata?.album_spotify_id || track.metadata?.spotify_album_id || "", musicbrainz_release_id: track.musicbrainz_release_id || track.release_id || track.metadata?.musicbrainz_release_id || "", year: track.year || "", tracks: [], trackKeys: new Set() });
        const entry = items.get(key);
        const keyForTrack = trackKey(track);
        if (!entry.trackKeys.has(keyForTrack)) entry.tracks.push(track);
        entry.trackKeys.add(keyForTrack);
        if (!entry.artwork_url && (track.album_artwork_url || track.artwork_url)) entry.artwork_url = track.album_artwork_url || track.artwork_url;
        if (!entry.year && track.year) entry.year = track.year;
      }
    }
  }
  const libraryItems = [...items.values()].sort((a, b) => (a.name || a.title).localeCompare(b.name || b.title));
  if (!libraryItems.length) return `<div class="mobile-empty-state">${filter === "artists" ? "Artists" : "Albums"} from your playlists will appear here.</div>`;
  return libraryItems.map(item => {
    const art = item.artwork_url || "";
    const count = item.trackKeys.size;
    const isArtist = filter === "artists";
    const label = isArtist ? item.name : item.title;
    const detail = isArtist ? `Artist · ${count} song${count === 1 ? "" : "s"}` : `${item.artist || "Album"} · ${count} song${count === 1 ? "" : "s"}`;
    return `<button class="mobile-library-item" type="button" ${isArtist ? `data-mobile-artist='${attrJson(item)}'` : `data-mobile-album='${attrJson(item)}'`}>
      <span class="mobile-library-art ${isArtist ? "mobile-library-art-round" : ""}" style="${art ? `background-image:url('${esc(art)}')` : ""}">${art ? "" : `<i class="bi ${isArtist ? "bi-person-fill" : "bi-disc"}"></i>`}</span>
      <span><strong>${esc(label)}</strong><small>${esc(detail)}</small></span>
    </button>`;
  }).join("");
}

function bindLibraryHold(button, openMenu) {
  let timer = null;
  let start = null;
  let held = false;
  const cancel = () => { clearTimeout(timer); timer = null; };
  button.addEventListener("pointerdown", event => {
    cancel();
    held = false;
    if (event.pointerType === "mouse" || !event.isPrimary) return;
    start = { x: event.clientX, y: event.clientY };
    timer = setTimeout(() => {
      if (!button.isConnected) return;
      held = true;
      openMenu({ preventDefault() {}, target: button, clientX: start.x, clientY: start.y });
    }, 550);
  });
  button.addEventListener("pointermove", event => {
    if (start && Math.hypot(event.clientX - start.x, event.clientY - start.y) > 10) cancel();
  });
  ["pointerup", "pointercancel", "pointerleave"].forEach(name => button.addEventListener(name, cancel));
  button.addEventListener("click", event => {
    if (!held) return;
    event.preventDefault();
    event.stopImmediatePropagation();
  }, true);
  button.oncontextmenu = event => {
    event.preventDefault();
    cancel();
    if (!held) openMenu(event);
    held = true;
  };
}

function playlistShareUrl(playlist) {
  const source = String(playlist.spotify_url || "").trim();
  const uri = source.match(/^spotify:playlist:([A-Za-z0-9]+)$/);
  if (uri) return `https://open.spotify.com/playlist/${uri[1]}`;
  try {
    const url = new URL(source);
    return url.protocol === "https:" && url.hostname === "open.spotify.com" && /^\/playlist\/[A-Za-z0-9]+\/?$/.test(url.pathname) ? url.href : "";
  } catch (_) { return ""; }
}

function showPlaylistContextMenu(event, playlist) {
  const menu = $("playlistContextMenu");
  $("ctxPlaylistTitle").textContent = playlist.name || "Playlist";
  $("ctxPlaylistSubtitle").textContent = `Playlist · ${playlist.tracks?.length || 0} songs`;
  $("ctxPlaylistArt").outerHTML = playlistArtworkHtml(playlist, "context-menu-header-art", "ctxPlaylistArt");
  const url = playlistShareUrl(playlist);
  const share = $("ctxPlaylistShare");
  share.disabled = !url;
  share.title = url ? "Share playlist link" : "This local playlist has no public link.";
  $("ctxPlaylistShareHint").hidden = !!url;
  share.onclick = async () => {
    menu.hidden = true;
    try {
      if (window.MindinguflacAndroid?.sharePlaylistLink) {
        window.MindinguflacAndroid.sharePlaylistLink(playlist.name || "Playlist", url);
      } else if (navigator.share) {
        await navigator.share({ title: playlist.name || "Playlist", url });
      } else {
        await navigator.clipboard.writeText(url);
        showToast("Playlist link copied");
      }
    } catch (error) {
      if (error.name !== "AbortError") showToast("Could not share the playlist link.");
    }
  };
  $("ctxPlaylistDelete").style.display = isReadOnlyPlaylist(playlist) ? "none" : "";
  $("ctxPlaylistDelete").onclick = () => { menu.hidden = true; deletePlaylist(playlist.id); };
  openContextMenu(event, menu);
}

function bindMobileLibraryItems() {
  document.querySelectorAll("[data-mobile-playlist-id]").forEach(button => {
    button.onclick = () => {
      const playlist = state.playlists.find(item => item.id === button.dataset.mobilePlaylistId);
      if (playlist) openLibraryPlaylist(playlist);
    };
    bindLibraryHold(button, event => {
      const playlist = state.playlists.find(item => item.id === button.dataset.mobilePlaylistId);
      if (playlist) showPlaylistContextMenu(event, playlist);
    });
  });
  document.querySelectorAll("[data-mobile-artist]").forEach(button => {
    button.onclick = () => pushPage(() => renderArtistPage(JSON.parse(button.dataset.mobileArtist || "{}")));
    bindLibraryHold(button, event => showArtistContextMenu(event, JSON.parse(button.dataset.mobileArtist || "{}")));
  });
  document.querySelectorAll("[data-mobile-album]").forEach(button => {
    button.onclick = () => {
      const album = JSON.parse(button.dataset.mobileAlbum || "{}");
      album.saved_playlist_context = { kind: "saved-album", tracks: album.tracks || [] };
      pushPage(() => renderAlbumPage(album));
    };
    bindLibraryHold(button, event => showAlbumContextMenu(event, JSON.parse(button.dataset.mobileAlbum || "{}")));
  });
}

// Album saves are library shortcuts to the canonical album page. Keep custom
// playlists on their existing playlist page and playback context.
function openLibraryPlaylist(playlist) {
  if (inferPlaylistOrigin(playlist) !== "album") {
    pushPage(() => renderPlaylistPage(playlist));
    return;
  }
  const seed = (playlist.tracks || []).find(track => track && (track.album || track.artist)) || {};
  const target = albumTarget({
    ...seed,
    album_spotify_id: savedAlbumSpotifyId(playlist) || seed.album_spotify_id || seed.spotify_album_id || "",
    album: seed.album || playlist.name || "",
    artist: seed.album_artist || playlist.owner || seed.artist || "",
    artwork_url: playlist.artwork_url || seed.album_artwork_url || seed.artwork_url || "",
    year: seed.year || playlist.year || "",
  });
  state.activePlaylistId = playlist.id;
  document.querySelectorAll(".sidebar-playlist-item").forEach(item => {
    item.classList.toggle("active", item.dataset.playlistId === playlist.id);
  });
  target.saved_playlist_context = {
    kind: "playlist",
    id: playlist.id,
    name: playlist.name,
    origin: "album",
    allow_playlist_continuation: false,
    tracks: playlist.tracks || [],
  };
  pushPage(() => renderAlbumPage(target));
}

// Repaint Your Library in place when the playlist set changes. The phone never
// shows the desktop sidebar, so refreshing only that left a newly created
// playlist invisible until the app was restarted.
function refreshMobileLibraryList() {
  const container = $("mobileLibraryItems");
  if (!container) return;
  container.innerHTML = mobileLibraryItemsHtml(state.playlists || []);
  bindMobileLibraryItems();
}

function renderMobileLibraryPage() {
  setActiveView("home");
  setMobileNavActive("library");
  const playlists = state.playlists || [];
  $("pageContent").innerHTML = `
    <div class="scroll-area mobile-library-page">
      <div class="mobile-page-title">
        <div class="mobile-profile-dot">M</div>
        <h1>Your Library</h1>
        <button class="mobile-title-action" type="button" data-mobile-search aria-label="Search library"><i class="bi bi-search"></i></button>
        <button class="mobile-title-action" type="button" id="mobileCreatePlaylist" aria-label="Create playlist"><i class="bi bi-plus-lg"></i></button>
      </div>
      <div class="mobile-filter-pills" role="tablist" aria-label="Library type">
        ${[["playlists", "Playlists"], ["albums", "Albums"], ["artists", "Artists"]].map(([key, label]) => `<button class="${(state.mobileLibraryFilter || "playlists") === key ? "active" : ""}" type="button" role="tab" aria-selected="${(state.mobileLibraryFilter || "playlists") === key}" data-mobile-library-filter="${key}">${label}</button>`).join("")}
      </div>
      <div class="mobile-library-sort"><strong><i class="bi bi-arrow-down-up"></i> Recents</strong><i class="bi bi-grid"></i></div>
      <div id="mobileLibraryItems" class="mobile-library-items">
        ${mobileLibraryItemsHtml(playlists)}
      </div>
    </div>`;
  bindMobileLibraryItems();
  document.querySelectorAll("[data-mobile-library-filter]").forEach(button => {
    button.onclick = () => {
      state.mobileLibraryFilter = button.dataset.mobileLibraryFilter;
      document.querySelectorAll("[data-mobile-library-filter]").forEach(tab => {
        const active = tab === button;
        tab.classList.toggle("active", active);
        tab.setAttribute("aria-selected", String(active));
      });
      const list = $("mobileLibraryItems");
      if (list) list.innerHTML = mobileLibraryItemsHtml(state.playlists || []);
      bindMobileLibraryItems();
    };
  });
  document.querySelector("[data-mobile-search]")?.addEventListener("click", focusMobileSearch);
  const create = $("mobileCreatePlaylist");
  if (create && $("createPlaylistBtn")) create.onclick = () => $("createPlaylistBtn").click();
}

function advisorStatusText(kind, status) {
  const labels = {
    available: "ready",
    downloadable: "download available",
    downloading: "downloading",
    installed: "ready",
    not_installed: "not installed",
    unavailable: "unavailable on this device",
  };
  return `${kind}: ${labels[status] || status || "unavailable"}`;
}

function stopAndroidAdvisorPolling() {
  if (state.androidAdvisorTimer) {
    clearInterval(state.androidAdvisorTimer);
    state.androidAdvisorTimer = null;
  }
}

// The local model download can run for minutes; without polling, the status
// line only ever showed whatever it said the moment Settings was opened.
function startAndroidAdvisorPolling() {
  if (!IS_ANDROID || state.androidAdvisorTimer) return;
  state.androidAdvisorTimer = setInterval(refreshAndroidAdvisorStatus, 3000);
}

function refreshAndroidAdvisorStatus() {
  const row = $("androidAdvisorRow");
  if (!row) return;
  row.classList.toggle("hidden", !IS_ANDROID);
  if (!IS_ANDROID || !window.MindinguflacAndroid) return;
  startAndroidAdvisorPolling();
  try {
    $("nanoAdvisorStatus").textContent = advisorStatusText("Gemini Nano", window.MindinguflacAndroid.nanoStatus());
    $("localModelStatus").textContent = advisorStatusText("Local model", window.MindinguflacAndroid.localModelStatus());
  } catch (_) {
    $("nanoAdvisorStatus").textContent = advisorStatusText("Gemini Nano", "unavailable");
    $("localModelStatus").textContent = advisorStatusText("Local model", "not_installed");
  }
  // "Download now" auto-starts over Wi-Fi already; this button is for forcing
  // it over mobile data, or retrying after a failed attempt. "Install from
  // file" stays for picking a different model, or a manual browser download.
  const download = $("downloadLocalModel");
  if (download) download.onclick = () => window.MindinguflacAndroid.downloadLocalModel();
  const install = $("installLocalModel");
  if (install) install.onclick = () => window.MindinguflacAndroid.installLocalModel();
}

window.onLocalModelInstalled = installed => {
  refreshAndroidAdvisorStatus();
  if (!installed) alert("That model could not be installed. Choose a compatible MediaPipe .task bundle.");
};

function focusMobileSearch() {
  setMobileNavActive("search");
  const input = $("searchInput");
  input?.focus();
  input?.select();
}

function bindMobileNavigation() {
  document.querySelectorAll("[data-mobile-nav]").forEach(button => {
    button.onclick = () => {
      const target = button.dataset.mobileNav;
      if (target === "home") {
        setMobileNavActive("home");
        replacePage(renderHomePage);
      } else if (target === "search") {
        focusMobileSearch();
      } else if (target === "library") {
        replacePage(renderMobileLibraryPage);
      } else if (target === "stats") {
        setMobileNavActive("stats");
        setActiveLibraryPill("stats");
        replacePage(() => renderStatsPage(state.statsPeriod || "month"));
      }
    };
  });
  document.querySelector(".player-track")?.addEventListener("click", event => {
    if (window.matchMedia("(max-width: 900px)").matches && !event.target.closest("#playerStatusIcon")) {
      setDetailsExpanded(true);
    }
  });
}

function setActiveView(id, preservePlaylistId = "") {
  if (id !== "settings") { stopCacheLogPolling(); stopAndroidAdvisorPolling(); }
  if (window.artistEvtSource) {
    window.artistEvtSource.close();
    window.artistEvtSource = null;
  }
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  state.activePlaylistId = preservePlaylistId || null;
  document.querySelectorAll(".sidebar-playlist-item").forEach(el => {
    el.classList.toggle("active", !!preservePlaylistId && el.dataset.playlistId === preservePlaylistId);
  });
  const view = $(id);
  if (view) view.classList.add("active");
}

// Android's back gesture. The interface is a JS view stack, not WebView
// history, so WebView.canGoBack() is always false and the system would just
// finish the Activity — which is why back closed the app instead of navigating.
// Java routes the gesture here; we unwind whatever is on top, and only ask to
// exit once there is genuinely nothing left to go back to.
window.__androidBack = function () {
  try {
    const pairingDialog = $("pairingConfirmation");
    if (pairingDialog?.open) { pairingDialog.close(); return; }
    if (state.lyrics?.open) { closeLyricsPanel(); return; }
    const queue = $("queuePanel");
    if (queue && !queue.hidden) { closeQueuePanel(); return; }
    const connect = $("connectPanel");
    if (connect && !connect.hidden) { closeConnectPanel(); return; }
    if (state.detailsExpanded) { setDetailsExpanded(false); return; }
    if (state.viewStack.length > 1) { popPage(); return; }
  } catch (_) {
    // Never trap the user in the app because a panel check threw.
  }
  try { window.MindinguflacAndroid?.exitApp(); } catch (_) {}
};

function pushPage(renderFn) {
  // A link clicked from inside the fullscreen now-playing screen (a tour
  // event, a related artist, a credit, "go to album") updates #pageContent
  // like any other navigation, but that content sits behind the fullscreen
  // overlay — the user would see nothing happen until they separately
  // swiped it away themselves. Collapsing it first, through the same close
  // animation swiping down already uses, makes the destination page the
  // thing that becomes visible.
  if (document.body.classList.contains("mobile-now-playing")) {
    setDetailsExpanded(false);
  }
  if (state.viewStack.length > 0) {
    const activeScrollArea = document.querySelector(".active .scroll-area");
    state.viewStack[state.viewStack.length - 1].scroll = activeScrollArea ? activeScrollArea.scrollTop : 0;
  }
  state.viewStack.push({ render: renderFn, scroll: 0 });
  state.forwardHistory = [];
  const rendered = renderFn();
  updateHistoryButtons();
  return rendered;
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
  setMobileNavActive("home");
  setActiveView("home");
  
  const personalTracks = (state.catalog.personal_tracks || []).slice(0, 6);
  const recentTracks = uniqueRecentTracks(state.catalog.recent_tracks || []).slice(0, 6);
  const globalTracks = (state.catalog.top_tracks || []).slice(0, 6);
  const topArtists = (state.catalog.artists || []).slice(0, 6);
  const topAlbums = (state.catalog.albums || []).slice(0, 6);

  // The hero used to sit outside .scroll-area, so it stayed pinned while the
  // sections moved under it. Inside the scroller it scrolls away, which is what
  // lets the first section header take the top spot.
  let html = `
    <div class="scroll-area">
      <div class="library-hero compact-hero">
        <div>
          <span class="eyebrow">Personal Music Discovery</span>
          <h1>Welcome Home</h1>
        </div>
      </div>`;

  if (recentTracks.length) {
    html += `
        <section class="home-section">
        <div class="section-head sticky-head">
          <h2>Recently Played</h2>
          <button class="see-more" id="seeMoreRecent">See all <i class="bi bi-chevron-right"></i></button>
        </div>
        <div id="recentTracksGrid" class="grid"></div>
        </section>
    `;
  }

  if (personalTracks.length) {
    html += `
        <section class="home-section">
        <div class="section-head sticky-head">
          <h2>Your Most Listened</h2>
          <button class="see-more" id="seeMorePersonal">See all <i class="bi bi-chevron-right"></i></button>
        </div>
        <div id="personalTracksGrid" class="grid"></div>
        </section>
    `;
  }

  html += `
<section class="home-section">
            <div class="section-head sticky-head">
        <h2>Top Songs (Global)</h2>
        <button class="see-more" id="seeMoreGlobalTracks">See all <i class="bi bi-chevron-right"></i></button>
      </div>
      <div id="topTracksGrid" class="grid"></div>
      </section>

<section class="home-section">
            <div class="section-head sticky-head">
        <h2>Top Artists (Global)</h2>
        <button class="see-more" id="seeMoreArtists">See all <i class="bi bi-chevron-right"></i></button>
      </div>
      <div id="topArtistsGrid" class="grid"></div>
      </section>

<section class="home-section">
            <div class="section-head sticky-head">
        <h2>Top Albums (Global)</h2>
        <button class="see-more" id="seeMoreAlbums">See all <i class="bi bi-chevron-right"></i></button>
      </div>
      <div id="topAlbumsGrid" class="grid"></div>
      </section>
    </div>
  `;

  $("pageContent").innerHTML = html;

  if (recentTracks.length) {
    renderCards("recentTracksGrid", recentTracks, "track", state.catalog.recent_tracks);
    bindRecentTrackContextMenus("recentTracksGrid", recentTracks);
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
  renderTrackList("fullRecentTracks", tracks, "general", { kind: "recent" });
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

function bindStatsTrackRows(containerId, items = [], onRemoved = null) {
  const container = $(containerId);
  if (!container) return;
  container.querySelectorAll(".stats-track-row").forEach(el => {
    const item = items[Number(el.dataset.itemIdx)];
    if (!item) return;
    el.onclick = () => selectMusicItem(item, "stream", items);
    el.oncontextmenu = (event) => {
      event.preventDefault();
      showTrackContextMenu(event, item, { kind: "stats", onRemoved });
    };
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
  if ($("statsTracks")) { $("statsTracks").innerHTML = renderStatsTrackRows(items); bindStatsTrackRows("statsTracks", items, () => renderStatsPage(activePeriod)); }
  if ($("statsSeeAllTracks")) $("statsSeeAllTracks").onclick = () => pushPage(() => renderStatsTracksPage(activePeriod));
}
// get_top_listened_artists/albums rows carry artist_name/no `type` field — stats
// cards are the only renderCards consumers reading those rows, so normalizing
// here (not inside the shared artistTarget/cardsHtml) can't affect other callers.
function _normalizeStatsArtistItem(item) {
  return { ...item, type: "artist", name: item.artist_name || item.name || "", artist: item.artist_name || item.artist || "" };
}
function _normalizeStatsAlbumItem(item) {
  return { ...item, type: "album" };
}

function _applyStatsArtists(artists, activePeriod) {
  const items = ((artists && artists.items) || []).map(_normalizeStatsArtistItem);
  if ($("statsArtists")) {
    renderCards("statsArtists", items, "artist");
    bindStatsEntityContextMenus("statsArtists", items, "artist", () => renderStatsPage(activePeriod));
  }
  if ($("statsSeeAllArtists")) $("statsSeeAllArtists").onclick = () => pushPage(() => renderStatsArtistsPage(activePeriod));
}
function _applyStatsAlbums(albums, activePeriod) {
  const items = ((albums && albums.items) || []).map(_normalizeStatsAlbumItem);
  if ($("statsAlbums")) {
    renderCards("statsAlbums", items, "album");
    bindStatsEntityContextMenus("statsAlbums", items, "album", () => renderStatsPage(activePeriod));
  }
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
  if (container) { container.innerHTML = renderStatsTrackRows(allItems); bindStatsTrackRows("statsTracksFull", allItems, () => replacePage(() => renderStatsTracksPage(activePeriod))); }
  const total = first.total || 0;
  for (let offset = 10; offset < Math.min(total, 200); offset += 20) {
    if (!$("statsTracksFull")) break;
    const chunk = await api(`/api/stats/top-listened-tracks?${q()}&limit=20&offset=${offset}`).catch(() => ({ items: [] }));
    allItems.push(...(chunk.items || []));
    if ($("statsTracksFull")) { $("statsTracksFull").innerHTML = renderStatsTrackRows(allItems); bindStatsTrackRows("statsTracksFull", allItems, () => replacePage(() => renderStatsTracksPage(activePeriod))); }
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
  const onRemoved = () => replacePage(() => renderStatsArtistsPage(activePeriod));
  const q = () => statsQueryParams({ period: activePeriod }).toString();
  const first = await api(`/api/stats/top-listened-artists?${q()}&limit=10&offset=0`).catch(() => ({ items: [], total: 0 }));
  allItems.push(...(first.items || []).map(_normalizeStatsArtistItem));
  if ($("statsArtistsFull")) { renderCards("statsArtistsFull", allItems, "artist"); bindEntityLinks($("pageContent")); bindStatsEntityContextMenus("statsArtistsFull", allItems, "artist", onRemoved); }
  const total = first.total || 0;
  for (let offset = 10; offset < Math.min(total, 200); offset += 20) {
    if (!$("statsArtistsFull")) break;
    const chunk = await api(`/api/stats/top-listened-artists?${q()}&limit=20&offset=${offset}`).catch(() => ({ items: [] }));
    allItems.push(...(chunk.items || []).map(_normalizeStatsArtistItem));
    if ($("statsArtistsFull")) { renderCards("statsArtistsFull", allItems, "artist"); bindEntityLinks($("pageContent")); bindStatsEntityContextMenus("statsArtistsFull", allItems, "artist", onRemoved); }
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
  const onRemoved = () => replacePage(() => renderStatsAlbumsPage(activePeriod));
  const q = () => statsQueryParams({ period: activePeriod }).toString();
  const first = await api(`/api/stats/top-listened-albums?${q()}&limit=10&offset=0`).catch(() => ({ items: [], total: 0 }));
  allItems.push(...(first.items || []).map(_normalizeStatsAlbumItem));
  if ($("statsAlbumsFull")) { renderCards("statsAlbumsFull", allItems, "album"); bindEntityLinks($("pageContent")); bindStatsEntityContextMenus("statsAlbumsFull", allItems, "album", onRemoved); }
  const total = first.total || 0;
  for (let offset = 10; offset < Math.min(total, 200); offset += 20) {
    if (!$("statsAlbumsFull")) break;
    const chunk = await api(`/api/stats/top-listened-albums?${q()}&limit=20&offset=${offset}`).catch(() => ({ items: [] }));
    allItems.push(...(chunk.items || []).map(_normalizeStatsAlbumItem));
    if ($("statsAlbumsFull")) { renderCards("statsAlbumsFull", allItems, "album"); bindEntityLinks($("pageContent")); bindStatsEntityContextMenus("statsAlbumsFull", allItems, "album", onRemoved); }
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
    const col6 = isTrack ? makeLibraryBtn(idx, item.offline ? { in_library: true } : null) : "";
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
        <button class="track-actions" type="button" data-track-actions="${idx}" aria-label="More options for ${esc(item.title || item.name || "track")}"><i class="bi bi-three-dots-vertical"></i></button>
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
      if (event.target.closest("[data-track-actions]")) return;
      selectMusicItem(item, "stream", playbackQueueItems, playbackContext);
    };
    // There is no right-click on a phone, so the overflow button opens the
    // same menu — download, add to playlist, queue, go to artist/album.
    el.querySelector("[data-track-actions]")?.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      showTrackContextMenu(event, item, playbackContext || {});
    });
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
    if (isTrackItem(item) && !item.offline) acc.push(idx);
    return acc;
  }, []);
  if (!trackIdxs.length) return;

  // One request for the whole list used to mean one slow or hung response
  // left every row stuck on its Phase 1 placeholder — on a large playlist (a
  // few hundred tracks is not unusual), that single call could take minutes
  // or simply never resolve, and the existing .catch(() => {}) swallowed
  // that with no retry, so the page looked permanently out of date after any
  // revisit. Chunking bounds each request's worst case and lets the tracks a
  // user can actually see update quickly regardless of how many more are
  // further down the list.
  const CHUNK_SIZE = 40;
  const CHUNK_TIMEOUT_MS = 12000;
  const chunks = [];
  for (let i = 0; i < trackIdxs.length; i += CHUNK_SIZE) chunks.push(trackIdxs.slice(i, i + CHUNK_SIZE));

  function applyStatuses(chunkIdxs, statuses) {
    if (!container.isConnected) return;
    chunkIdxs.forEach((itemIdx, i) => {
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
  }

  async function runChunk(chunkIdxs) {
    try {
      // api() runs its own AbortController internally and ignores a `signal`
      // passed through options (its own always wins), so the timeout has to
      // go through its supported `timeout` option instead.
      const statuses = await api("/api/library/status/batch", {
        method: "POST",
        timeout: CHUNK_TIMEOUT_MS,
        body: JSON.stringify({ tracks: chunkIdxs.map(idx => serviceDownloadPayload(items[idx], "download")) }),
      });
      applyStatuses(chunkIdxs, statuses);
    } catch (_) {
      // This chunk's rows keep their Phase 1 placeholder; the rest of the
      // list is unaffected, and nothing here blocks the other chunks.
    }
  }

  // A few chunks in flight at once, not all of them — a playlist of several
  // hundred tracks would otherwise open dozens of simultaneous connections.
  const CONCURRENCY = 3;
  let next = 0;
  async function worker() {
    while (next < chunks.length) {
      const chunk = chunks[next++];
      await runChunk(chunk);
    }
  }
  Promise.all(Array.from({ length: Math.min(CONCURRENCY, chunks.length) }, worker));
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
        <div class="track-list-header artist-track-list-header">
          <div>#</div>
          <div>Title</div>
          <div class="plays-column">Plays</div>
          <div>Album</div>
          <div class="time-column"><i class="bi bi-clock"></i></div>
          <div></div>
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
  let artistTracksLoading = false;

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
    const section = $("artistTopTracksSection");
    if (section) section.classList.toggle("tracks-loading", artistTracksLoading);
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
      const gallery = Array.isArray(about?.gallery) ? about.gallery : [];
      const followers = Number(about?.followers || 0);
      const monthlyListeners = Number(about?.monthly_listeners || 0);
      const firstGalleryImg = (gallery[0] && gallery[0].url) || "";
      const previewImage = about?.hero_image || about?.avatar || firstGalleryImg || artistArtwork || "";
      const bioText = about?.biography ? String(about.biography).replace(/<[^>]*>/g, "") : "";
      const hasRenderableAbout = !!(
        about && (
          monthlyListeners > 0 ||
          followers > 0 ||
          bioText ||
          about.biography_html ||
          previewImage ||
          gallery.length ||
          ((about.top_cities || []).length > 0)
        )
      );
      if (!hasRenderableAbout) return;

      const aboutSection = $("artistAboutSection");
      aboutSection.classList.remove("hidden");
      
      const format = (n) => new Intl.NumberFormat().format(n);

      const previewMeta = monthlyListeners > 0
        ? `${format(monthlyListeners)} monthly listeners`
        : (followers > 0 ? `${format(followers)} followers` : `Source: ${about.bio_source || "Spotify"}`);

      aboutSection.innerHTML = `
        <h2 style="margin: 48px 0 24px">About</h2>
        <div class="artist-about-preview" id="artistAboutTrigger">
          <img src="${previewImage}" class="artist-about-img">
          ${about.global_chart_position ? `
            <div class="rank-badge">
              <span class="rank-label">World</span>
              <span class="rank-num">#${about.global_chart_position}</span>
            </div>
          ` : ""}
          <div class="artist-about-overlay">
          <div class="about-listeners">${esc(previewMeta)}</div>
          <div class="about-bio-preview">${esc(bioText)}</div>
          </div>
          </div>
      `;
      $("artistAboutTrigger").onclick = () => showArtistAboutModal(
        about,
        artistName,
        resolvedArtistId,
        previewImage,
      );

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
      const clearArtistLoading = () => {
        if ($("artistLoading")) $("artistLoading").remove();
      };
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
        artistTracksLoading = !!part.loading;
        $("artistTopTracksSection").classList.remove("hidden");
        redrawArtistTracks();
        clearArtistLoading();
      }
      if (part.type === "albums") {
        if (part.albums && part.albums.length) {
            artistAlbums = part.albums;
            $("artistAlbumsSection").classList.remove("hidden");
            redrawArtistAlbums();
            clearArtistLoading();
        }
      }
      if (part.type === "related_artists") {
        if (part.artists && part.artists.length) {
            artistRelated = part.artists;
            $("artistRelatedSection").classList.remove("hidden");
            redrawArtistRelated();
            clearArtistLoading();
        }
      }
    } catch (err) {}
  };

  es.addEventListener("done", () => { if ($("artistLoading")) $("artistLoading").remove(); es.close(); });
  es.onerror = (err) => { if ($("artistLoading")) $("artistLoading").remove(); es.close(); };
}

async function renderAlbumPage(album) {
  const savedPlaylistId = album?.saved_playlist_context?.kind === "playlist"
    ? album.saved_playlist_context.id
    : "";
  setActiveView("home", savedPlaylistId);
  const content = $("pageContent");
  // Show the header straight away from what the click already knows (cover,
  // album, artist); the songs fill in when the backend answers.
  const headerTitle = album.title || album.album || "";
  const headerArt = album.artwork_url || album.album_artwork_url || "";
  content.innerHTML = `
    <div class="scroll-area album-page-loading">
      <div class="entity-hero">
        <div class="album-gallery-wrap">
          <div class="entity-art album-gallery">
            ${headerArt ? `<img src="${esc(headerArt)}" alt="${esc(headerTitle)} artwork">` : ""}
          </div>
        </div>
        <div>
          <span class="eyebrow">Album</span>
          <h1 id="albumLoadingTitle">${esc(headerTitle || "Loading album…")}</h1>
          ${album.artist ? `<div class="hero-meta-row"><span class="hero-artist-link">${esc(album.artist)}</span></div>` : ""}
        </div>
      </div>
      <div class="loading"><div class="spinner"></div><span>Loading songs…</span></div>
    </div>`;

  const loadingState = content.firstElementChild;
  try {
    let artistName = album.artist || "";
    let albumTitle = album.title || album.album || "";
    const releaseId = album.musicbrainz_release_id || "";
    let spotifyId = album.spotify_id || "";

    // Opened from a track that carries no album name or id (e.g. a queue or
    // top-tracks entry): ask which album it is first. That small lookup is
    // answered from the database once known, so the header shows the album
    // name long before the songs, which are then loaded straight by album id.
    if (!spotifyId && album.track_spotify_id) {
      const found = await api(`/api/music/track_album?spotify_id=${encodeURIComponent(album.track_spotify_id)}`).catch(() => null);
      if (content.firstElementChild !== loadingState) return;
      if (found?.album_spotify_id) {
        spotifyId = found.album_spotify_id;
        albumTitle = found.album || albumTitle;
        artistName = found.album_artist || found.artist || artistName;
        const titleEl = $("albumLoadingTitle");
        if (titleEl && albumTitle) titleEl.textContent = albumTitle;
      }
    }

    const params = new URLSearchParams({
      artist: artistName, album: albumTitle, release_id: releaseId, spotify_id: spotifyId,
      track_spotify_id: spotifyId ? "" : (album.track_spotify_id || ""),
    });
    let data = await api(`/api/music/album_tracks?${params}&details=0`);
    if (content.firstElementChild !== loadingState) return;
    const savedTracks = album.saved_playlist_context?.tracks || album.tracks || [];
    const useSavedTracks = Array.isArray(savedTracks) && savedTracks.length > 0;
    if (useSavedTracks) {
      data = {
        ...data,
        tracks: savedTracks,
        track_count: savedTracks.length,
        total_duration: data.total_duration || formatDuration(savedTracks),
        _extras_complete: true,
      };
    }
    data.tracks = (data.tracks || []).map(track => ({
      ...track,
      album_spotify_id: data.spotify_id || spotifyId || track.album_spotify_id || "",
      album_artist: data.artist || artistName || track.album_artist || "",
      album: data.album || albumTitle || track.album || "",
      album_context: (data.spotify_id || spotifyId) ? {
        spotify_id: data.spotify_id || spotifyId,
        album: data.album || albumTitle,
        album_artist: data.artist || artistName,
        artwork_url: data.artwork_url || headerArt,
      } : track.album_context,
    }));
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

                <button class="gallery-arrow previous${hasMultipleImages ? "" : " hidden"}" id="albumGalleryPrevious" type="button" aria-label="Previous album image"><i class="bi bi-chevron-left"></i></button>
                <button class="gallery-arrow next${hasMultipleImages ? "" : " hidden"}" id="albumGalleryNext" type="button" aria-label="Next album image"><i class="bi bi-chevron-right"></i></button>
                <span class="gallery-position${hasMultipleImages ? "" : " hidden"}" id="albumGalleryPosition">1 / ${galleryImages.length}</span>

            </div>

              <div class="discogs-attribution ${firstImage.source === "Discogs" ? "" : "hidden"}" id="discogsAttribution">
                <a href="${esc(data.discogs_release_url)}" target="_blank" rel="noopener">Data provided by Discogs</a>
                <span>This application uses Discogs' API but is not affiliated with, sponsored or endorsed by Discogs.</span>
              </div>

          </div>
          <div>
            <span class="eyebrow">Album</span>
            <h1>${esc(data.album)}</h1>
            <div class="hero-meta-row" id="albumHeroMeta">
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

            <button class="album-image-modal-arrow previous${hasMultipleImages ? "" : " hidden"}" id="albumImageModalPrevious" type="button" aria-label="Previous enlarged album image"><i class="bi bi-chevron-left"></i></button>
            <button class="album-image-modal-arrow next${hasMultipleImages ? "" : " hidden"}" id="albumImageModalNext" type="button" aria-label="Next enlarged album image"><i class="bi bi-chevron-right"></i></button>

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
      if (!galleryImages.length) return;
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
    renderTrackList("albumTrackList", data.tracks || [], "album", album.saved_playlist_context || null);
    const trackList = $("albumTrackList");
    if (data._extras_complete === false && !useSavedTracks) {
      // Artwork scans and secondary metadata must never delay playable tracks.
      api(`/api/music/album_tracks?${params}`, { timeout: 90000 }).then(details => {
        if ($("albumTrackList") !== trackList) return;
        const displayedTracks = data.tracks || [];
        Object.assign(data, details, { tracks: displayedTracks });
        const enrichedImages = details.gallery_images || [];
        if (enrichedImages.length) {
          galleryImages.splice(0, galleryImages.length, ...enrichedImages);
          const multiple = galleryImages.length > 1;
          $("albumGallery").classList.toggle("has-slides", multiple);
          for (const id of ["albumGalleryPrevious", "albumGalleryNext", "albumGalleryPosition", "albumImageModalPrevious", "albumImageModalNext"]) {
            $(id)?.classList.toggle("hidden", !multiple);
          }
          if (discogsAttribution) {
            discogsAttribution.querySelector("a").href = details.discogs_release_url || "#";
          }
          if (!albumImageModal.open) showGalleryImage(galleryIndex);
        }
        const heroArtist = $("heroArtistLink");
        const image = details.artist_artwork_url || artistArtwork;
        heroArtist.innerHTML = `${image ? `<div class="mini-art" style="background-image: url('${esc(image)}')"></div>` : ""}${esc(data.artist)}`;
        const meta = [details.year || year, `${data.track_count} tracks`, data.total_duration].filter(Boolean);
        $("albumHeroMeta").querySelectorAll(":scope > span").forEach(el => el.remove());
        $("albumHeroMeta").insertAdjacentHTML("beforeend", meta.map(value => `<span class="dot">•</span><span>${esc(value)}</span>`).join(""));
        trackList.querySelectorAll(".track-row").forEach((row, index) => {
          const enriched = details.tracks?.[index];
          if (!enriched) return;
          Object.assign(data.tracks[index], enriched);
          row.dataset.itemData = JSON.stringify(data.tracks[index]);
          const count = row.querySelector(".views-count");
          if (count) count.textContent = trackPlaysValue(enriched) ? trackPlaysValue(enriched).toLocaleString() : "-";
        });
      }).catch(() => {});
    }
  } catch (e) {
    if (content.firstElementChild === loadingState) {
      content.innerHTML = `<div class="error-state">Failed to load album: ${esc(e.message)}</div>`;
    }
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
  state.rebuffering = false;
  state.audioBuffering = false;
  state.audioHasPlayed = false;
  state.directStreamPosition = 0;
  state.directStreamReconnectPending = false;
  state.directStreamReconnectAttempts = 0;
  state.directStreamResumePending = false;
  state.directStreamNativeFallbackAttempted = false;
  if (state.directStreamReconnectTimer) clearTimeout(state.directStreamReconnectTimer);
  state.directStreamReconnectTimer = null;
  state.rebufferPosition = 0;
  state.rebufferAfterBytes = 0;
  state.lastActiveReadyBytes = 0;
  state.manualPauseRequested = false;
  state.activeJobId = null;
  state.currentTrack = item;
  state.currentLibraryPath = ""; // Clear path for new selection
  state.videoFetch = { trackKey: trackKey(item), status: "", path: "" };
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

  // Offline playback must use the saved file even if the selected provider's
  // preferred quality is higher than this download's quality.
  if (item.offline && item.library_path) {
    await playFromLibraryPath(item.library_path, item, requestId, null, "Playing offline");
    return;
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

function isMonochromeDirectStreamUrl(url) {
  return typeof url === "string" && /^https:\/\/tracks\.monochrome\.st\/track\/\d+/.test(url);
}

// WebView and native playback share one buffered fetch. Sync reads this
// already playing audio, including when the selected output is the browser.
function browserAudioStreamUrl(url) {
  return isMonochromeDirectStreamUrl(url)
    ? `/api/monochrome/stream?url=${encodeURIComponent(url.split("?")[0])}` : url;
}

function knownTrackDurationSeconds(track = state.currentTrack) {
  const candidates = [
    track?.duration_ms,
    track?.metadata?.duration_ms,
    track?.duration?.totalMilliseconds,
    track?.metadata?.duration?.totalMilliseconds,
    track?.duration,
    track?.metadata?.duration,
    track?.length,
  ];
  for (const value of candidates) {
    if (typeof value === "number" && Number.isFinite(value) && value > 0) {
      return value > 1000 ? value / 1000 : value;
    }
    if (typeof value === "string") {
      const clock = value.trim().match(/^(\d+):(\d{2})(?::(\d{2}))?$/);
      if (clock) {
        return clock[3]
          ? Number(clock[1]) * 3600 + Number(clock[2]) * 60 + Number(clock[3])
          : Number(clock[1]) * 60 + Number(clock[2]);
      }
      const numeric = Number(value);
      if (Number.isFinite(numeric) && numeric > 0) return numeric > 1000 ? numeric / 1000 : numeric;
    }
  }
  return 0;
}

function isLibraryStreamUrl(url) {
  if (!url || isActiveJobStreamUrl(url)) return false;
  try {
    return new URL(url, window.location.origin).pathname === "/api/library/stream";
  } catch (e) {
    return url.includes("/api/library/stream?") && !url.includes("/api/library/stream_active_job");
  }
}

async function activeJobStillRunning(jobId) {
  if (!jobId) return false;
  const data = await api("/api/service/downloads").catch(() => null);
  if (!data) return true;
  const job = data && Array.isArray(data.jobs) ? data.jobs.find(item => item.id === jobId) : null;
  return !!job && (job.status === "starting" || job.status === "running");
}

async function reconnectActiveJobStream(audio, requestId, jobId, position = 0) {
  if (!audio || requestId !== state.playbackRequestId || state.activeJobId !== jobId || !jobId) return;
  const streamUrl = `${API_BASE}/api/library/stream_active_job?job_id=${jobId}&t=${Date.now()}`;
  state.currentStreamUrl = streamUrl;
  state.currentPlayableReady = true;
  state.autoplayWanted = !state.manualPauseRequested;
  audio.src = browserAudioStreamUrl(streamUrl);
  audio.load();
  if (Number.isFinite(position) && position > 0) {
    const applyResume = () => {
      seekAfterMetadata(audio, position);
      audio.removeEventListener("loadedmetadata", applyResume);
    };
    audio.addEventListener("loadedmetadata", applyResume);
  }
  if (!state.manualPauseRequested && state.currentTrack) {
    tryStartAudio(audio, state.currentTrack, requestId, jobId);
  }
}

function seekAfterMetadata(audio, position) {
  const target = Number(position);
  if (!Number.isFinite(target) || target <= 0) return;

  // A media element may ignore currentTime assignments until metadata or a
  // seekable range exists. Keep retrying after load instead of removing the
  // listeners after an early, silently ignored assignment.
  if (audio._resumeSeekHandler) {
    for (const eventName of ["loadedmetadata", "durationchange", "progress", "canplay", "seeked"]) {
      audio.removeEventListener(eventName, audio._resumeSeekHandler);
    }
  }
  const apply = () => {
    if (audio.readyState < 1 && !audio.seekable?.length) return;
    const duration = Number(audio.duration);
    const seekTarget = Number.isFinite(duration) && duration > 0
      ? Math.max(0, Math.min(target, Math.max(0, duration - 0.25)))
      : target;
    try {
      if (Math.abs(Number(audio.currentTime || 0) - seekTarget) < 0.5) {
        cleanup();
        return;
      }
      audio.currentTime = seekTarget;
      if (audio.seeking || Math.abs(Number(audio.currentTime || 0) - seekTarget) < 0.5) cleanup();
    } catch (e) {
      // Some WebKit builds only enable seeking after the next range arrives.
      // Keep the listeners so a later progress/canplay event gets another try.
    }
  };
  const cleanup = () => {
    for (const eventName of ["loadedmetadata", "durationchange", "progress", "canplay", "seeked"]) {
      audio.removeEventListener(eventName, apply);
    }
    audio._resumeSeekHandler = null;
  };
  audio._resumeSeekHandler = apply;
  for (const eventName of ["loadedmetadata", "durationchange", "progress", "canplay", "seeked"]) {
    audio.addEventListener(eventName, apply);
  }
  apply();
}

async function playFromLibraryPath(filePath, track, requestId, jobId, statusText = "Playing from library", startAt = 0) {
  if (requestId !== state.playbackRequestId) return;
  state.rebuffering = false;
  state.rebufferAfterBytes = 0;
  state.rebufferPosition = 0;
  const pendingResume = Number(state.pendingResumePosition || 0);
  if ((!Number.isFinite(startAt) || startAt <= 0) && pendingResume > 0) {
    startAt = pendingResume;
  }
  if (pendingResume > 0) state.pendingResumePosition = 0;
  console.log(`[Player] playFromLibraryPath: ${filePath} (startAt: ${startAt})`);
  state.currentLibraryPath = filePath;
  if (state.videoMode && isVideoLibraryPath(filePath)) {
    renderSideCover(track || state.currentTrack);
  }
  state.pendingNativeStartAt = 0;
  const streamUrl = `${API_BASE}/api/library/stream?path=${encodeURIComponent(filePath)}&t=${Date.now()}&audio=1`;
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
  audio.src = browserAudioStreamUrl(streamUrl);
  state.currentPlayableReady = true;
  state.autoplayWanted = true;
  
  setPlayerStatusIcon("ready");
  setPlayerStatus(statusText, track);
  audio.load();
  seekAfterMetadata(audio, startAt);
  syncPlayPauseButton();
  tryStartAudio(audio, track, requestId, jobId);
  if (track && !canSwitchToLocalVideo(track)) fetchVideoForTrack(track).catch(() => {});
  // Restart side-video from the beginning so it stays in sync with the audio.
  const _sv = $("sideVideoPlayer");
  if (_sv && _sv.tagName === "VIDEO" && state.videoMode) { _sv.currentTime = 0; _sv.play().catch(() => {}); }
}

async function resumeBrowserAudioFromStableSource(audio) {
  if (!audio) return;
  console.log("[Player] resumeBrowserAudioFromStableSource, current src:", audio.src);
  state.manualPauseRequested = false;
  if (isMonochromeDirectStreamUrl(state.currentStreamUrl)) {
    // Reopen a local range at the saved playhead using the shared buffer.
    const resumeAt = Number.isFinite(audio.currentTime) && audio.currentTime > 0
      ? audio.currentTime : Number(state.directStreamPosition || state.rebufferPosition || 0);
    state.directStreamAttemptPosition = resumeAt;
    state.autoplayWanted = true;
    state.rebuffering = false;
    state.audioBuffering = true;
    state.directStreamResumePending = true;
    syncPlayPauseButton();
    audio.src = browserAudioStreamUrl(state.currentStreamUrl);
    audio.load();
    seekAfterMetadata(audio, resumeAt);
    tryStartAudio(audio, state.currentTrack, state.playbackRequestId, null);
    return;
  }
  if (state.activeJobId && isActiveJobStreamUrl(state.currentStreamUrl)) {
    // Pausing closes WebKit's current ranged HTTP response. Reopen the active
    // job stream at the saved playhead so resume continues from that byte range
    // instead of reusing a dead response (or restarting the track).
    const resumeAt = Number.isFinite(audio.currentTime) ? audio.currentTime : 0;
    state.rebuffering = false;
    state.rebufferAfterBytes = 0;
    await reconnectActiveJobStream(audio, state.playbackRequestId, state.activeJobId, resumeAt);
    return;
  }
  if (state.rebuffering && isActiveJobStreamUrl(state.currentStreamUrl)) {
    state.autoplayWanted = true;
    return;
  }
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
    if (state.activeJobId && isActiveJobStreamUrl(state.currentStreamUrl)) {
      waitForActiveJobBuffer(audio);
      return;
    }
    const key = trackKey(state.currentTrack);
    if (state.currentTrack && error.name !== "NotAllowedError" && error.name !== "AbortError") {
      if (state.lastAutoRetryKey === key) {
          console.warn("[Player] Already tried re-resolving this track, stopping loop.");
          setPlayerStatus("Playback failed", state.currentTrack);
          return;
      }
      state.lastAutoRetryKey = key;
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
  if (isMonochromeDirectStreamUrl(state.currentStreamUrl) && Number.isFinite(audio?.currentTime)) {
    state.directStreamPosition = audio.currentTime || state.directStreamPosition || 0;
  }
  state.directStreamReconnectPending = false;
  state.directStreamReconnectAttempts = 0;
  state.directStreamResumePending = false;
  // A user pause is a stable state, not a buffering condition. WebKit may
  // emit `waiting` or a late media error after closing the active range.
  state.audioBuffering = false;
  if (state.directStreamReconnectTimer) clearTimeout(state.directStreamReconnectTimer);
  state.directStreamReconnectTimer = null;
  if (audio) audio.pause();
  if (state.currentTrack) setPlayerStatus("Paused", state.currentTrack);
  syncPlayPauseButton();
}

const _monochromePlaybackLogTimes = new Map();
function logMonochromePlaybackActivity(message, track = state.currentTrack, key = message, cooldownMs = 1000) {
  const now = Date.now();
  const dedupeKey = `${trackKey(track || {})}:${key}`;
  const last = _monochromePlaybackLogTimes.get(dedupeKey) || 0;
  if (now - last < cooldownMs) return;
  _monochromePlaybackLogTimes.set(dedupeKey, now);
  if (_monochromePlaybackLogTimes.size > 100) {
    for (const [entry, timestamp] of _monochromePlaybackLogTimes) {
      if (now - timestamp > 60000) _monochromePlaybackLogTimes.delete(entry);
    }
  }
  api("/api/cache/logs", {
    method: "POST",
    body: JSON.stringify({ message, title: track?.title || "Monochrome stream" }),
  }).catch(() => {});
}

const MAX_MONOCHROME_BROWSER_RECONNECTS = 4;

function reconnectMonochromeAfterBuffer(audio) {
  if (!audio || state.manualPauseRequested || state.directStreamReconnectPending ||
      !isMonochromeDirectStreamUrl(state.currentStreamUrl)) return;
  const requestId = state.playbackRequestId;
  let resumeAt = Number.isFinite(audio.currentTime) && audio.currentTime > 0
    ? audio.currentTime : Number(state.directStreamPosition || state.rebufferPosition || 0);
  if ((state.directStreamReconnectPending || state.directStreamResumePending) &&
      resumeAt + 0.75 < Number(state.directStreamAttemptPosition || 0)) {
    resumeAt = Math.max(resumeAt, Number(state.directStreamAttemptPosition || 0), Number(state.directStreamPosition || 0));
  }
  // The browser/WebView <audio> element hides HTTP status, so a Monochrome
  // 429/403 only looks like a stream that will not come back. Each reconnect
  // is another request, which keeps a rate limit going; after a few in a row
  // without audio, start the backend cooldown and play the track from YouTube.
  // (Attempts reset to 0 whenever audio plays again.)
  if (state.directStreamReconnectAttempts >= MAX_MONOCHROME_BROWSER_RECONNECTS) {
    const track = state.currentTrack;
    state.directStreamReconnectAttempts = 0;
    api("/api/monochrome/stream_failing", { method: "POST", body: "{}" })
      .catch(() => null)
      .then((result) => {
        if (requestId !== state.playbackRequestId) return;
        audio.pause();
        audio.removeAttribute("src");
        audio.load();
        fallbackFromBlockedMonochrome(track, requestId, result?.reason || "Monochrome stream kept failing");
      });
    return;
  }
  state.directStreamReconnectPending = true;
  state.directStreamReconnectAttempts += 1;
  state.directStreamAttemptPosition = resumeAt;
  state.rebufferPosition = resumeAt;
  logMonochromePlaybackActivity(
    `Monochrome stream buffering at ${formatTime(resumeAt)}; retry ${state.directStreamReconnectAttempts} in 5s`,
    state.currentTrack,
    `retry-${state.directStreamReconnectAttempts}`,
  );
  state.directStreamReconnectTimer = setTimeout(async () => {
    state.directStreamReconnectTimer = null;
    if (requestId !== state.playbackRequestId || state.manualPauseRequested ||
        !isMonochromeDirectStreamUrl(state.currentStreamUrl)) {
      state.directStreamReconnectPending = false;
      return;
    }
    // WebKit can leave a stalled range response in a non-paused state forever.
    // Reopen the Monochrome URL at the saved playhead to request a fresh range.
    audio.pause();
    await resumeBrowserAudioFromStableSource(audio).catch((error) => {
      console.warn("[Player] Monochrome buffer reconnect failed:", error);
      state.directStreamReconnectPending = false;
    });
    if (requestId === state.playbackRequestId && state.directStreamReconnectPending) {
      state.directStreamReconnectTimer = setTimeout(() => {
        state.directStreamReconnectTimer = null;
        if (requestId !== state.playbackRequestId || state.manualPauseRequested ||
            !state.directStreamReconnectPending) return;
        state.directStreamReconnectPending = false;
        reconnectMonochromeAfterBuffer(audio);
      }, Math.min(30000, 5000 * Math.pow(1.5, Math.min(state.directStreamReconnectAttempts - 1, 8))));
    }
  }, 5000);
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
  state.playerStatusIconMode = mode;
  state.playerStatusIconPct = pct || 0;
  renderPlayerStatusIcon();
}

function renderPlayerStatusIcon() {
  const icon = $("playerStatusIcon");
  if (!icon) return;
  // Keep the ready check as the underlying state, but show the established
  // animated pie while playback is waiting for audio data.
  const mode = state.audioBuffering && state.playerStatusIconMode === "ready"
    ? "buffering" : state.playerStatusIconMode;
  const pct = state.playerStatusIconPct;
  const renderKey = `${mode}:${mode === "downloading" ? Math.round(pct || 0) : 0}`;
  if (state.renderedPlayerStatusIcon === renderKey) return;
  state.renderedPlayerStatusIcon = renderKey;
  icon.className = "player-status " + (mode === "ready" ? "ready" : mode === "error" ? "error" : mode === "buffering" ? "buffering" : "downloading");
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
  state.currentStreamUrl = "";
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
  // Treat track resolution as busy too. The animated status pie appears as
  // soon as a new selection starts, so the transport must lock at that point.
  // Restored paused snapshots remain playable.
  state.audioBuffering = !/^Paused(?:\b| at\b)/i.test(String(status));
  setPlayerStatusIcon("downloading", 0);
  setPlayerStatus(status, track);
  syncActiveTrackRows();
  syncPlayPauseButton();
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
    if (!canSwitchToLocalVideo(track)) fetchVideoForTrack(track).catch(() => {});
    prefetchLyricsForTrack(track);
    if (state.lyrics.open && state.lyrics.trackKey !== trackKey(track)) {
      loadLyricsForTrack(track, { force: true }).catch(() => {});
    }
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
  const ready = Number(job?.active_audio_ready_bytes || 0);
  const total = Number(job?.active_audio_size || 0);
  const duration = Number(state.currentTrack?.duration_ms || state.currentTrack?.length || 0) / 1000;
  const position = Math.max(0, Number(state.rebufferPosition || 0));
  const target = Math.max(512 * 1024, duration > 0 && total > 0 ? total * (position + 1.5) / duration : 0);
  const required = total > 0 ? Math.min(total, target) : target;
  return ready >= required && ready >= Math.min(total || Infinity, Number(state.rebufferAfterBytes || 0));
}

function waitForActiveJobBuffer(audio) {
  state.rebufferPosition = Number.isFinite(audio?.currentTime) ? audio.currentTime : 0;
  state.rebufferAfterBytes = Number(state.lastActiveReadyBytes || 0) + 1024 * 1024;
  state.rebuffering = true;
  state.currentPlayableReady = false;
  state.autoplayWanted = !state.manualPauseRequested;
  audio?.pause();
  if (state.currentTrack) setPlayerStatus("Buffering more audio...", state.currentTrack);
}

function isVideoLibraryPath(path) {
  const ext = String(path || "").split("?")[0].split(".").pop().toLowerCase();
  return ["mp4", "webm", "mov", "mkv", "ogv"].includes(ext);
}

function canSwitchToLocalVideo(track = state.currentTrack) {
  if (!track || !state.currentLibraryPath || !isVideoLibraryPath(state.currentLibraryPath)) return false;
  // ytp-dl downloads audio as .mp4 containers — only treat them as real video
  // when the quality is explicitly set to the music-video mode.
  if ((state.settings.download_engine || "") === "ytp-dl" &&
      (state.settings.default_quality || "") !== "video") return false;
  return true;
}

function canSwitchToVideo(track = state.currentTrack) {
  if (!track || (!track.title && !track.artist)) return false;
  return canSwitchToLocalVideo(track) ||
    state.videoFetch.status === "ready" ||
    state.videoFetch.status === "downloading" ||
    state.videoFetch.status === "error" ||
    state.videoFetch.status === "not_found";
}

function localMediaStreamUrl(filePath) {
  return `${API_BASE}/api/library/stream?path=${encodeURIComponent(filePath)}&t=${Date.now()}`;
}


async function fetchVideoForTrack(track, { force = false } = {}) {
  if (track?.offline) return;
  const key = trackKey(track || {});
  if (!track) return state.videoFetch;
  if (!force && state.videoFetch.trackKey === key) {
    const s = state.videoFetch.status;
      if (s === "ready" || s === "not_found" || s === "downloading") return state.videoFetch;
  }
  state.videoFetch = { trackKey: key, status: "downloading", path: "" };
  renderSideVideoButton();
  const params = new URLSearchParams({
    artist: track.artist || "",
    title: track.title || "",
    album: track.album || "",
    track_key: key,
    ...(track.duration_ms ? { duration_ms: String(track.duration_ms) } : {}),
    ...(force ? { force: "1" } : {}),
  });
  for (let attempt = 0; attempt < 60; attempt++) {
    if (state.videoFetch.trackKey !== key) return state.videoFetch;
    // Only send force=1 on the first poll; subsequent retries are normal checks
    if (attempt === 1) params.delete("force");
    try {
      const data = await api(`/api/video/fetch?${params.toString()}`);
      if (state.videoFetch.trackKey !== key) return state.videoFetch;
      state.videoFetch = { trackKey: key, status: data.status || "not_found", path: data.path || "" };
      if (state.videoFetch.status === "not_found" && state.videoMode && state.sideVideoTrackKey === key) {
        state.videoMode = false;
        state.sideVideoTrackKey = "";
        renderSideCover(track);
      }
      renderSideVideoButton();
      if (data.status === "ready" || data.status === "not_found" || data.status === "error") {
        if (data.status === "error") {
          state.videoMode = false;
          state.sideVideoTrackKey = "";
          renderSideCover(track);
          showToast(data.error || "Video download failed. Try again.", 6000);
        }
        if (data.status === "not_found") showToast("No video found for this track");
        if (state.videoMode && state.sideVideoTrackKey === key && data.status === "ready") {
          renderSideCover(track);
        }
        return state.videoFetch;
      }
    } catch (_) {}
    await new Promise((r) => setTimeout(r, 3000));
  }
  // Timed out — treat as not found
  if (state.videoFetch.trackKey === key) {
    state.videoFetch = { trackKey: key, status: "not_found", path: "" };
    if (state.videoMode && state.sideVideoTrackKey === key) {
      state.videoMode = false;
      state.sideVideoTrackKey = "";
      renderSideCover(track);
    }
    renderSideVideoButton();
    showToast("No video found for this track");
  }
  return state.videoFetch;
}

function showToast(msg, durationMs = 3000) {
  let el = document.getElementById("appToast");
  if (!el) {
    el = document.createElement("div");
    el.id = "appToast";
    el.className = "app-toast";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.remove("app-toast-actionable");
  el.classList.remove("app-toast-hide");
  el.classList.add("app-toast-show");
  clearTimeout(el._hideTimer);
  el._hideTimer = setTimeout(() => {
    el.classList.remove("app-toast-show");
    el.classList.add("app-toast-hide");
  }, durationMs);
}

let youtubeLoginFlow = null;

function showActionToast(message, actionLabel, onAction) {
  let el = document.getElementById("appToast");
  if (!el) {
    el = document.createElement("div");
    el.id = "appToast";
    el.className = "app-toast";
    document.body.appendChild(el);
  }
  clearTimeout(el._hideTimer);
  el.innerHTML = `<span>${esc(message)}</span><button type="button" class="app-toast-action">${esc(actionLabel)}</button>`;
  el.classList.add("app-toast-actionable", "app-toast-show");
  el.classList.remove("app-toast-hide");
  el.querySelector(".app-toast-action").onclick = onAction;
}

function hideActionToast() {
  const el = document.getElementById("appToast");
  if (!el) return;
  el.classList.remove("app-toast-show", "app-toast-actionable");
  el.classList.add("app-toast-hide");
}

function requestYoutubeLoginAndRetry(job, retryDownload) {
  if (youtubeLoginFlow) return;
  const flow = { retrying: false, loginOpened: false, loginPoll: null };
  youtubeLoginFlow = flow;
  api("/api/system/notify", {
    method: "POST",
    body: JSON.stringify({
      title: "YouTube login required",
      message: "Use Log in in Mindinguflac to sign in, then retry the track.",
      url: job.youtube_login_url || "https://www.youtube.com/",
    }),
  }).catch(() => {});

  let retryArmed = false;
  let leftApp = document.hidden || !document.hasFocus();
  const cleanupReturnWatcher = () => {
    window.removeEventListener("blur", onAway);
    window.removeEventListener("focus", onReturn);
    document.removeEventListener("visibilitychange", onVisibilityChange);
  };
  const onAway = () => { leftApp = true; };
  const onReturn = async () => {
    if (retryArmed && leftApp && document.visibilityState !== "hidden") {
      try {
        const status = await api("/api/system/youtube-login-status", { method: "POST", body: JSON.stringify({}) });
        if (status.signed_in && (!status.embedded_available || status.login_outcome === "completed")) await retryOnce();
      } catch (_) {}
    }
  };
  const onVisibilityChange = () => {
    if (document.hidden) onAway();
    else onReturn();
  };

  const retryOnce = async () => {
    if (flow.retrying) return;
    flow.retrying = true;
    if (flow.loginPoll) clearInterval(flow.loginPoll);
    cleanupReturnWatcher();
    hideActionToast();
    youtubeLoginFlow = null;
    try {
      await retryDownload();
    } catch (error) {
      showToast(error.message || "YouTube retry failed", 5000);
    }
  };

  // Arm this before either notification is clicked. A native macOS/Windows
  // banner opens the browser outside the webview, so it must share the same
  // leave-app/return watcher as the in-app Log in button.
  window.addEventListener("blur", onAway);
  window.addEventListener("focus", onReturn);
  document.addEventListener("visibilitychange", onVisibilityChange);
  setTimeout(() => { retryArmed = true; }, 750);

  showActionToast("YouTube login required to download this track.", "Log in", async () => {
    try {
      const opened = await api("/api/system/open-url", {
        method: "POST",
        body: JSON.stringify({ url: job.youtube_login_url || "https://www.youtube.com/" }),
      });
      flow.embedded = !!opened.embedded;
    } catch (error) {
      cleanupReturnWatcher();
      showToast(error.message || "Could not open the browser", 5000);
      youtubeLoginFlow = null;
      return;
    }

    flow.loginOpened = true;
    // Opening the system browser does not reliably blur/focus the macOS
    // webview.  Poll the local cookie store so a completed sign-in retries
    // even when those browser events are never delivered.
    flow.loginPoll = setInterval(async () => {
      if (flow.retrying || !flow.loginOpened) return;
      try {
        const status = await api("/api/system/youtube-login-status", { method: "POST", body: JSON.stringify({}) });
        if (status && status.signed_in && (!flow.embedded || status.login_outcome === "completed")) await retryOnce();
      } catch (_) {}
    }, 2000);
    showActionToast(flow.embedded ? "Sign in in the YouTube window. The download will retry automatically." : "Sign in to YouTube, then return to Mindinguflac.", "Retry now", retryOnce);
  });
}

function renderSideVideoButton() {
  const button = $("sideVideoSwitch");
  const refresh = $("sideVideoRefresh");
  if (!button) return;
  const hasUsableVideo = canSwitchToLocalVideo() || (state.videoFetch.status === "ready" && !!state.videoFetch.path);
  const available = (state.videoMode && hasUsableVideo) || canSwitchToVideo();
  button.hidden = !available;
  button.classList.toggle("active", !!state.videoMode && hasUsableVideo);
  if (state.videoMode && hasUsableVideo) {
    button.innerHTML = '<i class="bi bi-music-note-beamed"></i><span>Switch to audio</span>';
  } else if (state.videoFetch.status === "downloading") {
    button.innerHTML = '<i class="bi bi-hourglass-split"></i><span>Loading video…</span>';
  } else if (state.videoFetch.status === "not_found") {
    button.innerHTML = '<i class="bi bi-camera-video-off"></i><span>No video</span>';
  } else {
    button.innerHTML = '<i class="bi bi-play-btn"></i><span>Switch to video</span>';
  }
  if (refresh) refresh.hidden = !(state.videoMode && hasUsableVideo);
  renderVideoSyncControls();
}

function renderSideCover(track) {
  const cover = $("sideCover");
  const media = $("sideCoverMedia");
  const playerCover = document.querySelector(".player-cover");
  const url = track?.artwork_url || "";
  if (playerCover) {
    playerCover.style.backgroundImage = url ? `url('${url}')` : "";
    playerCover.innerHTML = url ? "" : `<i class="bi bi-music-note"></i>`;
  }
  if (!cover) return;
  if (media) {
    const currentTime = currentPlaybackSeconds();
    const hasLocalVideo = canSwitchToLocalVideo(track);
    const hasFetchedVideo = !hasLocalVideo && state.videoFetch.status === "ready" && !!state.videoFetch.path;
    const videoFilePath = hasLocalVideo ? state.currentLibraryPath : (hasFetchedVideo ? state.videoFetch.path : "");
    if (state.videoMode && videoFilePath) {
      const existingVideo = $("sideVideoPlayer");
      const existingSrc = existingVideo && existingVideo.tagName === "VIDEO" ? existingVideo.dataset.filePath || "" : "";
      cover.classList.add("video-mode");
      if (existingSrc !== videoFilePath) {
        const videoSrc = localMediaStreamUrl(videoFilePath);
        media.style.backgroundImage = "";
        media.innerHTML = `<video id="sideVideoPlayer" playsinline muted src="${esc(videoSrc)}" data-file-path="${esc(videoFilePath)}"></video>`;
        const video = $("sideVideoPlayer");
        refreshVideoSync().catch(() => {});
        if (video) {
          video.addEventListener("loadedmetadata", () => {
            syncLocalVideoOverlay(currentTime, false, { allowSeek: true });
          }, { once: true });
          // canplay fires after the seek from loadedmetadata completes and the
          // video actually has data to render — more reliable than loadedmetadata
          // for starting playback, especially when re-entering video mode mid-song.
          video.addEventListener("canplay", () => {
            if (!state.manualPauseRequested && isPlaybackVisiblyActive()) {
              video.play().catch(() => {});
            }
          }, { once: true });
        }
      }
    } else {
      cover.classList.remove("video-mode");
      media.innerHTML = url ? "" : `<i class="bi bi-music-note"></i>`;
      media.style.backgroundImage = url ? `url('${url}')` : "";
    }
  } else {
    cover.classList.remove("video-mode");
    cover.style.backgroundImage = url ? `url('${url}')` : "";
    cover.innerHTML = url ? "" : `<i class="bi bi-music-note"></i>`;
  }
  renderSideVideoButton();
}

function switchSideVideoMode(enabled) {
  state.videoMode = !!enabled;
  state.sideVideoTrackKey = state.videoMode ? trackKey(state.currentTrack) : "";
  if (state.videoMode && state.currentTrack && !canSwitchToLocalVideo()) {
    fetchVideoForTrack(state.currentTrack, { force: false }).catch(() => {});
  }
  renderSideCover(state.currentTrack);
}

function updateDetailsPanel(track, job = null) {
  if (state.videoMode) state.sideVideoTrackKey = trackKey(track);
  renderSideCover(track);
  if (!canSwitchToLocalVideo(track)) fetchVideoForTrack(track).catch(() => {});
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
  const followers = Number(about.followers || 0);
  const monthlyListeners = Number(about.monthly_listeners || 0);
  const statsHtml = [
    followers > 0 ? `<div class="about-stat-item"><b>${formatCount(followers)}</b><span>Followers</span></div>` : "",
    monthlyListeners > 0 ? `<div class="about-stat-item"><b>${formatCount(monthlyListeners)}</b><span>Monthly Listeners</span></div>` : "",
  ].filter(Boolean).join("");
  const source = about.bio_source ? String(about.bio_source) : "";
  const galleryUrls = [];
  const seenGallery = new Set();
  for (const img of gallery) {
    const url = String(img?.url || "").trim();
    if (!url || seenGallery.has(url)) continue;
    seenGallery.add(url);
    galleryUrls.push(url);
  }
  if (heroImage && !seenGallery.has(heroImage)) {
    galleryUrls.unshift(heroImage);
  }
  const topCities = Array.isArray(about.top_cities) ? about.top_cities : [];
  const dialog = document.createElement("dialog");
  dialog.className = "about-modal";
  dialog.id = "sidebarArtistAboutModal";
  dialog.innerHTML = `
    <button class="about-close" type="button" aria-label="Close"><i class="bi bi-x-lg"></i></button>
    <div class="about-modal-content">
      ${galleryUrls.length ? `
        <div class="about-gallery">
          ${galleryUrls.map(url => `<img src="${url}" loading="lazy">`).join("")}
        </div>
      ` : ""}
      <div class="about-modal-grid">
        <div>
        ${statsHtml ? `<div class="about-stat-row">${statsHtml}</div>` : ""}
        <div class="about-bio-full">${bioHtml}</div>
        ${source ? `<div class="bio-source">Source: ${esc(source)}</div>` : ""}
        </div>
        <div>
        ${topCities.length ? `
          <h3>Where people listen</h3>
          <ul class="top-cities-list">
            ${topCities.slice(0, 8).map(c => `
              <li><b>${esc(c.city)}, ${esc(c.country)}</b><span>${formatCount(c.count)} listeners</span></li>
            `).join("")}
          </ul>
        ` : ""}
        </div>
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
  const spotifyId = trackIdentityValue(track, "spotify_id");
  const isrc = trackIdentityValue(track, "isrc");
  const selectedEngine = state.settings?.download_engine || "ytp-dl";
  // Keep the phone payload inside what the backend reported it can run. The
  // backend clamps this again, but matching here keeps the requested engine
  // and the job's engine identical so the UI never shows a quality it did
  // not actually ask for.
  const androidCapability = runtimeEngine(selectedEngine);
  const androidEngine = androidCapability ? selectedEngine : (selectedEngine === "torrent" ? "torrent" : "ytp-dl");
  const androidServices = androidCapability?.services || (androidEngine === "torrent"
    ? ["all", "torlock", "torrentdownloads", "limetorrents", "1337x", "kickass"]
    : ["youtube"]);
  const androidQualities = androidCapability?.qualities || (androidEngine === "torrent" ? ["LOSSLESS"] : ["best", "m4a"]);
  const androidQuality = androidQualities.includes(state.settings?.default_quality)
    ? state.settings.default_quality
    : androidQualities[0];
  const androidService = androidServices.includes(state.settings?.download_service)
    ? state.settings.download_service
    : androidServices[0];
  return {
    kind: "track",
    mode,
    prefetch,
    artist: track.artist || "",
    album: track.album || "",
    title: track.title || "",
    quality: IS_ANDROID ? androidQuality : (state.settings.default_quality || "best"),
    service: IS_ANDROID ? androidService : (state.settings.download_service || "youtube"),
    engine: IS_ANDROID ? androidEngine : (state.settings.download_engine || "ytp-dl"),
    // A bare identity snapshot, not the raw `track` object. The backend only
    // ever reads identity fields out of `track`/`metadata` (see
    // _payload_metadata on the server), never the whole object — but
    // `track: track` here used to embed it directly, and `track` itself was
    // very often ITSELF a previous payload's `.track`, complete with its own
    // nested `track`/`metadata`. Every play or download added one more
    // nesting level with no way to unwind it, so a track replayed over months
    // of use could carry a payload many layers deep. A 572-track playlist's
    // batch status check — one POST, one payload per track — stopped
    // completing at all once enough tracks had grown large enough, which is
    // why their download badges silently never updated after a page revisit.
    track: trackIdentitySnapshot(track),
    metadata: trackIdentitySnapshot(track.metadata || track),
    spotify_id: spotifyId,
    isrc,
    track_key: trackKey(track),
  };
}

// Just the fields identity/display logic actually reads, never a previous
// payload's own `track`/`metadata`, which is what let serviceDownloadPayload
// compound without bound across repeated plays of the same track.
function trackIdentitySnapshot(track) {
  if (!track || typeof track !== "object") return {};
  return {
    ...(track.offline && track.library_path ? { offline: true, library_path: track.library_path } : {}),
    type: track.type || "track",
    title: track.title || "",
    artist: track.artist || "",
    artist_id: track.artist_id || "",
    album: track.album || "",
    year: track.year || "",
    artwork_url: track.artwork_url || "",
    spotify_id: track.spotify_id || "",
    spotify_url: track.spotify_url || "",
    duration_ms: track.duration_ms || 0,
    isrc: track.isrc || "",
    track_key: track.track_key || trackKey(track),
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

function lyricsPayload(track) {
  const payload = serviceDownloadPayload(track || {}, "stream");
  const durationMs = track?.source_recording?.duration_ms || track?.duration_ms || track?.metadata?.duration_ms || track?.duration || track?.metadata?.duration || 0;
  return {
    artist: track?.source_recording?.artist || payload.artist || "",
    album: track?.source_recording ? (track.source_recording.album || "") : (payload.album || ""),
    title: track?.source_recording?.title || payload.title || "",
    spotify_id: track?.source_recording ? (track.source_recording.spotify_id || "") : (payload.spotify_id || ""),
    isrc: track?.source_recording?.isrc || payload.isrc || "",
    track_key: payload.track_key || "",
    duration_s: durationMs > 1000 ? Math.round(Number(durationMs) / 1000) : Number(durationMs || 0),
  };
}

function parseLrcTimestamp(value) {
  const match = String(value || "").match(/^(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?$/);
  if (!match) return null;
  const minutes = Number(match[1] || 0);
  const seconds = Number(match[2] || 0);
  const fraction = match[3] ? Number(`0.${match[3].padEnd(3, "0").slice(0, 3)}`) : 0;
  return minutes * 60 + seconds + fraction;
}

function parseLyrics(raw) {
  const text = String(raw || "").trim();
  if (!text) return [];
  const lines = [];
  text.split(/\r?\n/).forEach((line) => {
    const stamps = [...line.matchAll(/\[(\d{1,2}:\d{2}(?:[.:]\d{1,3})?)\]/g)]
      .map(match => parseLrcTimestamp(match[1]))
      .filter(value => value !== null);
    // Enhanced ("word-synced" / A2) LRC puts a <mm:ss.xx> tag in front of every
    // word. Those are timing data, not words: leaving them in printed the raw
    // markup into the lyrics panel, and a file carrying only word tags produced
    // no lines at all because it has no [mm:ss.xx] line stamp to key off.
    const wordStamps = [...line.matchAll(/<(\d{1,2}:\d{2}(?:[.:]\d{1,3})?)>/g)]
      .map(match => parseLrcTimestamp(match[1]))
      .filter(value => value !== null);
    const times = stamps.length ? stamps : wordStamps.slice(0, 1);
    if (!times.length) return;
    const content = line
      .replace(/\[[^\]]*\]/g, "")
      .replace(/<\d{1,2}:\d{2}(?:[.:]\d{1,3})?>/g, "")
      .replace(/\s+/g, " ")
      .trim();
    times.forEach(time => lines.push({ time, text: content, instrumental: !content }));
  });
  return lines.sort((a, b) => a.time - b.time);
}

function proxiedImageUrl(url) {
  if (!url) return "";
  try {
    const parsed = new URL(url, window.location.href);
    if (parsed.origin === window.location.origin) return parsed.href;
    return `/api/image?url=${encodeURIComponent(parsed.href)}`;
  } catch (_) {
    return url;
  }
}

function setLyricsFallbackPalette() {
  const panel = $("lyricsPanel");
  if (!panel) return;
  panel.style.setProperty("--lyrics-bg", "#06445a");
  panel.style.setProperty("--lyrics-bg-2", "#062b3b");
  panel.style.setProperty("--lyrics-muted", "rgba(178, 226, 246, 0.58)");
  panel.style.setProperty("--lyrics-active", "#ffffff");
}

function applyLyricsPalette(track) {
  const panel = $("lyricsPanel");
  if (!panel) return;
  setLyricsFallbackPalette();
  const url = proxiedImageUrl(track?.artwork_url || track?.metadata?.artwork_url || "");
  if (!url) return;
  const img = new Image();
  img.crossOrigin = "anonymous";
  img.onload = () => {
    try {
      const canvas = document.createElement("canvas");
      const size = 32;
      canvas.width = size;
      canvas.height = size;
      const ctx = canvas.getContext("2d", { willReadFrequently: true });
      ctx.drawImage(img, 0, 0, size, size);
      const data = ctx.getImageData(0, 0, size, size).data;
      let r = 0, g = 0, b = 0, count = 0;
      for (let i = 0; i < data.length; i += 16) {
        const alpha = data[i + 3];
        if (alpha < 128) continue;
        r += data[i]; g += data[i + 1]; b += data[i + 2]; count++;
      }
      if (!count) return;
      r = Math.round(r / count); g = Math.round(g / count); b = Math.round(b / count);
      const dark = `rgb(${Math.max(18, Math.round(r * 0.42))}, ${Math.max(24, Math.round(g * 0.42))}, ${Math.max(28, Math.round(b * 0.42))})`;
      const darker = `rgb(${Math.max(8, Math.round(r * 0.25))}, ${Math.max(10, Math.round(g * 0.25))}, ${Math.max(12, Math.round(b * 0.25))})`;
      const muted = `rgba(${Math.min(255, Math.round(r * 1.5 + 50))}, ${Math.min(255, Math.round(g * 1.5 + 50))}, ${Math.min(255, Math.round(b * 1.5 + 50))}, 0.58)`;
      panel.style.setProperty("--lyrics-bg", dark);
      panel.style.setProperty("--lyrics-bg-2", darker);
      panel.style.setProperty("--lyrics-muted", muted);
    } catch (_) {
      setLyricsFallbackPalette();
    }
  };
  img.onerror = setLyricsFallbackPalette;
  img.src = url;
}

function currentPlaybackSeconds() {
  if (state.nativeAudio.active) return Number(state.nativeAudio.position || 0);
  const audio = $("audioPlayer");
  return audio && isFinite(audio.currentTime) ? Number(audio.currentTime || 0) : 0;
}

// Video follows the audio by timestamp: second N of the song is second
// N + offset of the video. The offset comes from matching the two soundtracks
// on the backend (video intros, cold opens) plus the user's saved nudge.
function videoSyncOffset() {
  return Number(state.videoSync.offset || 0) + Number(state.videoSync.manual || 0);
}

function videoTimeForAudio(position, video) {
  const raw = (Number(position) || 0) + videoSyncOffset();
  return Math.max(0, Math.min(raw, Math.max(0, video.duration - 0.25)));
}

function currentSideVideoPath() {
  if (canSwitchToLocalVideo()) return state.currentLibraryPath || "";
  return state.videoFetch.status === "ready" ? (state.videoFetch.path || "") : "";
}

function renderVideoSyncControls() {
  const box = $("sideVideoSync");
  if (!box) return;
  const show = !!state.videoMode && !!currentSideVideoPath() && state.videoSync.status !== "same-file";
  box.hidden = !show;
  if (!show) return;
  const total = videoSyncOffset();
  const signed = `${total >= 0 ? "+" : "−"}${Math.abs(total).toFixed(2).replace(/\.?0+$/, "") || "0"}s`;
  const label = {
    matched: `Synced ${signed}`,
    checking: "Syncing…",
    pending: "Syncing…",
  }[state.videoSync.status] || (state.videoSync.manual ? `Offset ${signed}` : "Not matched");
  $("sideVideoSyncLabel").textContent = label;
  box.title = state.videoSync.status === "matched"
    ? "Video lined up to the song by matching their soundtracks. Use − / + to fine-tune."
    : "Could not match the soundtracks automatically. Use − / + to line the video up.";
}

// Identity of the recording for the normalized sync tables: Spotify id first,
// then ISRC; title/artist only identify tracks that have neither.
function videoSyncTrackFields(track) {
  return {
    spotify_id: trackIdentityValue(track, "spotify_id") || "",
    isrc: trackIdentityValue(track, "isrc") || "",
    title: track?.title || "",
    artist: track?.artist || "",
    duration_ms: Math.round((knownTrackDurationSeconds(track) || 0) * 1000),
  };
}

// Ask the backend to match this video against the song's audio. Monochrome
// audio becomes matchable once enough of the stream has downloaded, so
// "pending" / "unavailable" answers are retried for a while.
function videoSyncKey(track, videoPath) {
  return `${trackKey(track)}|${videoPath}|${trackIdentityValue(track, "isrc")}|${state.currentLibraryPath || state.nativeAudio.stream_url || state.currentStreamUrl || ""}`;
}

async function refreshVideoSync() {
  const track = state.currentTrack;
  const videoPath = currentSideVideoPath();
  if (!state.videoMode || !track || !videoPath) {
    renderVideoSyncControls();
    return;
  }
  const key = videoSyncKey(track, videoPath);
  if (state.videoSync.key !== key) {
    clearTimeout(state.videoSync.timer);
    state.videoSync = { key, status: "checking", offset: 0, manual: 0, attempts: 0, timer: null };
  } else if (state.videoSync.status !== "pending" && state.videoSync.status !== "unavailable") {
    renderVideoSyncControls();
    return;
  }
  if (canSwitchToLocalVideo()) {
    // Audio and picture come from the same downloaded file: already in sync.
    state.videoSync.status = "same-file";
    renderVideoSyncControls();
    return;
  }
  renderVideoSyncControls();
  state.videoSync.attempts += 1;
  // Past the same-file check, the playing file is audio — including the
  // .webm/.mp4 audio-only downloads from YouTube, which share video extensions.
  const audioPath = state.currentLibraryPath || "";
  const result = await api("/api/video/sync", {
    method: "POST",
    body: JSON.stringify({
      ...videoSyncTrackFields(track),
      video_path: videoPath,
      audio_path: audioPath,
      stream_url: state.nativeAudio.stream_url || state.currentStreamUrl || "",
    }),
  }).catch(() => null);
  if (state.videoSync.key !== key) return;
  if (result) {
    state.videoSync.status = result.status || "unmatched";
    state.videoSync.offset = Number(result.offset || 0);
    state.videoSync.manual = Number(result.manual_offset || 0);
  } else {
    state.videoSync.status = "unavailable";
  }
  renderVideoSyncControls();
  syncLocalVideoOverlay(audiblePlaybackSeconds(), false, { allowSeek: true });
  if ((state.videoSync.status === "pending" || state.videoSync.status === "unavailable") && state.videoSync.attempts < 36) {
    state.videoSync.timer = setTimeout(() => refreshVideoSync().catch(() => {}), 5000);
  }
}

async function nudgeVideoSync(delta) {
  const track = state.currentTrack;
  const videoPath = currentSideVideoPath();
  if (!track || !videoPath) return;
  state.videoSync.manual = Number(state.videoSync.manual || 0) + delta;
  renderVideoSyncControls();
  followAudioWithVideo();
  const result = await api("/api/video/sync/nudge", {
    method: "POST",
    body: JSON.stringify({ ...videoSyncTrackFields(track), video_path: videoPath, audio_path: state.currentLibraryPath || "",
      stream_url: state.nativeAudio.stream_url || state.currentStreamUrl || "", delta }),
  }).catch(() => null);
  if (result?.ok && state.videoSync.key === videoSyncKey(track, videoPath)) {
    state.videoSync.manual = Number(result.manual_offset || 0);
    renderVideoSyncControls();
  }
}

// What the listener hears now. The native player's position counts PCM handed
// to the device, which leads the speaker by the output latency (~1s on
// Bluetooth), so the video would otherwise run ahead.
function audiblePlaybackSeconds() {
  if (state.nativeAudio.active) {
    return Math.max(0, Number(state.nativeAudio.position || 0) - Number(state.nativeAudio.output_latency || 0));
  }
  return currentPlaybackSeconds();
}

// Keep the side video locked to the audio: same play/pause state (including
// pausing while audio buffers), and drift corrected continuously. Small drift
// is absorbed by nudging playbackRate so frames are never dropped; only a big
// jump (seek, stall) re-seeks the video. Runs from audio timeupdate and from
// the native-audio poll, which has no media events of its own.
function followAudioWithVideo() {
  if (!state.videoMode) return;
  const video = $("sideVideoPlayer");
  if (!video || video.tagName !== "VIDEO" || !Number.isFinite(video.duration) || video.duration <= 0) return;
  if (state.manualPauseRequested || !isPlaybackVisiblyActive()) {
    if (!video.paused) video.pause();
    video.playbackRate = 1;
    return;
  }
  const raw = audiblePlaybackSeconds() + videoSyncOffset();
  if (raw < 0 || raw > video.duration - 0.3) {
    // The song is playing a part the video does not have (e.g. the album
    // intro before the video starts): hold the nearest frame until it does.
    const hold = raw < 0 ? 0 : Math.max(0, video.duration - 0.25);
    if (!video.paused) video.pause();
    if (Math.abs((video.currentTime || 0) - hold) > 0.3) video.currentTime = hold;
    video.playbackRate = 1;
    return;
  }
  const target = videoTimeForAudio(audiblePlaybackSeconds(), video);
  const drift = (video.currentTime || 0) - target;
  if (Math.abs(drift) > 1.0) {
    video.currentTime = target;
    video.playbackRate = 1;
  } else if (Math.abs(drift) > 0.08) {
    video.playbackRate = drift > 0 ? 0.95 : 1.05;
  } else {
    video.playbackRate = 1;
  }
  if (video.paused) video.play().catch(() => {});
}

function syncLocalVideoOverlay(position = currentPlaybackSeconds(), forcePlay = false, options = {}) {
  if (!state.videoMode) return;
  if (!canSwitchToLocalVideo() && state.videoFetch.status !== "ready") return;
  const video = $("sideVideoPlayer");
  if (!video || video.tagName !== "VIDEO") return;
  if (options.allowSeek && Number.isFinite(position) && position >= 0 && Number.isFinite(video.duration) && video.duration > 0) {
    const target = videoTimeForAudio(position, video);
    if (Math.abs((video.currentTime || 0) - target) > 0.4) {
      video.currentTime = target;
    }
  }
  if (forcePlay && !state.manualPauseRequested && isPlaybackVisiblyActive()) {
    video.play().catch(() => {});
  }
}

function currentLyricsIndex(position) {
  const lines = state.lyrics.lines || [];
  if (!lines.length) return -1;
  let lo = 0, hi = lines.length - 1, best = -1;
  while (lo <= hi) {
    const mid = Math.floor((lo + hi) / 2);
    if (lines[mid].time <= position - state.lyrics.syncOffset) {
      best = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return best;
}

function renderLyricsContent(message = "") {
  const content = $("lyricsContent");
  if (!content) return;
  if (message) {
    content.innerHTML = `<div class="lyrics-empty">${esc(message)}</div>`;
    return;
  }
  const lines = state.lyrics.lines || [];
  if (lines.length) {
    content.innerHTML = lines.map((line, index) => {
      const text = line.instrumental ? '<i class="bi bi-music-note-beamed"></i>' : esc(line.text);
      return `<div class="lyrics-line${line.instrumental ? " instrumental" : ""}" data-lyrics-index="${index}">${text}</div>`;
    }).join("");
    updateLyricsPosition(currentPlaybackSeconds(), true);
    return;
  }
  if (state.lyrics.raw) {
    content.innerHTML = `<div class="lyrics-empty">Timed lyrics unavailable</div><div class="lyrics-line unsynced">${esc(state.lyrics.raw)}</div>`;
  } else {
    content.innerHTML = '<div class="lyrics-empty">No synced lyrics found</div>';
  }
}

function setLyricsSynced(value) {
  state.lyrics.synced = !!value;
  const sync = $("lyricsSync");
  if (sync) sync.hidden = state.lyrics.synced;
  if (state.lyrics.synced) scrollActiveLyricsLine(true);
}

function scrollActiveLyricsLine(force = false) {
  if (!state.lyrics.open || !state.lyrics.synced) return;
  const idx = state.lyrics.activeIndex;
  if (idx < 0) return;
  const line = document.querySelector(`.lyrics-line[data-lyrics-index="${idx}"]`);
  if (!line) return;
  state.lyrics.programmaticScroll = true;
  line.scrollIntoView({ block: "center", behavior: force ? "smooth" : "smooth" });
  setTimeout(() => { state.lyrics.programmaticScroll = false; }, 450);
}

function updateLyricsPosition(position = currentPlaybackSeconds(), forceScroll = false) {
  if (!state.lyrics.open || !(state.lyrics.lines || []).length) return;
  const idx = currentLyricsIndex(position);
  if (idx === state.lyrics.activeIndex && !forceScroll) return;
  document.querySelectorAll(".lyrics-line.active").forEach(el => el.classList.remove("active"));
  state.lyrics.activeIndex = idx;
  if (idx >= 0) {
    document.querySelector(`.lyrics-line[data-lyrics-index="${idx}"]`)?.classList.add("active");
    if (state.lyrics.synced) scrollActiveLyricsLine(forceScroll);
  }
}

async function loadLyricsForTrack(track, { force = false } = {}) {
  const key = JSON.stringify(lyricsPayload(track));
  if (!track || (!force && state.lyrics.trackKey === key && (state.lyrics.lines.length || state.lyrics.raw))) return;
  state.lyrics.loading = true;
  state.lyrics.trackKey = key;
  state.lyrics.lines = [];
  state.lyrics.raw = "";
  state.lyrics.activeIndex = -1;
  renderLyricsContent("Loading lyrics...");
  applyLyricsPalette(track);
  try {
    const params = new URLSearchParams(lyricsPayload(track));
    const data = await api(`/api/lyrics?${params.toString()}`);
    if (state.lyrics.trackKey !== key) return;
    state.lyrics.provider = data.provider || "";
    state.lyrics.source = data.source || "";
    state.lyrics.raw = data.lyrics || "";
    state.lyrics.lines = data.synced ? parseLyrics(data.lyrics || "") : [];
    renderLyricsContent(data.found ? "" : "No synced lyrics found");
    setLyricsSynced(true);
  } catch (error) {
    if (state.lyrics.trackKey === key) renderLyricsContent("Lyrics unavailable");
  } finally {
    state.lyrics.loading = false;
  }
}

function prefetchLyricsForTrack(track) {
  if (!track) return;
  api("/api/lyrics/prefetch", {
    method: "POST",
    body: JSON.stringify(lyricsPayload(track)),
  }).catch(() => {});
}

function openLyricsPanel() {
  const panel = $("lyricsPanel");
  if (!panel) return;
  state.lyrics.open = true;
  panel.hidden = false;
  attachPanelSwipeClose(panel, () => $("lyricsContent"), closeLyricsPanel);
  const bg = $("lyricsBg");
  if (bg) bg.hidden = false;
  $("btnLyrics")?.classList.add("active");
  const label = $("lyricsOffsetLabel");
  if (label) label.textContent = state.lyrics.syncOffset.toFixed(1) + "s";
  if (!state.currentTrack) {
    renderLyricsContent("Play a song to see lyrics");
    return;
  }
  applyLyricsPalette(state.currentTrack);
  setLyricsSynced(true);
  loadLyricsForTrack(state.currentTrack, { force: false }).catch(() => {});
  updateLyricsPosition(currentPlaybackSeconds(), true);
}

function closeLyricsPanel() {
  const panel = $("lyricsPanel");
  if (!panel) return;
  state.lyrics.open = false;
  panel.hidden = true;
  const bg = $("lyricsBg");
  if (bg) bg.hidden = true;
  $("btnLyrics")?.classList.remove("active");
}

function toggleLyricsPanel() {
  if (state.lyrics.open) closeLyricsPanel();
  else openLyricsPanel();
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

// Hides every finished download/stream job matching this track's identity
// from "Recently Played" (server-side, persists across restarts) without
// touching the cached file or job state anything else still relies on, then
// mirrors the removal into local state and re-renders whichever "Recently
// Played" surfaces (Home grid, full page, Queue panel's Recent tab) are
// currently mounted.
async function removeFromRecentlyPlayed(track) {
  await api("/api/service/recent", {
    method: "DELETE",
    body: JSON.stringify(serviceDownloadPayload(track, "stream")),
  }).catch(() => {});

  const removedKey = recentTrackKey(track);
  if (state.catalog && state.catalog.recent_tracks) {
    state.catalog.recent_tracks = state.catalog.recent_tracks.filter(t => recentTrackKey(t) !== removedKey);
  }

  if ($("recentTracksGrid")) {
    const recentTracks = uniqueRecentTracks(state.catalog.recent_tracks || []).slice(0, 6);
    renderCards("recentTracksGrid", recentTracks, "track", state.catalog.recent_tracks);
    bindRecentTrackContextMenus("recentTracksGrid", recentTracks);
  }
  if ($("fullRecentTracks")) {
    const tracks = uniqueRecentTracks(state.catalog.recent_tracks || []);
    renderTrackList("fullRecentTracks", tracks, "general", { kind: "recent" });
  }
  if ($("queueRecentList") && !$("queuePanel").hidden) {
    renderQueueTracks("queueRecentList", state.catalog.recent_tracks || [], true);
  }
}

// Mirrors bindStatsEntityContextMenus: re-binds oncontextmenu on the Home
// page's "Recently Played" card grid (renderCards/bindCardClicks has no
// contextInfo hook) without touching the generic card-click binder shared by
// every other kind="track" grid on the Home page.
function bindRecentTrackContextMenus(containerId, items) {
  const container = $(containerId);
  if (!container) return;
  container.querySelectorAll("[data-card]").forEach((button) => {
    const item = items[Number(button.dataset.card)];
    if (!item || !playableQueueItem(item)) return;
    button.oncontextmenu = (event) => {
      event.preventDefault();
      showTrackContextMenu(event, item, { kind: "recent" });
    };
  });
}

function playableQueueItem(item) {
  return item && item.type !== "artist" && item.type !== "album";
}

function prefetchAlbumKey(item) {
  const meta = item?.metadata && typeof item.metadata === "object" ? item.metadata : {};
  const normalize = (value, isAlbum) => {
    let text = String(value || "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
    if (isAlbum) {
      text = text.replace(/\b\d{1,3}(?:st|nd|rd|th)\b/g, " ")
        .replace(/\b(?:deluxe|anniversary|remaster(?:ed)?|expanded|edition|special|version)\b/g, " ");
    } else {
      text = text.replace(/^the\s+/, "");
    }
    return text.match(/[a-z0-9]+/g)?.join(" ") || "";
  };
  const album = normalize(item?.album || meta.album, true);
  const artist = normalize(item?.album_artist || meta.album_artist || item?.artist || meta.artist, false);
  return album ? `${artist}||${album}` : "";
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
  const currentAlbum = prefetchAlbumKey(state.currentTrack);
  if (!currentAlbum) return tracks;
  return tracks.map((track, index) => ({ track, index }))
    .sort((a, b) => {
      const aSameAlbum = prefetchAlbumKey(a.track) === currentAlbum;
      const bSameAlbum = prefetchAlbumKey(b.track) === currentAlbum;
      return Number(bSameAlbum) - Number(aSameAlbum) || a.index - b.index;
    })
    .map(({ track }) => track);
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
  if (next.offline && next.library_path) return;
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

function maybePrefetchUpcomingTracks(position) {
  if (isMonochromeDirectStreamUrl(state.currentStreamUrl) ||
      (state.nativeAudio.active && isMonochromeDirectStreamUrl(state.nativeAudio.stream_url))) return;
  if (position < 2 || state.manualPauseRequested || state.prefetchedForRequestId === state.playbackRequestId) return;
  state.prefetchedForRequestId = state.playbackRequestId;
  prefetchNextTracks().catch(() => { state.prefetchedForRequestId = -1; });
  prefetchNextVideos();
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
  const currentAlbum = prefetchAlbumKey(state.currentTrack);
  const sameAlbum = currentAlbum ? targets.filter(track => prefetchAlbumKey(track) === currentAlbum) : [];
  const otherAlbums = targets.filter(track => !sameAlbum.includes(track));
  await Promise.all(sameAlbum.map(track => prefetchOneTrack(track, orderKey)));
  await Promise.all(otherAlbums.map(track => prefetchOneTrack(track, orderKey)));
}

const _videoPrefetchInflight = new Set();

function _triggerVideoFetchForTrack(track) {
  if (track?.offline) return;
  const key = trackKey(track);
  if (_videoPrefetchInflight.has(key)) return;
  if (canSwitchToLocalVideo(track)) return;
  const params = new URLSearchParams({
    artist: track.artist || "",
    title: track.title || "",
    album: track.album || "",
    track_key: key,
    ...(track.duration_ms ? { duration_ms: String(track.duration_ms) } : {}),
  });
  _videoPrefetchInflight.add(key);
  api(`/api/video/fetch?${params.toString()}`).catch(() => {}).finally(() => {
    _videoPrefetchInflight.delete(key);
  });
  console.log("[VideoPrefetch] queued:", track.title);
}

function prefetchNextVideos() {
  // Walk the entire queue in batches of 2 staggered by 500 ms so we don't
  // slam the backend with dozens of simultaneous torrent/YouTube searches.
  if (!state.queue.length) return;
  const idx = getQueueIndex();
  const start = idx >= 0 ? idx + 1 : 0;
  const remaining = [];
  const seen = new Set([state.currentTrack ? trackKey(state.currentTrack) : ""]);
  for (let i = 0; i < state.queue.length; i++) {
    const track = state.queue[(start + i) % state.queue.length];
    const key = trackKey(track);
    if (!playableQueueItem(track) || seen.has(key)) continue;
    seen.add(key);
    remaining.push(track);
  }
  if (!remaining.length) return;
  // Fire first batch immediately, then stagger subsequent batches 10 s apart
  const BATCH = 2;
  remaining.forEach((track, i) => {
    const delay = Math.floor(i / BATCH) * 10000;
    if (delay === 0) {
      _triggerVideoFetchForTrack(track);
    } else {
      setTimeout(() => _triggerVideoFetchForTrack(track), delay);
    }
  });
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
    prefetchLyricsForTrack(track);
    const activeJobId = (result.job && result.job.id) || result.active_job_id || "";
    if (activeJobId) button.dataset.activeJobId = activeJobId;
    if (result.action === "started" || result.action === "queued") {
      await waitForLibraryToggle(track, activeJobId, button);
    }
    if (typeof refresh === "function") refresh();
    loadPlaylists();
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

// Android keeps downloaded files in this app's private storage (not visible
// to other apps or a file manager), so an explicit "add to library" download
// also copies the file into the phone's shared Music library. Desktop writes
// straight into the user's chosen Music folder already, so this is a no-op
// there — nothing about desktop's save path or behaviour changes.
function exportLibraryDownloadToPhone(libraryPath) {
  if (!IS_ANDROID || !libraryPath || !window.MindinguflacAndroid?.exportDownloadToMusicLibrary) return;
  const name = libraryPath.split("/").pop() || "";
  const ext = (name.split(".").pop() || "").toLowerCase();
  const mime = {
    flac: "audio/flac", mp3: "audio/mpeg", m4a: "audio/mp4", aac: "audio/aac",
    ogg: "audio/ogg", opus: "audio/opus", wav: "audio/wav", alac: "audio/alac",
  }[ext] || "audio/mpeg";
  try {
    window.MindinguflacAndroid.exportDownloadToMusicLibrary(libraryPath, name, mime);
  } catch (_) {}
}

function updateLibraryProgressButton(button, status) {
  if (!button) return;
  button.classList.add("progress");
  const s = typeof status === "object" ? status : { progress: status };
  button.innerHTML = progressButtonMarkup(s);
}

// The track list re-renders constantly — the Phase 2 batch status fetch
// replaces every button node once real status is known, switching tabs
// rebuilds the whole container, scrolling a virtualized grid recreates rows.
// None of that means the download stopped; it means the DOM node a poller
// started with is gone. Re-find whatever button currently represents this
// same track (by stable identity, not by index) so the poller can keep
// animating it instead of just going dark.
function findLiveLibraryButtonForTrack(track) {
  const key = trackKey(track);
  for (const candidate of document.querySelectorAll("[data-library-action]")) {
    const row = candidate.closest("[data-item-data]");
    if (!row || !row.dataset.itemData) continue;
    try {
      if (trackKey(JSON.parse(row.dataset.itemData)) === key) return candidate;
    } catch (_) {
      // Not this row's track; keep looking.
    }
  }
  return null;
}

async function waitForLibraryToggle(track, jobId = "", button = null) {
  for (let attempt = 0; attempt < 900; attempt++) {
    if (button && button.dataset.cancelled === "1") return null;
    // The button that started this poll may have been replaced by a later
    // render. Re-acquire the current one for this same track by identity
    // before deciding there is nothing left to update — losing a DOM
    // reference used to be treated as "give up," which left the backend job
    // running to completion with no button left tracking it: the spinner
    // just stopped, with no checkmark and no error, because nothing told the
    // user it had quietly detached from the download it still owned.
    if (button && !button.isConnected) {
      button = findLiveLibraryButtonForTrack(track);
    }
    await new Promise(resolve => setTimeout(resolve, 1000));
    if (button && button.dataset.cancelled === "1") return null;
    if (button && !button.isConnected) {
      button = findLiveLibraryButtonForTrack(track);
    }
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
      exportLibraryDownloadToPhone(status.library_path);
      return status;
    }
    if (jobId) {
      const data = await api("/api/service/downloads").catch(() => ({ jobs: [] }));
      const job = (data.jobs || []).find(item => item.id === jobId);
      if (job && job.status === "error" && job.youtube_login_required) {
        requestYoutubeLoginAndRetry(job, async () => {
          if (button) {
            button.dataset.cancelled = "";
            updateLibraryProgressButton(button, { progress: 0, last_status: "Retrying after YouTube login..." });
          }
          const retryJob = await api("/api/service/download", {
            method: "POST",
            body: JSON.stringify(serviceDownloadPayload(track, "download")),
          });
          if (button) button.dataset.activeJobId = retryJob.id;
          await waitForLibraryToggle(track, retryJob.id, button);
        });
        return null;
      }
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
      if (job.engine === "monochrome" && job.direct_stream && job.resolved_url) {
        startMonochromeDirectPlayback(job, track, requestId);
      } else if (job.status === "finished" && job.library_path) {
        await playFromLibraryPath(job.library_path, track, requestId, job.id, "Playing from cache");
      } else if (!canStreamActiveJobInBrowser(job) || state.pendingResumePosition > 0) {
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
          audio.src = browserAudioStreamUrl(streamUrl);
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
    if (requestId !== state.playbackRequestId) return;
    state.audioBuffering = false;
    state.autoplayWanted = false;
    setPlayerStatusIcon("error");
    setPlayerStatus(error.message || "Download failed", track);
    syncPlayPauseButton();
  }
}

function startMonochromeDirectPlayback(job, track, requestId) {
  if (requestId !== state.playbackRequestId || !job?.resolved_url) return;
  if (["original_album", "same_recording"].includes(job.recording_match?.kind)) {
    track = { ...track, requested_isrc: job.recording_match.requested_isrc,
      isrc: job.recording_match.resolved_isrc, source_isrc: job.recording_match.resolved_isrc,
      source_album: job.recording_match.source_album || "", duration_ms: job.recording_match.duration_ms };
    state.currentTrack = track;
  }
  if (job.source_recording) {
    track = { ...track, source_recording: job.source_recording };
    state.currentTrack = track;
    // Lyrics follow the actual audio, without changing its saved album link.
    if (state.lyrics.open) loadLyricsForTrack(track).catch(() => {});
    else prefetchLyricsForTrack(track);
  }
  // Monochrome's direct stream needs no next-track download/prefetch job.
  // Cancel work queued for a previous track so it cannot compete with or
  // replace this live stream.
  cancelAllPrefetchJobs("Monochrome direct stream");
  const audio = $("audioPlayer");
  if (!audio) return;
  const resumeAt = Number(state.pendingResumePosition || 0);
  state.pendingResumePosition = 0;
  state.activeJobId = null;
  state.audioHasPlayed = false;
  // Keep the play control locked from selection through decode/startup. The
  // confirmed `playing` event clears this state once audio is actually heard.
  state.audioBuffering = !state.manualPauseRequested;
  state.directStreamReconnectPending = false;
  state.directStreamNativeFallbackAttempted = false;
  state.currentLibraryPath = "";
  state.currentStreamUrl = job.resolved_url;
  state.currentPlayableReady = true;
  state.activeJobPhase = "";
  state.autoplayWanted = !state.manualPauseRequested;
  setPlayerStatusIcon("ready");
  setPlayerStatus(
    state.manualPauseRequested ? "Ready — paused" : "Buffering Monochrome stream",
    track,
    job,
  );
  syncPlayPauseButton();
  logMonochromePlaybackActivity("Opening Monochrome audio stream", track, "open", 0);
  // On Android the native player (ExoPlayer) handles Monochrome even on This
  // phone: it records the start of the track for music-video matching and
  // seeks without rebuffering. The WebView stays as the fallback.
  const androidNative = IS_ANDROID && !!window.MindinguflacAndroid && !isNativeAudioSelected();
  if (isNativeAudioSelected() || androidNative) {
    audio.pause();
    audio.removeAttribute("src");
    audio.load();
    startNativeAudio("", track, requestId, resumeAt, job.resolved_url, androidNative).catch((error) => {
      if (requestId !== state.playbackRequestId) return;
      if (androidNative) {
        logMonochromePlaybackActivity(`Native player unavailable (${error.message || error}); using the WebView`, track, "android-webview-fallback", 0);
        audio.src = browserAudioStreamUrl(job.resolved_url);
        audio.load();
        seekAfterMetadata(audio, resumeAt);
        if (!state.manualPauseRequested) tryStartAudio(audio, track, requestId, null);
        return;
      }
      state.audioBuffering = false;
      state.autoplayWanted = false;
      setPlayerStatus(`Selected audio device unavailable: ${error.message || "native stream failed"}`, track);
      syncPlayPauseButton();
    });
    return;
  }
  audio.src = browserAudioStreamUrl(job.resolved_url);
  audio.load();
  seekAfterMetadata(audio, resumeAt);
  if (!state.manualPauseRequested) tryStartAudio(audio, track, requestId, null);
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
      state.lastActiveReadyBytes = Number(job.active_audio_ready_bytes || 0);
      if (job.status === "error") {
        state.audioBuffering = false;
        if (job.youtube_login_required) {
          state.activeJobId = null;
          setPlayerStatusIcon("error");
          setPlayerStatus("YouTube login required", track, job);
          syncPlayPauseButton();
          requestYoutubeLoginAndRetry(job, () => startServiceDownload(track, mode, requestId));
          return;
        }
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
        syncPlayPauseButton();
        return;
      }
      const pct = job.progress ? Math.max(0, Math.min(99, Math.round(job.progress))) : 0;
      if (job.status === "finished") {
        if (mode === "stream" && job.engine === "monochrome" && job.direct_stream && job.resolved_url) {
          startMonochromeDirectPlayback(job, track, requestId);
          return;
        }
        if (mode === "stream" && job.library_path) {
          state.currentLibraryPath = job.library_path;
          state.currentPlayableReady = true;
          if (state.videoMode && isVideoLibraryPath(job.library_path)) {
            renderSideCover(track);
          }
        }
        setPlayerStatusIcon("ready");
        setPlayerStatus(mode === "stream" ? (state.manualPauseRequested ? "Ready — paused" : "Playing from cache") : "Saved to library", track, job);
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
              state.audioBuffering = false;
              setPlayerStatusIcon("error");
              setPlayerStatus(error.message || "Native audio failed", track);
              syncPlayPauseButton();
            }
          }
        }
        state.activeJobId = null;
        return;
      }
      if (mode === "stream" && !state.currentPlayableReady && activeJobHasPlayableAudio(job) && canStreamActiveJobInBrowser(job)) {
        const audio = $("audioPlayer");
        const resumeAt = Number(state.rebufferPosition || 0);
        state.rebuffering = false;
        state.rebufferAfterBytes = 0;
        const streamUrl = `${API_BASE}/api/library/stream_active_job?job_id=${job.id}&t=${Date.now()}`;
        state.currentStreamUrl = streamUrl;
        audio.src = browserAudioStreamUrl(streamUrl);
        state.currentPlayableReady = true;
        if (!state.manualPauseRequested) {
          state.autoplayWanted = true;
          audio.load();
          seekAfterMetadata(audio, resumeAt);
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
      // The Monochrome lookup finishes after WebKit's short-lived click
      // activation expires. Do not leave the first selected track paused and
      // waiting for a second click: hand FLAC to the native decoder, which can
      // start without browser autoplay permission and still uses the selected
      // app output (or the system default).
      if (isMonochromeDirectStreamUrl(state.currentStreamUrl) &&
          navigator.userAgent.includes("Macintosh") && !IS_ANDROID &&
          !state.directStreamNativeFallbackAttempted && !state.manualPauseRequested) {
        const fallbackRequestId = state.playbackRequestId;
        const resumeAt = Number.isFinite(audio.currentTime) && audio.currentTime > 0
          ? audio.currentTime : Number(state.directStreamPosition || 0);
        const streamUrl = state.currentStreamUrl;
        state.directStreamNativeFallbackAttempted = true;
        state.audioBuffering = true;
        state.autoplayWanted = true;
        logMonochromePlaybackActivity(
          "Browser autoplay was denied after Monochrome lookup; starting native audio automatically",
          track,
          "native-autoplay-fallback",
          0,
        );
        syncPlayPauseButton();
        audio.pause();
        audio.removeAttribute("src");
        audio.load();
        startNativeAudio("", track, fallbackRequestId, resumeAt, streamUrl, true).catch((fallbackError) => {
          if (fallbackRequestId !== state.playbackRequestId) return;
          state.audioBuffering = false;
          state.autoplayWanted = false;
          setPlayerStatus(`Monochrome playback failed: ${fallbackError.message || "native audio unavailable"}`, track);
          syncPlayPauseButton();
        });
        return;
      }
      state.autoplayWanted = true;
      state.audioBuffering = false;
      setPlayerStatusIcon("ready");
      setPlayerStatus("Ready — press play", track);
      syncPlayPauseButton();
    } else if (error && error.name !== "AbortError") {
      // AbortError means src changed mid-load — keep autoplayWanted so oncanplay retries.
      state.autoplayWanted = false;
      state.audioBuffering = false;
      setPlayerStatusIcon("error");
      setPlayerStatus(error.message || "Playback failed", track);
      syncPlayPauseButton();
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
  if (item.type === "query") {
    return `
      <button class="suggestion" type="button" data-suggestion="${index}">
        <div class="suggestion-art"><i class="bi bi-search"></i></div>
        <div class="suggestion-info"><strong>${esc(item.title || item.query || "")}</strong><div class="suggestion-sub"><span class="pill">Search</span></div></div>
      </button>
    `;
  }
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
  if (item.type === "query") {
    searchMusic(item.query || item.title || "");
    return;
  }
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
      $("searchInput").value = item.query || item.title || item.artist || "";
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
      const isCurrentActiveJob = event.job_id && event.job_id === state.activeJobId;
      if (msg.includes("Ready to play") && state.currentTrack && !state.manualPauseRequested && !state.nativeAudio.playing && $("audioPlayer").paused && isActiveJobStreamUrl(state.currentStreamUrl) && isCurrentActiveJob) {
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

async function refreshCodexStatus() {
  const label = $("codexAuthStatus");
  if (!label) return false;
  const status = await api("/api/codex/status").catch(() => null);
  const authenticated = !!status?.authenticated;
  label.textContent = authenticated ? `Signed in · ${status.model || "Codex"}` : "Not signed in";
  return authenticated;
}

async function loginCodex() {
  const button = $("codexLogin");
  const label = $("codexAuthStatus");
  if (button) button.disabled = true;
  if (label) label.textContent = "Complete login in your browser…";
  try {
    const result = await api("/api/codex/login", { method: "POST", body: "{}", timeout: 0 });
    if (!result.authenticated) throw new Error(result.error || "Codex login failed");
    await refreshCodexStatus();
    showToast("Codex login complete");
    return true;
  } catch (error) {
    if (label) label.textContent = error.message || "Codex login failed";
    showToast(error.message || "Codex login failed", 5000);
    return false;
  } finally {
    if (button) button.disabled = false;
  }
}

async function renderSettings() {
  setActiveView("settings");
  startCacheLogPolling();
  state.settings = await api("/api/settings");
  if (IS_ANDROID) await loadRuntimeCapabilities();
  setupYoutubeSignInSettings();

  $("cacheDir").value = state.settings.cache_dir || "";
  $("cacheDir").title = state.settings.cache_dir || "";

  $("musicDir").value = state.settings.music_dir || "";
  $("musicDir").title = state.settings.music_dir || "";

  $("storageSection")?.classList.toggle("hidden", IS_ANDROID);
  $("aiProviderRow")?.classList.toggle("hidden", IS_ANDROID);

  let engine = state.settings.download_engine || "ytp-dl";
  if (IS_ANDROID) {
    const options = androidEngineOptions();
    if (options.length) {
      $("downloadEngine").innerHTML = options
        .map(option => `<option value="${option.value}">${option.label}</option>`)
        .join("");
      if (!options.some(option => option.value === engine)) engine = options[0].value;
      $("downloadEngine").disabled = options.length < 2;
    }
    $("downloadService").disabled = false;
    renderAndroidEngineNotes();
  }
  $("downloadEngine").value = engine;
  $("torrentPlaybackCandidates").value = state.settings.torrent_playback_candidates ?? 3;
  $("torrentPrefetchCandidates").value = state.settings.torrent_prefetch_candidates ?? 2;
  $("torrentMetadataTimeout").value = state.settings.torrent_metadata_timeout_seconds ?? 60;
  updateEngineControls(
    engine,
    state.settings.download_service || (IS_ANDROID && engine === "torrent" ? "all" : "youtube"),
    state.settings.default_quality || (IS_ANDROID && engine === "torrent" ? "LOSSLESS" : "m4a"),
  );
  $("downloadEngine").onchange = () => {
    const newEngine = $("downloadEngine").value;
    updateEngineControls(newEngine, $("downloadService").value, $("defaultQuality").value);
  };

  if ($("duckModel")) {
    $("duckModel").value = state.settings.duck_model || "1";
  }

  const aiProvider = $("aiProvider");
  if (aiProvider) {
    aiProvider.value = IS_ANDROID ? "android" : (state.settings.ai_provider || "duckai");
    aiProvider.disabled = IS_ANDROID;
    const updateAiRows = () => {
      const provider = aiProvider.value;
      $("duckModelRow")?.classList.toggle("hidden", provider !== "duckai");
      $("geminiModelRow")?.classList.toggle("hidden", provider !== "gemini");
      $("codexAuthRow")?.classList.toggle("hidden", provider !== "codex");
    };
    aiProvider.onchange = async () => {
      updateAiRows();
      if (aiProvider.value === "codex" && !(await refreshCodexStatus())) {
        await loginCodex();
      }
    };
    updateAiRows();
    if (aiProvider.value === "codex") refreshCodexStatus();
  }
  refreshAndroidAdvisorStatus();

  if ($("codexLogin")) $("codexLogin").onclick = loginCodex;

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
  $("discogsToken").value = state.settings.discogs_token || "";

  try {
    const stats = await api("/api/cache");
    const sizeMB = stats.bytes / (1024 * 1024);
    const sizeText = sizeMB >= 1024 ? `${(sizeMB / 1024).toFixed(1)} GB` : `${sizeMB.toFixed(1)} MB`;
    $("cacheUsage").textContent = `${sizeText} used by ${stats.files} files`;
  } catch (e) {}
  setupPairingSettings();
}

let youtubeSettingsLoginPoll = null;

async function setupYoutubeSignInSettings() {
  if (youtubeSettingsLoginPoll) clearInterval(youtubeSettingsLoginPoll);
  youtubeSettingsLoginPoll = null;
  const row = $("youtubeSignInRow");
  const button = $("youtubeSignInButton");
  const label = $("youtubeSignInStatus");
  if (!row || !button || IS_ANDROID) return;
  let signedIn = false;
  const showStatus = status => {
    signedIn = !!status.signed_in;
    label.textContent = signedIn ? "YouTube session saved on this device." : "Sign in in the app. Your session stays on this device.";
    button.textContent = signedIn ? "Sign out" : "Sign in to YouTube";
    button.disabled = false;
  };
  try {
    const status = await api("/api/system/youtube-login-status", { method: "POST", body: JSON.stringify({}) });
    row.classList.toggle("hidden", !status.embedded_available);
    if (!status.embedded_available) return;
    showStatus(status);
  } catch (_) { return; }
  button.onclick = async () => {
    button.disabled = true;
    try {
      if (signedIn) {
        await api("/api/system/youtube-logout", { method: "POST", body: JSON.stringify({}) });
        if (youtubeSettingsLoginPoll) clearInterval(youtubeSettingsLoginPoll);
        youtubeSettingsLoginPoll = null;
        showStatus({ signed_in: false });
        showToast("Signed out of YouTube");
        return;
      }
      const opened = await api("/api/system/open-url", { method: "POST", body: JSON.stringify({ url: "https://www.youtube.com/" }) });
      if (!opened.ok) throw new Error("Could not open YouTube sign-in");
      label.textContent = "Complete sign-in in the YouTube window.";
      if (youtubeSettingsLoginPoll) clearInterval(youtubeSettingsLoginPoll);
      let checking = false;
      youtubeSettingsLoginPoll = setInterval(async () => {
        if (checking) return;
        checking = true;
        try {
          const status = await api("/api/system/youtube-login-status", { method: "POST", body: JSON.stringify({}) });
          if (status.signed_in && status.login_outcome === "completed") {
            clearInterval(youtubeSettingsLoginPoll);
            youtubeSettingsLoginPoll = null;
            showStatus(status);
            showToast("Signed in to YouTube");
          } else if (!status.login_open) {
            clearInterval(youtubeSettingsLoginPoll);
            youtubeSettingsLoginPoll = null;
            showStatus(status);
            label.textContent = status.signed_in
              ? "Sign-in cancelled. The previously saved YouTube session is still available."
              : "Sign-in closed before completion. You can try again.";
          }
        } catch (_) {} finally { checking = false; }
      }, 2000);
    } catch (error) {
      showToast(error.message || "Could not open YouTube sign-in", 5000);
    } finally { button.disabled = false; }
  };
}

function setupPairingSettings() {
  $("pairingDesktopActions")?.classList.toggle("hidden", IS_ANDROID);
  $("pairingAndroidActions")?.classList.toggle("hidden", !IS_ANDROID);
  const makeQr = $("createPairingQr");
  const invitationPanel = $("pairingInvitation");
  const setQrVisible = visible => {
    state.pairingQrVisible = visible;
    invitationPanel?.classList.toggle("hidden", !visible);
    if (makeQr) {
      makeQr.textContent = visible ? "Hide pairing QR code" : "Show pairing QR code";
      makeQr.setAttribute("aria-expanded", String(visible));
    }
  };
  const createQr = async () => {
    makeQr.disabled = true;
    try {
      const before = await api("/api/pairing/status");
      state.pairingBeforeInvite = (before.devices || []).map(device => device.device_id);
      const invite = await api("/api/pairing/invitation", { method: "POST", body: "{}" });
      state.pairingInvite = invite;
      $("pairingQrImage").src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(invite.qr_svg)}`;
      $("pairingQrExpiry").textContent = `This one-time code expires at ${new Date(invite.expires_at * 1000).toLocaleTimeString()}. It will refresh automatically while shown.`;
      setQrVisible(true);
      clearTimeout(state.pairingQrTimer);
      state.pairingQrTimer = setTimeout(async () => {
        if (!state.pairingQrVisible) return;
        try { await createQr(); }
        catch (error) { showToast(error.message || "Could not refresh the pairing code", 5000); }
      }, Math.max(1000, invite.expires_at * 1000 - Date.now() + 250));
      refreshPairingSettings();
    } catch (error) {
      showToast(error.message || "Could not create a pairing code", 5000);
      if (!state.pairingQrVisible) setQrVisible(false);
    } finally {
      makeQr.disabled = false;
    }
  };
  if (makeQr) makeQr.onclick = async () => {
    if (state.pairingQrVisible) {
      setQrVisible(false);
      clearTimeout(state.pairingQrTimer);
      return;
    }
    if (state.pairingInvite && state.pairingInvite.expires_at * 1000 > Date.now()) {
      setQrVisible(true);
      state.pairingQrTimer = setTimeout(createQr, Math.max(1000, state.pairingInvite.expires_at * 1000 - Date.now() + 250));
      return;
    }
    await createQr();
  };
  const scan = $("scanPairingQr");
  if (scan) scan.onclick = () => {
    if (window.MindinguflacAndroid?.scanDevicePairingQr) window.MindinguflacAndroid.scanDevicePairingQr();
    else showToast("The QR scanner is only available in the Android app", 4000);
  };
  const cancelConfirmation = $("cancelPairingConfirm");
  const pairingDialog = $("pairingConfirmation");
  if (pairingDialog) pairingDialog.onclose = () => {
    state.pendingPairingInvitation = "";
    state.pairingPreview = null;
  };
  if (cancelConfirmation) cancelConfirmation.onclick = () => {
    state.pendingPairingInvitation = "";
    state.pairingPreview = null;
    const dialog = $("pairingConfirmation");
    if (dialog?.open) dialog.close();
  };
  const confirm = $("confirmPairing");
  if (confirm) confirm.onclick = async () => {
    const invitation = state.pendingPairingInvitation;
    if (!invitation || !state.pairingPreview?.can_pair || confirm.disabled) return;
    confirm.disabled = true;
    cancelConfirmation && (cancelConfirmation.disabled = true);
    $("pairingConfirmMessage").textContent = "Pairing and starting Wi-Fi sync…";
    try {
      await api("/api/pairing/connect", { method: "POST", body: JSON.stringify({ invitation }), timeout: 30000 });
      state.pendingPairingInvitation = "";
      state.pairingPreview = null;
      const dialog = $("pairingConfirmation");
      if (dialog?.open) dialog.close();
      await refreshPairingSettings();
      showToast("Device paired. Syncing over Wi-Fi.");
    } catch (error) {
      $("pairingConfirmMessage").textContent = error.message || "Pairing failed. Scan the QR code again.";
      confirm.disabled = false;
    } finally {
      if (cancelConfirmation) cancelConfirmation.disabled = false;
    }
  };
  if (state.pairingPollTimer) clearInterval(state.pairingPollTimer);
  refreshPairingSettings();
  state.pairingPollTimer = setInterval(refreshPairingSettings, 2500);
}

async function refreshPairingSettings() {
  const statusEl = $("pairingStatus");
  const list = $("pairedDeviceList");
  if (!statusEl || !list) return;
  try {
    const data = await api("/api/pairing/status");
    list.replaceChildren();
    if (data.role === "desktop") {
      const devices = data.devices || [];
      statusEl.textContent = devices.length ? `${devices.length} paired device${devices.length === 1 ? "" : "s"} · syncing over Wi-Fi` : "No devices paired";
      if (devices.some(device => !state.pairingBeforeInvite.includes(device.device_id))) {
        clearTimeout(state.pairingQrTimer);
        state.pairingInvite = null;
        state.pairingQrVisible = false;
        $("pairingInvitation")?.classList.add("hidden");
        const toggle = $("createPairingQr");
        if (toggle) { toggle.textContent = "Show pairing QR code"; toggle.setAttribute("aria-expanded", "false"); }
      }
      for (const device of devices) {
        const row = document.createElement("div");
        row.className = "paired-device-row";
        const info = document.createElement("div");
        const name = document.createElement("strong");
        name.textContent = device.name || "Android device";
        const detail = document.createElement("span");
        detail.textContent = `Paired ${new Date((device.paired_at || 0) * 1000).toLocaleString()} · last sync ${new Date((device.last_seen || 0) * 1000).toLocaleTimeString()}`;
        info.append(name, detail);
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "danger";
        remove.textContent = "Remove";
        remove.onclick = async () => {
          remove.disabled = true;
          try {
            await api("/api/pairing/remove", { method: "POST", body: JSON.stringify({ device_id: device.device_id }) });
            await refreshPairingSettings();
          } catch (error) { showToast(error.message || "Could not remove device", 5000); remove.disabled = false; }
        };
        row.append(info, remove);
        list.append(row);
      }
    } else {
      const pair = data.pair || {};
      const scanButton = $("scanPairingQr");
      if (scanButton) scanButton.classList.toggle("hidden", !!data.paired);
      if (data.paired) {
        statusEl.textContent = `Paired with ${pair.name || "desktop"}${data.last_sync ? ` · synced ${new Date(data.last_sync * 1000).toLocaleTimeString()}` : " · syncing…"}`;
        const row = document.createElement("div");
        row.className = "paired-device-row";
        const info = document.createElement("div");
        const name = document.createElement("strong"); name.textContent = pair.name || "Mindinguflac desktop";
        const detail = document.createElement("span"); detail.textContent = data.last_error || "Recently played, settings and listening statistics sync automatically.";
        info.append(name, detail);
        const remove = document.createElement("button"); remove.type = "button"; remove.className = "danger"; remove.textContent = "Remove pairing";
        remove.onclick = async () => {
          remove.disabled = true;
          try { await api("/api/pairing/remove", { method: "POST", body: "{}" }); await refreshPairingSettings(); }
          catch (error) { showToast(error.message || "Could not send the removal message", 5000); remove.disabled = false; }
        };
        row.append(info, remove); list.append(row);
      } else {
        const nearby = (data.discovered || []).map(item => item.name).filter(Boolean);
        statusEl.textContent = data.last_error || (nearby.length ? `Nearby: ${nearby.join(", ")}` : "Waiting for a desktop on this Wi-Fi network");
      }
    }
  } catch (error) {
    statusEl.textContent = error.message || "Pairing status unavailable";
  }
}

window.handleDevicePairingUrl = function (value) {
  if (!IS_ANDROID) return false;
  const invitation = String(value || "").trim();
  if (!invitation) return false;
  void presentDevicePairingConfirmation(invitation);
  return true;
};

async function presentDevicePairingConfirmation(invitation) {
  state.pendingPairingInvitation = invitation;
  state.pairingPreview = null;
  if (!$("settings")?.classList.contains("active")) await pushPage(renderSettings);
  const confirmation = $("pairingConfirmation");
  const confirm = $("confirmPairing");
  const cancel = $("cancelPairingConfirm");
  if (!confirmation || !confirm) {
    showToast("Could not open the pairing confirmation in Settings.", 5000);
    return;
  }
  if (!confirmation.open) confirmation.showModal();
  $("pairingConfirmTitle").textContent = "Confirm device pairing";
  $("pairingConfirmMessage").textContent = "Checking the desktop identity on your Wi-Fi network…";
  let qrName = "Mindinguflac desktop";
  let qrFingerprint = "";
  try {
    const parsed = new URL(invitation);
    qrName = parsed.searchParams.get("name") || qrName;
    qrFingerprint = parsed.searchParams.get("fingerprint") || "";
  } catch (_) {
    try {
      const parsed = JSON.parse(invitation);
      qrName = parsed.name || qrName;
      qrFingerprint = parsed.fingerprint || "";
    } catch (_) {}
  }
  $("pairingConfirmName").textContent = qrName;
  $("pairingConfirmFingerprint").textContent = qrFingerprint.match(/.{1,4}/g)?.join(" ") || "Checking fingerprint…";
  confirm.disabled = true;
  if (cancel) cancel.disabled = false;
  try {
    const preview = await api("/api/pairing/preview", {
      method: "POST",
      body: JSON.stringify({ invitation }),
      timeout: 30000,
    });
    if (state.pendingPairingInvitation !== invitation) return;
    state.pairingPreview = preview;
    $("pairingConfirmName").textContent = preview.name || "Mindinguflac desktop";
    $("pairingConfirmFingerprint").textContent = String(preview.fingerprint || "").match(/.{1,4}/g)?.join(" ") || "Unavailable";
    if (!preview.verified) {
      $("pairingConfirmTitle").textContent = "Could not verify desktop";
      $("pairingConfirmMessage").textContent = preview.error || "The scanned device could not be verified on this Wi-Fi network.";
      confirm.disabled = true;
    } else if (preview.already_paired) {
      $("pairingConfirmTitle").textContent = "Already paired";
      $("pairingConfirmMessage").textContent = `This phone is already paired with ${preview.name || "this desktop"}. Remove the existing pairing before scanning again.`;
    } else if (!preview.can_pair) {
      $("pairingConfirmTitle").textContent = "Another desktop is paired";
      $("pairingConfirmMessage").textContent = `This phone is already paired with ${preview.paired_with || "another desktop"}. Remove that pairing before continuing.`;
    } else {
      $("pairingConfirmMessage").textContent = "Pair this phone with the desktop shown above? Confirm to begin syncing, or cancel to leave the devices unpaired.";
      confirm.disabled = false;
    }
  } catch (error) {
    if (state.pendingPairingInvitation !== invitation) return;
    $("pairingConfirmTitle").textContent = "Could not verify desktop";
    $("pairingConfirmName").textContent = qrName;
    $("pairingConfirmFingerprint").textContent = qrFingerprint.match(/.{1,4}/g)?.join(" ") || "Unavailable";
    $("pairingConfirmMessage").textContent = error.message || "Could not verify this pairing request.";
    confirm.disabled = true;
  }
}

function showSettingsNotice(title, message) {
  const dialog = $("settingsNoticeDialog");
  if (!dialog) return;
  $("settingsNoticeTitle").textContent = title;
  $("settingsNoticeMessage").textContent = message;
  $("settingsNoticeClose").onclick = () => dialog.close();
  if (!dialog.open) dialog.showModal();
}

async function saveSettings(e) {
  e.preventDefault();
  const body = {
    ...state.settings,
    cache_dir: $("cacheDir").value,
    music_dir: $("musicDir").value,
    download_engine: $("downloadEngine").value,
    torrent_playback_candidates: Number($("torrentPlaybackCandidates").value),
    torrent_prefetch_candidates: Number($("torrentPrefetchCandidates").value),
    torrent_metadata_timeout_seconds: Number($("torrentMetadataTimeout").value),
    ai_provider: IS_ANDROID ? "android" : ($("aiProvider") ? $("aiProvider").value : "duckai"),
    duck_model: $("duckModel") ? $("duckModel").value : "1",
    gemini_model: $("geminiModel") ? $("geminiModel").value : "gemini-1.5-flash",
    tour_source: $("tourSource") ? $("tourSource").value : "ai",
    tour_city: $("tourCity") ? $("tourCity").value.trim() : "",
    tour_lat: $("tourLat") ? $("tourLat").value.trim() : "",
    tour_lon: $("tourLon") ? $("tourLon").value.trim() : "",
    download_service: $("downloadService").value,
    default_quality: $("defaultQuality").value || (IS_ANDROID ? "m4a" : "LOSSLESS"),
    track_max_retries: parseInt($("trackMaxRetries").value),

    cache_cleanup_frequency: $("cacheCleanupFrequency").value,

    demo_music_indexer: $("demoMusicIndexer") ? $("demoMusicIndexer").checked : !!state.settings.demo_music_indexer,
    strict_title_match: $("strictTitleMatch") ? $("strictTitleMatch").checked : !!state.settings.strict_title_match,
    discogs_token: $("discogsToken").value.trim(),
    music_indexers: []
  };
  try {
    await api("/api/settings", { method: "POST", body: JSON.stringify(body) });
    state.settings = body;
    state.tourLocation = null;
    showSettingsNotice("Settings saved", "Your preferences have been saved.");
  } catch (e) { showSettingsNotice("Could not save settings", e.message || "Please try again."); }
}

// ---------------------------------------------------------------------------
// Player & Boot
// ---------------------------------------------------------------------------

function isNativeAudioSelected() {
  return typeof _activeSinkId === "string" && _activeSinkId.startsWith("native:") && !!_nativeAudioDeviceUid;
}

function canStreamActiveJobInBrowser(job) {
  // Monochrome's growing FLAC is played by WebKit while the native player
  // waits for a complete local file. Hand off to native output after download.
  return String(job?.engine || "").toLowerCase() === "monochrome" || !isNativeAudioSelected();
}

function nativeAudioVolume() {
  const audio = $("audioPlayer");
  return audio ? Number(audio.volume || 0) : storedVolume();
}

async function stopNativeAudio() {
  if (state.nativeAudio.active) {
    const result = await api("/api/native_audio/stop", { method: "POST", body: "{}" });
    if (result && result.ok === false) {
      throw new Error(result.error || "Native audio did not stop");
    }
  }
  if (state.nativeAudioPollTimer) {
    clearInterval(state.nativeAudioPollTimer);
    state.nativeAudioPollTimer = null;
  }
  state.nativeAudio = { active: false, playing: false, position: 0, duration: 0, path: "", ended: false };
  state.nativeAudioStarting = false;
  state.nativeAudioPauseAfterStart = false;
  syncPlayPauseButton();
}

async function startNativeAudio(filePath, track, requestId, position = 0, streamUrl = "", forceNative = false) {
  if (!forceNative && !isNativeAudioSelected()) return false;
  const directStreamUrl = streamUrl && isMonochromeDirectStreamUrl(streamUrl) ? streamUrl : "";
  // Close the startup window where the UI still thinks the browser owns the
  // player. A pause click during native initialization must never be applied
  // to the stale HTMLAudio element while this stream takes over.
  if (directStreamUrl && requestId === state.playbackRequestId) {
    state.nativeAudioStarting = true;
    state.audioBuffering = !state.manualPauseRequested;
    if (state.audioBuffering) setPlayerStatus("Buffering Monochrome stream", track);
    syncPlayPauseButton();
  }
  const deviceUid = isNativeAudioSelected() ? _nativeAudioDeviceUid : "";
  const startKey = `${requestId}|${deviceUid}|${directStreamUrl || filePath}`;
  if (state.nativeAudioStart?.key === startKey) {
    const pendingResult = await state.nativeAudioStart.promise;
    if (!pendingResult.ok) throw new Error(pendingResult.error || "Native audio failed");
    return true;
  }
  const startPromise = api("/api/native_audio/play", {
    method: "POST",
    body: JSON.stringify({
      path: filePath,
      stream_url: directStreamUrl,
      device_uid: deviceUid,
      device_name: isNativeAudioSelected() ? String(state.settings?.preferred_audio_output_name || "") : "",
      volume: nativeAudioVolume(),
      position,
      metadata: track,
    }),
  });
  state.nativeAudioStart = { key: startKey, promise: startPromise };
  let result;
  try {
    result = await startPromise;
  } catch (error) {
    if (requestId === state.playbackRequestId && directStreamUrl) {
      state.nativeAudioStarting = false;
      state.audioBuffering = false;
      syncPlayPauseButton();
    }
    throw error;
  } finally {
    if (state.nativeAudioStart?.promise === startPromise) {
      state.nativeAudioStart = null;
      syncPlayPauseButton();
    }
  }
  if (!result.ok) {
    if (requestId === state.playbackRequestId && directStreamUrl) {
      state.nativeAudioStarting = false;
      state.nativeAudioPauseAfterStart = false;
      state.audioBuffering = false;
      syncPlayPauseButton();
    }
    if (directStreamUrl && result.stream_blocked && fallbackFromBlockedMonochrome(track, requestId, result.error)) {
      return false;
    }
    throw new Error(result.error || "Native audio failed");
  }
  state.nativeAudio = {
    active: true,
    playing: !!result.playing,
    position: result.position || 0,
    duration: result.duration || 0,
    path: filePath,
    stream_url: directStreamUrl,
    stream_phase: result.stream_phase || "",
    buffering: !!result.buffering || result.stream_phase === "buffering",
    ended: false,
  };
  state.nativeAudioStarting = false;
  if (state.nativeAudioPauseAfterStart && requestId === state.playbackRequestId) {
    state.nativeAudioPauseAfterStart = false;
    state.manualPauseRequested = true;
    state.autoplayWanted = false;
    const paused = await api("/api/native_audio/pause", { method: "POST", body: "{}" });
    state.nativeAudio.playing = !!paused.playing;
    if (Number.isFinite(Number(paused.position))) state.nativeAudio.position = Number(paused.position);
    state.audioBuffering = false;
  }
  state.audioBuffering = !!directStreamUrl && !state.nativeAudio.playing && !state.manualPauseRequested;
  if (state.audioBuffering) setPlayerStatus("Buffering Monochrome stream", track);
  updateListeningSessionPosition(state.nativeAudio.position, state.nativeAudio.duration);
  syncPlayPauseButton();
  updateMediaSession(track);
  startNativeAudioPolling(requestId);
  return true;
}

// Monochrome answers repeated requests with 429 and then 403. Retrying the
// same URL only extends the block, so the backend starts a cooldown during
// which new jobs use YTP-DL; restart the current track once through it.
function fallbackFromBlockedMonochrome(track, requestId, reason = "") {
  if (!track || requestId !== state.playbackRequestId) return false;
  if (state.monochromeBlockedFallbackRequestId === requestId) return false;
  state.monochromeBlockedFallbackRequestId = requestId;
  const message = reason || "Monochrome refused the stream";
  logMonochromePlaybackActivity(`${message}; switching this track to YouTube`, track, "blocked-fallback", 0);
  state.nativeAudio = { ...state.nativeAudio, active: false, playing: false, stream_url: "" };
  state.currentStreamUrl = "";
  state.directStreamNativeFallbackAttempted = false;
  state.audioBuffering = !state.manualPauseRequested;
  setPlayerStatusIcon("downloading", 0);
  setPlayerStatus(`${message} — trying YouTube`, track);
  syncPlayPauseButton();
  startServiceDownload(track, "stream", requestId);
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
  await _persistPreferredAudioOutput({ deviceId: "", name: "", nativeUid: "", bluetoothAddress: "" });
  $("btnConnectDevice").classList.toggle("active", false);
  _refreshConnectPanel().catch(() => {});
  if (track && isMonochromeDirectStreamUrl(state.currentStreamUrl)) {
    const audio = $("audioPlayer");
    audio.src = browserAudioStreamUrl(state.currentStreamUrl);
    audio.load();
    seekAfterMetadata(audio, position);
    if (!state.manualPauseRequested) tryStartAudio(audio, track, requestId, null);
  } else if (libraryPath && track) {
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
      if (isMonochromeDirectStreamUrl(state.nativeAudio.stream_url)) {
        await setAudioOutputDevice("");
        await _persistPreferredAudioOutput({ deviceId: "", name: "", nativeUid: "", bluetoothAddress: "" });
        await _refreshConnectPanel().catch(() => {});
      } else {
        await fallbackToDefaultOutputAndResume(state.playbackRequestId, state.nativeAudio.position || 0);
      }
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
    if (status.error) {
      const failedStreamUrl = state.nativeAudio.stream_url;
      state.nativeAudio = { ...state.nativeAudio, active: false, playing: false };
      clearInterval(state.nativeAudioPollTimer);
      state.nativeAudioPollTimer = null;
      if ([403, 429].includes(Number(status.stream_http_status)) && isMonochromeDirectStreamUrl(failedStreamUrl) &&
          fallbackFromBlockedMonochrome(state.currentTrack, requestId, status.error)) {
        publishNowPlayingState(2);
        return;
      }
      state.audioBuffering = false;
      state.autoplayWanted = false;
      if (state.currentTrack) setPlayerStatus(`Audio output stopped: ${status.error}`, state.currentTrack);
      syncPlayPauseButton();
      publishNowPlayingState(2);
      return;
    }
    state.nativeAudio = {
      ...state.nativeAudio,
      playing: !!status.playing,
      stream_phase: status.stream_phase || "",
      buffering: !!status.buffering || status.stream_phase === "buffering",
      position: status.position || 0,
      duration: status.duration || 0,
      ended: !!status.ended,
      output_latency: Number(status.output_latency || 0),
    };
    // The worker moves the stream to the default output by itself when the
    // selected device stops accepting audio (Bluetooth dropped). Follow it so
    // the device menu and the next switch start from the real route.
    // (Android's player does the same for files when the chosen output goes.)
    if ((isMonochromeDirectStreamUrl(state.nativeAudio.stream_url) || IS_ANDROID) && !_outputSwitchesInFlight &&
        typeof status.device_uid === "string" && status.device_uid !== (_nativeAudioDeviceUid || "")) {
      _nativeAudioDeviceUid = status.device_uid;
      _activeSinkId = status.device_uid ? `native:${status.device_uid}` : "";
      if (status.output_notice && state.currentTrack) setPlayerStatus(status.output_notice, state.currentTrack);
      _refreshConnectPanel().catch(() => {});
    }
    if (status.playing) {
      const wasBuffering = state.audioBuffering;
      state.audioBuffering = false;
      if (isMonochromeDirectStreamUrl(state.nativeAudio.stream_url)) setPlayerStatusIcon("ready");
      if (wasBuffering && state.currentTrack) {
        setPlayerStatus(
          isMonochromeDirectStreamUrl(state.nativeAudio.stream_url)
            ? "Streaming from Monochrome" : "Playing on selected device",
          state.currentTrack,
        );
      }
    }
    else if (state.nativeAudio.stream_url && !state.manualPauseRequested) state.audioBuffering = true;
    updateListeningSessionPosition(state.nativeAudio.position, state.nativeAudio.duration);
    syncNativeAudioUi();
    followAudioWithVideo();
    updateLyricsPosition(state.nativeAudio.position || 0);
    // Prefetch the next track once playback is underway. The <audio> element's
    // ontimeupdate never fires on the native path, so trigger it here too.
    maybePrefetchUpcomingTracks(state.nativeAudio.position);
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
  const duration = state.nativeAudio.duration || knownTrackDurationSeconds(state.currentTrack);
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
  if (playbackTransportBusy()) return;
  if (!state.nativeAudio.active) {
    if (state.nativeAudioStarting) {
      state.manualPauseRequested = true;
      state.autoplayWanted = false;
      state.nativeAudioPauseAfterStart = true;
    }
    return;
  }

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
    state.audioBuffering = false;
    const status = await api("/api/native_audio/pause", { method: "POST", body: "{}" });
    state.nativeAudio.playing = !!status.playing;
    if (Number.isFinite(Number(status.position))) state.nativeAudio.position = Number(status.position);
    if (Number.isFinite(Number(status.duration)) && Number(status.duration) > 0) state.nativeAudio.duration = Number(status.duration);
    state.audioBuffering = false;
    // If it's still playing after a pause request, it might be out of sync
    if (state.nativeAudio.playing) {
        console.warn("[NativeAudio] Pause request did not stop playback, forcing state update");
        const forced = await api("/api/native_audio/status").catch(() => null);
        if (forced) state.nativeAudio.playing = !!forced.playing;
    }
    publishNowPlayingState(2);
  } else {
    state.manualPauseRequested = false;
    state.audioBuffering = !!state.nativeAudio.stream_url;
    const status = await api("/api/native_audio/resume", { method: "POST", body: "{}" });
    if (Number.isFinite(Number(status.position))) state.nativeAudio.position = Number(status.position);
    if (Number.isFinite(Number(status.duration)) && Number(status.duration) > 0) state.nativeAudio.duration = Number(status.duration);
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
    state.audioBuffering = !!state.nativeAudio.stream_url && !state.nativeAudio.playing;
    publishNowPlayingState(1);
  }
  syncNativeAudioUi();
  syncPlayPauseButton();
  followAudioWithVideo();
}

function playbackTransportBusy() {
  const native = state.nativeAudio || {};
  const pendingStart = state.nativeAudioStarting || !!state.nativeAudioStart?.promise;
  const nativeWaiting = native.active && !native.ended && !state.manualPauseRequested && (
    native.buffering || ["opening", "buffering", "resolving", "connecting"].includes(native.stream_phase)
    || (native.stream_url && !native.playing)
  );
  return !!(state.audioBuffering || pendingStart || nativeWaiting);
}

function syncPlayPauseButton() {
  const audio = $("audioPlayer");
  const playPause = $("playPause");
  const busy = playbackTransportBusy();
  const paused = state.nativeAudio.active
    ? (state.manualPauseRequested || !state.nativeAudio.playing)
    : !audio || audio.paused || state.audioBuffering;
  const icon = playPause?.querySelector("i");
  if (playPause) {
    playPause.disabled = busy;
    playPause.setAttribute("aria-label", busy ? (state.nativeAudioStarting ? "Loading" : "Buffering") : (paused ? "Play" : "Pause"));
    playPause.setAttribute("aria-busy", busy ? "true" : "false");
  }
  if (icon) {
    icon.className = paused ? "bi bi-play-fill" : "bi bi-pause-fill";
  }
  renderPlayerStatusIcon();
  publishDockPlayingState(!paused);
  persistPlaybackSnapshot();
}

let _lastDockPlayingState = null;
function publishDockPlayingState(playing, force = false) {
  const next = !!playing;
  if (!force && _lastDockPlayingState === next) return;
  _lastDockPlayingState = next;
  api("/api/dock/playing-state", {
    method: "POST",
    body: JSON.stringify({ playing: next }),
  }).catch(() => { _lastDockPlayingState = null; });
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
      if (playbackTransportBusy()) return;
      if (state.nativeAudio.active) {
        toggleNativeAudioPlayback().catch(() => {});
        return;
      }
      if (isNativeAudioSelected() && state.currentTrack && $("audioPlayer").paused &&
          (state.currentLibraryPath || isMonochromeDirectStreamUrl(state.currentStreamUrl))) {
        state.manualPauseRequested = false;
        startNativeAudio(state.currentLibraryPath, state.currentTrack, state.playbackRequestId,
          state.nativeAudio.position || state.directStreamPosition || 0,
          isMonochromeDirectStreamUrl(state.currentStreamUrl) ? state.currentStreamUrl : "").catch(() => {});
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
  });
}

function storedVolume() {
  // On a phone the hardware keys and the system volume panel own playback
  // volume. Keeping a second software attenuation in the page meant the audio
  // could be quiet with the system volume at full and no obvious reason why,
  // so Android always plays at unity gain.
  if (IS_ANDROID) return 1;
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

// On Android the page's audio element is the player, but the system knows
// nothing about it: there is no notification, no lock-screen controls, and the
// WebView is free to be suspended once the app is backgrounded. Mirroring the
// state into the native bridge gives the foreground media service something to
// show and keeps playback alive while the app is not on screen.
function pushAndroidNowPlaying(payload, playing) {
  if (!IS_ANDROID || !window.MindinguflacAndroid?.updateNowPlaying) return;
  try {
    window.MindinguflacAndroid.updateNowPlaying(JSON.stringify({
      title: payload.title || "",
      artist: payload.artist || "",
      album: payload.album || "",
      artwork_url: payload.artwork_url || "",
      duration_ms: Math.max(0, Math.round((payload.duration || 0) * 1000)),
      position_ms: Math.max(0, Math.round((payload.position || 0) * 1000)),
      playing: Boolean(playing),
    }));
  } catch (_) {}
}

function clearAndroidNowPlaying() {
  if (!IS_ANDROID || !window.MindinguflacAndroid?.clearNowPlaying) return;
  try { window.MindinguflacAndroid.clearNowPlaying(); } catch (_) {}
}

function clearMediaSession() {
  if ("mediaSession" in navigator) {
    navigator.mediaSession.metadata = null;
    navigator.mediaSession.playbackState = "none";
  }
  clearAndroidNowPlaying();
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

  const payload = {
    title: track.title || "Unknown",
    artist: track.artist || "",
    album: track.album || "",
    duration: durSec,
    position,
    artwork_url: art,
  };

  const audioElement = $("audioPlayer");
  pushAndroidNowPlaying(payload, state.nativeAudio.active
    ? Boolean(state.nativeAudio.playing && !state.manualPauseRequested)
    : Boolean(audioElement && !audioElement.paused && !state.audioBuffering));

  if (state.settings?.native_now_playing_active) {
    // If the desktop native helper is active, use it as the primary source.
    _callNowPlaying("set_now_playing", payload);
    // Clear browser media session to avoid duplicate widgets on macOS.
    if ("mediaSession" in navigator) {
      navigator.mediaSession.metadata = null;
    }
  } else if ("mediaSession" in navigator) {
    // Fallback for standard browsers: use navigator.mediaSession
    navigator.mediaSession.metadata = new MediaMetadata({
      title: payload.title,
      artist: payload.artist,
      album: payload.album,
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

function publishNowPlayingState(stateValue = null) {
  if (!state.currentTrack || !shouldExposeNowPlaying()) return;
  updateMediaSession(state.currentTrack);
  if (stateValue !== null) {
    _callNowPlaying("set_playback_state", stateValue);
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
    if (playbackTransportBusy()) return;
    // A restored snapshot can finish loading after the stream has already
    // started. Never interpret the first Pause click as a request to reselect
    // that active track (which restarts it at 0:00). Consume the pending flag
    // once the player is actually running; only use the special restore path
    // when playback is still idle and the media element has no source.
    if (state.restoredPlaybackPending && !audio.paused) {
      state.restoredPlaybackPending = false;
    }
    if (state.restoredPlaybackPending && state.currentTrack && audio.paused &&
        (!audio.src || audio.src === window.location.href) && !state.nativeAudio.active) {
      const track = state.currentTrack;
      const position = Number(state.pendingResumePosition || 0);
      state.restoredPlaybackPending = false;
      state.pendingResumePosition = position;
      selectMusicItem(track, "stream", null, null).catch((error) => {
        state.restoredPlaybackPending = true;
        state.pendingResumePosition = position;
        setPlayerStatus(error.message || "Playback failed", track);
      });
      return;
    }
    if (state.nativeAudio.active) {
      toggleNativeAudioPlayback().catch((error) => {
        if (state.currentTrack) setPlayerStatus(error.message || "Native audio failed", state.currentTrack);
      });
      return;
    }
    // WebKit cannot decode Monochrome's FLAC, so its audio element is cleared
    // when we hand off to the native decoder. If that first native request is
    // rate-limited or otherwise fails, Play must retry the native stream
    // instead of treating the empty browser element as an idle player.
    if (state.directStreamNativeFallbackAttempted && state.currentTrack &&
        isMonochromeDirectStreamUrl(state.currentStreamUrl)) {
      if (state.audioBuffering || state.nativeAudioStarting) return;
      state.manualPauseRequested = false;
      state.autoplayWanted = true;
      state.audioBuffering = true;
      syncPlayPauseButton();
      startNativeAudio("", state.currentTrack, state.playbackRequestId,
        state.nativeAudio.position || state.directStreamPosition || 0,
        state.currentStreamUrl, true).catch((error) => {
        state.audioBuffering = false;
        state.autoplayWanted = false;
        if (state.currentTrack) setPlayerStatus(`Monochrome playback failed: ${error.message || error}`, state.currentTrack);
        syncPlayPauseButton();
      });
      return;
    }
    // Only hand a click to native-start when the browser isn't already playing.
    // If a switch to native output didn't actually move playback (no cache file
    // yet, or native start failed), the browser keeps playing while
    // isNativeAudioSelected() is true; without this guard every click re-fires
    // startNativeAudio and the pause button can never stop the browser audio.
    if (isNativeAudioSelected() && state.currentTrack && audio.paused &&
        (state.currentLibraryPath || isMonochromeDirectStreamUrl(state.currentStreamUrl))) {
      state.manualPauseRequested = false;
      startNativeAudio(state.currentLibraryPath, state.currentTrack, state.playbackRequestId,
        state.nativeAudio.position || state.directStreamPosition || 0,
        isMonochromeDirectStreamUrl(state.currentStreamUrl) ? state.currentStreamUrl : "").catch((error) => {
        if (state.currentTrack) setPlayerStatus(error.message || "Native audio failed", state.currentTrack);
      });
      return;
    }
    if (audio.paused || state.audioBuffering) {
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
    const vid = $("sideVideoPlayer");
    if (vid && vid.tagName === "VIDEO") {
      if (!isPlaybackVisiblyActive()) vid.pause();
      else vid.play().catch(() => {});
    }
    if (audio.paused || state.audioBuffering) {
      if (state.currentTrack) {
        publishNowPlayingState(2);
      } else {
        _callNowPlaying("clear_now_playing");
      }
    } else if (shouldExposeNowPlaying()) {
      publishNowPlayingState(1);
    }
  };
  audio.onended = async () => {
    if (state.nativeAudioStarting || state.nativeAudio.active) return;
    // A user-paused stream must never auto-advance. A growing-file active-job
    // stream can fire "ended" when playback reaches the current download head;
    // if the user paused, that would wrap a length-1 queue back onto the same
    // track and replay it from the start.
    if (state.manualPauseRequested) return;
    if (isMonochromeDirectStreamUrl(state.currentStreamUrl)) {
      const reportedDuration = knownTrackDurationSeconds(state.currentTrack) ||
        (Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : 0);
      const endedAt = Number.isFinite(audio.currentTime) && audio.currentTime > 0
        ? audio.currentTime : Number(state.directStreamPosition || 0);
      // WebKit can signal `ended` when a ranged FLAC response stalls or closes,
      // even though Spotify metadata says the recording is still in progress.
      // Treat that as a dropped stream and resume at its last known playhead.
      if (reportedDuration > 0 && endedAt < reportedDuration - 2) {
        state.directStreamPosition = endedAt;
        state.rebufferPosition = endedAt;
        state.audioBuffering = true;
        const video = $("sideVideoPlayer");
        if (video && video.tagName === "VIDEO") video.pause();
        logMonochromePlaybackActivity(
          `Monochrome stream ended early at ${formatTime(endedAt)} of ${formatTime(reportedDuration)}; reconnecting without advancing`,
          state.currentTrack,
          "premature-ended",
          0,
        );
        if (state.currentTrack) setPlayerStatus("Buffering Monochrome stream", state.currentTrack);
        syncPlayPauseButton();
        if (!state.directStreamReconnectPending) reconnectMonochromeAfterBuffer(audio);
        return;
      }
    }
    const endedRequestId = state.playbackRequestId;
    const endedJobId = state.activeJobId;
    if (isActiveJobStreamUrl(state.currentStreamUrl) && endedJobId) {
      if (await activeJobStillRunning(endedJobId)) {
        waitForActiveJobBuffer(audio);
        return;
      }
      if (endedRequestId !== state.playbackRequestId || state.activeJobId !== endedJobId) return;
    }
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
    if (state.nativeAudioStarting || state.nativeAudio.active) return;
    maybePrefetchUpcomingTracks(audio.currentTime || 0);
    const spotifyDuration = knownTrackDurationSeconds(state.currentTrack);
    const duration = isMonochromeDirectStreamUrl(state.currentStreamUrl)
      ? (spotifyDuration || (Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : 0))
      : (Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : spotifyDuration);
    const position = Number.isFinite(audio.currentTime) ? audio.currentTime : 0;
    if (isMonochromeDirectStreamUrl(state.currentStreamUrl)) {
      const restoringPosition = state.directStreamReconnectPending || state.directStreamResumePending;
      // WebKit can emit `playing` before the reopened range produces usable
      // audio. Only clear the retry loop after the playhead actually advances.
      if (restoringPosition && position + 0.75 < Number(state.directStreamAttemptPosition || 0)) {
        // Ignore the transient zero timestamp emitted while the new range is
        // opening; it is not the current playhead and must not replace the
        // saved position used by a subsequent retry.
        state.directStreamPosition = Number(state.directStreamAttemptPosition || state.directStreamPosition || 0);
      } else {
        state.directStreamPosition = position;
      }
      if (restoringPosition && position > Number(state.directStreamAttemptPosition || 0) + 0.75) {
        state.directStreamReconnectPending = false;
        state.directStreamReconnectAttempts = 0;
        state.directStreamResumePending = false;
        if (state.directStreamReconnectTimer) clearTimeout(state.directStreamReconnectTimer);
        state.directStreamReconnectTimer = null;
      }
    }
    if (duration <= 0) return;
    updateListeningSessionPosition(position, duration);
    if (state.streamRetryCount) state.streamRetryCount = 0; // playback recovered
    $("seekBar").value = (position / duration) * 1000;
    $("currentTime").textContent = formatTime(position);
    $("durationTime").textContent = formatTime(duration);
    $("seekBar").style.backgroundSize = `${(position / duration) * 100}% 100%`;
    setMiniPlayerProgress(position / duration);
    followAudioWithVideo();
    updateLyricsPosition(position);
    if (shouldExposeNowPlaying()) updateMediaSession(state.currentTrack);
    persistPlaybackSnapshot();
  };
  audio.onseeked = () => {
    if (isMonochromeDirectStreamUrl(state.currentStreamUrl) && Number.isFinite(audio.currentTime)) {
      state.directStreamPosition = audio.currentTime;
    }
    syncLocalVideoOverlay(audio.currentTime || 0, true, { allowSeek: true });
  };
  audio.onloadedmetadata = () => {
    if (state.currentTrack && shouldExposeNowPlaying()) {
      updateMediaSession(state.currentTrack);
    }
    if (audio.duration) {
      updateListeningSessionPosition(audio.currentTime || 0, audio.duration);
      updateLyricsPosition(audio.currentTime || 0, true);
      syncLocalVideoOverlay(audio.currentTime || 0, false, { allowSeek: true });
    }
  };
  audio.oncanplay = () => {
    if (state.autoplayWanted && !state.manualPauseRequested && !state.rebuffering && audio.paused) {
      audio.play().catch(() => {});
    }
    // canplay only means data is available; wait for the audio element's
    // `playing` event before resuming video so both tracks restart together.
    syncLocalVideoOverlay(audio.currentTime || 0, false, { allowSeek: true });
  };
  audio.onwaiting = () => {
    if (state.nativeAudioStarting || state.nativeAudio.active) return;
    // Safari/WebKit often reports `waiting` as it tears down a ranged response
    // on pause. Do not convert the user's pause into a reconnect/buffer loop.
    if (state.manualPauseRequested) {
      state.audioBuffering = false;
      syncPlayPauseButton();
      return;
    }
    state.audioBuffering = true;
    if (isMonochromeDirectStreamUrl(state.currentStreamUrl)) {
      const position = Number.isFinite(audio.currentTime) ? audio.currentTime : state.directStreamPosition || 0;
      logMonochromePlaybackActivity(
        `Monochrome stream is buffering at ${formatTime(position)}`,
        state.currentTrack,
        "waiting",
        5000,
      );
    }
    const video = $("sideVideoPlayer");
    if (video && video.tagName === "VIDEO") video.pause();
    syncPlayPauseButton();
    if (state.currentTrack && !state.manualPauseRequested) publishNowPlayingState(2);
    reconnectMonochromeAfterBuffer(audio);
    if (state.activeJobId && isActiveJobStreamUrl(state.currentStreamUrl) && !state.manualPauseRequested) {
      waitForActiveJobBuffer(audio);
    }
    if (state.currentTrack) {
      setPlayerStatus(state.activeJobPhase === "Searching..." ? "Searching..." : "Buffering...", state.currentTrack);
    }
  };
  audio.onplaying = () => {
    if (state.nativeAudioStarting || state.nativeAudio.active) return;
    // Do NOT clear manualPauseRequested here. This event also fires on buffer
    // recovery; clearing the user's pause intent would let other auto-play
    // triggers (onended, onerror, the job watcher) resume a track the user
    // deliberately paused. The intent is cleared only by an explicit play /
    // new-track action.
    const recoveringMonochrome = isMonochromeDirectStreamUrl(state.currentStreamUrl) &&
      (state.directStreamReconnectAttempts > 0 || state.directStreamResumePending);
    state.autoplayWanted = false;
    state.audioBuffering = false;
    state.audioHasPlayed = true;
    state.activeJobPhase = "";
    if (isMonochromeDirectStreamUrl(state.currentStreamUrl)) {
      setPlayerStatusIcon("ready");
      logMonochromePlaybackActivity(
        recoveringMonochrome ? "Monochrome stream recovered; audio playback resumed" : "Monochrome stream audio playback started",
        state.currentTrack,
        recoveringMonochrome ? "recovered" : "playing",
      );
    }
    const video = $("sideVideoPlayer");
    if (video && video.tagName === "VIDEO" && state.videoMode && !state.manualPauseRequested) {
      video.play().catch(() => {});
    }
    syncPlayPauseButton();
    // `playing` is the browser's confirmed transition. Force this update so a
    // newly started desktop/Dock process cannot retain an earlier paused state.
    publishDockPlayingState(true, true);
    if (state.currentTrack) {
        const isCache = isLibraryStreamUrl(state.currentStreamUrl);
        if (isMonochromeDirectStreamUrl(state.currentStreamUrl) || isCache || (state.currentLibraryPath && !isActiveJobStreamUrl(state.currentStreamUrl))) {
          setPlayerStatusIcon("ready");
        }
        setPlayerStatus(isCache ? "Playing from cache" : "Streaming...", state.currentTrack);
        publishNowPlayingState(1);
    }
  };
  audio.onerror = () => {
    if (state.nativeAudioStarting || state.nativeAudio.active) return;
    const error = audio.error;
    const erroredSrc = audio.currentSrc || audio.src || "";
    // Ignore errors if we don't have a source (common when using native output)
    if (!audio.src || audio.src === window.location.href) return;
    // WebKit may deliver a late error from the response that was closed by a
    // pause/reconnect. Do not let that obsolete response start a second search.
    if (erroredSrc) {
      try {
        if (new URL(erroredSrc, window.location.href).href !== new URL(audio.src, window.location.href).href) return;
      } catch (_) {}
    }
    if (state.activeJobId && isActiveJobStreamUrl(state.currentStreamUrl)) {
      // A growing stream may temporarily run out of data. Keep the download
      // and its already-tested torrents; reselecting cancels and deletes them.
      waitForActiveJobBuffer(audio);
      return;
    }
    if (state.manualPauseRequested) return;
    if (isMonochromeDirectStreamUrl(state.currentStreamUrl) && error && [2, 3, 4].includes(error.code)) {
      if (error.code === 4 && !state.directStreamNativeFallbackAttempted) {
        state.directStreamNativeFallbackAttempted = true;
        const resumeAt = Number.isFinite(audio.currentTime) && audio.currentTime > 0
          ? audio.currentTime : Number(state.directStreamPosition || 0);
        const streamUrl = state.currentStreamUrl;
        const fallbackRequestId = state.playbackRequestId;
        logMonochromePlaybackActivity(
          "Browser cannot decode Monochrome FLAC; switching to the 30-second native audio buffer",
          state.currentTrack,
          "native-fallback",
          0,
        );
        state.directStreamPosition = resumeAt;
        state.audioBuffering = true;
        state.autoplayWanted = true;
        syncPlayPauseButton();
        const video = $("sideVideoPlayer");
        if (video && video.tagName === "VIDEO") video.pause();
        audio.pause();
        audio.removeAttribute("src");
        audio.load();
        startNativeAudio("", state.currentTrack, fallbackRequestId, resumeAt, streamUrl, true)
          .then((started) => {
            if (state.playbackRequestId !== fallbackRequestId) {
              if (started) stopNativeAudio().catch(() => {});
              return;
            }
            if (!started) return;
            if (state.currentTrack) setPlayerStatus("Buffering Monochrome stream", state.currentTrack);
          })
          .catch((fallbackError) => {
            state.audioBuffering = false;
            state.autoplayWanted = false;
            logMonochromePlaybackActivity(
              `Native Monochrome playback failed: ${fallbackError.message || fallbackError}`,
              state.currentTrack,
              "native-fallback-error",
              0,
            );
            setPlayerStatus(`Monochrome playback failed: ${fallbackError.message || "native audio unavailable"}`, state.currentTrack);
            syncPlayPauseButton();
          });
        return;
      }
      logMonochromePlaybackActivity(
        `Monochrome browser audio error ${error.code}; reconnecting from ${formatTime(state.directStreamPosition || audio.currentTime || 0)}`,
        state.currentTrack,
        `media-error-${error.code}`,
        5000,
      );
      state.audioBuffering = true;
      syncPlayPauseButton();
      const video = $("sideVideoPlayer");
      if (video && video.tagName === "VIDEO") video.pause();
      if (state.currentTrack) {
        setPlayerStatus("Buffering… reconnecting to Monochrome", state.currentTrack);
        publishNowPlayingState(2);
      }
      reconnectMonochromeAfterBuffer(audio);
      return;
    }
    // WebKit can still dispatch an error for a previous active-job URL after
    // the player has already switched to the finalized cache file. Do not let
    // that stale failure repaint a currently selected cache source as failed.
    if (
      state.currentLibraryPath &&
      isLibraryStreamUrl(state.currentStreamUrl) &&
      erroredSrc &&
      erroredSrc !== state.currentStreamUrl
    ) {
      return;
    }

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
            audio.src = browserAudioStreamUrl(url.toString());
            audio.load();
            audio.currentTime = pos;
            audio.play().catch(() => {});
        }, 800);
    } else if (error && state.currentTrack) {
        console.error("[Player] Media error:", error.code, error.message);
        // Error codes: 1=ABORTED, 2=NETWORK, 3=DECODE, 4=SRC_NOT_SUPPORTED
        if (error.code === 2 || error.code === 3) {
            const key = trackKey(state.currentTrack);
            if (state.lastAutoRetryKey === key) {
                console.warn("[Player] Already tried re-resolving this track, stopping loop.");
                setPlayerStatusIcon("error");
                setPlayerStatus(`Playback failed (${error.code})`, state.currentTrack);
                return;
            }
            state.lastAutoRetryKey = key;
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
        // The native stream rebuffers after a seek; hold the video on the new
        // frame until the poll sees audio playing again.
        syncLocalVideoOverlay(position, false, { allowSeek: true });
        const seekVideo = $("sideVideoPlayer");
        if (seekVideo && seekVideo.tagName === "VIDEO") seekVideo.pause();
        if (shouldExposeNowPlaying()) {
          updateMediaSession(state.currentTrack);
        }
      }
      return;
    }
    const spotifyDuration = knownTrackDurationSeconds(state.currentTrack);
    const duration = isMonochromeDirectStreamUrl(state.currentStreamUrl)
      ? (spotifyDuration || (Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : 0))
      : (Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : spotifyDuration);
    if (duration > 0) {
      const position = ($("seekBar").value / 1000) * duration;
      audio.currentTime = position;
      if (isMonochromeDirectStreamUrl(state.currentStreamUrl)) state.directStreamPosition = position;
      if (shouldExposeNowPlaying()) {
        updateMediaSession(state.currentTrack);
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
      publishNowPlayingState(1);
    }
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && !audio.paused && state.currentTrack) {
      publishNowPlayingState(1);
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

        prefetchNextTracks().catch(() => {}); prefetchNextVideos();
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

const OFFLINE_PLAYLIST_ID = "__offline__";

function isReadOnlyPlaylist(playlist) {
  return !!playlist && (playlist.id === OFFLINE_PLAYLIST_ID || playlist.read_only === true);
}

function playlistArtworkHtml(playlist, className, id = "") {
  const idAttr = id ? ` id="${esc(id)}"` : "";
  if (playlist.id === OFFLINE_PLAYLIST_ID) {
    const covers = playlist.artwork_urls || [];
    const tiles = Array.from({ length: 4 }, (_, i) => covers.length
      ? `<img src="${esc(covers[i % covers.length])}" alt="" loading="lazy">`
      : '<span><i class="bi bi-music-note-beamed"></i></span>').join("");
    return `<div${idAttr} class="${className} playlist-art-grid" role="img" aria-label="Offline playlist cover">${tiles}</div>`;
  }
  const art = playlist.artwork_url || playlist.tracks?.[0]?.artwork_url || "";
  return `<div${idAttr} class="${className}" style="${art ? `background-image:url('${esc(art)}')` : ""}">${art ? "" : '<i class="bi bi-music-note-list"></i>'}</div>`;
}

async function loadPlaylists() {
  try {
    const playlists = await api("/api/playlists");
    if (JSON.stringify(state.playlists) !== JSON.stringify(playlists)) {
      state.playlists = playlists;
      renderSidebarPlaylists();
      if (state.activePlaylistId === OFFLINE_PLAYLIST_ID && $("pageContent")?.querySelector('[data-playlist-page="__offline__"]')) {
        const offline = playlists.find(pl => pl.id === OFFLINE_PLAYLIST_ID);
        if (offline) {
          const scrollTop = $("pageContent").querySelector(".scroll-area")?.scrollTop || 0;
          _renderPlaylistContent(offline, { kind: "playlist", id: offline.id, name: offline.name, origin: "offline", read_only: true, allow_playlist_continuation: false });
          $("pageContent").querySelector(".scroll-area").scrollTop = scrollTop;
        } else {
          state.activePlaylistId = null;
          replacePage(window.matchMedia("(max-width: 900px)").matches ? renderMobileLibraryPage : renderHomePage);
        }
      }
    }
    if (!state.playlistSyncRefreshTimer) {
      state.playlistSyncRefreshTimer = setInterval(() => {
        if (!document.hidden) loadPlaylists();
      }, 5000);
    }
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
  // Both creation paths funnel through here, so this is where the phone's
  // Your Library list has to be kept in step with the desktop sidebar.
  refreshMobileLibraryList();
  const list = $("sidebarPlaylistList");
  if (!list) return;
  if (!state.playlists.length) {
    list.innerHTML = `<div style="padding: 8px 10px; font-size: 12px; color: var(--muted);">No playlists yet</div>`;
    return;
  }
  list.innerHTML = state.playlists.map(pl => {
    const origin = inferPlaylistOrigin(pl);
    const originLabel = origin === "album" ? "Album" : origin === "offline" ? "Downloaded" : "Created";
    const yearLabel = origin === "album" && pl.year ? ` · ${esc(pl.year)}` : "";
    const isActive = state.activePlaylistId === pl.id;
    return `
      <div class="sidebar-playlist-item${isActive ? " active" : ""}" data-playlist-id="${pl.id}">
        ${playlistArtworkHtml(pl, "sidebar-playlist-art")}
        <div class="sidebar-playlist-info">
          <div class="sidebar-playlist-name">${esc(pl.name)}</div>
          <div class="sidebar-playlist-count">${pl.tracks.length} song${pl.tracks.length !== 1 ? "s" : ""}${yearLabel} · ${esc(originLabel)}</div>
        </div>
        ${isReadOnlyPlaylist(pl) ? "" : `<button class="sidebar-playlist-delete" type="button" data-delete-playlist="${pl.id}" aria-label="Delete playlist" title="Delete playlist"><i class="bi bi-trash3"></i></button>`}
      </div>
    `;
  }).join("");

  list.querySelectorAll(".sidebar-playlist-item").forEach(el => {
    el.onclick = (event) => {
      if (event.target.closest("[data-delete-playlist]")) return;
      const pl = state.playlists.find(p => p.id === el.dataset.playlistId);
      if (pl) openLibraryPlaylist(pl);
    };
  });
  list.querySelectorAll("[data-delete-playlist]").forEach(btn => {
    btn.onclick = (event) => {
      event.stopPropagation();
      btn.classList.add("clicked");
      deletePlaylist(btn.dataset.deletePlaylist).finally(() => btn.classList.remove("clicked"));
    };
  });
}

async function deletePlaylist(id) {
  const playlist = state.playlists.find(item => item.id === id);
  if (!playlist || isReadOnlyPlaylist(playlist)) return;
  const dialog = $("deletePlaylistDialog");
  if (dialog.open) return;
  $("deletePlaylistMessage").textContent = `Delete “${playlist.name || "this playlist"}” from your library? Your music files will be kept.`;
  const confirmed = await new Promise(resolve => {
    dialog.returnValue = "cancel";
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "delete"), { once: true });
    dialog.showModal();
  });
  if (!confirmed) return;
  const viewingDeletedPlaylist = state.activePlaylistId === id && !!$("pageContent")?.querySelector(".playlist-hero");
  try {
    await api("/api/playlists", { method: "DELETE", body: JSON.stringify({ id }) });
    state.playlists = state.playlists.filter(p => p.id !== id);
    renderSidebarPlaylists();
    // If we're viewing this playlist, go back
    if (viewingDeletedPlaylist && state.viewStack.length > 1) popPage();
    showToast("Playlist deleted");
  } catch (e) {
    showSettingsNotice("Could not delete playlist", e.message || "Please try again.");
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
  if (playlist.id === OFFLINE_PLAYLIST_ID && !state.playlists.some(pl => pl.id === OFFLINE_PLAYLIST_ID)) {
    state.activePlaylistId = null;
    replacePage(window.matchMedia("(max-width: 900px)").matches ? renderMobileLibraryPage : renderHomePage);
    return;
  }
  setActiveView("home");
  if (window.matchMedia("(max-width: 900px)").matches) setMobileNavActive("library");
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
    read_only: isReadOnlyPlaylist(pl),
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
  const duration = formatDuration(pl.tracks);
  const playlistOrigin = String(pl.playlist_origin || "").trim().toLowerCase();
  const isAlbumPlaylist = playlistOrigin === "album";
  const showRecommendations = !isAlbumPlaylist && !isReadOnlyPlaylist(pl);
  const primaryTrack = (pl.tracks || []).find(track => track && (track.artist || track.album)) || (pl.tracks || [])[0] || {};
  const heroArtist = primaryTrack.artist || pl.owner || "";
  const heroYear = primaryTrack.year || pl.year || "";
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
      <div class="playlist-hero" data-playlist-page="${esc(pl.id)}">
        ${playlistArtworkHtml(pl, "playlist-hero-art")}
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
        ${isAlbumPlaylist ? `<div class="plays-column">Plays</div><div></div><div class="time-column"><i class="bi bi-clock"></i></div><div></div>` : `<div></div><div>Album</div><div class="time-column"><i class="bi bi-clock"></i></div><div></div>`}
      </div>

      <div id="playlistTrackList" class="track-list"></div>

      <div class="playlist-recommendations-head" ${showRecommendations ? "" : 'style="display:none"'}>
        <div>
          <h2>Recommended</h2>
          <p>Based on this playlist and your listening taste</p>
        </div>
      </div>
      <div id="playlistRecommendations" class="playlist-recommendations" ${showRecommendations ? "" : 'style="display:none"'}></div>
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
  if (pl.id === OFFLINE_PLAYLIST_ID) return "offline";
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
  const artistName = seed.album_artist || playlist.owner || seed.artist || "";
  const albumTitle = seed.album || playlist.name || "";
  const releaseId = seed.musicbrainz_release_id || "";
  const spotifyId = savedAlbumSpotifyId(playlist) || seed.album_spotify_id || seed.spotify_album_id || seed.metadata?.album_spotify_id || "";
  if (!artistName || !albumTitle) return playlist;

  try {
    const params = new URLSearchParams({
      artist: artistName,
      album: albumTitle,
      release_id: releaseId,
      spotify_id: spotifyId,
      track_spotify_id: spotifyId ? "" : (seed.spotify_id || ""),
    });
    const data = await api(`/api/music/album_tracks?${params.toString()}&details=0`);
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
      year: data.year || playlist.year || "",
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
      !isReadOnlyPlaylist(pl) && (!searchVal || pl.name.toLowerCase().includes(searchVal.toLowerCase()))
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
  $("detailsExpandBtn").onclick = () => setDetailsExpanded(!state.detailsExpanded);

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

// Boot restores last session's track paused. It runs after the saved output
// is reactivated (up to 10s while Bluetooth reconnects), so the user may have
// started a song in the meantime; restoring then would swap in the old track
// and set the pause intent on the new one. `bootRequestId` is the playback
// request id from before boot's awaits; any newer selection wins.
async function restorePlaybackState(bootRequestId = state.playbackRequestId) {
  const userSelectedSinceBoot = () => state.playbackRequestId !== bootRequestId;
  try {
    const status = await api("/api/native_audio/status");
    if (userSelectedSinceBoot()) return;
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
      updateMediaSession(track);
      syncPlayPauseButton();
      persistPlaybackSnapshot(true);
      
      console.log("[Boot] Restored playback state for:", track.title);
      return;
    }
  } catch (e) {
    console.warn("[Boot] Failed to restore playback state:", e);
  }

  const saved = await storedPlaybackSnapshot();
  if (userSelectedSinceBoot()) return;
  if (!saved) {
    publishDockPlayingState(false);
    return;
  }
  state.currentTrack = saved.track;
  state.pendingResumePosition = saved.position;
  state.restoredPlaybackPending = true;
  state.manualPauseRequested = true;
  state.autoplayWanted = false;
  prepareSelectedTrackUi(
    saved.track,
    saved.position > 0 ? `Paused at ${formatTime(saved.position)}` : "Paused"
  );
  state.currentLibraryPath = saved.libraryPath;
  state.pendingResumePosition = saved.position;
  const duration = saved.duration || Number(saved.track.duration_ms || 0) / 1000;
  if (duration > 0) {
    const ratio = Math.max(0, Math.min(1, saved.position / duration));
    $("seekBar").value = ratio * 1000;
    $("seekBar").style.backgroundSize = `${ratio * 100}% 100%`;
    $("currentTime").textContent = formatTime(saved.position);
    $("durationTime").textContent = formatTime(duration);
  }
  setPlayerStatusIcon("ready");
  syncPlayPauseButton();
  updateMediaSession(saved.track);
  publishNowPlayingState(2);
  console.log("[Boot] Restored saved track at", saved.position, "seconds:", saved.track.title);
}

const SCROLLBAR_TARGETS = ".scroll-area, .queue-content-area, .playlist-picker-body, .lyrics-content";

// Overlay scrollbars for the app's inner scroll regions.
//
// Android WebView draws nothing for a non-root scroller, and a native
// ::-webkit-scrollbar wide enough to drag with a thumb would permanently eat
// ~30px of a 411px screen. So the native bar is hidden in CSS and this draws a
// fixed-position one over the container instead: a 6px bar inside a 30px touch
// strip, visible only while scrolling or being dragged.
function bindCustomScrollbars() {
  const MIN_THUMB = 52;
  const IDLE_MS = 1100;
  const bars = [];

  function recordFor(el) {
    let found = null;
    // Pages re-render by replacing innerHTML, so scroll containers are
    // discarded constantly. Prune detached ones here rather than leaking an
    // overlay per navigation.
    for (let i = bars.length - 1; i >= 0; i--) {
      const entry = bars[i];
      if (!entry.el.isConnected) {
        entry.root.remove();
        bars.splice(i, 1);
      } else if (entry.el === el) {
        found = entry;
      }
    }
    if (found) return found;

    const root = document.createElement("div");
    root.className = "vscrollbar";
    const thumb = document.createElement("div");
    thumb.className = "vscrollbar-thumb";
    root.appendChild(thumb);
    document.body.appendChild(root);
    const entry = { el, root, thumb, hideTimer: 0, dragging: false };
    bars.push(entry);
    attachDrag(entry);
    return entry;
  }

  function scrollable(el) {
    return el.scrollHeight - el.clientHeight > 2;
  }

  function layout(entry) {
    const { el, root, thumb } = entry;
    const box = el.getBoundingClientRect();
    if (!scrollable(el) || box.height <= 0) {
      root.classList.remove("is-visible");
      return false;
    }
    root.style.top = `${box.top}px`;
    root.style.left = `${box.right - root.offsetWidth}px`;
    root.style.height = `${box.height}px`;
    const height = Math.max(MIN_THUMB, Math.round(box.height * (el.clientHeight / el.scrollHeight)));
    const travel = Math.max(0, box.height - height);
    const progress = el.scrollTop / (el.scrollHeight - el.clientHeight);
    thumb.style.height = `${height}px`;
    thumb.style.top = `${Math.round(travel * Math.min(1, Math.max(0, progress)))}px`;
    return true;
  }

  function show(el) {
    const entry = recordFor(el);
    if (!layout(entry)) return;
    entry.root.classList.add("is-visible");
    clearTimeout(entry.hideTimer);
    entry.hideTimer = setTimeout(() => {
      if (!entry.dragging) entry.root.classList.remove("is-visible");
    }, IDLE_MS);
  }

  function attachDrag(entry) {
    const { el, root, thumb } = entry;
    let grabOffset = 0;

    root.addEventListener("pointerdown", (event) => {
      const box = el.getBoundingClientRect();
      const thumbTop = box.top + thumb.offsetTop;
      // Tapping the track jumps the thumb to the finger; otherwise keep the
      // grab point so the bar does not leap on contact.
      const inside = event.clientY >= thumbTop && event.clientY <= thumbTop + thumb.offsetHeight;
      grabOffset = inside ? event.clientY - thumbTop : thumb.offsetHeight / 2;
      entry.dragging = true;
      root.classList.add("is-dragging");
      try { root.setPointerCapture(event.pointerId); } catch (_) {}
      dragTo(event.clientY);
      event.preventDefault();
    });

    root.addEventListener("pointermove", (event) => {
      if (!entry.dragging) return;
      dragTo(event.clientY);
      event.preventDefault();
    });

    const release = (event) => {
      if (!entry.dragging) return;
      entry.dragging = false;
      root.classList.remove("is-dragging");
      try { root.releasePointerCapture(event.pointerId); } catch (_) {}
      show(el);
    };
    root.addEventListener("pointerup", release);
    root.addEventListener("pointercancel", release);

    function dragTo(clientY) {
      const box = el.getBoundingClientRect();
      const travel = Math.max(1, box.height - thumb.offsetHeight);
      const position = clientY - box.top - grabOffset;
      const progress = Math.min(1, Math.max(0, position / travel));
      el.scrollTop = progress * (el.scrollHeight - el.clientHeight);
      layout(entry);
    }
  }

  document.addEventListener("scroll", (event) => {
    const el = event.target;
    if (!el || el.nodeType !== 1 || !el.matches?.(SCROLLBAR_TARGETS)) return;
    show(el);
  }, true);

  // Keep a visible bar aligned if the window changes shape mid-scroll.
  window.addEventListener("resize", () => {
    bars.forEach(entry => { if (entry.el.isConnected) layout(entry); });
  });
}

// Spotify-style vertical gestures on the player: swipe up on the mini bar to
// open the full now-playing screen, swipe down to dismiss it.
function bindNowPlayingSwipe() {
  const SWIPE_PX = 46;   // far enough that a tap never counts as a swipe
  const SLOP_PX = 44;    // ignore gestures that are mostly horizontal

  function onVerticalSwipe(el, handler, canStart) {
    let startX = 0;
    let startY = 0;
    let active = false;
    el.addEventListener("touchstart", (event) => {
      active = event.touches.length === 1 && (!canStart || canStart());
      if (!active) return;
      startX = event.touches[0].clientX;
      startY = event.touches[0].clientY;
    }, { passive: true });
    el.addEventListener("touchend", (event) => {
      if (!active) return;
      active = false;
      const touch = event.changedTouches[0];
      if (!touch) return;
      if (Math.abs(touch.clientX - startX) > SLOP_PX) return;
      handler(touch.clientY - startY);
    }, { passive: true });
  }

  const player = document.querySelector(".player");
  if (player) {
    onVerticalSwipe(player, (dy) => {
      if (dy < -SWIPE_PX) setDetailsExpanded(true);
    }, () => !state.detailsExpanded);
  }

  function anOverlayIsOpen() {
    // #queuePanel and #connectPanel are fixed-position overlays stacked on top
    // of .details-panel with their own scroller, so .details-panel's own
    // scrollTop tells you nothing about what is happening inside them — every
    // touch inside the queue still bubbles up to this listener. Without this
    // check, any downward drag in the queue list (even one meant to scroll
    // back toward the top) could close the whole now-playing screen the
    // moment it passed the swipe threshold.
    const queue = $("queuePanel");
    const connect = $("connectPanel");
    return (queue && !queue.hidden) || (connect && !connect.hidden);
  }

  const panel = document.querySelector(".details-panel");
  if (panel) {
    onVerticalSwipe(panel, (dy) => {
      if (dy > SWIPE_PX) setDetailsExpanded(false);
      // Only from the top of the panel, otherwise a downward swipe meant to
      // scroll the queue back up would dismiss the screen instead.
    }, () => state.detailsExpanded && panel.scrollTop <= 0 && !anOverlayIsOpen());
  }
}

async function boot() {
  const bootRequestId = state.playbackRequestId;
  state.dockRecentItems = storedDockRecentItems();
  bindSearch();
  bindPlayer();
  bindKeyboardControls();
  bindPlaylistDialogs();
  bindMobileNavigation();
  bindCustomScrollbars();
  bindNowPlayingSwipe();
  if (IS_ANDROID) {
    const health = await api("/api/health");
    if (!health.ok || !health.android) throw new Error("The embedded Android backend did not pass its health check");
    state.settings = await api("/api/settings");
    await loadRuntimeCapabilities();
    if (state.settings.ai_provider !== "android") {
      throw new Error("Android backend setting ai_provider is not wired correctly");
    }
    // The engine is the user's choice and persists across launches, so check
    // that the saved engine is one the backend can run rather than pinning it
    // to YouTube/M4A — that check used to make a saved torrent engine fail boot.
    const saved = runtimeEngine(state.settings.download_engine);
    if (!saved || !saved.available) {
      throw new Error(
        `Android backend engine ${state.settings.download_engine || "(unset)"} is not available: `
        + ((saved && saved.reason) || "not reported by the runtime capability probe"));
    }
    if (!(saved.services || []).includes(state.settings.download_service)
        || !(saved.qualities || []).includes(state.settings.default_quality)) {
      throw new Error(
        `Android backend setting mismatch: ${state.settings.download_engine}`
        + `/${state.settings.download_service}/${state.settings.default_quality}`);
    }
  } else {
    state.settings = await api("/api/settings").catch(() => ({}));
  }
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
  await restorePreferredAudioOutput().catch(() => {});
  
  // Try to restore playback state before showing home page
  await restorePlaybackState(bootRequestId);
  
  replacePage(renderHomePage);
}

boot().catch(error => {
  console.error(error);
  const content = $("pageContent");
  if (content) {
    content.innerHTML = `<div class="mobile-empty-state"><strong>Backend unavailable</strong><br>${esc(error?.message || error || "Unknown startup error")}</div>`;
  }
});

// Global keyboard shortcuts
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    if (document.body.classList.contains("mobile-now-playing")) {
      setDetailsExpanded(false);
      return;
    }
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

function isPlaybackVisiblyActive() {
  const audio = $("audioPlayer");
  return !!(
    (state.nativeAudio && state.nativeAudio.active && state.nativeAudio.playing) ||
    (audio && !audio.paused && !state.audioBuffering)
  );
}

async function _persistPreferredAudioOutput(details = {}) {
  if (!state.settings) state.settings = {};
  state.settings.preferred_audio_output_id = String(details.deviceId || "");
  state.settings.preferred_audio_output_name = String(details.name || "");
  state.settings.preferred_native_device_uid = String(details.nativeUid || "");
  state.settings.preferred_bluetooth_address = String(details.bluetoothAddress || "");
  await api("/api/settings", {
    method: "POST",
    body: JSON.stringify(state.settings),
  }).catch(() => {});
}

function _findOutputRouteCandidate(preferred, backendDevices, browserOutputs, nativeAvailable = false) {
  const preferredId = String(preferred?.deviceId || "").trim();
  const preferredName = String(preferred?.name || "").trim().toLowerCase();
  const preferredNativeUid = String(preferred?.nativeUid || "").trim();

  for (const bd of (backendDevices || [])) {
    const label = String(bd.name || "Audio Device");
    const match = (browserOutputs || []).find(b =>
      (b.label && _audioLabelsMatch(b.label, label)) ||
      b.deviceId === bd.uid
    );
    const nativeId = bd.uid ? `native:${bd.uid}` : "";
    const candidate = {
      name: label,
      deviceId: match ? match.deviceId : (nativeAvailable && nativeId ? nativeId : bd.uid),
      nativeUid: nativeAvailable && bd.uid ? bd.uid : "",
    };
    // Windows UIDs are PortAudio indexes ("sounddevice:5"), which shift when
    // devices come and go, so a saved index only counts if the name agrees.
    const nameAgrees = !preferredName || _audioLabelsMatch(candidate.name, preferredName);
    const uidIsIndex = preferredNativeUid.startsWith("sounddevice:");
    if (
      (preferredNativeUid && candidate.nativeUid === preferredNativeUid && (!uidIsIndex || nameAgrees)) ||
      (preferredId && candidate.deviceId === preferredId && (!uidIsIndex || nameAgrees))
    ) {
      return candidate;
    }
  }
  // No exact saved identity: fall back to the device name (also covers names
  // saved before the device list switched to full WASAPI names).
  if (preferredName) {
    for (const bd of (backendDevices || [])) {
      const label = String(bd.name || "Audio Device");
      if (!_audioLabelsMatch(label, preferredName)) continue;
      const match = (browserOutputs || []).find(b =>
        (b.label && _audioLabelsMatch(b.label, label)) || b.deviceId === bd.uid
      );
      const nativeId = bd.uid ? `native:${bd.uid}` : "";
      return {
        name: label,
        deviceId: match ? match.deviceId : (nativeAvailable && nativeId ? nativeId : bd.uid),
        nativeUid: nativeAvailable && bd.uid ? bd.uid : "",
      };
    }
  }

  for (const b of (browserOutputs || [])) {
    const label = String(b.label || "").trim();
    if (!label) continue;
    if (
      (preferredId && b.deviceId === preferredId) ||
      (preferredName && _audioLabelsMatch(label, preferredName))
    ) {
      return { name: label, deviceId: b.deviceId, nativeUid: "" };
    }
  }
  return null;
}

async function _switchToDefaultOutput(reason = "") {
  await setAudioOutputDevice("");
  await _persistPreferredAudioOutput({ deviceId: "", name: "", nativeUid: "", bluetoothAddress: "" });
  await _refreshConnectPanel().catch(() => {});
  if (reason && state.currentTrack) setPlayerStatus(reason, state.currentTrack);
}

async function _activatePreferredOutput(preferred, timeoutMs = 8000, persist = true) {
  const deadline = Date.now() + Math.max(1000, Number(timeoutMs) || 0);
  while (Date.now() < deadline) {
    const [audioState, browserOutputs] = await Promise.all([
      api("/api/audio/devices").catch(() => null),
      _getOutputDevices().catch(() => []),
    ]);
    const backendDevices = audioState?.devices || [];
    const nativeAvailable = !!audioState?.native_available;
    const candidate = _findOutputRouteCandidate(preferred, backendDevices, browserOutputs, nativeAvailable);
    if (candidate) {
      const targetId = candidate.nativeUid ? `native:${candidate.nativeUid}` : candidate.deviceId;
      await setAudioOutputDevice(targetId, candidate.name);
      if (persist) {
        await _persistPreferredAudioOutput({
          deviceId: targetId,
          name: candidate.name,
          nativeUid: candidate.nativeUid,
          bluetoothAddress: preferred.bluetoothAddress || "",
        });
      }
      await _refreshConnectPanel().catch(() => {});
      return true;
    }
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  return false;
}

async function restorePreferredAudioOutput() {
  const preferred = {
    deviceId: state.settings?.preferred_audio_output_id || "",
    name: state.settings?.preferred_audio_output_name || "",
    nativeUid: state.settings?.preferred_native_device_uid || "",
    bluetoothAddress: state.settings?.preferred_bluetooth_address || "",
  };
  if (!preferred.deviceId && !preferred.name && !preferred.nativeUid && !preferred.bluetoothAddress) return;

  if (preferred.bluetoothAddress) {
    const btState = await api("/api/bluetooth/state").catch(() => null);
    const btDevice = (btState?.devices || []).find(d => d.address === preferred.bluetoothAddress);
    if (btDevice && btDevice.paired && !btDevice.connected) {
      await api("/api/bluetooth/pair", {
        method: "POST",
        body: JSON.stringify({ address: btDevice.address }),
      }).catch(() => {});
    }
  }

  const activated = await _activatePreferredOutput(preferred, 10000, false).catch(() => false);
  if (!activated) {
    await _switchToDefaultOutput("Saved Bluetooth output unavailable — using this computer");
  }
}

// Output switches run one at a time. Each one tears down and reopens a device
// (slow on Bluetooth), and overlapping requests used to race each other's
// rollback, leaving the route on the wrong device. Clicks made while a switch
// is running collapse to the most recent selection.
let _outputSwitchChain = Promise.resolve();
let _outputSwitchSeq = 0;
let _outputSwitchesInFlight = 0;

function setAudioOutputDevice(deviceId, selectedDeviceName = "") {
  const seq = ++_outputSwitchSeq;
  _outputSwitchesInFlight++;
  const run = _outputSwitchChain.then(() => (
    seq === _outputSwitchSeq ? _applyAudioOutputDevice(deviceId, selectedDeviceName) : false
  )).then((switched) => {
    // Replace the "Switching output…" notice unless the switch already
    // reported something more specific (an error, buffering, a fallback).
    if (switched && state.currentTrack && String(state.playerStatus || "").startsWith("Switching output")) {
      setPlayerStatus(`Playing on ${selectedDeviceName || "This computer"}`, state.currentTrack);
    }
    return switched;
  }).finally(() => { _outputSwitchesInFlight--; });
  _outputSwitchChain = run.catch(() => false);
  return run;
}

async function _applyAudioOutputDevice(deviceId, selectedDeviceName = "") {
  const nativeTargetUid = typeof deviceId === "string" && deviceId.startsWith("native:")
    ? deviceId.slice("native:".length) : "";
  // Preferred-output restoration can finish after a track starts. Reapplying
  // the same live native route must not tear down and restart that first stream.
  if (nativeTargetUid && deviceId === _activeSinkId &&
      nativeTargetUid === _nativeAudioDeviceUid && state.nativeAudio.active) {
    if (selectedDeviceName && state.settings) {
      state.settings.preferred_audio_output_name = String(selectedDeviceName);
    }
    return true;
  }
  _activeSinkId = deviceId;
  if (deviceId && deviceId.startsWith("native:") && selectedDeviceName) {
    if (!state.settings) state.settings = {};
    state.settings.preferred_audio_output_name = String(selectedDeviceName);
  }
  const audio = $("audioPlayer");

  // Keep a healthy Monochrome HTTP/decoder stream alive across output changes.
  // The native worker swaps only its sounddevice OutputStream and retains its
  // FFmpeg process, already-decoded PCM queue, playhead, and pause state.
  const nativeMonochromeUrl = isMonochromeDirectStreamUrl(state.nativeAudio.stream_url)
    ? state.nativeAudio.stream_url
    : (isMonochromeDirectStreamUrl(state.currentStreamUrl) ? state.currentStreamUrl : "");
  if (state.nativeAudio.active && nativeMonochromeUrl) {
    const previousUid = _nativeAudioDeviceUid;
    _nativeAudioDeviceUid = nativeTargetUid;
    const targetName = nativeTargetUid ? String(selectedDeviceName || state.settings?.preferred_audio_output_name || "") : "";
    const targetLabel = targetName || "This computer";
    logMonochromePlaybackActivity(`Switching Monochrome output to ${targetLabel}`, state.currentTrack, "output-switch-start", 0);
    try {
      const result = await api("/api/native_audio/output", {
        method: "POST",
        body: JSON.stringify({ device_uid: nativeTargetUid, device_name: targetName }),
      });
      if (!result?.ok) throw new Error(result?.error || "Could not change the audio output");
      state.nativeAudio.device_uid = nativeTargetUid;
      if (state.settings) state.settings.preferred_audio_output_name = nativeTargetUid ? targetName : "";
      logMonochromePlaybackActivity(
        `Monochrome output switched to ${targetLabel} (route ${result.output_applied_revision ?? result.output_revision ?? "applied"})`,
        state.currentTrack,
        "output-switch-applied",
        0,
      );
      syncNativeAudioUi();
      syncPlayPauseButton();
      return true;
    } catch (error) {
      _nativeAudioDeviceUid = previousUid;
      _activeSinkId = previousUid ? `native:${previousUid}` : "";
      logMonochromePlaybackActivity(`Monochrome output switch failed: ${error.message || "output unavailable"}`, state.currentTrack, "output-switch-error", 0);
      setPlayerStatus(`Could not change audio output: ${error.message || "output unavailable"}`, state.currentTrack);
      return false;
    }
  }
  
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

    if (!nativePath && state.currentTrack && isMonochromeDirectStreamUrl(state.currentStreamUrl)) {
      const streamUrl = state.currentStreamUrl;
      try {
        await startNativeAudio("", state.currentTrack, state.playbackRequestId, resumeAt, streamUrl);
        audio.pause();
        audio.removeAttribute("src");
        audio.load();
        if (shouldKeepPaused) {
          await api("/api/native_audio/pause", { method: "POST", body: "{}" });
          state.nativeAudio.playing = false;
        }
      } catch (error) {
        // A stream failure is not a device failure: keep the user's choice so
        // Play retries on it, and never hand FLAC to WebKit (it cannot decode
        // it, and each attempt is one more request Monochrome may rate-limit).
        audio.pause();
        audio.removeAttribute("src");
        audio.load();
        state.directStreamNativeFallbackAttempted = true;
        state.directStreamPosition = resumeAt;
        setPlayerStatus(`Could not start Monochrome on the selected device: ${error.message || "audio output unavailable"}`, state.currentTrack);
      }
      syncPlayPauseButton();
      return true;
    }

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
        await _switchToDefaultOutput(error?.message || "Bluetooth output unavailable — using this computer");
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
    return true;
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
  if (wasNativeActive && isMonochromeDirectStreamUrl(state.currentStreamUrl) && state.currentTrack) {
    audio.src = browserAudioStreamUrl(state.currentStreamUrl);
    audio.load();
    seekAfterMetadata(audio, nativeResumeAt || state.directStreamPosition || 0);
    if (!keepPaused) tryStartAudio(audio, state.currentTrack, state.playbackRequestId, null);
    else pauseBrowserAudio(audio);
  } else if (wasNativeActive && state.currentLibraryPath && state.currentTrack) {
    await playFromLibraryPath(
      state.currentLibraryPath, state.currentTrack, state.playbackRequestId,
      state.activeJobId, "Playing from cache", nativeResumeAt
    ).catch(() => {});
    if (keepPaused) pauseBrowserAudio(audio);
  }
  return true;
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

  // On desktop, native routing owns device selection. Browser enumeration can
  // prompt for microphone permission just to reveal labels, delaying the first
  // open of this panel; native device names already come from the backend.
  const browserOutputs = nativeAvailable ? [] : await _getOutputDevices();

  // Section: available output devices.
  const items = [];
  // "This computer" is our universal "Default" which handles built-in speakers automatically.
  items.push({
    name: IS_ANDROID ? "This phone" : "This computer",
    deviceId: "",
    icon: IS_ANDROID ? "bi-phone" : "bi-laptop",
    sub: "Default output",
  });

  const filterKeywords = ["speaker", "internal speaker", "built-in", "microphone", "input", "driver", "background music", "teams", "zoom"];

  for (const bd of backendDevices) {
    if (bd.uid === "default") continue;
    const lname = bd.name.toLowerCase();
    
    // Strictly hide built-in speakers from the list so they don't duplicate "This computer"
    // except for explicitly allowed external ones. Android's list never
    // contains the built-in speaker, and names like "JBL Flip Speaker" are real.
    if (!IS_ANDROID && filterKeywords.some(k => lname.includes(k)) && !lname.includes("airplay") && !lname.includes("edifier")) {
        continue;
    }
    
    // Cross-reference to get browser-internal ID
    const match = browserOutputs.find(b =>
        (b.label && _audioLabelsMatch(b.label, bd.name)) ||
        b.deviceId === bd.uid
    );

    const label = bd.name || "Audio Device";
    const isAirPlay = label.toLowerCase().includes("airplay");
    const btMatch = (btState?.devices || []).find(dev => _audioLabelsMatch(dev.name, label));
    
    const nativeId = bd.uid ? `native:${bd.uid}` : "";
    items.push({
        name: label,
        deviceId: match ? match.deviceId : (nativeAvailable && nativeId ? nativeId : bd.uid),
        backendUid: bd.uid,
        nativeUid: nativeAvailable && bd.uid ? bd.uid : "",
        bluetoothAddress: btMatch?.address || "",
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
      // "This computer" is already the universal default route. Handle it
      // before enumerating browser outputs, which can request microphone
      // permission and delay the first switch away from app-only Bluetooth.
      if (targetId === "" && isMonochromeDirectStreamUrl(state.currentStreamUrl)) {
        logMonochromePlaybackActivity("Device menu selected This computer", state.currentTrack, "default-output-selected", 0);
        if (state.currentTrack) setPlayerStatus(`Switching output to ${item.name}…`, state.currentTrack);
        const switched = await setAudioOutputDevice("", item.name);
        if (!switched) { await _refreshConnectPanel(); return; }
        closeConnectPanel();
        await _persistPreferredAudioOutput({ deviceId: "", name: "", nativeUid: "", bluetoothAddress: "" });
        await _refreshConnectPanel();
        return;
      }
      if (targetId === "__choose_output__") {
        const selected = await _selectBrowserAudioOutput();
        if (!selected) return;
        const switched = await setAudioOutputDevice(selected.deviceId);
        if (!switched) { await _refreshConnectPanel(); return; }
        closeConnectPanel();
        await _persistPreferredAudioOutput({
          deviceId: selected.deviceId,
          name: selected.label || item.name,
          nativeUid: "",
          bluetoothAddress: "",
        });
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
      if (state.currentTrack) setPlayerStatus(`Switching output to ${item.name}…`, state.currentTrack);
      const switched = await setAudioOutputDevice(targetId, item.name);
      if (!switched) { await _refreshConnectPanel(); return; }
      closeConnectPanel();
      await _persistPreferredAudioOutput({
        deviceId: targetId,
        name: item.name,
        nativeUid: item.nativeUid || "",
        bluetoothAddress: item.bluetoothAddress || "",
      });
      await _refreshConnectPanel();
    };
    list.appendChild(li);
  }

  // Android owns Bluetooth discovery and pairing; hand that to its settings.
  // A newly connected device then appears above (the list is read live).
  if (IS_ANDROID) {
    if (window.MindinguflacAndroid?.openBluetoothSettings) {
      const pair = document.createElement("li");
      pair.className = "connect-device-item";
      pair.innerHTML = `
        <div class="connect-device-icon"><i class="bi bi-bluetooth"></i></div>
        <div class="connect-device-info">
          <span class="connect-device-name">Pair new device</span>
          <span class="connect-device-sub">Opens Bluetooth settings</span>
        </div>`;
      pair.onclick = () => window.MindinguflacAndroid.openBluetoothSettings();
      list.appendChild(pair);
    }
    return;
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
    const btnText = dev.connected ? "Use" : (dev.paired ? "Connect" : "Pair");
    const btnClass = dev.connected ? "connect-pair-btn connected" : "connect-pair-btn";

    li.innerHTML = `
      <div class="connect-device-icon"><i class="bi ${_deviceIcon(dev.name)}"></i></div>
      <div class="connect-device-info">
        <span class="connect-device-name">${dev.name}</span>
        <span class="connect-device-sub">${subtext}</span>
      </div>
      <button class="${btnClass}" type="button">${btnText}</button>
    `;
    li.querySelector(".connect-pair-btn").onclick = async (e) => {
      e.stopPropagation();
      const btn = e.currentTarget;
      btn.textContent = dev.connected ? "Activating..." : (dev.paired ? "Connecting..." : "Pairing...");
      btn.disabled = true;
      try {
        if (!dev.connected) {
          const res = await api("/api/bluetooth/pair", { method: "POST", body: JSON.stringify({ address: dev.address }) });
          if (res.error) {
            btn.textContent = "Failed";
            btn.disabled = false;
            return;
          }
        }
        const activated = await _activatePreferredOutput({
          name: dev.name,
          bluetoothAddress: dev.address,
        }, 10000, true);
        if (!activated) {
          btn.textContent = "Default";
          btn.disabled = false;
          await _switchToDefaultOutput(`"${dev.name}" is not reachable — using this computer`);
          return;
        }
        btn.textContent = "Active";
        setTimeout(() => _refreshConnectPanel(), 400);
      } catch {
        btn.textContent = "Default";
        btn.disabled = false;
        await _switchToDefaultOutput("Bluetooth output unavailable — using this computer");
      }
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
  attachPanelSwipeClose($("connectPanel"), () => $("connectDeviceList"), closeConnectPanel);
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
      if (Date.now() < (Number(container.dataset.suppressQueueClickUntil) || 0)) return;
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
          const cinfo = el.dataset.qRecent === "true" ? { kind: "recent" } : { queueIndex: track._qIdx };
          showTrackContextMenu(event, track, cinfo);
        }
      };
    }
  });
  if (!isRecent) bindQueueReorder(container);
}

function reorderQueueTrack(fromIndex, toIndex) {
  if (!Number.isInteger(fromIndex) || !Number.isInteger(toIndex)) return false;
  if (fromIndex < 0 || toIndex < 0 || fromIndex >= state.queue.length || toIndex > state.queue.length) return false;
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
  prefetchNextTracks(); prefetchNextVideos();
  refreshQueuePanel();
  updateSidebarNextQueue();
  return true;
}

function bindQueueReorder(container) {
  let draggedIndex = -1;
  let touchDrag = null;
  const clearDropTargets = () => {
    container.querySelectorAll(".queue-drop-before, .queue-drop-after").forEach(el => {
      el.classList.remove("queue-drop-before", "queue-drop-after");
    });
  };
  container.querySelectorAll(".queue-track-reorderable").forEach(row => {
    const handle = row.querySelector(".queue-drag-handle");
    if (handle) {
      handle.addEventListener("pointerdown", event => {
        if (event.pointerType === "mouse" || !event.isPrimary || event.button > 0) return;
        const fromIndex = parseInt(row.dataset.qAbsIndex || "-1", 10);
        if (fromIndex < 0) return;
        touchDrag = { pointerId: event.pointerId, fromIndex, startX: event.clientX, startY: event.clientY, moved: false, handle };
        try { handle.setPointerCapture(event.pointerId); } catch (_) {}
        event.preventDefault();
      });
      handle.addEventListener("pointermove", event => {
        if (!touchDrag || touchDrag.pointerId !== event.pointerId) return;
        const dx = event.clientX - touchDrag.startX;
        const dy = event.clientY - touchDrag.startY;
        if (!touchDrag.moved && Math.hypot(dx, dy) < 8) return;
        touchDrag.moved = true;
        row.classList.add("queue-dragging");
        const target = document.elementFromPoint(event.clientX, event.clientY)?.closest(".queue-track-reorderable");
        clearDropTargets();
        if (target && target !== row) {
          const rect = target.getBoundingClientRect();
          target.classList.add(event.clientY > rect.top + rect.height / 2 ? "queue-drop-after" : "queue-drop-before");
        }
        event.preventDefault();
      });
      const finishPointerDrag = event => {
        if (!touchDrag || touchDrag.pointerId !== event.pointerId) return;
        const drag = touchDrag;
        touchDrag = null;
        row.classList.remove("queue-dragging");
        clearDropTargets();
        try { handle.releasePointerCapture(event.pointerId); } catch (_) {}
        if (!drag.moved) return;
        container.dataset.suppressQueueClickUntil = String(Date.now() + 400);
        const target = document.elementFromPoint(event.clientX, event.clientY)?.closest(".queue-track-reorderable");
        if (target) {
          const targetIndex = parseInt(target.dataset.qAbsIndex || "-1", 10);
          if (targetIndex >= 0 && targetIndex !== drag.fromIndex) {
            const rect = target.getBoundingClientRect();
            reorderQueueTrack(drag.fromIndex, event.clientY > rect.top + rect.height / 2 ? targetIndex + 1 : targetIndex);
          }
        } else {
          const last = container.querySelector(".queue-track-reorderable:last-child");
          if (last && event.clientY > last.getBoundingClientRect().bottom) {
            reorderQueueTrack(drag.fromIndex, state.queue.length);
          }
        }
      };
      handle.addEventListener("pointerup", finishPointerDrag);
      handle.addEventListener("pointercancel", finishPointerDrag);
    }
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
  attachPanelSwipeClose($("queuePanel"), () => {
    const recent = $("queueContentRecent");
    return recent && !recent.hidden ? recent : $("queueContentQueue");
  }, closeQueuePanel);
  attachQueueTabSwipe($("queuePanel"));
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

$("btnLyrics").onclick = toggleLyricsPanel;
$("lyricsBg").onclick = closeLyricsPanel;
$("lyricsSync").onclick = () => {
  setLyricsSynced(true);
  updateLyricsPosition(currentPlaybackSeconds(), true);
};
function updateLyricsOffset(delta) {
  state.lyrics.syncOffset = Math.round((state.lyrics.syncOffset + delta) * 100) / 100;
  const label = $("lyricsOffsetLabel");
  if (label) label.textContent = state.lyrics.syncOffset.toFixed(1) + "s";
  updateLyricsPosition(currentPlaybackSeconds(), true);
}
$("lyricsOffsetDown").onclick = () => updateLyricsOffset(-0.25);
$("lyricsOffsetUp").onclick = () => updateLyricsOffset(0.25);
$("lyricsScroll").addEventListener("scroll", () => {
  if (!state.lyrics.open || state.lyrics.programmaticScroll) return;
  state.lyrics.lastScrollAt = Date.now();
  setLyricsSynced(false);
}, { passive: true });
$("sideVideoSwitch").onclick = () => {
  if (!state.videoMode && state.videoFetch.status === "not_found" && state.currentTrack) {
    state.videoFetch = { trackKey: trackKey(state.currentTrack), status: "downloading", path: "" };
    renderSideVideoButton();
    fetchVideoForTrack(state.currentTrack, { force: true }).catch(() => {});
    return;
  }
  switchSideVideoMode(!state.videoMode);
};
// Touchscreens have no hover, so the video controls (which only appear on
// hover) would be unreachable. A tap reveals them for a few seconds; while they
// are hidden, a tap that lands on one only reveals it rather than pressing it.
(function bindTouchVideoControls() {
  const cover = $("sideCover");
  if (!cover) return;
  let hideTimer = null;
  let revealedAt = 0;
  cover.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "mouse") return;
    if (!cover.classList.contains("show-video-controls")) revealedAt = Date.now();
    cover.classList.add("show-video-controls");
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => cover.classList.remove("show-video-controls"), 4000);
  });
  cover.addEventListener("click", (event) => {
    if (Date.now() - revealedAt < 400 && event.target.closest("button")) {
      event.preventDefault();
      event.stopPropagation();
    }
  }, true);
})();
$("sideVideoEarlier").onclick = () => nudgeVideoSync(-0.25).catch(() => {});
$("sideVideoLater").onclick = () => nudgeVideoSync(0.25).catch(() => {});
$("sideVideoRefresh").onclick = () => {
  if (!state.currentTrack) return;
  clearTimeout(state.videoSync.timer);
  state.videoSync.key = "";
  state.videoFetch = { trackKey: trackKey(state.currentTrack), status: "downloading", path: "" };
  renderSideVideoButton();
  renderSideCover(state.currentTrack);
  fetchVideoForTrack(state.currentTrack, { force: true }).catch(() => {});
};

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
// The row's own library button, so the sheet's Download acts on the real
// element instead of a detached one whose class changes nobody ever sees.
let contextMenuTargetLibraryBtn = null;
let contextMenuLibraryReady = false;

function ensureContextMenuLibrary() {
  if (contextMenuLibraryReady) return;
  ["trackContextMenu", "albumContextMenu", "artistContextMenu", "playlistContextMenu"].forEach((menuId) => {
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

// On a phone a floating menu anchored to a tap point is the wrong shape, so
// the same menu is presented as a bottom sheet instead — the pattern every
// mobile music app uses, and the one that gives each row a real touch target.
function openContextSheet(menu) {
  menu.hidden = false;
  menu.style.display = "block";
  menu.style.left = "";
  menu.style.top = "";
  // Clear anything a previous drag left behind, so the open animation runs.
  menu.style.transform = "";
  menu.style.transition = "";
  menu.style.animation = "";
  menu.classList.add("as-sheet");
  attachSheetDrag(menu);

  let scrim = $("contextSheetScrim");
  if (!scrim) {
    scrim = document.createElement("div");
    scrim.id = "contextSheetScrim";
    scrim.className = "context-sheet-scrim";
    scrim.addEventListener("click", () => {
      document.querySelectorAll(".context-menu.as-sheet").forEach(el => { el.hidden = true; });
    });
    document.body.appendChild(scrim);
  }
  scrim.hidden = false;

  // Every existing close path just sets `hidden`, so rather than editing all of
  // them, watch the attribute and tear the sheet down when it flips.
  if (!menu.dataset.sheetObserved) {
    menu.dataset.sheetObserved = "1";
    new MutationObserver(() => {
      if (!menu.hidden) return;
      menu.classList.remove("as-sheet");
      const open = document.querySelectorAll(".context-menu.as-sheet:not([hidden])").length;
      if (!open && $("contextSheetScrim")) $("contextSheetScrim").hidden = true;
    }).observe(menu, { attributes: true, attributeFilter: ["hidden"] });
  }
}

// Drag the sheet down to dismiss it.
//
// This uses touch events rather than pointer events on purpose. The sheet is an
// overflow-y:auto scroller, so Chromium treats a vertical drag as a scroll
// gesture and cancels the pointer stream part-way through — which is why a
// pointer-based version looked right in a synthetic test and did nothing under
// a real finger. Calling preventDefault() on touchmove claims the gesture, and
// it is only claimed for downward drags that start at the top of the sheet, so
// scrolling a long list still works normally.
// Swipe a full-screen phone panel down to close it: the lyrics panel, the
// queue, and the connect-to-device panel all use this. Touch events so the
// gesture can be claimed with preventDefault(), and only claimed when
// `scroller()` (the panel's own inner scroll region — never the panel
// element itself, which does not scroll) is already at its top, so a
// downward swipe mid-scroll keeps scrolling instead of closing the panel.
function attachPanelSwipeClose(panel, scroller, close) {
  if (!panel || panel.dataset.swipeClose) return;
  panel.dataset.swipeClose = "1";
  const DISMISS_PX = 90;
  let startY = 0;
  let offset = 0;
  let dragging = false;

  panel.addEventListener("touchstart", (event) => {
    // Queue reordering owns gestures that start on a drag handle; treating a
    // downward reorder as a panel-dismiss swipe would move the whole overlay.
    if (event.target.closest?.(".queue-drag-handle")) {
      dragging = false;
      return;
    }
    const content = typeof scroller === "function" ? scroller() : scroller;
    if (event.touches.length !== 1 || (content && content.scrollTop > 0)) {
      dragging = false;
      return;
    }
    dragging = true;
    offset = 0;
    startY = event.touches[0].clientY;
    panel.style.transition = "none";
  }, { passive: true });

  panel.addEventListener("touchmove", (event) => {
    if (!dragging) return;
    const dy = event.touches[0].clientY - startY;
    if (dy <= 0) return;
    offset = dy;
    event.preventDefault();
    panel.style.transform = `translateY(${dy}px)`;
    panel.style.opacity = String(Math.max(0.35, 1 - dy / 600));
  }, { passive: false });

  const settle = () => {
    if (!dragging) return;
    dragging = false;
    panel.style.transition = "transform 190ms ease, opacity 190ms ease";
    if (offset > DISMISS_PX) {
      panel.style.transform = "translateY(100%)";
      panel.style.opacity = "0";
      setTimeout(() => {
        close();
        panel.style.transform = "";
        panel.style.opacity = "";
        panel.style.transition = "";
      }, 190);
    } else {
      panel.style.transform = "";
      panel.style.opacity = "";
    }
  };
  panel.addEventListener("touchend", settle, { passive: true });
  panel.addEventListener("touchcancel", settle, { passive: true });
}

// Swipe left/right on the queue panel to switch between its Queue and
// Recently played tabs, the way a phone tab strip is expected to behave.
function attachQueueTabSwipe(panel) {
  if (!panel || panel.dataset.tabSwipe) return;
  panel.dataset.tabSwipe = "1";
  const SWIPE_PX = 48;
  const SLOP_PX = 40;
  let startX = 0;
  let startY = 0;
  let tracking = false;

  panel.addEventListener("touchstart", (event) => {
    tracking = event.touches.length === 1;
    if (!tracking) return;
    startX = event.touches[0].clientX;
    startY = event.touches[0].clientY;
  }, { passive: true });

  panel.addEventListener("touchend", (event) => {
    if (!tracking) return;
    tracking = false;
    const touch = event.changedTouches[0];
    if (!touch) return;
    const dx = touch.clientX - startX;
    const dy = touch.clientY - startY;
    if (Math.abs(dy) > SLOP_PX || Math.abs(dx) < SWIPE_PX) return;
    const tabs = [...panel.querySelectorAll(".queue-tab")];
    const activeIndex = tabs.findIndex(t => t.classList.contains("active"));
    if (activeIndex === -1) return;
    // Swipe left moves to the next tab, right moves to the previous — the
    // content appears to travel with the finger, same as a horizontal pager.
    const nextIndex = activeIndex + (dx < 0 ? 1 : -1);
    if (nextIndex < 0 || nextIndex >= tabs.length) return;
    tabs[nextIndex].click();
  }, { passive: true });
}

function attachSheetDrag(menu) {
  if (menu.dataset.sheetDrag) return;
  menu.dataset.sheetDrag = "1";
  const DISMISS_PX = 100;
  let startY = 0;
  let offset = 0;
  let dragging = false;
  let moved = false;

  menu.addEventListener("touchstart", (event) => {
    if (event.touches.length !== 1 || menu.scrollTop > 0) {
      dragging = false;
      return;
    }
    dragging = true;
    moved = false;
    offset = 0;
    startY = event.touches[0].clientY;
    // The open animation uses fill:both, which would otherwise outrank the
    // inline transform the drag sets.
    menu.style.animation = "none";
    menu.style.transition = "none";
  }, { passive: true });

  menu.addEventListener("touchmove", (event) => {
    if (!dragging) return;
    const dy = event.touches[0].clientY - startY;
    if (dy <= 0) return;
    offset = dy;
    if (dy > 6) moved = true;
    event.preventDefault();
    menu.style.transform = `translateY(${dy}px)`;
  }, { passive: false });

  const settle = () => {
    if (!dragging) return;
    dragging = false;
    menu.style.transition = "transform 190ms ease";
    if (offset > DISMISS_PX) {
      menu.style.transform = "translateY(100%)";
      setTimeout(() => { menu.hidden = true; }, 190);
    } else {
      menu.style.transform = "";
    }
  };
  menu.addEventListener("touchend", settle, { passive: true });
  menu.addEventListener("touchcancel", settle, { passive: true });

  // A drag must not also fire the action row it started on.
  menu.addEventListener("click", (event) => {
    if (!moved) return;
    moved = false;
    event.preventDefault();
    event.stopPropagation();
  }, true);
}

// Re-read one track's library state and repaint its button. toggleTrackLibrary
// leaves the button mid-flight when a download finishes, so without this the
// icon keeps the spinner it had when the job started.
async function refreshLibraryButtonState(track, button) {
  if (!button || !button.isConnected || !isTrackItem(track)) return;
  try {
    const statuses = await api("/api/library/status/batch", {
      method: "POST",
      body: JSON.stringify({ tracks: [serviceDownloadPayload(track, "download")] }),
    });
    const status = (statuses || [])[0] || {};
    const downloaded = !!status.in_library;
    const busy = !!status.library_requested;
    button.classList.toggle("downloaded", downloaded);
    button.classList.toggle("progress", busy);
    const label = downloaded ? "Remove from library" : (busy ? "Cancel library download" : "Add to library");
    button.setAttribute("aria-label", label);
    button.title = label;
    button.innerHTML = busy
      ? progressButtonMarkup(status)
      : `<i class="bi ${downloaded ? "bi-arrow-down-circle-fill downloaded" : "bi-arrow-down-circle"}"></i>`;
  } catch (_) {
    // Leave the button as-is; a later render will correct it.
  }
}

function openContextMenu(event, menu) {
  if (!menu) return;
  event.preventDefault();
  if (window.matchMedia("(max-width: 900px)").matches) {
    openContextSheet(menu);
    return;
  }
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
    // Drive the row's real button when there is one. The previous version made
    // a detached dummy, so every progress and "downloaded" class landed on an
    // orphan element and the row's icon never changed after the download.
    const button = contextMenuTargetLibraryBtn && contextMenuTargetLibraryBtn.isConnected
      ? contextMenuTargetLibraryBtn
      : document.createElement("button");
    toggleTrackLibrary(contextMenuTargetTrack, button, () => {
      syncActiveTrackRows();
      refreshLibraryButtonState(contextMenuTargetTrack, button);
    });
  }
  $("trackContextMenu").hidden = true;
});

function showTrackContextMenu(event, track, contextInfo = {}) {
  contextMenuTargetTrack = track;
  contextMenuTargetLibraryBtn =
    event?.target?.closest?.(".track-row, .track")?.querySelector?.("[data-library-action]") || null;
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

  // Remove from statistics (stats page only — contextInfo.kind === "stats")
  const btnRemoveFromStats = $("ctxRemoveFromStats");
  if (btnRemoveFromStats) {
    const statsCtx = contextInfo && contextInfo.kind === "stats" ? contextInfo : null;
    btnRemoveFromStats.style.display = statsCtx ? "flex" : "none";
    if (statsCtx) {
      btnRemoveFromStats.onclick = async () => {
        menu.hidden = true;
        // track.track_key (the backend's raw stats identity) — NOT trackKey(track),
        // which prefixes identifiers (e.g. "spotify_id:...") for client-side queue/
        // playlist matching and won't match the track_key column in the DB.
        await api("/api/stats/remove", {
          method: "DELETE",
          body: JSON.stringify({ kind: "track", key: track.track_key || "" }),
        }).catch(() => {});
        state.statsCache = {};
        if (statsCtx.onRemoved) statsCtx.onRemoved();
      };
    }
  }

  // Remove from recently played (contextInfo.kind === "recent")
  const btnRemoveFromRecent = $("ctxRemoveFromRecent");
  if (btnRemoveFromRecent) {
    const isRecent = contextInfo && contextInfo.kind === "recent";
    btnRemoveFromRecent.style.display = isRecent ? "flex" : "none";
    if (isRecent) {
      btnRemoveFromRecent.onclick = async () => {
        menu.hidden = true;
        await removeFromRecentlyPlayed(track);
      };
    }
  }

  // Remove from playlist
  const btnRemoveFromPlaylist = $("ctxRemoveFromPlaylist");
  if (btnRemoveFromPlaylist) {
    const playlistCtx = contextInfo && contextInfo.kind === "playlist" && contextInfo.id !== OFFLINE_PLAYLIST_ID && !contextInfo.read_only ? contextInfo : null;
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

function showAlbumContextMenu(event, album, contextInfo = {}) {
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

  // Remove from statistics (stats page only — contextInfo.kind === "stats")
  const btnRemoveFromStats = $("ctxAlbumRemoveFromStats");
  if (btnRemoveFromStats) {
    const statsCtx = contextInfo && contextInfo.kind === "stats" ? contextInfo : null;
    btnRemoveFromStats.style.display = statsCtx ? "flex" : "none";
    if (statsCtx) {
      btnRemoveFromStats.onclick = async () => {
        menu.hidden = true;
        await api("/api/stats/remove", {
          method: "DELETE",
          body: JSON.stringify({ kind: "album", key: album.album_key || "" }),
        }).catch(() => {});
        state.statsCache = {};
        if (statsCtx.onRemoved) statsCtx.onRemoved();
      };
    }
  }

  openContextMenu(event, menu);
}

// ---------------------------------------------------------------------------
// Artist Context Menu (statistics page only)
// ---------------------------------------------------------------------------
let contextMenuTargetArtist = null;

function showArtistContextMenu(event, artist, contextInfo = {}) {
  contextMenuTargetArtist = artist;
  const menu = $("artistContextMenu");
  if (!menu) return;
  const target = artistTarget(artist);

  const headerArt = $("ctxArtistHeaderArt");
  if (headerArt) {
    headerArt.style.backgroundImage = target.artwork_url ? `url('${target.artwork_url}')` : "";
    headerArt.style.display = target.artwork_url ? "block" : "none";
  }
  const headerTitle = $("ctxArtistHeaderTitle");
  if (headerTitle) headerTitle.textContent = target.name || target.artist || artist.name || artist.artist || "Unknown Artist";

  const btnGoArtist = $("ctxArtistGoArtist");
  if (btnGoArtist) {
    btnGoArtist.onclick = () => {
      menu.hidden = true;
      pushPage(() => renderArtistPage(target));
    };
  }

  $("ctxArtistCopySpotify")?.classList.toggle("hidden", !spotifyArtistUrl(target));

  const btnRemoveFromStats = $("ctxArtistRemoveFromStats");
  if (btnRemoveFromStats) {
    const statsCtx = contextInfo && contextInfo.kind === "stats" ? contextInfo : null;
    btnRemoveFromStats.style.display = statsCtx ? "flex" : "none";
    if (statsCtx) {
      btnRemoveFromStats.onclick = async () => {
        menu.hidden = true;
        await api("/api/stats/remove", {
          method: "DELETE",
          body: JSON.stringify({ kind: "artist", key: artist.artist_key || "" }),
        }).catch(() => {});
        state.statsCache = {};
        if (statsCtx.onRemoved) statsCtx.onRemoved();
      };
    }
  }

  openContextMenu(event, menu);
}

document.addEventListener("click", (e) => {
  const menu = $("artistContextMenu");
  if (menu && !menu.hidden && !menu.contains(e.target)) {
    menu.hidden = true;
  }
});

// A bare artist row has no track list of its own, so "Add to queue"/
// "Add to playlist" fetch the artist's top tracks first — same lightweight
// endpoint the sidebar "Related music" card already uses.
async function fetchArtistTopTracks(artist = {}) {
  const target = artistTarget(artist);
  try {
    const data = await api("/api/artist/top_tracks", {
      method: "POST",
      timeout: 20000,
      body: JSON.stringify({ artist_id: target.artist_id, name: target.name }),
    });
    return data.tracks || [];
  } catch (e) {
    console.error("Failed to fetch artist top tracks:", e);
    return [];
  }
}

$("ctxArtistAddQueue")?.addEventListener("click", async () => {
  const artist = contextMenuTargetArtist;
  $("artistContextMenu").hidden = true;
  if (!artist) return;
  const tracks = await fetchArtistTopTracks(artist);
  if (!tracks.length) return;
  tracks.forEach(t => {
    const trackItem = { ...t, kind: "track" };
    state.queue.push(trackItem);
    if (state.originalQueue) state.originalQueue.push(trackItem);
  });
  if (!$("queuePanel").hidden) refreshQueuePanel();
  updateSidebarNextQueue();
});

$("ctxArtistAddPlaylist")?.addEventListener("click", async () => {
  const artist = contextMenuTargetArtist;
  $("artistContextMenu").hidden = true;
  if (!artist) return;
  const tracks = await fetchArtistTopTracks(artist);
  if (!tracks.length) return;
  try {
    const target = artistTarget(artist);
    const pl = await api("/api/playlists", {
      method: "POST",
      body: JSON.stringify({
        name: target.name || "New Playlist",
        spotify_url: spotifyArtistUrl(target),
        origin: "artist",
      }),
    });
    await api("/api/playlists/tracks/add", { method: "POST", body: JSON.stringify({ id: pl.id, tracks: tracks.map(t => ({ ...t, kind: "track" })) }) });
    await loadPlaylists();
  } catch (e) {
    alert("Failed to add artist's top tracks to playlist: " + e.message);
  }
});

$("ctxArtistCopySpotify")?.addEventListener("click", () => {
  if (contextMenuTargetArtist) {
    const url = spotifyArtistUrl(contextMenuTargetArtist);
    if (url) navigator.clipboard.writeText(url);
  }
  $("artistContextMenu").hidden = true;
});

// Binds right-click/long-press on stats artist/album cards to show the
// stats-only context menu (with "Remove from statistics"), without touching
// the generic bindCardClicks used by the Home page's own Top Artists/Albums
// grids, which must never show that action.
function bindStatsEntityContextMenus(containerId, items, kind, onRemoved) {
  const container = $(containerId);
  if (!container) return;
  container.querySelectorAll("[data-card]").forEach((button) => {
    const item = items[Number(button.dataset.card)];
    if (!item) return;
    button.oncontextmenu = (event) => {
      event.preventDefault();
      const contextInfo = { kind: "stats", onRemoved };
      if (kind === "artist") showArtistContextMenu(event, item, contextInfo);
      else if (kind === "album") showAlbumContextMenu(event, item, contextInfo);
    };
  });
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
  persistPlaybackSnapshot(true);
  beaconListeningSession("", "beforeunload");
});

document.addEventListener("click", (e) => {
    const aMenu = $("albumContextMenu");
    if (aMenu && !aMenu.hidden && !aMenu.contains(e.target)) {
        aMenu.hidden = true;
    }
});
