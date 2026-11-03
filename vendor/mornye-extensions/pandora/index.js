var CONFIG = {
  apiBaseURL: "https://api.zarz.moe",
  downloadPath: "/v1/dl/pan",
  songLinkBaseURL: "https://api.song.link/v1-alpha.1/links",
  deezerBaseURL: "https://api.deezer.com",
  pandoraBaseURL: "https://www.pandora.com",
  userCountry: "US"
};

function initialize(settings) {
  settings = settings || {};

  var apiBase = String(settings.apiBaseUrl || "").trim();
  if (apiBase) {
    CONFIG.apiBaseURL = normalizeSecureURL(apiBase).replace(/\/+$/, "");
  }

  var songLinkBase = String(settings.songLinkBaseUrl || "").trim();
  if (songLinkBase) {
    CONFIG.songLinkBaseURL = normalizeSecureURL(songLinkBase).replace(/\/+$/, "");
  }

  return true;
}

function cleanup() {
  return true;
}

function normalizeSecureURL(value) {
  var text = String(value || "").trim();
  if (!text) return "";
  if (/^http:\/\//i.test(text)) {
    return text.replace(/^http:\/\//i, "https://");
  }
  return text;
}

function mergeHeaders(base, extra) {
  var merged = {};
  var key;

  base = base || {};
  extra = extra || {};

  for (key in base) {
    if (base.hasOwnProperty(key)) {
      merged[key] = base[key];
    }
  }

  for (key in extra) {
    if (extra.hasOwnProperty(key)) {
      merged[key] = extra[key];
    }
  }

  return merged;
}

function appUserAgent() {
  if (utils && typeof utils.appUserAgent === "function") {
    return String(utils.appUserAgent() || "").trim() || "SpotiFLAC-Mobile";
  }
  return "SpotiFLAC-Mobile";
}

function userAgentForURL(url) {
  var text = String(url || "").trim().toLowerCase();
  if (text.indexOf("https://api.zarz.moe") === 0 || text.indexOf("http://api.zarz.moe") === 0) {
    return appUserAgent();
  }
  return utils.randomUserAgent();
}

function getJSON(url, headers) {
  var response = http.get(
    url,
    mergeHeaders(
      {
        "Accept": "application/json",
        "User-Agent": userAgentForURL(url)
      },
      headers
    )
  );

  if (!response || response.error) {
    throw new Error(response && response.error ? response.error : "request failed");
  }
  if (response.statusCode !== 200) {
    throw new Error("HTTP " + response.statusCode + " for " + url);
  }

  return JSON.parse(response.body);
}

function postJSON(url, body, headers) {
  var response = http.post(
    url,
    JSON.stringify(body),
    mergeHeaders(
      {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": userAgentForURL(url)
      },
      headers
    )
  );

  if (!response || response.error) {
    throw new Error(response && response.error ? response.error : "request failed");
  }
  if (response.statusCode !== 200) {
    throw new Error("HTTP " + response.statusCode + " for " + url);
  }

  return JSON.parse(response.body);
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

function titleCaseFromSlug(value) {
  value = String(value || "").trim();
  if (!value) return "";

  var cleaned = value
    .replace(/[-_]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  if (!cleaned) return "";

  return cleaned.replace(/\b\w/g, function (ch) {
    return ch.toUpperCase();
  });
}

function normalizePandoraID(value) {
  var raw = String(value || "").trim();
  if (!raw) return "";

  try {
    raw = decodeURIComponent(raw);
  } catch (e) {
  }

  var match = raw.match(/\b(TR|AL|AR|PL|ST):[A-Za-z0-9:]+\b/i);
  if (match) {
    return match[0].toUpperCase();
  }

  var prettyMatch = raw.match(/(?:^|[\/?=&])((TR|AL|AR|PL|ST)[A-Za-z0-9]+)(?=$|[\/?&#])/i);
  return prettyMatch ? prettyMatch[1] : "";
}

function extractPandoraTrackID(value) {
  var id = normalizePandoraID(value);
  return /^TR(?::)?/i.test(id) ? id : "";
}

function extractPandoraAlbumID(value) {
  var id = normalizePandoraID(value);
  return /^AL(?::)?/i.test(id) ? id : "";
}

function buildPandoraURL(id) {
  return CONFIG.pandoraBaseURL + "/" + String(id || "").trim();
}

function stripURLQuery(url) {
  return String(url || "").replace(/[?#].*$/, "");
}

function normalizePandoraWebURL(url) {
  var normalized = stripURLQuery(normalizeSecureURL(url));
  var parsed = tryParseURL(normalized);
  if (!parsed || parsed.hostname.toLowerCase().indexOf("pandora.com") === -1) {
    return normalized;
  }

  var segments = parsed.pathname.replace(/^\/+|\/+$/g, "").split("/");
  if (!segments.length || !segments[0]) {
    return normalized;
  }
  if (segments[0] === "artist" || segments[0] === "playlist") {
    return normalized;
  }

  var lastSegment = segments[segments.length - 1] || "";
  if ((/^TR/i.test(lastSegment) && segments.length >= 4) || (/^AL/i.test(lastSegment) && segments.length >= 3)) {
    return CONFIG.pandoraBaseURL + "/artist/" + segments.join("/");
  }

  return normalized;
}

function normalizePandoraCanonicalURL(input, pandoraID) {
  var normalized = normalizeSecureURL(String(input || "").trim());
  if (normalized.indexOf("pandora.com/") >= 0 && extractPandoraTrackID(normalized)) {
    return normalizePandoraWebURL(normalized);
  }
  if (normalized.indexOf("pandora.com/") >= 0 && extractPandoraAlbumID(normalized)) {
    return normalizePandoraWebURL(normalized);
  }
  return buildPandoraURL(pandoraID);
}

function tryParseURL(url) {
  if (!url) return null;

  if (typeof URL !== "undefined") {
    try {
      var parsed = new URL(url);
      return {
        hostname: parsed.hostname || "",
        pathname: parsed.pathname || ""
      };
    } catch (e) {
    }
  }

  var match = String(url || "").match(/^https?:\/\/([^\/]+)(\/[^?#]*)?/i);
  if (!match) {
    return null;
  }

  return {
    hostname: match[1] || "",
    pathname: match[2] || "/"
  };
}

function isPandoraAppLink(url) {
  var parsed = tryParseURL(url);
  if (!parsed || !parsed.hostname) return false;
  return parsed.hostname.toLowerCase() === "pandora.app.link";
}

function extractPandoraURLFromAppLinkHTML(html) {
  var body = String(html || "");
  if (!body) return "";

  var matches = body.match(/https?:\/\/(?:www\.)?pandora\.com\/[^"'<>\\\s]+/gi) || [];
  for (var i = 0; i < matches.length; i++) {
    var candidate = normalizeSecureURL(matches[i]).replace(/&amp;/gi, "&");
    if (candidate.indexOf("pandora.com/") >= 0) {
      return candidate;
    }
  }

  var encodedIdMatch = body.match(/pandoraId=([^"'&<>\s]+)/i);
  if (encodedIdMatch && encodedIdMatch[1]) {
    var decoded = encodedIdMatch[1];
    try {
      decoded = decodeURIComponent(decoded);
    } catch (e) {
    }

    var pandoraID = normalizePandoraID(decoded);
    if (pandoraID) {
      return buildPandoraURL(pandoraID);
    }
  }

  return "";
}

function resolvePandoraAppLink(url) {
  var response = http.get(normalizeSecureURL(url), {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "User-Agent": appUserAgent()
  });

  if (!response || response.error) {
    throw new Error(response && response.error ? response.error : "Pandora app link request failed");
  }

  if (
    response.url &&
    response.url.indexOf("pandora.com/") !== -1 &&
    response.url.indexOf("pandora.app.link") === -1
  ) {
    return normalizeSecureURL(response.url);
  }

  if (response.statusCode !== 200) {
    throw new Error("Pandora app link returned HTTP " + response.statusCode);
  }

  var resolvedURL = extractPandoraURLFromAppLinkHTML(response.body || "");
  if (!resolvedURL) {
    throw new Error("Could not resolve Pandora app link");
  }

  return resolvedURL;
}

function normalizePandoraInput(input) {
  var normalized = String(input || "").trim();
  if (!normalized) return "";

  if (isPandoraAppLink(normalized)) {
    return resolvePandoraAppLink(normalized);
  }

  return normalized;
}

function parsePandoraPrettyURL(url) {
  if (!url) return null;

  try {
    var parsed = tryParseURL(normalizePandoraWebURL(normalizePandoraInput(url)));
    if (!parsed || parsed.hostname.toLowerCase().indexOf("pandora.com") === -1) {
      return null;
    }

    var segments = parsed.pathname.replace(/^\/+|\/+$/g, "").split("/");
    if (!segments.length) return null;

    if (segments[0] === "artist") {
      if (segments.length >= 5) {
        return {
          type: "track",
          artistName: titleCaseFromSlug(segments[1]),
          albumName: titleCaseFromSlug(segments[2]),
          trackName: titleCaseFromSlug(segments[3])
        };
      }

      if (segments.length >= 4 && /^AL/i.test(segments[3])) {
        return {
          type: "album",
          artistName: titleCaseFromSlug(segments[1]),
          albumName: titleCaseFromSlug(segments[2])
        };
      }

      if (segments.length >= 2) {
        return {
          type: "artist",
          artistName: titleCaseFromSlug(segments[1])
        };
      }
    }

    if (segments[0] === "playlist") {
      return {
        type: "playlist",
        playlistName: titleCaseFromSlug(segments[1] || "Pandora Playlist")
      };
    }
  } catch (e) {
  }

  return null;
}

function resolveSongLink(url) {
  return getJSON(
    CONFIG.songLinkBaseURL +
      "?url=" +
      encodeURIComponent(url) +
      "&userCountry=" +
      encodeURIComponent(CONFIG.userCountry)
  );
}

function extractPandoraURLFromSongLink(songLinkData) {
  var linksByPlatform = (songLinkData && songLinkData.linksByPlatform) || {};
  var pandoraLink = linksByPlatform.pandora;
  if (!pandoraLink || !pandoraLink.url) {
    return "";
  }

  return normalizeSecureURL(pandoraLink.url);
}

function extractEntityFromSongLink(songLinkData) {
  if (!songLinkData) return null;

  var uniqueID = songLinkData.entityUniqueId;
  var entities = songLinkData.entitiesByUniqueId || {};
  if (!uniqueID || !entities[uniqueID]) {
    return null;
  }

  return entities[uniqueID];
}

function extractDeezerTrackIDFromSongLink(songLinkData) {
  var linksByPlatform = (songLinkData && songLinkData.linksByPlatform) || {};
  var deezer = linksByPlatform.deezer;
  if (deezer && deezer.url) {
    var match = String(deezer.url).match(/deezer\.com\/(?:[a-z]{2}\/)?track\/(\d+)/i);
    if (match) {
      return match[1];
    }
  }

  return "";
}

function fetchDeezerTrack(trackID) {
  if (!trackID) return null;

  try {
    return getJSON(CONFIG.deezerBaseURL + "/track/" + encodeURIComponent(trackID));
  } catch (e) {
    log.debug("[Pandora] Deezer enrichment failed:", e.message);
    return null;
  }
}

function fetchDeezerAlbum(albumID) {
  if (!albumID) return null;

  try {
    return getJSON(CONFIG.deezerBaseURL + "/album/" + encodeURIComponent(albumID));
  } catch (e) {
    log.debug("[Pandora] Deezer album enrichment failed:", e.message);
    return null;
  }
}

function normalizeAlbumArtistFromDeezer(album, track) {
  if (album && album.artist && album.artist.name) {
    return String(album.artist.name);
  }

  if (track && track.artist && track.artist.name) {
    return String(track.artist.name);
  }

  return "";
}

function extractDeezerGenre(album) {
  var genres = album && album.genres && album.genres.data;
  if (!genres || !genres.length) return "";

  var names = [];
  for (var i = 0; i < genres.length; i++) {
    if (genres[i] && genres[i].name) {
      names.push(String(genres[i].name));
    }
  }

  return names.join(", ");
}

function extractDeezerComposer(track) {
  if (!track || !track.contributors || !track.contributors.length) {
    return "";
  }

  var names = [];
  for (var i = 0; i < track.contributors.length; i++) {
    var contributor = track.contributors[i];
    if (!contributor || !contributor.name) continue;

    var role = String(contributor.role || "").toLowerCase();
    if (role === "composer" || role === "author" || role === "writer") {
      names.push(String(contributor.name));
    }
  }

  return names.join(", ");
}

function normalizeArtistsFromDeezer(track) {
  if (!track) return "";

  if (track.contributors && track.contributors.length) {
    var names = [];
    for (var i = 0; i < track.contributors.length; i++) {
      if (track.contributors[i] && track.contributors[i].name) {
        names.push(track.contributors[i].name);
      }
    }
    if (names.length) {
      return names.join(", ");
    }
  }

  if (track.artist && track.artist.name) {
    return String(track.artist.name);
  }

  return "";
}

function resolvePandoraTrack(input) {
  input = normalizePandoraInput(input);
  var pandoraID = extractPandoraTrackID(input);
  if (!pandoraID) {
    throw new Error("Could not resolve Pandora track ID");
  }

  var sourceURL = String(input || "").trim();
  if (!sourceURL || sourceURL.indexOf("pandora.com/") === -1) {
    sourceURL = buildPandoraURL(pandoraID);
  }

  var pretty = parsePandoraPrettyURL(input);
  var songLinkData = null;
  var entity = null;
  var deezerTrack = null;
  var deezerAlbum = null;
  var pandoraURL = normalizePandoraCanonicalURL(sourceURL, pandoraID);

  try {
    songLinkData = resolveSongLink(pandoraURL);
    entity = extractEntityFromSongLink(songLinkData);

    var resolvedPandoraURL = extractPandoraURLFromSongLink(songLinkData);
    if (resolvedPandoraURL) {
      pandoraURL = normalizePandoraCanonicalURL(resolvedPandoraURL, pandoraID);
    }

    var resolvedID = extractPandoraTrackID(pandoraURL);
    if (resolvedID) {
      pandoraID = resolvedID;
    }

    if (entity && entity.type !== "song") {
      throw new Error("Resolved entity is not a Pandora track");
    }

    var deezerTrackID = extractDeezerTrackIDFromSongLink(songLinkData);
    deezerTrack = fetchDeezerTrack(deezerTrackID);
    if (deezerTrack && deezerTrack.album && deezerTrack.album.id) {
      deezerAlbum = fetchDeezerAlbum(deezerTrack.album.id);
    }
  } catch (e) {
    if (!pretty) {
      throw e;
    }
  }

  return {
    pandoraID: pandoraID,
    pandoraURL: pandoraURL,
    entity: entity,
    deezerTrack: deezerTrack,
    deezerAlbum: deezerAlbum,
    pretty: pretty
  };
}

function resolvePandoraAlbum(input) {
  input = normalizePandoraInput(input);
  var pandoraID = extractPandoraAlbumID(input);
  if (!pandoraID) {
    throw new Error("Could not resolve Pandora album ID");
  }

  var sourceURL = String(input || "").trim();
  if (!sourceURL || sourceURL.indexOf("pandora.com/") === -1) {
    sourceURL = buildPandoraURL(pandoraID);
  }

  var pretty = parsePandoraPrettyURL(input);
  var songLinkData = null;
  var entity = null;
  var pandoraURL = normalizePandoraCanonicalURL(sourceURL, pandoraID);

  try {
    songLinkData = resolveSongLink(pandoraURL);
    entity = extractEntityFromSongLink(songLinkData);

    var resolvedPandoraURL = extractPandoraURLFromSongLink(songLinkData);
    if (resolvedPandoraURL) {
      pandoraURL = normalizePandoraCanonicalURL(resolvedPandoraURL, pandoraID);
    }

    var resolvedID = extractPandoraAlbumID(pandoraURL);
    if (resolvedID) {
      pandoraID = resolvedID;
    }

    if (entity && entity.type !== "album") {
      throw new Error("Resolved entity is not a Pandora album");
    }
  } catch (e) {
    if (!pretty) {
      throw e;
    }
  }

  return {
    pandoraID: pandoraID,
    pandoraURL: pandoraURL,
    entity: entity,
    pretty: pretty
  };
}

function buildTrackMetadata(resolved) {
  var entity = resolved.entity || {};
  var deezerTrack = resolved.deezerTrack || {};
  var deezerAlbum = resolved.deezerAlbum || {};
  var pretty = resolved.pretty || {};
  var album = deezerAlbum.id ? deezerAlbum : (deezerTrack.album || {});
  var albumArtist =
    normalizeAlbumArtistFromDeezer(deezerAlbum, deezerTrack) ||
    entity.artistName ||
    pretty.artistName ||
    "";
  var releaseDate = deezerTrack.release_date || album.release_date || "";
  var totalTracks = album.nb_tracks || 0;
  var composer = extractDeezerComposer(deezerTrack);

  return {
    id: resolved.pandoraID,
    name: deezerTrack.title || entity.title || pretty.trackName || resolved.pandoraID,
    artists:
      normalizeArtistsFromDeezer(deezerTrack) ||
      entity.artistName ||
      pretty.artistName ||
      "",
    album_name: album.title || pretty.albumName || "",
    album_artist: albumArtist,
    duration_ms: deezerTrack.duration ? deezerTrack.duration * 1000 : 0,
    cover_url:
      album.cover_xl ||
      album.cover_big ||
      album.cover_medium ||
      entity.thumbnailUrl ||
      "",
    images:
      album.cover_xl ||
      album.cover_big ||
      album.cover_medium ||
      entity.thumbnailUrl ||
      "",
    release_date: releaseDate,
    track_number: deezerTrack.track_position || 0,
    total_tracks: totalTracks,
    disc_number: deezerTrack.disk_number || 1,
    total_discs: deezerTrack.disk_number || 1,
    isrc: deezerTrack.isrc || "",
    genre: extractDeezerGenre(deezerAlbum),
    label: deezerAlbum.label || "",
    composer: composer,
    provider_id: "pandora",
    item_type: "track"
  };
}

function buildAlbumMetadata(resolved) {
  var entity = resolved.entity || {};
  var pretty = resolved.pretty || {};

  return {
    id: resolved.pandoraID,
    name: entity.title || pretty.albumName || resolved.pandoraID,
    artists: entity.artistName || pretty.artistName || "",
    cover_url: entity.thumbnailUrl || "",
    images: entity.thumbnailUrl || "",
    release_date: "",
    total_tracks: 0,
    album_type: "album",
    provider_id: "pandora",
    tracks: []
  };
}

function buildArtistMetadata(url) {
  url = normalizePandoraInput(url);
  var pretty = parsePandoraPrettyURL(url);
  var artistID = normalizePandoraID(url);

  if (!pretty || !pretty.artistName) {
    return null;
  }

  return {
    id: artistID || String(url || "").trim(),
    name: pretty.artistName,
    image_url: "",
    provider_id: "pandora",
    albums: [],
    releases: [],
    top_tracks: []
  };
}

function normalizePandoraTrackURL(input) {
  input = normalizePandoraInput(input);
  var trackID = extractPandoraTrackID(input);
  if (trackID) {
    return normalizePandoraCanonicalURL(input, trackID);
  }

  var songLinkData = resolveSongLink(String(input || "").trim());
  var pandoraURL = extractPandoraURLFromSongLink(songLinkData);
  if (!extractPandoraTrackID(pandoraURL)) {
    throw new Error("Could not resolve Pandora track URL");
  }

  return normalizePandoraCanonicalURL(pandoraURL, extractPandoraTrackID(pandoraURL));
}

function normalizeDownloadCandidateURL(value) {
  value = normalizeSecureURL(value);
  if (!value) return "";

  if (/^https?:\/\//i.test(value) || value.indexOf("pandora.com") >= 0 || value.indexOf("pandora.app.link") >= 0) {
    return value;
  }

  if (/^(TR|AL|AR|PL|ST)(?::)?[A-Za-z0-9:]+$/i.test(value)) {
    return buildPandoraURL(value);
  }

  if (/^[A-Za-z0-9]{22}$/.test(value)) {
    return "https://open.spotify.com/track/" + value;
  }

  if (/^spotify:track:[A-Za-z0-9]{22}$/i.test(value)) {
    return "https://open.spotify.com/track/" + value.split(":").pop();
  }

  if (/^\d+$/.test(value)) {
    return "https://www.deezer.com/track/" + value;
  }

  return "";
}

function selectQualityLink(payload, quality) {
  var links = payload && payload.cdnLinks ? payload.cdnLinks : {};
  var requested = String(quality || "mp3_192").toLowerCase();

  if (requested === "aac_64" && links.mediumQuality) {
    return links.mediumQuality;
  }
  if (requested === "aac_32" && links.lowQuality) {
    return links.lowQuality;
  }
  if (links.highQuality) {
    return links.highQuality;
  }
  if (links.mediumQuality) {
    return links.mediumQuality;
  }
  if (links.lowQuality) {
    return links.lowQuality;
  }

  return null;
}

function outputExtensionForLink(linkInfo) {
  if (!linkInfo) return ".bin";

  var encoding = String(linkInfo.encoding || "").toLowerCase();
  if (encoding === "mp3" || encoding === "mpeg") {
    return ".mp3";
  }
  if (encoding.indexOf("aac") >= 0) {
    return ".m4a";
  }

  var url = String(linkInfo.url || "");
  if (/\.mp3(?:$|\?)/i.test(url)) return ".mp3";
  if (/\.m4a(?:$|\?)/i.test(url)) return ".m4a";
  if (/\.mp4(?:$|\?)/i.test(url)) return ".m4a";

  return ".bin";
}

function handleUrl(url) {
  var input = String(url || "").trim();
  if (!input) {
    return null;
  }

  try {
    input = normalizePandoraInput(input);
  } catch (e) {
    log.error("[Pandora] Failed to resolve shared link:", e.message);
    return null;
  }

  if (input.indexOf("pandora.com") === -1) {
    return null;
  }

  var pretty = parsePandoraPrettyURL(input);

  try {
    var trackID = extractPandoraTrackID(input);
    if (trackID || input.indexOf("pandora.com/") >= 0) {
      try {
        var resolvedTrack = resolvePandoraTrack(input);
        return {
          success: true,
          type: "track",
          track: buildTrackMetadata(resolvedTrack)
        };
      } catch (trackErr) {
        log.debug("[Pandora] Track URL handling failed:", trackErr.message);
      }
    }

    var albumID = extractPandoraAlbumID(input);
    if (albumID || (pretty && pretty.type === "album")) {
      var resolvedAlbum = resolvePandoraAlbum(input);
      var album = buildAlbumMetadata(resolvedAlbum);
      return {
        success: true,
        type: "album",
        album: album,
        tracks: [],
        name: album.name,
        cover_url: album.cover_url
      };
    }

    var artist = buildArtistMetadata(input);
    if (artist) {
      return {
        success: true,
        type: "artist",
        artist: artist
      };
    }
  } catch (e) {
    log.error("[Pandora] URL handling failed:", e.message);
  }

  return null;
}

function getTrack(trackId) {
  try {
    return buildTrackMetadata(resolvePandoraTrack(trackId));
  } catch (e) {
    log.error("[Pandora] getTrack failed:", e.message);
    return null;
  }
}

function getAlbum(albumId) {
  try {
    return buildAlbumMetadata(resolvePandoraAlbum(albumId));
  } catch (e) {
    log.error("[Pandora] getAlbum failed:", e.message);
    return null;
  }
}

function getArtist(artistId) {
  try {
    return buildArtistMetadata(artistId);
  } catch (e) {
    log.error("[Pandora] getArtist failed:", e.message);
    return null;
  }
}

function checkAvailability(isrc, trackName, artistName, options) {
  log.info("[Pandora] checkAvailability:", trackName, "-", artistName);

  options = options || {};

  var directPandoraTrackID = extractPandoraTrackID(options.spotify_id || "");
  if (directPandoraTrackID) {
    return { available: true, track_id: directPandoraTrackID };
  }

  var candidates = [
    normalizeDownloadCandidateURL(options.spotify_id || ""),
    normalizeDownloadCandidateURL(options.deezer_id || ""),
    normalizeDownloadCandidateURL(options.url || ""),
    normalizeDownloadCandidateURL(options.link || "")
  ];

  for (var i = 0; i < candidates.length; i++) {
    if (!candidates[i]) continue;

    try {
      var resolvedURL = normalizePandoraTrackURL(candidates[i]);
      var trackID = extractPandoraTrackID(resolvedURL);
      if (trackID) {
        return { available: true, track_id: trackID };
      }
    } catch (e) {
      log.debug("[Pandora] availability candidate failed:", e.message);
    }
  }

  return { available: false, reason: "not_found_on_pandora" };
}

function download(trackID, quality, outputPath, onProgress) {
  try {
    var downloadURL = normalizeSecureURL(normalizePandoraTrackURL(trackID));
    var resolvedTrack = null;
    var trackMetadata = null;

    try {
      resolvedTrack = resolvePandoraTrack(trackID);
      trackMetadata = buildTrackMetadata(resolvedTrack);
    } catch (metadataErr) {
      log.debug("[Pandora] Download metadata prefetch failed:", metadataErr.message);
    }

    if (onProgress) onProgress(0.1);

    var payload = postJSON(CONFIG.apiBaseURL + CONFIG.downloadPath, {
      url: downloadURL
    });

    if (!payload || payload.success !== true) {
      var errorMessage =
        payload && payload.error && payload.error.message
          ? payload.error.message
          : "Pandora API request failed";
      return {
        success: false,
        error_message: errorMessage,
        error_type: "api_error"
      };
    }

    var selectedLink = selectQualityLink(payload, quality);
    if (!selectedLink || !selectedLink.url) {
      return {
        success: false,
        error_message: "No downloadable Pandora stream available",
        error_type: "api_error"
      };
    }

    selectedLink.url = normalizeSecureURL(selectedLink.url);

    var actualOutputPath = ensureOutputExtension(
      outputPath,
      outputExtensionForLink(selectedLink)
    );

    if (onProgress) onProgress(0.3);

    var downloadResult = file.download(selectedLink.url, actualOutputPath, {
      headers: {
        "User-Agent": userAgentForURL(selectedLink.url)
      }
    });

    if (!downloadResult || !downloadResult.success) {
      return {
        success: false,
        error_message:
          "Failed to download Pandora file: " +
          (downloadResult && downloadResult.error
            ? downloadResult.error
            : "file.download returned null"),
        error_type: "download_error"
      };
    }

    if (onProgress) onProgress(1.0);

    return {
      success: true,
      file_path: downloadResult.path || actualOutputPath,
      bit_depth: 0,
      sample_rate: 0,
      title: trackMetadata && trackMetadata.name ? trackMetadata.name : "",
      artist: trackMetadata && trackMetadata.artists ? trackMetadata.artists : "",
      album: trackMetadata && trackMetadata.album_name ? trackMetadata.album_name : "",
      album_artist:
        trackMetadata && trackMetadata.album_artist ? trackMetadata.album_artist : "",
      track_number:
        trackMetadata && trackMetadata.track_number ? trackMetadata.track_number : 0,
      total_tracks:
        trackMetadata && trackMetadata.total_tracks ? trackMetadata.total_tracks : 0,
      disc_number:
        trackMetadata && trackMetadata.disc_number ? trackMetadata.disc_number : 0,
      total_discs:
        trackMetadata && trackMetadata.total_discs ? trackMetadata.total_discs : 0,
      release_date:
        trackMetadata && trackMetadata.release_date ? trackMetadata.release_date : "",
      cover_url: trackMetadata && trackMetadata.cover_url ? trackMetadata.cover_url : "",
      isrc: trackMetadata && trackMetadata.isrc ? trackMetadata.isrc : "",
      genre: trackMetadata && trackMetadata.genre ? trackMetadata.genre : "",
      label: trackMetadata && trackMetadata.label ? trackMetadata.label : "",
      composer: trackMetadata && trackMetadata.composer ? trackMetadata.composer : ""
    };
  } catch (e) {
    return {
      success: false,
      error_message: e.message || String(e),
      error_type: "runtime_error"
    };
  }
}

registerExtension({
  initialize: initialize,
  cleanup: cleanup,
  handleUrl: handleUrl,
  getTrack: getTrack,
  getAlbum: getAlbum,
  getArtist: getArtist,
  checkAvailability: checkAvailability,
  download: download,
  getDownloadUrl: function () {
    return null;
  }
});

log.info("[Pandora] Pandora extension loaded");
