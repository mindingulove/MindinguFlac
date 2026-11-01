// ============================================
// Apple Music Extension for SpotiFLAC Mobile
// Version: 1.4.2
//
// Uses Apple Music's public catalog API (amp-api)
// to fetch metadata including ISRC. No login required.
//
// LYRICS: Requires a Media User Token (Apple Music
// subscription). Supports word-by-word syllable sync,
// translations, and pronunciation/romanization via TTML.
//
// Token is obtained from the music.apple.com web page
// (Apple's own developer token embedded in the HTML).
// ============================================

const API_BASE = "https://amp-api.music.apple.com/v1/catalog/";
const DOWNLOAD_PROXY_BASE = "https://api.zarz.moe/v1/dl/app";
const DOWNLOAD_PROXY_FALLBACK_BASE = "https://api.zarz.moe/v1/dl/app2";
const DOWNLOAD_URL_CACHE_LIMIT = 200;

let state = {
  token: null,
  tokenExpiry: 0,
  storefront: "us",
  mediaUserToken: "",
  lyricsTranslation: "",
  lyricsPronunciation: "",
  proxyApiKey: "",
  downloadPollIntervalMs: 2500,
  downloadMaxWaitMinutes: 60,
  trackURLCache: {}
};

function initialize(config) {
  log.info("Apple Music Extension initializing...");

  // The host passes the flat settings object as the argument. Accept both the
  // flat form and a legacy { settings: {...} } wrapper for safety.
  var s = (config && config.settings) ? config.settings : (config || {});
  if (s) {
    var sf = (s.storefront || "").trim().toLowerCase();
    if (sf) {
      state.storefront = sf;
    }
    state.mediaUserToken = (s.mediaUserToken || "").trim();
    state.lyricsTranslation = (s.lyricsTranslation || "").trim().toLowerCase();
    state.lyricsPronunciation = (s.lyricsPronunciation || "").trim().toLowerCase();
    state.proxyApiKey = (s.proxyApiKey || "").trim();
    state.downloadPollIntervalMs = clampInt(s.downloadPollIntervalMs, 2500, 500, 30000);
    state.downloadMaxWaitMinutes = clampInt(s.downloadMaxWaitMinutes, 60, 1, 24 * 60);
  }

  try {
    const cached = storage.get("am_state");
    if (cached) {
      const parsed = JSON.parse(cached);
      if (parsed.token && parsed.tokenExpiry && Date.now() < parsed.tokenExpiry) {
        state.token = parsed.token;
        state.tokenExpiry = parsed.tokenExpiry;
        log.info("Loaded cached token (expires in " +
          Math.round((state.tokenExpiry - Date.now()) / 60000) + " min)");
      }
      if (parsed.trackURLCache && typeof parsed.trackURLCache === "object") {
        state.trackURLCache = parsed.trackURLCache;
      }
    }
  } catch (e) {
  }

  return true;
}

function persistState() {
  try {
    return storage.set("am_state", JSON.stringify({
      token: state.token,
      tokenExpiry: state.tokenExpiry,
      trackURLCache: state.trackURLCache
    }));
  } catch (e) {
    log.warn("Failed to persist Apple Music session:", e.message || String(e));
    return false;
  }
}

function cleanup() {
  persistState();
}

function clampInt(value, fallback, minValue, maxValue) {
  var num = parseInt(value, 10);
  if (isNaN(num)) {
    num = fallback;
  }
  if (num < minValue) num = minValue;
  if (num > maxValue) num = maxValue;
  return num;
}

function parseJSONSafe(text) {
  try {
    return JSON.parse(text);
  } catch (e) {
    return null;
  }
}

function appUserAgent() {
  if (utils && typeof utils.appUserAgent === "function") {
    return String(utils.appUserAgent() || "").trim() || "SpotiFLAC-Mobile";
  }
  return "SpotiFLAC-Mobile";
}

function proxyHeaders() {
  var headers = {
    "Accept": "application/json",
    "User-Agent": appUserAgent()
  };

  if (state.proxyApiKey) {
    headers["Authorization"] = "Bearer " + state.proxyApiKey;
    headers["X-API-Key"] = state.proxyApiKey;
  }

  return headers;
}

function proxyErrorMessage(response, fallback) {
  if (!response) return fallback;

  var headers = response.headers || {};
  var cfMitigated = headers["cf-mitigated"] || headers["Cf-Mitigated"];
  if (cfMitigated === "challenge") {
    return "Apple downloader proxy is blocked by a Cloudflare challenge";
  }

  var parsed = parseJSONSafe(response.body || "");
  if (parsed) {
    if (parsed.error && typeof parsed.error === "string") {
      return parsed.error;
    }
    if (parsed.message && typeof parsed.message === "string") {
      return parsed.message;
    }
  }

  return fallback;
}

function ensureLeadingDot(ext) {
  ext = String(ext || "").trim();
  if (!ext) return "";
  return ext.charAt(0) === "." ? ext : "." + ext;
}

function ensureOutputExtension(outputPath, extension) {
  var normalizedExt = ensureLeadingDot(extension);
  if (!normalizedExt) return outputPath;

  var dotIndex = outputPath.lastIndexOf(".");
  if (dotIndex < 0) {
    return outputPath + normalizedExt;
  }
  if (outputPath.substring(dotIndex).toLowerCase() === normalizedExt.toLowerCase()) {
    return outputPath;
  }
  return outputPath.substring(0, dotIndex) + normalizedExt;
}

function rememberTrackURL(trackID, url) {
  trackID = String(trackID || "").trim();
  url = String(url || "").trim();
  if (!trackID || !url) return;

  state.trackURLCache[trackID] = url;

  var keys = [];
  for (var key in state.trackURLCache) {
    if (state.trackURLCache.hasOwnProperty(key)) {
      keys.push(key);
    }
  }
  while (keys.length > DOWNLOAD_URL_CACHE_LIMIT) {
    delete state.trackURLCache[keys.shift()];
  }
}

function getCachedTrackURL(trackID) {
  trackID = String(trackID || "").trim();
  if (!trackID) return "";
  return String(state.trackURLCache[trackID] || "").trim();
}

// ============================================
// TOKEN MANAGEMENT
// ============================================

function fetchToken() {
  log.info("Fetching Apple Music developer token...");

  var response = http.get("https://music.apple.com/us/browse", {
    "User-Agent": utils.randomUserAgent(),
    "Accept-Encoding": "identity"
  });

  if (!response || response.error || response.statusCode !== 200) {
    throw new Error("Failed to fetch music.apple.com: HTTP " +
      (response ? response.statusCode : "no response"));
  }

  var body = response.body || "";

  // Strategy 1: Token in an iframe devToken= parameter (browser-rendered HTML)
  var tokenMatch = body.match(/devToken=([A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)/);

  // Strategy 2: JWT directly in the HTML (match both header field orderings)
  if (!tokenMatch) {
    tokenMatch = body.match(/((?:eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6IldlYlBsYXlLaWQifQ|eyJ0eXAiOiJKV1QiLCJhbGciOiJFUzI1NiIsImtpZCI6IldlYlBsYXlLaWQifQ)\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)/);
  }

  // Strategy 3: Token is in the main JS bundle — find and fetch it
  if (!tokenMatch) {
    log.info("Token not in HTML, checking JS bundles...");
    var bundleMatches = body.match(/src="(\/assets\/index[^"]*\.js)"/g);
    if (!bundleMatches) {
      bundleMatches = body.match(/src="(\/assets\/[^"]*\.js)"/g);
    }
    if (bundleMatches) {
      for (var i = 0; i < bundleMatches.length && i < 6; i++) {
        var srcMatch = bundleMatches[i].match(/src="([^"]+)"/);
        if (!srcMatch) continue;
        // Skip legacy bundles — they're duplicates and may be larger
        if (srcMatch[1].indexOf("-legacy") !== -1) continue;
        var bundleURL = "https://music.apple.com" + srcMatch[1];
        log.debug("Checking bundle:", srcMatch[1]);
        try {
          var bundleResp = http.get(bundleURL, {
            "User-Agent": utils.randomUserAgent(),
            "Accept-Encoding": "identity"
          });
          if (bundleResp && !bundleResp.error && bundleResp.statusCode === 200) {
            var bundleBody = bundleResp.body || "";
            log.debug("Bundle size:", bundleBody.length, "bytes");
            // Use indexOf for speed on large strings instead of regex
            var token = extractJWTFromString(bundleBody);
            if (token) {
              log.info("Found token in JS bundle:", srcMatch[1]);
              state.token = token;
              parseTokenExpiry();
              return;
            }
          }
        } catch (e) {
          log.debug("Bundle fetch failed:", e.message);
        }
      }
    }
  }

  if (!tokenMatch) {
    throw new Error("Could not find developer token in page HTML or JS bundles");
  }

  state.token = tokenMatch[1];
  parseTokenExpiry();
}

/**
 * Extract a JWT token from a large string using indexOf (avoids regex on multi-MB strings).
 * Looks for the known Apple Music JWT header prefix.
 */
function extractJWTFromString(str) {
  // Apple Music's web token uses the WebPlayKid key id but the JWT header
  // field order has varied over time, so match both known orderings:
  //   {"alg":"ES256","typ":"JWT","kid":"WebPlayKid"}
  //   {"typ":"JWT","alg":"ES256","kid":"WebPlayKid"}
  var prefixes = [
    "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6IldlYlBsYXlLaWQifQ.",
    "eyJ0eXAiOiJKV1QiLCJhbGciOiJFUzI1NiIsImtpZCI6IldlYlBsYXlLaWQifQ."
  ];
  var idx = -1;
  for (var p = 0; p < prefixes.length; p++) {
    idx = str.indexOf(prefixes[p]);
    if (idx !== -1) break;
  }
  if (idx === -1) return null;

  // Read from the start of the JWT until we hit a non-JWT character
  var start = idx;
  var end = start;
  var jwtChars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-.";
  while (end < str.length && jwtChars.indexOf(str.charAt(end)) !== -1) {
    end++;
  }

  var candidate = str.substring(start, end);
  // A valid JWT has exactly 3 parts separated by dots
  var parts = candidate.split(".");
  if (parts.length === 3 && parts[0].length > 0 && parts[1].length > 0 && parts[2].length > 0) {
    return candidate;
  }
  return null;
}

function parseTokenExpiry() {
  try {
    var parts = state.token.split(".");
    var payload = JSON.parse(decodeBase64URL(parts[1]));
    if (payload.exp) {
      // Expire 5 minutes early to avoid edge cases
      state.tokenExpiry = (payload.exp * 1000) - 300000;
    } else {
      state.tokenExpiry = Date.now() + (12 * 60 * 60 * 1000);
    }
  } catch (e) {
    state.tokenExpiry = Date.now() + (12 * 60 * 60 * 1000);
  }

  log.info("Token valid for " +
    Math.round((state.tokenExpiry - Date.now()) / 60000) + " minutes");
  persistState();
}

