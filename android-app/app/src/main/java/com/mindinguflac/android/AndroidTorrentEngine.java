package com.mindinguflac.android;

import com.frostwire.jlibtorrent.FileStorage;
import com.frostwire.jlibtorrent.LibTorrent;
import com.frostwire.jlibtorrent.Priority;
import com.frostwire.jlibtorrent.SessionManager;
import com.frostwire.jlibtorrent.SessionParams;
import com.frostwire.jlibtorrent.SettingsPack;
import com.frostwire.jlibtorrent.TorrentHandle;
import com.frostwire.jlibtorrent.TorrentInfo;
import com.frostwire.jlibtorrent.TorrentStatus;
import com.frostwire.jlibtorrent.TorrentFlags;
import com.frostwire.jlibtorrent.swig.torrent_flags_t;

import org.json.JSONObject;

import java.io.File;
import java.text.Normalizer;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/** Android-native libtorrent bridge used by the embedded Python backend. */
public final class AndroidTorrentEngine {
    private static final ConcurrentHashMap<String, TorrentJob> JOBS = new ConcurrentHashMap<>();
    private static final ConcurrentHashMap<String, AtomicBoolean> STARTS = new ConcurrentHashMap<>();
    private static final ConcurrentHashMap<String, byte[]> METADATA = new ConcurrentHashMap<>();
    private static final ConcurrentHashMap<String, Long> WARM_EXPIRIES = new ConcurrentHashMap<>();
    private static final ScheduledExecutorService WARM_SWARMS = Executors.newSingleThreadScheduledExecutor(task -> {
        Thread thread = new Thread(task, "torrent-warm-expiry");
        thread.setDaemon(true);
        return thread;
    });
    private static final Set<String> LOSSLESS_EXTENSIONS = immutableSet(
            ".flac", ".alac", ".wav", ".wave", ".aiff", ".aif", ".ape", ".wv");
    private static final Set<String> AUDIO_EXTENSIONS = immutableSet(
            ".flac", ".alac", ".wav", ".wave", ".aiff", ".aif", ".ape", ".wv",
            ".mp3", ".m4a", ".aac", ".ogg", ".opus");
    private static final Set<String> STOP_WORDS = immutableSet(
            "the", "and", "feat", "with", "remastered");

    /** Same DHT routers the desktop engine seeds its session with. */
    private static final String DHT_BOOTSTRAP_NODES = String.join(",",
            "router.bittorrent.com:6881",
            "router.utorrent.com:6881",
            "dht.transmissionbt.com:6881",
            "dht.libtorrent.org:25401",
            "router.silence.is:6881");

    /** Mirrors backend_torrent._HARDCODED_TRACKERS. */
    private static final String[] FALLBACK_TRACKERS = {
            "udp://tracker.opentrackr.org:1337/announce",
            "udp://open.stealth.si:80/announce",
            "udp://tracker.torrent.eu.org:451/announce",
            "udp://exodus.desync.com:6969/announce",
            "udp://open.demonii.com:1337/announce",
            "udp://tracker.openbittorrent.com:6969/announce",
            "udp://opentracker.i2p.rocks:6969/announce",
            "udp://tracker.tiny-vps.com:6969/announce",
    };

    private static final Object SESSION_LOCK = new Object();
    private static SessionManager sharedSession;

    private AndroidTorrentEngine() {}

    private static final class TorrentJob {
        final TorrentHandle handle;
        final File selectedFile;
        final long selectedSize;
        final int selectedIndex;
        final long fileOffset;
        final int pieceLength;
        boolean prefetch = false;

        TorrentJob(TorrentHandle handle, File selectedFile,
                   long selectedSize, int selectedIndex, long fileOffset, int pieceLength) {
            this.handle = handle;
            this.selectedFile = selectedFile;
            this.selectedSize = selectedSize;
            this.selectedIndex = selectedIndex;
            this.fileOffset = fileOffset;
            this.pieceLength = pieceLength;
        }
    }

