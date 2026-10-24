const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../static/app.js'), 'utf8');
const section = source.slice(source.indexOf('function lyricsPayload('), source.indexOf('function parseLrcTimestamp('));
const context = vm.createContext({serviceDownloadPayload: track => track});
vm.runInContext(section, context);
const selected = {title:'Song - Single Edit',artist:'Artist',album:'Various Hits',spotify_id:'compilation-track',
 isrc:'requested', duration_ms:200000, source_recording:{title:'Song',artist:'Artist',album:'Studio Album',
 spotify_id:'',isrc:'actual',duration_ms:240000}};
const actual = context.lyricsPayload(selected);
assert.equal(actual.title,'Song'); assert.equal(actual.album,'Studio Album');
assert.equal(actual.spotify_id,''); assert.equal(actual.isrc,'actual'); assert.equal(actual.duration_s,240);
assert.equal(selected.album,'Various Hits'); assert.equal(selected.spotify_id,'compilation-track');
const original = context.lyricsPayload({title:'Original',album:'Deluxe',spotify_id:'original',duration_ms:100000});
assert.equal(original.spotify_id,'original'); assert.equal(original.album,'Deluxe');
assert.ok(source.includes('const key = JSON.stringify(lyricsPayload(track))'));
console.log('Lyrics follow resolved audio metadata while saved album identity stays intact');