function ensureToken() {
  if (!state.token || Date.now() >= state.tokenExpiry) {
    fetchToken();
  }
}

// ============================================
// API HELPERS
// ============================================

function apiGet(path, allowRetry) {
  ensureToken();

  var url = API_BASE + state.storefront + "/" + path;
  var response = http.get(url, {
    "Authorization": "Bearer " + state.token,
    "Origin": "https://music.apple.com",
    "Referer": "https://music.apple.com/",
    "User-Agent": utils.randomUserAgent()
  });

  if (!response || response.error) {
    throw new Error("API request failed: " + (response ? response.error : "no response"));
  }

  if (response.statusCode === 401 && allowRetry !== false) {
    log.info("Token expired, refreshing...");
    state.token = null;
    state.tokenExpiry = 0;
    persistState();
    return apiGet(path, false);
  }

  if (response.statusCode !== 200) {
    throw new Error("API request failed: HTTP " + response.statusCode);
  }

  return JSON.parse(response.body);
}

/**
 * API GET with both developer token and Media-User-Token (for lyrics etc.).
 * Returns parsed JSON or null if the request fails (404 = no lyrics available).
 */
function apiGetWithUserToken(path) {
  ensureToken();

  var url = API_BASE + state.storefront + "/" + path;
  var headers = {
    "Authorization": "Bearer " + state.token,
    "Media-User-Token": state.mediaUserToken,
    "Origin": "https://music.apple.com",
    "Referer": "https://music.apple.com/",
    "User-Agent": utils.randomUserAgent()
  };

  var response = http.get(url, headers);

  if (!response || response.error) {
    return null;
  }

  // 404 = no lyrics for this song; 403 = token invalid/expired
  if (response.statusCode === 404) {
    return null;
  }

  if (response.statusCode === 401 || response.statusCode === 403) {
    log.warn("Lyrics API auth failed (HTTP " + response.statusCode + "). Media User Token may be invalid or expired.");
    return null;
  }

  if (response.statusCode !== 200) {
    log.debug("Lyrics API returned HTTP " + response.statusCode);
    return null;
  }

  try {
    return JSON.parse(response.body);
  } catch (e) {
    log.debug("Failed to parse lyrics API response:", e.message);
    return null;
  }
}

function artworkURL(artwork, size) {
  if (!artwork || !artwork.url) return "";
  size = size || Math.max(Number(artwork.width || 0), Number(artwork.height || 0), 3000);
  if (size > 6000) size = 6000;
  return artwork.url.replace("{w}", String(size)).replace("{h}", String(size));
}

function previewURL(attributes) {
  var previews = attributes && attributes.previews;
  if (!Array.isArray(previews) || previews.length === 0) return "";
  return previews[0] && previews[0].url ? previews[0].url : "";
}

/**
 * Extract the best tall (3:4) cover URL from editorialArtwork if available.
 * Falls back to standard square artwork.
 * Priority: superHeroTall > staticDetailTall > superHeroWide (cropped) > square artwork
 */
function tallArtworkURL(editorialArtwork, regularArtwork, size) {
  size = size || 3000;
  var tallSize = Math.round(size * 4 / 3); // 3:4 ratio

  if (editorialArtwork) {
    // superHeroTall: 1680x2240 (ratio 1.33 = 3:4) — available on albums
    var tall = editorialArtwork.superHeroTall || editorialArtwork.staticDetailTall;
    if (tall && tall.url) {
      return tall.url.replace("{w}", String(size)).replace("{h}", String(tallSize));
    }
  }

  // Fallback to regular square artwork
  return artworkURL(regularArtwork, size);
}

// Apple editorialVideo key priority for a "moving banner". The detail headers
// (album/artist) are full-width and portrait (taller than wide), so a tall 3:4
// motion source fills them with the least cropping (matches Apple Music).
// Covers both artist (motionArtist*) and album (motionDetail*) keys.
var MOTION_VIDEO_KEYS = [
  "motionDetailTall",
  "motionTallVideo3x4",
  "motionArtworkTall3x4",
  "motionArtistSquare1x1",
  "motionDetailSquare",
  "motionSquareVideo1x1",
  "motionArtworkSquare1x1",
  "motionArtistFullscreen16x9",
  "motionArtistWide16x9",
  "motionArtworkWide16x9",
  "motionDetailWide"
];

function motionArtworkIsTallKey(key) {
  return key.indexOf("Tall") >= 0 || key.indexOf("3x4") >= 0;
}

// Best HLS motion-artwork (.m3u8) video URL, or "" when none exists.
// The .video field is a direct HLS URL (no {w}/{h} template).
function motionArtworkVideoURL(editorialVideo, allowNonTall) {
  if (!editorialVideo) return "";
  for (var i = 0; i < MOTION_VIDEO_KEYS.length; i++) {
    var key = MOTION_VIDEO_KEYS[i];
    if (!allowNonTall && !motionArtworkIsTallKey(key)) continue;
    var entry = editorialVideo[key];
    if (entry && entry.video) return entry.video;
  }
  return "";
}

function motionArtworkPreviewHeight(key, entry, width) {
  var frame = entry && entry.previewFrame ? entry.previewFrame : null;
  var frameWidth = frame && Number(frame.width || frame.w || 0);
  var frameHeight = frame && Number(frame.height || frame.h || 0);
  if (frameWidth > 0 && frameHeight > 0) {
    return Math.round(width * frameHeight / frameWidth);
  }

  if (motionArtworkIsTallKey(key)) {
    return Math.round(width * 4 / 3);
  }
  if (
    key.indexOf("Wide") >= 0 ||
    key.indexOf("Fullscreen") >= 0 ||
    key.indexOf("16x9") >= 0
  ) {
    return Math.round(width * 9 / 16);
  }
  return width;
}

// Static preview-frame image for the motion artwork (banner placeholder /
// fallback when the HLS video cannot play).
function motionArtworkPreviewURL(editorialVideo, size) {
  if (!editorialVideo) return "";
  size = size || 1080;
  for (var i = 0; i < MOTION_VIDEO_KEYS.length; i++) {
    var key = MOTION_VIDEO_KEYS[i];
    var entry = editorialVideo[key];
    if (entry && entry.previewFrame && entry.previewFrame.url) {
      var height = motionArtworkPreviewHeight(key, entry, size);
      return entry.previewFrame.url
        .replace("{w}", String(size))
        .replace("{h}", String(height));
    }
  }
  return "";
}

// ============================================
// URL PARSING
// ============================================

function parseAppleMusicURL(url) {
  url = (url || "").trim();
  if (!url) return null;

  // https://music.apple.com/{storefront}/album/{name}/{id}
  // https://music.apple.com/{storefront}/album/{name}/{albumId}?i={songId}
  // https://music.apple.com/{storefront}/playlist/{name}/{id}
  // https://music.apple.com/{storefront}/artist/{name}/{id}
  // https://music.apple.com/{storefront}/song/{name}/{id}
  var match = url.match(
    /music\.apple\.com\/([a-z]{2})\/(album|playlist|artist|song)\/[^/]*\/([a-z0-9.]+)/i
  );
  if (!match) return null;

  var storefront = match[1].toLowerCase();
  var type = match[2].toLowerCase();
  var id = match[3];

  // Check for ?i=songId on album URLs
  var songMatch = url.match(/[?&]i=(\d+)/);

  if (type === "album" && songMatch) {
    return { type: "track", id: songMatch[1], storefront: storefront };
  }
  if (type === "song") {
    return { type: "track", id: id, storefront: storefront };
  }
  if (type === "album") {
    return { type: "album", id: id, storefront: storefront };
  }
  if (type === "playlist") {
    return { type: "playlist", id: id, storefront: storefront };
  }
  if (type === "artist") {
    return { type: "artist", id: id, storefront: storefront };
  }

  return null;
}

// ============================================
// DATA FORMATTERS
// ============================================

function uniqueValues(values) {
  var result = [];
  var seen = {};
  values = values || [];
  for (var i = 0; i < values.length; i++) {
    var value = String(values[i] || "").trim();
    var key = value.toLowerCase();
    if (!value || seen[key]) continue;
    seen[key] = true;
    result.push(value);
  }
  return result;
}

function appleGenres(attributes) {
  var genres = attributes && attributes.genreNames || [];
  return uniqueValues(genres.filter(function (genre) {
    return String(genre || "").trim().toLowerCase() !== "music";
  })).join("; ");
}

function appleAlbumType(attributes) {
  attributes = attributes || {};
  if (attributes.isCompilation === true) return "compilation";
  if (attributes.isSingle === true) return "single";
  return "album";
}

function appleAudioQuality(attributes) {
  var traits = attributes && attributes.audioTraits || [];
  var normalizedTraits = traits.map(function (trait) {
    return String(trait || "").trim().toLowerCase().replace(/_/g, "-");
  });
  if (normalizedTraits.indexOf("hi-res-lossless") >= 0) return "24-bit";
  if (normalizedTraits.indexOf("lossless") >= 0) return "16-bit";
  if (normalizedTraits.indexOf("lossy-stereo") >= 0) return "LOSSY";
  return "";
}

function appleAudioModes(attributes) {
  var traits = attributes && attributes.audioTraits || [];
  var modes = [];
  if (traits.indexOf("atmos") >= 0) modes.push("DOLBY_ATMOS");
  if (traits.indexOf("spatial") >= 0) modes.push("SPATIAL_AUDIO");
  return modes.join(",");
}

function firstRelationshipItem(resource, relationshipName) {
  var relationship = resource && resource.relationships && resource.relationships[relationshipName];
  var items = relationship && relationship.data || [];
  return items.length ? items[0] : null;
}

function appleArtistURL(artist) {
  return String(artist && artist.attributes && artist.attributes.url || "").trim();
}

function appleAlbumURL(album) {
  var attributes = album && album.attributes || {};
  if (attributes.url) return String(attributes.url);
  return album && album.id
    ? "https://music.apple.com/" + state.storefront + "/album/" + album.id
    : "";
}

function totalDiscsFromSongs(songs) {
  var total = 0;
  songs = songs || [];
  for (var i = 0; i < songs.length; i++) {
    var disc = Number(songs[i] && songs[i].attributes && songs[i].attributes.discNumber || 0);
    if (disc > total) total = disc;
  }
  return total;
}

function albumIDFromSong(song) {
  var album = firstRelationshipItem(song, "albums");
  if (album && album.id) return album.id;
  var url = String(song && song.attributes && song.attributes.url || "");
  var match = url.match(/\/album\/[^/]+\/(\d+)/i);
  return match ? match[1] : "";
}