    /**
     * One session for the whole process, bootstrapped into the DHT.
     *
     * Each candidate used to get a brand new SessionManager with no DHT
     * bootstrap nodes, so every magnet started from an empty routing table and
     * burned the full fetchMagnet timeout before failing — which is exactly
     * what "Torrent metadata timed out" was, repeated once per source. Sharing
     * one warm session means the second and later candidates resolve against a
     * routing table that is already populated.
     */
    private static SessionManager sharedSession() throws InterruptedException {
        synchronized (SESSION_LOCK) {
            if (sharedSession != null && sharedSession.isRunning()) return sharedSession;
            SettingsPack settings = new SettingsPack();
            settings.setEnableDht(true);
            settings.setEnableLsd(true);
            settings.setDhtBootstrapNodes(DHT_BOOTSTRAP_NODES);
            settings.activeDownloads(30);
            settings.activeSeeds(0);
            settings.activeLimit(40);
            settings.connectionsLimit(200);
            settings.maxPeerlistSize(1000);
            settings.inactivityTimeout(120);
            SessionManager session = new SessionManager();
            session.start(new SessionParams(settings));
            sharedSession = session;
        }
        return sharedSession;
    }

    /**
     * Give the magnet a tracker list if it arrived without one. Indexer magnets
     * are frequently DHT-only, which makes metadata lookup slow or hopeless on
     * a phone network.
     */
    private static String withTrackers(String magnet) {
        if (magnet == null || !magnet.startsWith("magnet:?")) return magnet;
        StringBuilder out = new StringBuilder(magnet);
        for (String tracker : FALLBACK_TRACKERS) {
            if (magnet.contains(tracker)) continue;
            out.append("&tr=").append(java.net.URLEncoder.encode(tracker, java.nio.charset.StandardCharsets.UTF_8));
        }
        return out.toString();
    }

    /**
     * Fetch magnet metadata, select the requested audio file, and begin only
     * that file. Returns JSON so Chaquopy can pass the result to Python without
     * reflecting custom Java objects.
     */
    public static String startDownload(String jobId, String magnet, String outputPath,
                                       String artist, String title, String album,
                                       String trackNumber, boolean requireLossless,
                                       int metadataTimeoutSeconds) {
        cancel(jobId);
        AtomicBoolean cancelled = new AtomicBoolean(false);
        STARTS.put(jobId, cancelled);
        try {
            File outputDir = new File(outputPath);
            File metadataDir = new File(outputDir, ".metadata");
            if ((!outputDir.isDirectory() && !outputDir.mkdirs())
                    || (!metadataDir.isDirectory() && !metadataDir.mkdirs())) {
                throw new IllegalStateException("Could not create torrent cache directory");
            }

            SessionManager session = sharedSession();
            String resolvable = withTrackers(magnet);
            if (cancelled.get()) throw new InterruptedException("Cancelled");
            String metadataKey = java.net.URLDecoder.decode(magnet, java.nio.charset.StandardCharsets.UTF_8)
                    .replaceAll("(?i)^.*[?&]xt=urn:btih:([^&]+).*$", "$1").toLowerCase(Locale.ROOT);
            byte[] metadata = METADATA.get(metadataKey);
            int metadataTimeout = Math.max(10, Math.min(180, metadataTimeoutSeconds));
            if (metadata == null) metadata = session.fetchMagnet(resolvable, metadataTimeout, metadataDir);
            if (cancelled.get()) throw new InterruptedException("Cancelled");
            if (metadata == null || metadata.length == 0) {
                throw new IllegalStateException("Torrent metadata timed out");
            }
            TorrentInfo info = new TorrentInfo(metadata);
            if (!info.isValid()) {
                throw new IllegalStateException("Torrent metadata is invalid");
            }
            if (METADATA.size() >= 32) METADATA.remove(METADATA.keys().nextElement());
            METADATA.put(metadataKey, metadata);

            int selected = selectFile(info.files(), artist, title, album, trackNumber, requireLossless);
            if (selected < 0) {
                throw new IllegalStateException(requireLossless
                        ? "No matching lossless audio file in torrent"
                        : "No matching audio file in torrent");
            }

            // Keep adding/registering a shared handle atomic with release.
            synchronized (SESSION_LOCK) {
            if (cancelled.get()) throw new InterruptedException("Cancelled");
            Priority[] requestedFiles = Priority.array(Priority.IGNORE, info.numFiles());
            requestedFiles[selected] = Priority.SEVEN;
            // jlibtorrent 2.0.12 dereferences the flags wrapper in download();
            // passing null here crashes native code after metadata is resolved.
            session.download(info, outputDir, null, requestedFiles, null, new torrent_flags_t());
            TorrentHandle handle = null;
            for (int attempt = 0; attempt < 100; attempt++) {
                handle = session.find(info);
                if (handle != null && handle.isValid()) break;
                Thread.sleep(50);
            }
            if (handle == null || !handle.isValid()) {
                throw new IllegalStateException("libtorrent did not add the selected source");
            }

            FileStorage files = info.files();
            File selectedFile = new File(handle.savePath(), files.filePath(selected));
            TorrentJob state = new TorrentJob(
                    handle, selectedFile, files.fileSize(selected), selected, files.fileOffset(selected), info.pieceLength());
            JOBS.put(jobId, state);
            handle.setFlags(TorrentFlags.SEQUENTIAL_DOWNLOAD);
            updatePriorities(handle);
            handle.resume();

            return json(true, "", selectedFile.getAbsolutePath(), files.fileSize(selected),
                    0L, 0, 0, false, info.name()).put("save_path", handle.savePath()).toString();
            }
        } catch (Throwable error) {
            // Never tear the shared session down here: the caller simply moves
            // on to the next candidate, and killing the session would make it
            // start from a cold DHT all over again.
            return json(false, message(error), "", 0L, 0L, 0, 0, false, "").toString();
        } finally {
            STARTS.remove(jobId, cancelled);
        }
    }

