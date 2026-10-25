const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../static/app.js'), 'utf8');
const section = (start, end) => source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start)));
const context = vm.createContext({
  console, state: {}, document: {querySelectorAll: () => []},
  inferPlaylistOrigin: () => 'album', pushPage: fn => fn(),
});
context.renderAlbumPage = album => { context.opened = album; };
vm.runInContext(section('function albumTarget(', 'function spotifyArtistUrl('), context);
vm.runInContext(section('function openLibraryPlaylist(', '// Repaint Your Library'), context);
context.compilation = {type:'track', title:'One Of Us', artist:'Joan Osborne', artist_id:'joan',
  album:'Hits Of The 90s', album_artist:'Various Artists', album_spotify_id:'7AecHhPbyoban69HXHUL7a', spotify_id:'compilation-track'};
context.original = {...context.compilation, album:'Relish', album_artist:'Joan Osborne',
  album_spotify_id:'0123456789abcdefghijkl', spotify_id:'original-track'};
let album = vm.runInContext('albumTarget(compilation)', context);
assert.equal(album.spotify_id, '7AecHhPbyoban69HXHUL7a');
assert.equal(album.artist, 'Various Artists');
assert.equal(album.artist_id, ''); // Do not link Various Artists to Joan's ID.
assert.equal(album.track_spotify_id, 'compilation-track');
album = vm.runInContext('albumTarget(original)', context);
assert.equal(album.spotify_id, '0123456789abcdefghijkl');
assert.equal(album.artist, 'Joan Osborne');
assert.equal(album.artist_id, 'joan');
context.savedCompilation = {id:'saved-compilation', name:'Hits Of The 90s', owner:'Various Artists',
  spotify_url:'https://open.spotify.com/album/7AecHhPbyoban69HXHUL7a',
  tracks:[{...context.compilation, album_spotify_id:'stale-wrong-id', album_artist:''}]};
vm.runInContext('openLibraryPlaylist(savedCompilation)', context);
assert.equal(context.opened.spotify_id, '7AecHhPbyoban69HXHUL7a');
assert.equal(context.opened.artist, 'Various Artists');
assert.equal(context.opened.saved_playlist_context.id, 'saved-compilation');
context.savedOriginal = {id:'saved-original', name:'Relish', owner:'Joan Osborne',
  spotify_url:'https://open.spotify.com/album/0123456789abcdefghijkl', tracks:[context.original]};
vm.runInContext('openLibraryPlaylist(savedOriginal)', context);
assert.equal(context.opened.spotify_id, '0123456789abcdefghijkl');
assert.equal(context.opened.saved_playlist_context.id, 'saved-original');
console.log('Various Artists and original album identities remain distinct across title and saved-library links');
context.deluxe = {...context.original, album_context: {spotify_id:'DDD0123456789abcdefghiJ', album:'Relish (Deluxe)', album_artist:'Joan Osborne', artwork_url:'deluxe.jpg'}};
album = vm.runInContext('albumTarget(deluxe)', context);
assert.equal(album.spotify_id, 'DDD0123456789abcdefghiJ');
assert.equal(album.album, 'Relish (Deluxe)');
assert.equal(album.artwork_url, 'deluxe.jpg');