function formatSong(song, albumData, totalDiscsOverride) {
  var attr = song.attributes || {};
  var albumAttr = albumData ? (albumData.attributes || {}) : {};

  // Use square artwork for images (UI display + download embedding).
  // tallArtworkURL is kept for future use when UI supports tall containers.
  var coverURL = artworkURL(attr.artwork);
  var albumID = "";
  var albumName = attr.albumName || "";

  // Try to get album ID from relationships
  var albumRel = song.relationships && song.relationships.albums;
  if (albumRel && albumRel.data && albumRel.data.length > 0) {
    albumID = albumRel.data[0].id || "";
  }
  // If we have albumData directly, use its ID
  if (albumData) {
    albumID = albumData.id || albumID;
    albumName = albumAttr.name || albumName;
    if (!coverURL) coverURL = artworkURL(albumAttr.artwork);
  }

  var artistResource = firstRelationshipItem(song, "artists") ||
    firstRelationshipItem(albumData, "artists");
  var albumURL = appleAlbumURL(albumData) || (albumID
    ? "https://music.apple.com/" + state.storefront + "/album/" + albumID
    : "");
  var trackURL = attr.url || ("https://music.apple.com/" + state.storefront + "/song/" + song.id);
  var totalDiscs = Number(totalDiscsOverride || albumData && albumData._totalDiscs || 0);
  var genre = appleGenres(attr) || appleGenres(albumAttr);

  rememberTrackURL(song.id || "", attr.url || "");

  return {
    id: song.id || "",
    name: attr.name || "",
    artists: attr.artistName || "",
    album_name: albumName,
    album_artist: attr.albumArtistName || albumAttr.artistName || attr.artistName || "",
    artist_id: artistResource && artistResource.id || "",
    artist_url: appleArtistURL(artistResource),
    duration_ms: attr.durationInMillis || 0,
    preview_url: previewURL(attr),
    images: coverURL,
    cover_url: coverURL,
    release_date: albumAttr.releaseDate || attr.releaseDate || "",
    track_number: attr.trackNumber || 0,
    total_tracks: albumAttr.trackCount || 0,
    disc_number: attr.discNumber || 1,
    total_discs: totalDiscs,
    external_urls: trackURL,
    external_links: {
      apple_music_track: trackURL,
      apple_music_album: albumURL
    },
    isrc: attr.isrc || "",
    album_id: albumID,
    album_url: albumURL,
    album_type: appleAlbumType(albumAttr),
    genre: genre,
    label: albumAttr.recordLabel || "",
    copyright: albumAttr.copyright || "",
    composer: attr.composerName || "",
    comment: albumURL,
    explicit: attr.contentRating === "explicit",
    audio_quality: appleAudioQuality(attr),
    audio_modes: appleAudioModes(attr),
    provider_id: "apple-music",
    item_type: "track",
    upc: albumAttr.upc || "",
    is_compilation: albumAttr.isCompilation === true,
    has_lyrics: attr.hasLyrics === true,
    has_time_synced_lyrics: attr.hasTimeSyncedLyrics === true
  };
}

function formatAlbumInfo(album) {
  var attr = album.attributes || {};
  var artistItems = album.relationships && album.relationships.artists
    ? album.relationships.artists.data
    : [];
  var firstArtistId = artistItems.length > 0 ? artistItems[0].id : "";
  var firstArtistURL = artistItems.length > 0 ? appleArtistURL(artistItems[0]) : "";
  var albumURL = appleAlbumURL(album);

  // Use square artwork — tall artwork causes 3:4 covers in downloaded files.
  var coverURL = artworkURL(attr.artwork);
  var editorialVideo = attr.editorialVideo;
  var headerVideo = motionArtworkVideoURL(editorialVideo);
  var headerImage = motionArtworkPreviewURL(editorialVideo) || coverURL;

  return {
    id: album.id || "",
    name: attr.name || "",
    artists: attr.artistName || "",
    artist_id: firstArtistId,
    artist_url: firstArtistURL,
    images: coverURL,
    cover_url: coverURL,
    header_image: headerImage,
    header_video: headerVideo,
    release_date: attr.releaseDate || "",
    total_tracks: attr.trackCount || 0,
    total_discs: Number(album._totalDiscs || 0),
    album_type: appleAlbumType(attr),
    album_url: albumURL,
    external_urls: albumURL,
    record_label: attr.recordLabel || "",
    label: attr.recordLabel || "",
    copyright: attr.copyright || "",
    genre: appleGenres(attr),
    comment: albumURL,
    explicit: attr.contentRating === "explicit",
    audio_traits: attr.audioTraits || [],
    provider_id: "apple-music",
    item_type: "album",
    upc: attr.upc || "",
    is_compilation: attr.isCompilation === true,
    editorial_notes: attr.editorialNotes || null
  };
}

// ============================================
// FETCH FUNCTIONS
// ============================================