    public static String status(String jobId) {
        TorrentJob state = JOBS.get(jobId);
        if (state == null) {
            return json(false, "Torrent job is not active", "", 0L, 0L, 0, 0, false, "").toString();
        }
        try {
            TorrentStatus torrent = state.handle.status();
            long[] progress = state.handle.fileProgress();
            long ready = state.selectedIndex < progress.length ? progress[state.selectedIndex] : 0L;
            ready = Math.max(0L, Math.min(ready, state.selectedSize));
            boolean finished = ready >= state.selectedSize || torrent.isFinished() || torrent.isSeeding();
            String error = "";
            if (torrent.errorCode() != null && torrent.errorCode().value() != 0) {
                error = torrent.errorCode().message();
            }
            long contiguous = -(state.fileOffset % state.pieceLength);
            int piece = (int) (state.fileOffset / state.pieceLength);
            while (contiguous < state.selectedSize && state.handle.havePiece(piece)) {
                contiguous += state.pieceLength;
                piece++;
            }
            return json(error.isEmpty(), error, state.selectedFile.getAbsolutePath(),
                    state.selectedSize, ready, torrent.numPeers(), torrent.numSeeds(),
                    finished, torrent.name()).put("contiguous", Math.max(0L, Math.min(contiguous, state.selectedSize))).toString();
        } catch (Throwable error) {
            return json(false, message(error), state.selectedFile.getAbsolutePath(),
                    state.selectedSize, 0L, 0, 0, false, "").toString();
        }
    }

    public static void release(String jobId) {
        release(jobId, true);
    }

