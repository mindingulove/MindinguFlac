const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../static/app.js'), 'utf8');
function section(start, end) {
  return source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start)));
}
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, { innerHTML: '', style: {}, dataset: {}, hidden: true, querySelectorAll: () => [], querySelector: () => null });
  return elements.get(id);
}
const context = vm.createContext({
  console, URL, Array, Set, Map,
  esc: text => String(text).replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;'),
  state: { playlists: [], mobileLibraryFilter: 'playlists', viewStack: [], settings: { default_quality: 'LOSSLESS' }, playbackRequestId: 0 },
  $: element, document: { querySelectorAll: () => [] },
  refreshMobileLibraryList: () => {}, renderTrackList: () => {}, setActiveView: () => {},
  syncActiveTrackRows: () => {}, prepareSelectedTrackUi: () => {}, startListeningSession: () => {},
  recordDockRecentSelection: () => {}, adoptPrefetchJobForTrack: () => {},
  cancelPrefetchJobs: () => {}, currentPrefetchWindowKeys: () => new Set(), currentQueueOrderKey: () => '',
  trackKey: track => track.title, openContextMenu: () => {}, playlistShareUrl: () => '',
  formatDuration: () => '', window: { matchMedia: () => ({ matches: false }) },
});
vm.runInContext(section('const OFFLINE_PLAYLIST_ID =', 'async function loadPlaylists()'), context);
vm.runInContext(section('function inferPlaylistOrigin(', 'function trackPlaysValue('), context);
vm.runInContext(section('function renderSidebarPlaylists()', 'async function deletePlaylist('), context);
vm.runInContext(section('function mobileLibraryItemsHtml(', 'function bindLibraryHold('), context);
vm.runInContext(section('function _renderPlaylistContent(', 'function playlistTrackKeys('), context);
vm.runInContext(section('function showPlaylistContextMenu(', 'function bindMobileLibraryItems('), context);
vm.runInContext(section('async function selectMusicItem(', 'function isActiveJobStreamUrl('), context);
vm.runInContext(section('async function prefetchOneTrack(', 'function maybePrefetchUpcomingTracks('), context);
vm.runInContext(section('async function loadPlaylists()', 'function trackInPlaylist('), context);

(async () => {
  const offline = { id: '__offline__', name: 'Offline', read_only: true, playlist_origin: 'offline', tracks: [{ title: 'Saved song', offline: true, library_path: '/Music/saved.m4a' }], artwork_urls: ['/cover1', '/cover2', '/cover3', '/cover4'] };
  context.offline = offline;
  assert.equal(vm.runInContext('inferPlaylistOrigin(offline)', context), 'offline');
  assert.equal(vm.runInContext('isReadOnlyPlaylist(offline)', context), true);
  const artwork = vm.runInContext('playlistArtworkHtml(offline, "playlist-hero-art")', context);
  assert.equal((artwork.match(/<img /g) || []).length, 4);
  assert.match(artwork, /playlist-art-grid/);
  const mobile = vm.runInContext('mobileLibraryItemsHtml([offline])', context);
  assert.match(mobile, /data-mobile-playlist-id="__offline__"/);
  assert.equal((mobile.match(/<img /g) || []).length, 4);
  context.state.playlists = [offline, { id: 'normal', name: 'Normal', tracks: [] }];
  vm.runInContext('renderSidebarPlaylists()', context);
  const sidebar = element('sidebarPlaylistList').innerHTML;
  assert.doesNotMatch(sidebar, /data-delete-playlist="__offline__"/);
  assert.match(sidebar, /data-delete-playlist="normal"/);
  vm.runInContext('_renderPlaylistContent(offline)', context);
  const hero = element('pageContent').innerHTML;
  assert.match(hero, /data-playlist-page="__offline__"/);
  assert.match(hero, /class="playlist-recommendations-head" style="display:none"/);
  vm.runInContext('showPlaylistContextMenu({}, offline)', context);
  assert.equal(element('ctxPlaylistDelete').style.display, 'none');
  vm.runInContext('showPlaylistContextMenu({}, {id:"normal", name:"Normal", tracks:[]})', context);
  assert.equal(element('ctxPlaylistDelete').style.display, '');
  let played = null;
  context.playFromLibraryPath = async (...args) => { played = args; };
  context.api = async () => { throw new Error('Offline selection must not resolve or download from a provider'); };
  element('queuePanel').hidden = true;
  await vm.runInContext('selectMusicItem(offline.tracks[0])', context);
  assert.equal(played[0], '/Music/saved.m4a');
  assert.equal(played[4], 'Playing offline');
  await vm.runInContext('prefetchOneTrack(offline.tracks[0], "order")', context);
  let refreshed = null;
  let destination = null;
  context._renderPlaylistContent = playlist => { refreshed = playlist; };
  context.replacePage = page => { destination = page; };
  context.renderHomePage = () => {};
  context.renderMobileLibraryPage = () => {};
  context.visibleAlbumControls = null;
  context.setInterval = () => 1;
  context.state.activePlaylistId = '__offline__';
  const scrollArea = { scrollTop: 25 };
  element('pageContent').querySelector = selector => selector === '.scroll-area' ? scrollArea : {};
  const updated = { ...offline, tracks: [...offline.tracks, { title: 'New download' }] };
  context.api = async () => [updated];
  await vm.runInContext('loadPlaylists()', context);
  assert.equal(refreshed.tracks.length, 2);
  assert.equal(scrollArea.scrollTop, 25);
  context.api = async () => [];
  await vm.runInContext('loadPlaylists()', context);
  assert.equal(context.state.activePlaylistId, null);
  assert.equal(destination, context.renderHomePage);
  console.log('Offline desktop/mobile artwork, immutable controls, local playback and prefetch checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