function collectRelationshipItems(resource, relationshipName) {
  var relationship = resource && resource.relationships && resource.relationships[relationshipName];
  var items = relationship && relationship.data ? relationship.data.slice() : [];
  var nextURL = relationship && relationship.next;
  while (nextURL) {
    try {
      var nextPath = nextURL.replace(/^\/v1\/catalog\/[a-z]{2}\//, "");
      var nextData = apiGet(nextPath);
      var nextItems = nextData.data || [];
      if (!nextItems.length) break;
      items = items.concat(nextItems);
      nextURL = nextData.next || null;
    } catch (e) {
      log.debug(relationshipName + " pagination error:", e.message);
      break;
    }
  }
  return items;
}

function hydrateAlbumsForSongs(songs) {
  var albumIDs = [];
  var seen = {};
  songs = songs || [];
  for (var i = 0; i < songs.length; i++) {
    var albumID = albumIDFromSong(songs[i]);
    if (!albumID || seen[albumID]) continue;
    seen[albumID] = true;
    albumIDs.push(albumID);
  }

  var albumsByID = {};
  for (var offset = 0; offset < albumIDs.length; offset += 25) {
    var chunk = albumIDs.slice(offset, offset + 25);
    try {
      var data = apiGet(
        "albums?ids=" + encodeURIComponent(chunk.join(",")) +
        "&include=tracks,artists" +
        "&extend=artistUrl,editorialArtwork,trackCount,upc"
      );
      var albums = data.data || [];
      for (var j = 0; j < albums.length; j++) {
        var album = albums[j];
        album._totalDiscs = totalDiscsFromSongs(
          collectRelationshipItems(album, "tracks")
        );
        albumsByID[String(album.id || "")] = album;
      }
    } catch (e) {
      log.debug("Batch album hydration failed:", e.message);
    }
  }
  return albumsByID;
}

function fetchTrack(trackID) {
  log.info("Fetching track:", trackID);

  var data = apiGet(
    "songs/" + trackID +
    "?include=albums,artists,composers,genres" +
    "&extend=artistUrl,editorialArtwork,trackCount,upc"
  );
  var songs = data.data || [];
  if (songs.length === 0) {
    throw new Error("Track not found: " + trackID);
  }

  var song = songs[0];
  // Try to get album details for label/copyright
  var albumData = null;
  var albumRel = song.relationships && song.relationships.albums;
  if (albumRel && albumRel.data && albumRel.data.length > 0) {
    albumData = albumRel.data[0];
  }

  var albumID = albumData && albumData.id || albumIDFromSong(song);
  if (albumID) {
    try {
      var fullAlbumData = apiGet(
        "albums/" + albumID +
        "?include=tracks,artists" +
        "&extend=artistUrl,editorialArtwork,trackCount,upc"
      );
      var fullAlbums = fullAlbumData.data || [];
      if (fullAlbums.length) {
        albumData = fullAlbums[0];
        albumData._totalDiscs = totalDiscsFromSongs(
          collectRelationshipItems(albumData, "tracks")
        );
      }
    } catch (e) {
      log.debug("Full album hydration failed:", e.message);
    }
  }

  var track = formatSong(song, albumData);
  log.info("Fetched track:", track.name, "by", track.artists, "ISRC:", track.isrc);

  return {
    type: "track",
    track: track
  };
}

function fetchAlbum(albumID) {
  log.info("Fetching album:", albumID);

  var data = apiGet(
    "albums/" + albumID +
    "?include=tracks,artists" +
    "&extend=artistUrl,editorialArtwork,editorialVideo,trackCount,upc"
  );
  var albums = data.data || [];
  if (albums.length === 0) {
    throw new Error("Album not found: " + albumID);
  }

  var album = albums[0];
  var trackItems = collectRelationshipItems(album, "tracks");
  var totalDiscs = totalDiscsFromSongs(trackItems) || (trackItems.length ? 1 : 0);
  album._totalDiscs = totalDiscs;
  var albumAttributes = album.attributes || {};
  var traitValues = (albumAttributes.audioTraits || []).slice();
  for (var traitIndex = 0; traitIndex < trackItems.length; traitIndex++) {
    traitValues = traitValues.concat(
      trackItems[traitIndex] && trackItems[traitIndex].attributes &&
      trackItems[traitIndex].attributes.audioTraits || []
    );
  }
  albumAttributes.audioTraits = uniqueValues(traitValues);
  var albumInfo = formatAlbumInfo(album);

  var tracks = [];
  for (var i = 0; i < trackItems.length; i++) {
    tracks.push(formatSong(trackItems[i], album, totalDiscs));
  }

  log.info("Fetched", tracks.length, "tracks from album");

  return {
    type: "album",
    album_info: albumInfo,
    track_list: tracks
  };
}

function fetchPlaylist(playlistID) {
  log.info("Fetching playlist:", playlistID);

  var data = apiGet("playlists/" + playlistID + "?include=tracks&extend=editorialArtwork,editorialVideo");
  var playlists = data.data || [];
  if (playlists.length === 0) {
    throw new Error("Playlist not found: " + playlistID);
  }

  var playlist = playlists[0];
  var attr = playlist.attributes || {};
  var description = "";
  if (attr.description) {
    // Strip HTML tags from description
    description = (attr.description.standard || attr.description.short || "")
      .replace(/<[^>]+>/g, "");
  }

  var playlistInfo = {
    id: playlist.id || playlistID,
    name: attr.name || "",
    description: description,
    owner: attr.curatorName || "",
    cover: artworkURL(attr.artwork),
    header_image: motionArtworkPreviewURL(attr.editorialVideo) || artworkURL(attr.artwork),
    header_video: motionArtworkVideoURL(attr.editorialVideo),
    totalTracks: 0,
    followers: 0,
    external_urls: attr.url || "",
    item_type: "playlist"
  };

  var trackItems = collectRelationshipItems(playlist, "tracks");

  playlistInfo.totalTracks = trackItems.length;

  var tracks = [];
  var albumsByID = hydrateAlbumsForSongs(trackItems);
  for (var i = 0; i < trackItems.length; i++) {
    var album = albumsByID[albumIDFromSong(trackItems[i])] || null;
    var formatted = formatSong(trackItems[i], album, album && album._totalDiscs);
    formatted.playlist_position = i + 1;
    tracks.push(formatted);
  }

  log.info("Fetched", tracks.length, "tracks from playlist");

  return {
    type: "playlist",
    playlist_info: playlistInfo,
    track_list: tracks
  };
}

function fetchArtist(artistID) {
  log.info("Fetching artist:", artistID);

  var data = apiGet("artists/" + artistID + "?include=albums&views=top-songs&extend=editorialVideo");
  var artists = data.data || [];
  if (artists.length === 0) {
    throw new Error("Artist not found: " + artistID);
  }

  var artist = artists[0];
  var attr = artist.attributes || {};

  var topTracks = [];
  var topSongsView = artist.views && artist.views["top-songs"];
  if (topSongsView && topSongsView.data) {
    var topAlbums = hydrateAlbumsForSongs(topSongsView.data);
    for (var i = 0; i < topSongsView.data.length; i++) {
      var song = topSongsView.data[i];
      var topAlbum = topAlbums[albumIDFromSong(song)] || null;
      topTracks.push(formatSong(song, topAlbum, topAlbum && topAlbum._totalDiscs));
    }
  }

  // Collect all albums with pagination
  var albumItems = artist.relationships && artist.relationships.albums
    ? artist.relationships.albums.data
    : [];
  var albumNext = artist.relationships && artist.relationships.albums
    ? artist.relationships.albums.next
    : null;
  while (albumNext) {
    try {
      var nextPath = albumNext.replace(/^\/v1\/catalog\/[a-z]{2}\//, "");
      var nextData = apiGet(nextPath);
      var nextItems = nextData.data || [];
      if (nextItems.length === 0) break;
      albumItems = albumItems.concat(nextItems);
      albumNext = nextData.next || null;
    } catch (e) {
      log.debug("Artist albums pagination error:", e.message);
      break;
    }
  }

  var albums = [];
  for (var j = 0; j < albumItems.length; j++) {
    var alb = albumItems[j];
    var albAttr = alb.attributes || {};

    var releaseDate = albAttr.releaseDate || "";
    albums.push({
      id: alb.id || "",
      name: albAttr.name || "",
      album_type: appleAlbumType(albAttr),
      release_date: releaseDate,
      total_tracks: albAttr.trackCount || 0,
      artists: albAttr.artistName || attr.name || "",
      artist_id: artistID,
      artist_url: attr.url || "",
      cover_url: artworkURL(albAttr.artwork),
      external_urls: albAttr.url || "",
      provider_id: "apple-music"
    });
  }

  log.info("Fetched artist with", albums.length, "releases and", topTracks.length, "top tracks");

  var editorialVideo = attr.editorialVideo;
  var headerVideo = motionArtworkVideoURL(editorialVideo);
  var headerImage = motionArtworkPreviewURL(editorialVideo) || artworkURL(attr.artwork);

  return {
    type: "artist",
    artist: {
      id: artistID,
      name: attr.name || "",
      image_url: artworkURL(attr.artwork),
      header_image: headerImage,
      header_video: headerVideo,
      artist_url: attr.url || "",
      external_urls: attr.url || "",
      listeners: 0,
      albums: albums,
      top_tracks: topTracks,
      provider_id: "apple-music"
    }
  };
}

// ============================================
// SEARCH
// ============================================

function customSearch(searchQuery, options) {
  log.info("Searching Apple Music:", searchQuery);

  var limit = (options && options.limit) || 20;
  var offset = (options && options.offset) || 0;
  var filter = (options && options.filter) || null;

  if (limit <= 0 || limit > 25) limit = 25;

  var isFiltered = filter && filter !== "all";

  // Map filter names to API types
  var types = "songs,albums,artists,playlists";
  if (isFiltered) {
    var typeMap = {
      "tracks": "songs",
      "albums": "albums",
      "artists": "artists",
      "playlists": "playlists"
    };
    types = typeMap[filter] || types;
  }

  var path = "search?term=" + encodeURIComponent(searchQuery) +
    "&types=" + types +
    "&limit=" + limit +
    "&offset=" + offset;

  var data = apiGet(path);
  var searchResults = data.results || {};
  var results = [];

  // Songs
  if (searchResults.songs && (!isFiltered || filter === "tracks")) {
    var songs = searchResults.songs.data || [];
    if (!isFiltered) songs = songs.slice(0, limit);
    var searchAlbumsByID = hydrateAlbumsForSongs(songs);

    for (var i = 0; i < songs.length; i++) {
      var songAttr = songs[i].attributes || {};
      rememberTrackURL(songs[i].id || "", songAttr.url || "");
      var searchAlbum = searchAlbumsByID[albumIDFromSong(songs[i])] || null;
      var formattedSearchSong = formatSong(
        songs[i],
        searchAlbum,
        searchAlbum && searchAlbum._totalDiscs
      );
      formattedSearchSong.source = "apple-music";
      results.push(formattedSearchSong);
    }
  }

  // Albums
  if (searchResults.albums && (!isFiltered || filter === "albums")) {
    var albumsData = searchResults.albums.data || [];
    if (!isFiltered) albumsData = albumsData.slice(0, 5);

    for (var j = 0; j < albumsData.length; j++) {
      var albAttr = albumsData[j].attributes || {};
      results.push({
        id: albumsData[j].id || "",
        name: albAttr.name || "",
        artists: albAttr.artistName || "",
        cover_url: artworkURL(albAttr.artwork),
        images: artworkURL(albAttr.artwork),
        release_date: albAttr.releaseDate || "",
        total_tracks: albAttr.trackCount || 0,
        album_type: appleAlbumType(albAttr),
        label: albAttr.recordLabel || "",
        copyright: albAttr.copyright || "",
        genre: appleGenres(albAttr),
        explicit: albAttr.contentRating === "explicit",
        album_url: albAttr.url || "",
        external_urls: albAttr.url || "",
        item_type: "album",
        provider_id: "apple-music"
      });
    }
  }

  // Artists
  if (searchResults.artists && (!isFiltered || filter === "artists")) {
    var artistsData = searchResults.artists.data || [];
    if (!isFiltered) artistsData = artistsData.slice(0, 2);

    for (var k = 0; k < artistsData.length; k++) {
      var artAttr = artistsData[k].attributes || {};
      results.push({
        id: artistsData[k].id || "",
        name: artAttr.name || "",
        image_url: artworkURL(artAttr.artwork),
        images: artworkURL(artAttr.artwork),
        artist_url: artAttr.url || "",
        external_urls: artAttr.url || "",
        item_type: "artist",
        provider_id: "apple-music"
      });
    }
  }

  // Playlists
  if (searchResults.playlists && (!isFiltered || filter === "playlists")) {
    var playlistsData = searchResults.playlists.data || [];
    if (!isFiltered) playlistsData = playlistsData.slice(0, 4);

    for (var m = 0; m < playlistsData.length; m++) {
      var plAttr = playlistsData[m].attributes || {};
      var playlistDescription = plAttr.description
        ? String(plAttr.description.standard || plAttr.description.short || "").replace(/<[^>]+>/g, "")
        : "";
      results.push({
        id: playlistsData[m].id || "",
        name: plAttr.name || "",
        owner: plAttr.curatorName || "",
        description: playlistDescription,
        cover_url: artworkURL(plAttr.artwork),
        images: artworkURL(plAttr.artwork),
        external_urls: plAttr.url || "",
        item_type: "playlist",
        provider_id: "apple-music"
      });
    }
  }

  log.info("Found", results.length, "items (filter:", filter || "all", ")");
  return results;
}

// ============================================
// ENRICHMENT
// ============================================

function overlayTrackMetadata(target, source) {
  target = target || {};
  source = source || {};
  var keys = Object.keys(source);
  for (var i = 0; i < keys.length; i++) {
    var value = source[keys[i]];
    if (value === null || value === undefined || value === "") continue;
    target[keys[i]] = value;
  }
  return target;
}

function enrichTrack(track) {
  track = track || {};
  log.info("enrichTrack called for:", track.name, "by", track.artists);

  var amTrackID = String(track.id || "").trim();
  if (amTrackID && /^\d+$/.test(amTrackID)) {
    try {
      var direct = fetchTrack(amTrackID);
      if (direct && direct.track) return overlayTrackMetadata(track, direct.track);
    } catch (e) {
      log.debug("Direct Apple Music enrichment failed:", e.message);
    }
  }

  var searchTerm = ((track.name || "") + " " + (track.artists || "")).trim();
  if (!searchTerm) return track;
  try {
    var searchData = apiGet(
      "search?term=" + encodeURIComponent(searchTerm) + "&types=songs&limit=5"
    );
    var searchSongs = searchData.results && searchData.results.songs
      ? searchData.results.songs.data
      : [];
    var bestMatch = findBestMatch(searchSongs, track.name, track.artists);
    if (bestMatch && bestMatch.id) {
      var resolved = fetchTrack(bestMatch.id);
      if (resolved && resolved.track) return overlayTrackMetadata(track, resolved.track);
    }
  } catch (e) {
    log.debug("Apple Music search enrichment failed:", e.message);
  }
  return track;
}

function findBestMatch(songs, targetName, targetArtist) {
  if (!songs || songs.length === 0) return null;

  var normTarget = normalizeText(targetName);
  var normArtist = normalizeText(targetArtist);

  for (var i = 0; i < songs.length; i++) {
    var attr = songs[i].attributes || {};
    var normName = normalizeText(attr.name || "");
    var normSongArtist = normalizeText(attr.artistName || "");

    if (normName === normTarget && normSongArtist === normArtist) {
      return songs[i];
    }
  }

  for (var j = 0; j < songs.length; j++) {
    var attr2 = songs[j].attributes || {};
    var n = normalizeText(attr2.name || "");
    var a = normalizeText(attr2.artistName || "");

    if ((n.indexOf(normTarget) !== -1 || normTarget.indexOf(n) !== -1) &&
        (a.indexOf(normArtist) !== -1 || normArtist.indexOf(a) !== -1)) {
      return songs[j];
    }
  }

  return songs[0];
}

function normalizeText(text) {
  if (!text) return "";
  return text.toLowerCase()
    .replace(/[^a-z0-9\u00c0-\u024f\u0400-\u04ff\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

// ============================================
// EXPORTED API
// ============================================

function handleURL(url) {
  log.info("Handling URL:", url);

  var parsed = parseAppleMusicURL(url);
  if (!parsed) {
    return { success: false, error: "Invalid Apple Music URL" };
  }

  // Temporarily switch storefront if URL has a different one
  var originalSF = state.storefront;
  if (parsed.storefront) {
    state.storefront = parsed.storefront;
  }

  try {
    var result;
    switch (parsed.type) {
      case "track":
        result = fetchTrack(parsed.id);
        return {
          success: true,
          type: "track",
          track: result.track
        };

      case "album":
        result = fetchAlbum(parsed.id);
        return {
          success: true,
          type: "album",
          album: {
            id: parsed.id,
            name: result.album_info.name,
            artists: result.album_info.artists,
            artist_id: result.album_info.artist_id,
            artist_url: result.album_info.artist_url,
            cover_url: result.album_info.images,
            header_image: result.album_info.header_image,
            header_video: result.album_info.header_video,
            audio_traits: result.album_info.audio_traits,
            release_date: result.album_info.release_date,
            total_tracks: result.album_info.total_tracks,
            total_discs: result.album_info.total_discs,
            album_type: result.album_info.album_type,
            album_url: result.album_info.album_url,
            external_urls: result.album_info.external_urls,
            label: result.album_info.label,
            copyright: result.album_info.copyright,
            genre: result.album_info.genre,
            comment: result.album_info.comment,
            explicit: result.album_info.explicit,
            tracks: result.track_list
          },
          tracks: result.track_list,
          name: result.album_info.name,
          cover_url: result.album_info.images,
          header_image: result.album_info.header_image,
          header_video: result.album_info.header_video,
          audio_traits: result.album_info.audio_traits
        };

      case "playlist":
        result = fetchPlaylist(parsed.id);
        return {
          success: true,
          type: "playlist",
          id: result.playlist_info.id,
          playlist: {
            id: result.playlist_info.id,
            name: result.playlist_info.name,
            artists: result.playlist_info.owner,
            description: result.playlist_info.description,
            cover_url: result.playlist_info.cover,
            header_image: result.playlist_info.header_image,
            header_video: result.playlist_info.header_video,
            total_tracks: result.playlist_info.totalTracks,
            external_urls: result.playlist_info.external_urls,
            tracks: result.track_list,
            provider_id: "apple-music"
          },
          tracks: result.track_list,
          name: result.playlist_info.name,
          cover_url: result.playlist_info.cover,
          header_image: result.playlist_info.header_image,
          header_video: result.playlist_info.header_video
        };

      case "artist":
        result = fetchArtist(parsed.id);
        return {
          success: true,
          type: "artist",
          artist: result.artist
        };

      default:
        return { success: false, error: "Unsupported URL type: " + parsed.type };
    }
  } catch (e) {
    log.error("URL handling failed:", e.message);
    return { success: false, error: e.message || "Failed to fetch metadata" };
  } finally {
    state.storefront = originalSF;
  }
}

function getTrack(trackId) {
  try {
    var result = fetchTrack(trackId);
    return result.track;
  } catch (e) {
    log.error("getTrack failed:", e.message);
    return null;
  }
}

function getAlbum(albumId) {
  try {
    var result = fetchAlbum(albumId);
    var tracks = result.track_list.map(function (t) {
      t.provider_id = "apple-music";
      return t;
    });
    return {
      id: albumId,
      name: result.album_info.name,
      artists: result.album_info.artists,
      artist_id: result.album_info.artist_id,
      artist_url: result.album_info.artist_url,
      release_date: result.album_info.release_date,
      total_tracks: result.album_info.total_tracks,
      total_discs: result.album_info.total_discs,
      album_type: result.album_info.album_type,
      album_url: result.album_info.album_url,
      external_urls: result.album_info.external_urls,
      label: result.album_info.label,
      copyright: result.album_info.copyright,
      genre: result.album_info.genre,
      comment: result.album_info.comment,
      explicit: result.album_info.explicit,
      images: result.album_info.images,
      cover_url: result.album_info.images,
      header_image: result.album_info.header_image,
      header_video: result.album_info.header_video,
      audio_traits: result.album_info.audio_traits,
      tracks: tracks,
      provider_id: "apple-music"
    };
  } catch (e) {
    log.error("getAlbum failed:", e.message);
    return null;
  }
}

function getArtist(artistId) {
  try {
    var result = fetchArtist(artistId);
    return result.artist;
  } catch (e) {
    log.error("getArtist failed:", e.message);
    return null;
  }
}

function getPlaylist(playlistId) {
  try {
    var result = fetchPlaylist(playlistId);
    var tracks = result.track_list.map(function (t) {
      t.provider_id = "apple-music";
      return t;
    });
    return {
      id: playlistId,
      name: result.playlist_info.name,
      description: result.playlist_info.description,
      owner: result.playlist_info.owner,
      cover: result.playlist_info.cover,
      cover_url: result.playlist_info.cover,
      header_image: result.playlist_info.header_image,
      header_video: result.playlist_info.header_video,
      total_tracks: result.playlist_info.totalTracks,
      external_urls: result.playlist_info.external_urls,
      tracks: tracks,
      provider_id: "apple-music"
    };
  } catch (e) {
    log.error("getPlaylist failed:", e.message);
    return null;
  }
}

function searchTracks(searchQuery, limit) {
  return customSearch(searchQuery, { limit: limit || 20 });
}

function normalizeRequestedCodec(quality) {
  var normalized = String(quality || "").trim().toLowerCase();
  switch (normalized) {
    case "alac":
    case "atmos":
    case "ac3":
    case "aac":
    case "aac-legacy":
      return normalized;
    case "hi_res":
    case "hi_res_lossless":
    case "lossless":
    case "default":
    case "":
      return "alac";
    default:
      return "alac";
  }
}

function extractFilenameFromURL(url) {
  url = String(url || "").trim();
  if (!url) return "";

  var fileMatch = url.match(/[?&]file=([^&]+)/i);
  if (fileMatch && fileMatch[1]) {
    try {
      return decodeURIComponent(fileMatch[1]);
    } catch (e) {
      return fileMatch[1];
    }
  }

  var sanitized = url.split("?")[0];
  var slashIndex = sanitized.lastIndexOf("/");
  if (slashIndex >= 0 && slashIndex < sanitized.length - 1) {
    return sanitized.substring(slashIndex + 1);
  }

  return "";
}

function inferDownloadExtension(codec, payload, streamURL) {
  var filename = "";
  if (payload) {
    filename = String(payload.filename || payload.file_name || "").trim();
  }
  if (!filename && streamURL) {
    filename = extractFilenameFromURL(streamURL);
  }

  var dotIndex = filename.lastIndexOf(".");
  if (dotIndex >= 0 && dotIndex < filename.length - 1) {
    return filename.substring(dotIndex);
  }

  codec = String(codec || "").trim().toLowerCase();
  if (codec === "ac3") {
    return ".m4a";
  }
  return ".m4a";
}

function resolveDownloadTrackURL(trackID) {
  trackID = String(trackID || "").trim();
  if (!trackID) return "";

  if (trackID.indexOf("music.apple.com/") !== -1) {
    return trackID;
  }

  var cachedURL = getCachedTrackURL(trackID);
  if (cachedURL) {
    return cachedURL;
  }

  if (/^\d+$/.test(trackID)) {
    try {
      var data = apiGet("songs/" + trackID);
      var songs = data.data || [];
      if (songs.length > 0) {
        var attr = songs[0].attributes || {};
        var resolvedURL = String(attr.url || "").trim();
        if (resolvedURL) {
          rememberTrackURL(trackID, resolvedURL);
          return resolvedURL;
        }
      }
    } catch (e) {
      log.debug("resolveDownloadTrackURL direct fetch failed:", e.message);
    }
  }

  return "";
}

function scoreAppleSearchSong(song, trackName, artistName, isrc) {
  var attr = song.attributes || {};
  var score = 0;

  if (isrc && attr.isrc && String(isrc).toUpperCase() === String(attr.isrc).toUpperCase()) {
    score += 100;
  }

  score += matching.compareStrings(trackName || "", attr.name || "") * 60;
  score += matching.compareStrings(artistName || "", attr.artistName || "") * 40;
  return score;
}

function resolveTrackURLByAppleSearch(trackName, artistName, isrc) {
  var query = ((trackName || "") + " " + (artistName || "")).trim();
  if (!query && isrc) {
    query = String(isrc).trim();
  }
  if (!query) {
    return "";
  }

  var searchData = apiGet(
    "search?term=" + encodeURIComponent(query) + "&types=songs&limit=10"
  );
  var songs = searchData.results && searchData.results.songs
    ? searchData.results.songs.data
    : [];

  if (!songs || songs.length === 0) {
    return "";
  }

  var bestScore = -1;
  var bestURL = "";
  var bestID = "";

  for (var i = 0; i < songs.length; i++) {
    var attr = songs[i].attributes || {};
    var url = String(attr.url || "").trim();
    if (!url) continue;

    var score = scoreAppleSearchSong(songs[i], trackName, artistName, isrc);
    if (score > bestScore) {
      bestScore = score;
      bestURL = url;
      bestID = songs[i].id || "";
    }
  }

  if (bestURL) {
    rememberTrackURL(bestID, bestURL);
  }

  return bestURL;
}

function queueAppleProxyDownload(trackURL, codec) {
  var response = http.post(
    DOWNLOAD_PROXY_BASE + "/download",
    JSON.stringify({
      url: trackURL,
      codec: codec
    }),
    proxyHeaders()
  );

  if (!response || response.error) {
    throw new Error(response && response.error ? response.error : "proxy request failed");
  }
  if (response.statusCode < 200 || response.statusCode >= 300) {
    throw new Error(proxyErrorMessage(
      response,
      "Apple downloader queue failed: HTTP " + response.statusCode
    ));
  }

  var payload = parseJSONSafe(response.body || "");
  if (!payload || !payload.job_id) {
    throw new Error("Apple downloader queue returned no job_id");
  }

  return payload;
}

function requestAppleProxyFallbackDownload(trackURL, codec) {
  var response = http.post(
    DOWNLOAD_PROXY_FALLBACK_BASE,
    JSON.stringify({
      url: trackURL,
      codec: codec
    }),
    proxyHeaders()
  );

  if (!response || response.error) {
    throw new Error(response && response.error ? response.error : "fallback request failed");
  }
  if (response.statusCode < 200 || response.statusCode >= 300) {
    throw new Error(proxyErrorMessage(
      response,
      "Apple downloader fallback failed: HTTP " + response.statusCode
    ));
  }

  var payload = parseJSONSafe(response.body || "");
  if (!payload) {
    throw new Error("Apple downloader fallback returned invalid JSON");
  }
  if (payload.success !== true || !payload.stream_url) {
    throw new Error(String(
      payload.error || payload.message || "Apple downloader fallback returned no stream URL"
    ));
  }

  return payload;
}

function fetchAppleProxyStatus(jobID) {
  var response = http.get(
    DOWNLOAD_PROXY_BASE + "/status/" + encodeURIComponent(jobID),
    proxyHeaders()
  );

  if (!response || response.error) {
    throw new Error(response && response.error ? response.error : "status request failed");
  }
  if (response.statusCode < 200 || response.statusCode >= 300) {
    throw new Error(proxyErrorMessage(
      response,
      "Apple downloader status failed: HTTP " + response.statusCode
    ));
  }

  var payload = parseJSONSafe(response.body || "");
  if (!payload) {
    throw new Error("Apple downloader status returned invalid JSON");
  }

  return payload;
}

function cancelledDownloadResult() {
  return {
    success: false,
    error_message: "Download cancelled",
    error_type: "cancelled"
  };
}

function failedDownloadResult(message, type) {
  return {
    success: false,
    error_message: message || "Apple Music download failed",
    error_type: type || "api_error"
  };
}

function waitForAppleProxyJob(jobID, onProgress) {
  var deadline = Date.now() + (state.downloadMaxWaitMinutes * 60 * 1000);

  while (Date.now() < deadline) {
    if (utils.isDownloadCancelled()) {
      return { cancelled: true };
    }

    var payload = fetchAppleProxyStatus(jobID);
    var status = String(payload.status || "").trim().toLowerCase();

    if (status === "completed") {
      return {
        success: true,
        payload: payload
      };
    }

    if (status === "failed") {
      return {
        success: false,
        error: String(payload.error || "Apple downloader job failed")
      };
    }

    if (typeof onProgress === "function") {
      if (status === "queued" || status === "waiting" || status === "pending") {
        onProgress(12);
      } else if (status === "downloading") {
        onProgress(20);
      } else {
        onProgress(15);
      }
    }

    if (!utils.sleep(state.downloadPollIntervalMs)) {
      return { cancelled: true };
    }
  }

  return {
    success: false,
    error: "Timed out while waiting for Apple downloader job"
  };
}

function downloadFromStreamURL(streamURL, outputPath, codec, payload, onProgress, headers) {
  var actualOutputPath = ensureOutputExtension(
    outputPath,
    inferDownloadExtension(codec, payload, streamURL)
  );

  var downloadResult = file.download(
    streamURL,
    actualOutputPath,
    {
      headers: headers || {
        "User-Agent": utils.randomUserAgent()
      },
      onProgress: function(written, total) {
        if (typeof onProgress === "function" && total > 0) {
          var ratio = written / total;
          if (ratio < 0) ratio = 0;
          if (ratio > 1) ratio = 1;
          onProgress(20 + Math.round(ratio * 80));
        }
      }
    }
  );

  if (!downloadResult || !downloadResult.success) {
    return failedDownloadResult(
      downloadResult && downloadResult.error
        ? downloadResult.error
        : "Failed to download Apple Music file",
      downloadResult && downloadResult.error === "download cancelled"
        ? "cancelled"
        : "download_error"
    );
  }

  return {
    success: true,
    file_path: downloadResult.path || actualOutputPath,
    bit_depth: 0,
    sample_rate: 0,
    title: payload && payload.title ? payload.title : "",
    artist: payload && payload.artist ? payload.artist : ""
  };
}

function attemptQueuedAppleDownload(trackURL, codec, outputPath, onProgress) {
  try {
    if (typeof onProgress === "function") {
      onProgress(5);
    }

    var queuePayload = queueAppleProxyDownload(trackURL, codec);
    if (typeof onProgress === "function") {
      onProgress(10);
    }

    var waitResult = waitForAppleProxyJob(queuePayload.job_id, onProgress);
    if (waitResult.cancelled) {
      return cancelledDownloadResult();
    }
    if (!waitResult.success) {
      return failedDownloadResult(waitResult.error || "Apple downloader job failed", "api_error");
    }

    var statusPayload = waitResult.payload || {};
    var fileURL = DOWNLOAD_PROXY_BASE + "/file/" + encodeURIComponent(queuePayload.job_id);
    return downloadFromStreamURL(fileURL, outputPath, codec, statusPayload, onProgress, proxyHeaders());
  } catch (e) {
    return failedDownloadResult(e && e.message ? e.message : String(e), "api_error");
  }
}

function attemptDirectAppleDownload(trackURL, codec, outputPath, onProgress) {
  try {
    if (typeof onProgress === "function") {
      onProgress(8);
    }

    var payload = requestAppleProxyFallbackDownload(trackURL, codec);
    if (typeof onProgress === "function") {
      onProgress(15);
    }

    return downloadFromStreamURL(payload.stream_url, outputPath, codec, payload, onProgress);
  } catch (e) {
    return failedDownloadResult(e && e.message ? e.message : String(e), "api_error");
  }
}

function shouldRetryWithAppleFallback(result) {
  return !!(result && result.success !== true && result.error_type !== "cancelled");
}

function mergeDownloadFailures(primaryResult, fallbackResult) {
  var primaryMessage = primaryResult && primaryResult.error_message
    ? String(primaryResult.error_message)
    : "Primary Apple downloader failed";
  var fallbackMessage = fallbackResult && fallbackResult.error_message
    ? String(fallbackResult.error_message)
    : "Fallback Apple downloader failed";

  return {
    success: false,
    error_message: "app2 failed: " + primaryMessage + "; app failed: " + fallbackMessage,
    error_type: fallbackResult && fallbackResult.error_type
      ? fallbackResult.error_type
      : (primaryResult && primaryResult.error_type ? primaryResult.error_type : "api_error")
  };
}

function checkAvailability(isrc, trackName, artistName) {
  try {
    var resolvedURL = resolveTrackURLByAppleSearch(trackName, artistName, isrc);
    if (!resolvedURL) {
      return {
        available: false,
        reason: "not_found_on_apple_music"
      };
    }

    return {
      available: true,
      track_id: resolvedURL
    };
  } catch (e) {
    log.warn("checkAvailability failed:", e.message);
    return {
      available: false,
      reason: e.message || "apple_music_search_failed"
    };
  }
}

function download(trackID, quality, outputPath, onProgress) {
  try {
    if (utils.isDownloadCancelled()) {
      return cancelledDownloadResult();
    }

    var codec = normalizeRequestedCodec(quality);
    var trackURL = resolveDownloadTrackURL(trackID);
    if (!trackURL) {
      return {
        success: false,
        error_message: "Could not resolve Apple Music track URL",
        error_type: "not_found"
      };
    }

    var primaryResult = attemptDirectAppleDownload(trackURL, codec, outputPath, onProgress);
    if (primaryResult.success === true || primaryResult.error_type === "cancelled") {
      return primaryResult;
    }

    log.warn("Primary /v1/dl/app2 download failed, trying /v1/dl/app fallback:", primaryResult.error_message);

    if (!shouldRetryWithAppleFallback(primaryResult)) {
      return primaryResult;
    }

    var fallbackResult = attemptQueuedAppleDownload(trackURL, codec, outputPath, onProgress);
    if (fallbackResult.success === true || fallbackResult.error_type === "cancelled") {
      return fallbackResult;
    }

    return mergeDownloadFailures(primaryResult, fallbackResult);
  } catch (e) {
    return {
      success: false,
      error_message: e.message || String(e),
      error_type: "runtime_error"
    };
  }
}

// ============================================
// HELPERS
// ============================================

function decodeBase64URL(str) {
  str = str.replace(/-/g, "+").replace(/_/g, "/");
  while (str.length % 4 !== 0) {
    str += "=";
  }
  return atob(str);
}

function atob(str) {
  var chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=";
  var result = "";
  var i = 0;

  str = str.replace(/[^A-Za-z0-9+/=]/g, "");

  while (i < str.length) {
    var enc1 = chars.indexOf(str.charAt(i++));
    var enc2 = chars.indexOf(str.charAt(i++));
    var enc3 = chars.indexOf(str.charAt(i++));
    var enc4 = chars.indexOf(str.charAt(i++));

    var chr1 = (enc1 << 2) | (enc2 >> 4);
    var chr2 = ((enc2 & 15) << 4) | (enc3 >> 2);
    var chr3 = ((enc3 & 3) << 6) | enc4;

    result += String.fromCharCode(chr1);
    if (enc3 !== 64) result += String.fromCharCode(chr2);
    if (enc4 !== 64) result += String.fromCharCode(chr3);
  }

  return result;
}

// ============================================
// TTML LYRICS PARSER
// ============================================

/**
 * Parse a TTML timecode string to milliseconds.
 * Supports formats: "HH:MM:SS.fff", "MM:SS.fff", "SS.fff", "12.3s"
 */
function parseTTMLTime(value) {
  if (!value) return -1;
  value = value.trim();

  // Format: "12.3s" (seconds with s suffix)
  if (value.charAt(value.length - 1) === "s" || value.charAt(value.length - 1) === "S") {
    var secs = parseFloat(value.substring(0, value.length - 1));
    if (isNaN(secs)) return -1;
    return Math.round(secs * 1000);
  }

  var parts = value.split(":");
  var hours = 0, minutes = 0, seconds = 0;

  if (parts.length === 3) {
    hours = parseInt(parts[0], 10);
    minutes = parseInt(parts[1], 10);
    seconds = parseFloat(parts[2].replace(",", "."));
  } else if (parts.length === 2) {
    minutes = parseInt(parts[0], 10);
    seconds = parseFloat(parts[1].replace(",", "."));
  } else {
    seconds = parseFloat(parts[0].replace(",", "."));
  }

  if (isNaN(hours) || isNaN(minutes) || isNaN(seconds)) return -1;
  return Math.round((hours * 3600 + minutes * 60 + seconds) * 1000);
}

/**
 * Convert milliseconds to LRC inline timestamp: "<MM:SS.cc>"
 */
function msToInlineLRC(ms) {
  if (ms < 0) return "";
  var totalSec = ms / 1000;
  var min = Math.floor(totalSec / 60);
  var sec = totalSec - min * 60;
  var mm = min < 10 ? "0" + min : "" + min;
  var ss = sec < 10 ? "0" + sec.toFixed(2) : sec.toFixed(2);
  return "<" + mm + ":" + ss + ">";
}

/**
 * Extract attribute value from an XML tag string.
 * e.g. extractAttr('<p begin="00:05.100" end="00:08.200">', 'begin') → '00:05.100'
 */
function extractAttr(tag, attrName) {
  // Handle both ns:attr and plain attr
  var patterns = [
    new RegExp('\\b' + attrName + '="([^"]*)"'),
    new RegExp('\\b' + attrName + "='([^']*)'")
  ];
  for (var i = 0; i < patterns.length; i++) {
    var m = tag.match(patterns[i]);
    if (m) return m[1];
  }
  return null;
}

/**
 * Decode XML entities in text.
 */
function decodeXMLEntities(text) {
  if (!text) return "";
  return text
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&#(\d+);/g, function (m, code) {
      return String.fromCharCode(parseInt(code, 10));
    })
    .replace(/&#x([0-9a-fA-F]+);/g, function (m, code) {
      return String.fromCharCode(parseInt(code, 16));
    });
}

/**
 * Strip all XML tags from a string, returning only text content.
 */
function stripXMLTags(str) {
  return str.replace(/<[^>]+>/g, "");
}

/**
 * Extract a nested <span> element with a specific ttm:role attribute.
 * Handles arbitrary nesting depth (unlike simple regex).
 * Returns { start, end, inner, openTag } or null if not found.
 */
function extractNestedSpan(str, role) {
  var searchStr = 'ttm:role="' + role + '"';
  var altSearchStr = "ttm:role='" + role + "'";
  var idx = str.indexOf(searchStr);
  if (idx === -1) idx = str.indexOf(altSearchStr);
  if (idx === -1) return null;

  // Find the beginning of this <span> tag
  var tagStart = str.lastIndexOf("<span", idx);
  if (tagStart === -1) return null;

  // Find the end of the opening tag
  var tagEnd = str.indexOf(">", idx);
  if (tagEnd === -1) return null;
  tagEnd++; // past the '>'

  var openTag = str.substring(tagStart, tagEnd);
  var contentStart = tagEnd;

  // Track nesting to find matching </span>
  var depth = 1;
  var pos = contentStart;
  while (pos < str.length && depth > 0) {
    var nextOpen = str.indexOf("<span", pos);
    var nextClose = str.indexOf("</span>", pos);

    if (nextClose === -1) break;

    if (nextOpen !== -1 && nextOpen < nextClose) {
      depth++;
      pos = nextOpen + 5; // past "<span"
    } else {
      depth--;
      if (depth === 0) {
        return {
          start: tagStart,
          end: nextClose + 7, // past "</span>"
          inner: str.substring(contentStart, nextClose),
          openTag: openTag
        };
      }
      pos = nextClose + 7;
    }
  }

  return null;
}

/**
 * Collect all role-based spans (x-translation, x-roman) from content.
 * These are non-nested spans with ttm:role attribute.
 * Returns [{ role, lang, text }]
 */
function collectRoleSpans(content) {
  var results = [];
  var re = /<span\s+([^>]*ttm:role="(x-translation|x-roman)"[^>]*)>([^<]*)<\/span>/gi;
  var m;
  while ((m = re.exec(content)) !== null) {
    var lang = "";
    var langM = m[1].match(/xml:lang="([^"]*)"/);
    if (langM) lang = langM[1].toLowerCase();
    results.push({
      role: m[2],
      lang: lang,
      text: decodeXMLEntities(m[3]).trim()
    });
  }
  return results;
}

/**
 * Remove all role-based spans from content string.
 * This safely removes spans like <span ttm:role="x-translation"...>text</span>
 * without affecting other spans.
 */
function removeRoleSpans(content) {
  return content.replace(/<span\s+[^>]*ttm:role="(?:x-translation|x-roman)"[^>]*>[^<]*<\/span>/gi, "");
}

/**
 * Parse TTML XML into structured lyrics data.
 *
 * Returns: {
 *   lines: [{ startMs, endMs, syllables: [{startMs, endMs, text}], agent, key,
 *             translation: "...", roman: "...",
 *             bgSyllables: [{startMs, endMs, text}], bgTranslation: "...", bgRoman: "..." }],
 *   headerTranslations: { "L1": "translated text", ... },
 *   headerTransliterations: { "L1": "romanized text", ... },
 *   timingMode: "Word" | "Line"
 * }
 */
function parseTTML(ttml) {
  if (!ttml) return null;

  var result = {
    lines: [],
    headerTranslations: {},
    headerTransliterations: {},
    timingMode: "Word"
  };

  // Detect timing mode from root <tt> element
  var ttMatch = ttml.match(/<tt\s[^>]*>/);
  if (ttMatch) {
    var timing = extractAttr(ttMatch[0], "itunes:timing");
    if (timing) result.timingMode = timing;
  }

  // ---- Parse header translations/transliterations ----
  var headMatch = ttml.match(/<head[^>]*>([\s\S]*?)<\/head>/i);
  if (headMatch) {
    var headContent = headMatch[1];

    // Extract translations from <iTunesMetadata> or similar container
    // <translation ...><text for="L1">translated text</text></translation>
    var translationBlocks = headContent.match(/<translation\b[^>]*>([\s\S]*?)<\/translation>/gi);
    if (translationBlocks) {
      for (var ti = 0; ti < translationBlocks.length; ti++) {
        var block = translationBlocks[ti];
        var blockLang = extractAttr(block.match(/<translation[^>]*>/)[0], "xml:lang") || "";

        // Check if this translation matches the user's preferred language
        if (state.lyricsTranslation && blockLang.toLowerCase().indexOf(state.lyricsTranslation) !== 0) {
          continue; // Skip non-matching languages
        }

        var textEntries = block.match(/<text\b[^>]*>[\s\S]*?<\/text>/gi);
        if (textEntries) {
          for (var tj = 0; tj < textEntries.length; tj++) {
            var textTag = textEntries[tj];
            var forKey = extractAttr(textTag.match(/<text[^>]*>/)[0], "for");
            if (forKey) {
              // Strip inner tags and get plain text
              var innerText = textTag.replace(/^<text[^>]*>/, "").replace(/<\/text>$/, "");
              // Handle background vocal text inside <span ttm:role="x-bg">
              var bgMatch = innerText.match(/<span[^>]*ttm:role="x-bg"[^>]*>([\s\S]*?)<\/span>/i);
              var mainText = innerText;
              if (bgMatch) {
                mainText = innerText.replace(bgMatch[0], "");
              }
              result.headerTranslations[forKey] = decodeXMLEntities(stripXMLTags(mainText)).trim();
            }
          }
        }
      }
    }

    // Extract transliterations
    var translitBlocks = headContent.match(/<transliteration\b[^>]*>([\s\S]*?)<\/transliteration>/gi);
    if (translitBlocks) {
      for (var ri = 0; ri < translitBlocks.length; ri++) {
        var rBlock = translitBlocks[ri];
        var rBlockLang = extractAttr(rBlock.match(/<transliteration[^>]*>/)[0], "xml:lang") || "";

        if (state.lyricsPronunciation && rBlockLang.toLowerCase().indexOf(state.lyricsPronunciation) !== 0) {
          continue;
        }

        var rTextEntries = rBlock.match(/<text\b[^>]*>[\s\S]*?<\/text>/gi);
        if (rTextEntries) {
          for (var rj = 0; rj < rTextEntries.length; rj++) {
            var rTextTag = rTextEntries[rj];
            var rForKey = extractAttr(rTextTag.match(/<text[^>]*>/)[0], "for");
            if (rForKey) {
              var rInnerText = rTextTag.replace(/^<text[^>]*>/, "").replace(/<\/text>$/, "");
              var rBgMatch = rInnerText.match(/<span[^>]*ttm:role="x-bg"[^>]*>([\s\S]*?)<\/span>/i);
              var rMainText = rInnerText;
              if (rBgMatch) {
                rMainText = rInnerText.replace(rBgMatch[0], "");
              }
              result.headerTransliterations[rForKey] = decodeXMLEntities(stripXMLTags(rMainText)).trim();
            }
          }
        }
      }
    }
  }

  // ---- Parse body: extract <p> lines ----
  var bodyMatch = ttml.match(/<body[^>]*>([\s\S]*?)<\/body>/i);
  if (!bodyMatch) return result;

  var bodyContent = bodyMatch[1];

  // Extract all <p> elements (may be nested in <div>)
  var pPattern = /<p\s([^>]*)>([\s\S]*?)<\/p>/gi;
  var pMatch;
  while ((pMatch = pPattern.exec(bodyContent)) !== null) {
    var pAttrs = pMatch[1];
    var pContent = pMatch[2];

    var lineStartMs = parseTTMLTime(extractAttr("<p " + pAttrs + ">", "begin"));
    var lineEndMs = parseTTMLTime(extractAttr("<p " + pAttrs + ">", "end"));
    var lineKey = extractAttr("<p " + pAttrs + ">", "itunes:key") || "";
    var lineAgent = extractAttr("<p " + pAttrs + ">", "ttm:agent") || "";

    var line = {
      startMs: lineStartMs,
      endMs: lineEndMs,
      key: lineKey,
      agent: lineAgent,
      syllables: [],
      translation: "",
      roman: "",
      bgSyllables: [],
      bgTranslation: "",
      bgRoman: "",
      plainText: ""
    };

    // First, extract background vocal span using nesting-aware extraction.
    // bg spans can contain nested <span> tags, so regex alone won't work.
    var mainContent = pContent;
    var bgContent = "";
    var bgExtracted = extractNestedSpan(pContent, "x-bg");
    if (bgExtracted) {
      bgContent = bgExtracted.inner;
      mainContent = pContent.substring(0, bgExtracted.start) +
                    pContent.substring(bgExtracted.end);
    }

    // Collect all role-based spans from main content (don't modify while iterating).
    var roleSpans = collectRoleSpans(mainContent);
    for (var ri = 0; ri < roleSpans.length; ri++) {
      var rs = roleSpans[ri];
      if (rs.role === "x-translation") {
        if (!state.lyricsTranslation || rs.lang.indexOf(state.lyricsTranslation) === 0) {
          line.translation = rs.text;
        }
      } else if (rs.role === "x-roman") {
        if (!state.lyricsPronunciation || rs.lang.indexOf(state.lyricsPronunciation) === 0) {
          line.roman = rs.text;
        }
      }
    }

    // Remove role spans from mainContent for syllable extraction
    mainContent = removeRoleSpans(mainContent);

    // Extract timed syllable spans from main content
    var timedSpanRe = /<span\s+([^>]*)>([^<]*)<\/span>/gi;
    var tsMatch;
    var tsPrevEnd = -1;
    while ((tsMatch = timedSpanRe.exec(mainContent)) !== null) {
      // Apple separates words with whitespace text nodes between the word
      // spans. The regex only captures span contents, so preserve that gap as
      // a trailing space on the previous syllable; otherwise words run
      // together (e.g. "Brownguiltyeyes"). Syllables within a single word have
      // no gap and stay joined.
      if (tsPrevEnd >= 0 && line.syllables.length > 0) {
        var gap = decodeXMLEntities(mainContent.substring(tsPrevEnd, tsMatch.index));
        if (/\s/.test(gap)) {
          var prevSyl = line.syllables[line.syllables.length - 1];
          if (!/\s$/.test(prevSyl.text)) prevSyl.text += " ";
        }
      }
      tsPrevEnd = timedSpanRe.lastIndex;

      var sTag = "<span " + tsMatch[1] + ">";
      var sBegin = parseTTMLTime(extractAttr(sTag, "begin"));
      var sEnd = parseTTMLTime(extractAttr(sTag, "end"));
      var sText = decodeXMLEntities(tsMatch[2]);

      if (sBegin >= 0) {
        line.syllables.push({ startMs: sBegin, endMs: sEnd, text: sText });
      } else if (sText.trim()) {
        // Untimed span — just text
        line.syllables.push({ startMs: -1, endMs: -1, text: sText });
      }
    }

    // If no syllable spans found, get plain text from content
    if (line.syllables.length === 0) {
      var cleanText = decodeXMLEntities(stripXMLTags(mainContent)).trim();
      cleanText = cleanText.replace(/\s+/g, " ");
      if (cleanText) {
        line.plainText = cleanText;
      }
    } else {
      // Build plain text from syllables
      var pt = [];
      for (var si = 0; si < line.syllables.length; si++) {
        pt.push(line.syllables[si].text);
      }
      line.plainText = pt.join("").replace(/\s+/g, " ").trim();
    }

    // Process background vocals
    if (bgContent) {
      var bgRoles = collectRoleSpans(bgContent);
      for (var bri = 0; bri < bgRoles.length; bri++) {
        var br = bgRoles[bri];
        if (br.role === "x-translation") {
          if (!state.lyricsTranslation || br.lang.indexOf(state.lyricsTranslation) === 0) {
            line.bgTranslation = br.text;
          }
        } else if (br.role === "x-roman") {
          if (!state.lyricsPronunciation || br.lang.indexOf(state.lyricsPronunciation) === 0) {
            line.bgRoman = br.text;
          }
        }
      }

      var bgClean = removeRoleSpans(bgContent);
      var bgTimedRe = /<span\s+([^>]*)>([^<]*)<\/span>/gi;
      var bgTsMatch;
      var bgPrevEnd = -1;
      while ((bgTsMatch = bgTimedRe.exec(bgClean)) !== null) {
        if (bgPrevEnd >= 0 && line.bgSyllables.length > 0) {
          var bgGap = decodeXMLEntities(bgClean.substring(bgPrevEnd, bgTsMatch.index));
          if (/\s/.test(bgGap)) {
            var prevBg = line.bgSyllables[line.bgSyllables.length - 1];
            if (!/\s$/.test(prevBg.text)) prevBg.text += " ";
          }
        }
        bgPrevEnd = bgTimedRe.lastIndex;

        var bgTag = "<span " + bgTsMatch[1] + ">";
        var bgBegin = parseTTMLTime(extractAttr(bgTag, "begin"));
        var bgEnd = parseTTMLTime(extractAttr(bgTag, "end"));
        var bgText = decodeXMLEntities(bgTsMatch[2]);
        if (bgBegin >= 0) {
          line.bgSyllables.push({ startMs: bgBegin, endMs: bgEnd, text: bgText });
        }
      }
    }

    // Fall back to header translations/transliterations if inline not found
    if (!line.translation && lineKey && result.headerTranslations[lineKey]) {
      line.translation = result.headerTranslations[lineKey];
    }
    if (!line.roman && lineKey && result.headerTransliterations[lineKey]) {
      line.roman = result.headerTransliterations[lineKey];
    }

    result.lines.push(line);
  }

  return result;
}

/**
 * Convert parsed TTML data to ExtLyricsResult format.
 * Produces enhanced LRC with inline timestamps for word-by-word sync.
 */
function ttmlToLyricsResult(parsed) {
  if (!parsed || !parsed.lines || parsed.lines.length === 0) {
    return null;
  }

  var lines = [];
  var plainParts = [];
  var hasTranslation = false;
  var hasRoman = false;
  var translationLines = [];
  var romanLines = [];

  for (var i = 0; i < parsed.lines.length; i++) {
    var line = parsed.lines[i];
    if (line.startMs < 0) continue;

    var words = "";

    // Build word-by-word content with inline timestamps
    if (line.syllables.length > 0) {
      var parts = [];
      for (var s = 0; s < line.syllables.length; s++) {
        var syl = line.syllables[s];
        var chunk = "";
        if (syl.startMs >= 0) {
          chunk += msToInlineLRC(syl.startMs);
        }
        chunk += syl.text;
        if (syl.endMs >= 0 && s === line.syllables.length - 1) {
          // Add end time marker for last syllable
          chunk += msToInlineLRC(syl.endMs);
        }
        parts.push(chunk);
      }
      words = parts.join("");
    } else {
      words = line.plainText || "";
    }

    if (!words.trim()) continue;

    // Add background vocals as [bg:...] tag
    if (line.bgSyllables.length > 0) {
      var bgParts = [];
      for (var b = 0; b < line.bgSyllables.length; b++) {
        var bgSyl = line.bgSyllables[b];
        var bgChunk = "";
        if (bgSyl.startMs >= 0) {
          bgChunk += msToInlineLRC(bgSyl.startMs);
        }
        bgChunk += bgSyl.text;
        if (bgSyl.endMs >= 0 && b === line.bgSyllables.length - 1) {
          bgChunk += msToInlineLRC(bgSyl.endMs);
        }
        bgParts.push(bgChunk);
      }
      words += "\n[bg:" + bgParts.join("") + "]";
    }

    lines.push({
      startTimeMs: line.startMs,
      words: words,
      endTimeMs: line.endMs
    });

    plainParts.push(line.plainText || words);

    // Collect translation lines
    if (line.translation && state.lyricsTranslation) {
      hasTranslation = true;
      translationLines.push({
        startTimeMs: line.startMs,
        words: line.translation,
        endTimeMs: line.endMs
      });
    }

    // Collect pronunciation/romanization lines
    if (line.roman && state.lyricsPronunciation) {
      hasRoman = true;
      romanLines.push({
        startTimeMs: line.startMs,
        words: line.roman,
        endTimeMs: line.endMs
      });
    }
  }

  if (lines.length === 0) return null;

  // Append translation lines after main lyrics (with blank separator)
  if (hasTranslation && translationLines.length > 0) {
    // Add separator
    lines.push({ startTimeMs: 999999999, words: "", endTimeMs: 999999999 });
    for (var tl = 0; tl < translationLines.length; tl++) {
      lines.push(translationLines[tl]);
    }
  }

  // Append pronunciation lines
  if (hasRoman && romanLines.length > 0) {
    lines.push({ startTimeMs: 999999999, words: "", endTimeMs: 999999999 });
    for (var rl = 0; rl < romanLines.length; rl++) {
      lines.push(romanLines[rl]);
    }
  }

  return {
    lines: lines,
    syncType: "LINE_SYNCED",
    instrumental: false,
    plainLyrics: plainParts.join("\n"),
    provider: "Apple Music"
  };
}

// ============================================
// LYRICS PROVIDER
// ============================================

/**
 * Fetch lyrics for a track. Called by the extension runtime.
 * @param {string} trackName
 * @param {string} artistName
 * @param {string} albumName
 * @param {number} durationSec
 * @returns {Object|null} ExtLyricsResult or null
 */
function fetchLyrics(trackName, artistName, albumName, durationSec) {
  if (!state.mediaUserToken) {
    log.debug("fetchLyrics: No Media User Token configured, skipping.");
    return null;
  }

  log.info("fetchLyrics: Searching for", trackName, "by", artistName);

  // Search for the track on Apple Music
  var trackId = findTrackId(trackName, artistName, albumName, durationSec);
  if (!trackId) {
    log.info("fetchLyrics: Could not find track on Apple Music.");
    return null;
  }

  log.info("fetchLyrics: Found Apple Music track ID:", trackId);

  // Fetch syllable-lyrics
  var lyricsData = apiGetWithUserToken("songs/" + trackId + "/syllable-lyrics");
  if (!lyricsData || !lyricsData.data || lyricsData.data.length === 0) {
    log.info("fetchLyrics: No syllable lyrics available for track", trackId);

    // Fall back to regular lyrics endpoint
    lyricsData = apiGetWithUserToken("songs/" + trackId + "/lyrics");
    if (!lyricsData || !lyricsData.data || lyricsData.data.length === 0) {
      log.info("fetchLyrics: No lyrics available for track", trackId);
      return null;
    }
  }

  var ttml = null;
  var attrs = lyricsData.data[0].attributes;
  if (attrs) {
    ttml = attrs.ttml || null;
  }

  if (!ttml) {
    log.info("fetchLyrics: No TTML content in lyrics response.");
    return null;
  }

  log.info("fetchLyrics: Got TTML lyrics (" + ttml.length + " bytes), parsing...");

  // Parse the TTML
  var parsed = parseTTML(ttml);
  if (!parsed || parsed.lines.length === 0) {
    log.info("fetchLyrics: TTML parsing returned no lines.");
    return null;
  }

  log.info("fetchLyrics: Parsed " + parsed.lines.length + " lines (timing: " + parsed.timingMode + ")");

  // Convert to ExtLyricsResult
  var result = ttmlToLyricsResult(parsed);
  if (result) {
    log.info("fetchLyrics: Returning " + result.lines.length + " lyrics lines" +
      (state.lyricsTranslation ? " (with translation)" : "") +
      (state.lyricsPronunciation ? " (with pronunciation)" : ""));
  }

  return result;
}

/**
 * Search Apple Music and find the best matching track ID.
 */
function findTrackId(trackName, artistName, albumName, durationSec) {
  var searchTerm = (trackName || "") + " " + (artistName || "");
  searchTerm = searchTerm.trim();
  if (!searchTerm) return null;

  try {
    var searchData = apiGet(
      "search?term=" + encodeURIComponent(searchTerm) + "&types=songs&limit=10"
    );
    var songs = searchData.results && searchData.results.songs
      ? searchData.results.songs.data
      : [];

    if (songs.length === 0) return null;

    // Score each result for best match
    var bestScore = -1;
    var bestId = null;

    for (var i = 0; i < songs.length; i++) {
      var attr = songs[i].attributes || {};
      var score = 0;

      // Title match
      var titleSim = matching.compareStrings(trackName || "", attr.name || "");
      score += titleSim * 50;

      // Artist match
      var artistSim = matching.compareStrings(artistName || "", attr.artistName || "");
      score += artistSim * 30;

      // Album match (if provided)
      if (albumName) {
        var albumSim = matching.compareStrings(albumName, attr.albumName || "");
        score += albumSim * 10;
      }

      // Duration match
      if (durationSec > 0 && attr.durationInMillis) {
        var durationMatch = matching.compareDuration(
          durationSec * 1000,
          attr.durationInMillis
        );
        score += durationMatch * 10;
      }

      if (score > bestScore) {
        bestScore = score;
        bestId = songs[i].id;
      }
    }

    // Require a minimum match quality
    if (bestScore < 40) {
      log.debug("findTrackId: Best score too low (" + bestScore.toFixed(1) + "), rejecting match.");
      return null;
    }

    return bestId;
  } catch (e) {
    log.debug("findTrackId: Search failed:", e.message);
    return null;
  }
}

// ============================================
// REGISTER EXTENSION
// ============================================

registerExtension({
  initialize: initialize,
  cleanup: cleanup,
  customSearch: customSearch,
  handleUrl: handleURL,
  getTrack: getTrack,
  getAlbum: getAlbum,
  getArtist: getArtist,
  getPlaylist: getPlaylist,
  searchTracks: searchTracks,
  enrichTrack: enrichTrack,
  fetchLyrics: fetchLyrics,
  checkAvailability: checkAvailability
});

log.info("Apple Music Extension loaded!");