    private static void release(String jobId, boolean keepWarm) {
        synchronized (SESSION_LOCK) {
        TorrentJob state = JOBS.remove(jobId);
        if (state == null) return;
        // Drop this job's torrent but keep the session: other jobs share it, and
        // a warm DHT routing table is the whole point of it being shared.
        SessionManager session;
        synchronized (SESSION_LOCK) {
            session = sharedSession;
        }
        if (session == null) return;
        for (TorrentJob other : JOBS.values()) {
            if (other.handle.infoHash().equals(state.handle.infoHash())) {
                updatePriorities(other.handle);
                return;
            }
        }
        String hash = state.handle.infoHash().toString();
        if (!keepWarm) {
            WARM_EXPIRIES.remove(hash);
            try { session.remove(state.handle); } catch (Throwable ignored) {}
            return;
        }
        // Keep a healthy album's peer connections briefly for the next track.
        long expiry = System.nanoTime();
        WARM_EXPIRIES.put(hash, expiry);
        WARM_SWARMS.schedule(() -> {
            synchronized (SESSION_LOCK) {
                if (!WARM_EXPIRIES.remove(hash, expiry)) return;
                for (TorrentJob other : JOBS.values()) {
                    if (other.handle.infoHash().equals(state.handle.infoHash())) return;
                }
                try { session.remove(state.handle); } catch (Throwable ignored) {}
            }
        }, 180, TimeUnit.SECONDS);
        }
    }

    public static void cancel(String jobId) {
        AtomicBoolean pending = STARTS.get(jobId);
        if (pending != null) pending.set(true);
        release(jobId, false);
    }

    public static void cancelGroup(String jobId) {
        String prefix = jobId + "::torrent::";
        for (String id : STARTS.keySet()) {
            if (id.equals(jobId) || id.startsWith(prefix)) cancel(id);
        }
        for (String id : JOBS.keySet()) {
            if (id.equals(jobId) || id.startsWith(prefix)) cancel(id);
        }
    }

    private static void updatePriorities(TorrentHandle handle) {
        Priority[] priorities = Priority.array(Priority.IGNORE, handle.filePriorities().length);
        for (TorrentJob other : JOBS.values()) {
            if (other.handle.infoHash().equals(handle.infoHash()) && other.selectedIndex < priorities.length) {
                if (!other.prefetch || priorities[other.selectedIndex] != Priority.SEVEN) {
                    priorities[other.selectedIndex] = other.prefetch ? Priority.TWO : Priority.SEVEN;
                }
            }
        }
        handle.prioritizeFiles(priorities);
    }

    public static void setPrefetch(String jobId, boolean prefetch) {
        synchronized (SESSION_LOCK) {
            TorrentJob state = JOBS.get(jobId);
            if (state != null && state.prefetch != prefetch) {
                state.prefetch = prefetch;
                updatePriorities(state.handle);
            }
        }
    }

    /**
     * Prove the arm64 jlibtorrent JNI library actually loaded, without paying
     * for a session. The Python capability probe calls this on every settings
     * read, so it must stay cheap; {@link #runtimeStatus()} is the heavier
     * check that also opens and closes a real session.
     */
    public static String nativeStatus() {
        try {
            String version = LibTorrent.jlibtorrentVersion();
            JSONObject value = json(true, "", "", 0L, 0L, 0, 0, false,
                    "jlibtorrent " + version + " / libtorrent " + LibTorrent.version());
            value.put("jlibtorrent_version", version);
            value.put("libtorrent_version", LibTorrent.version());
            value.put("abi", "arm64-v8a");
            return value.toString();
        } catch (Throwable error) {
            return json(false, message(error), "", 0L, 0L, 0, 0, false, "").toString();
        }
    }

    public static String runtimeStatus() {
        try {
            SessionManager session = sharedSession();
            JSONObject value = json(true, "", "", 0L, 0L, 0, 0, false,
                    "jlibtorrent " + LibTorrent.jlibtorrentVersion() + " arm64");
            value.put("dht_running", session.isDhtRunning());
            value.put("dht_nodes", session.dhtNodes());
            return value.toString();
        } catch (Throwable error) {
            return json(false, message(error), "", 0L, 0L, 0, 0, false, "").toString();
        }
    }

    private static int selectFile(FileStorage files, String artist, String title,
                                  String album, String trackNumber, boolean requireLossless) {
        int bestIndex = -1;
        double bestScore = 0.0;
        Set<String> wantedTitle = tokens(title);
        Set<String> wantedArtist = tokens(artist);
        Set<String> wantedAlbum = tokens(album);
        String paddedTrack = digits(trackNumber);
        if (paddedTrack.length() == 1) paddedTrack = "0" + paddedTrack;

        for (int index = 0; index < files.numFiles(); index++) {
            String path = files.filePath(index);
            String lower = path.toLowerCase(Locale.ROOT);
            String extension = extension(lower);
            if (!AUDIO_EXTENSIONS.contains(extension)) continue;
            if (requireLossless && !LOSSLESS_EXTENSIONS.contains(extension)) continue;

            Set<String> candidate = tokens(path);
            double titleCoverage = coverage(wantedTitle, candidate);
            double artistCoverage = coverage(wantedArtist, candidate);
            double albumCoverage = coverage(wantedAlbum, candidate);
            double score = (titleCoverage * 120.0) + (artistCoverage * 35.0)
                    + (albumCoverage * 28.0);
            if (".flac".equals(extension)) score += 28.0;
            else if (LOSSLESS_EXTENSIONS.contains(extension)) score += 12.0;

            String fileName = new File(path).getName().toLowerCase(Locale.ROOT);
            if (!paddedTrack.isEmpty()
                    && (fileName.startsWith(paddedTrack + " ")
                    || fileName.startsWith(paddedTrack + ".")
                    || fileName.startsWith(paddedTrack + "-")
                    || fileName.contains(" " + paddedTrack + " "))) {
                score += 45.0;
            }
            if (titleCoverage < (wantedTitle.size() <= 2 ? 0.72 : 0.52)) continue;
            if (score > bestScore) {
                bestScore = score;
                bestIndex = index;
            }
        }
        return bestIndex;
    }

    private static Set<String> tokens(String value) {
        String normalized = Normalizer.normalize(value == null ? "" : value, Normalizer.Form.NFD)
                .replaceAll("\\p{M}+", "")
                .toLowerCase(Locale.ROOT)
                .replaceAll("[^a-z0-9]+", " ");
        Set<String> out = new HashSet<>();
        for (String token : normalized.split("\\s+")) {
            if (token.length() > 1 && !STOP_WORDS.contains(token)) {
                out.add(token);
            }
        }
        return out;
    }

    private static double coverage(Set<String> wanted, Set<String> actual) {
        if (wanted.isEmpty()) return 0.0;
        int matches = 0;
        for (String token : wanted) if (actual.contains(token)) matches++;
        return (double) matches / (double) wanted.size();
    }

    private static String extension(String path) {
        int slash = Math.max(path.lastIndexOf('/'), path.lastIndexOf(File.separatorChar));
        int dot = path.lastIndexOf('.');
        return dot > slash ? path.substring(dot) : "";
    }

    private static String digits(String value) {
        return value == null ? "" : value.replaceAll("[^0-9]", "");
    }

    private static String message(Throwable error) {
        String value = error.getMessage();
        return value == null || value.trim().isEmpty() ? error.getClass().getSimpleName() : value;
    }

    private static Set<String> immutableSet(String... values) {
        return Collections.unmodifiableSet(new HashSet<>(Arrays.asList(values)));
    }

    private static JSONObject json(boolean ok, String error, String path, long size,
                                   long ready, int peers, int seeds, boolean finished,
                                   String name) {
        JSONObject value = new JSONObject();
        try {
            value.put("ok", ok);
            value.put("error", error == null ? "" : error);
            value.put("path", path == null ? "" : path);
            value.put("size", size);
            value.put("ready", ready);
            value.put("peers", peers);
            value.put("seeds", seeds);
            value.put("finished", finished);
            value.put("name", name == null ? "" : name);
        } catch (Exception ignored) {}
        return value;
    }
}
