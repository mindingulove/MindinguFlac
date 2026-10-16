"""Browser regression checks for album tracks followed by deferred details.

Run with a Python environment containing Playwright and its Chromium browser.
"""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / 'static/app.js').read_text()
page_function = source[source.index('async function renderAlbumPage('):source.index('// Selection & Playback')]
api_function = source[source.index('async function api('):source.index('function $(id)')]
core = {
    'artist': 'Seu Pereira e Coletivo 401', 'album': 'Eu Não Sou Boa Influência pra Você',
    'year': '2017', 'track_count': 1, 'total_duration': '3:00',
    'artwork_url': 'cover-one', 'gallery_images': [{'url': 'cover-one', 'source': 'Spotify'}],
    'tracks': [{'title': 'Song', 'plays': 42}], '_extras_complete': False,
}
details = {
    **core, '_extras_complete': True, 'discogs_release_url': 'https://discogs.com/release/1',
    'gallery_images': [*core['gallery_images'], {'url': 'cover-two', 'source': 'Discogs'}],
    'tracks': [{'title': 'Song', 'plays': 99}],
}
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page()
    page.set_content('<style>.hidden {display:none}</style><div id="pageContent"></div>')
    page.add_script_tag(content='''
      const $ = id => document.getElementById(id);
      const esc = value => String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll('"', "&quot;");
      const setActiveView = () => {};
      const openArtistLink = () => {};
      const trackPlaysValue = item => item.plays;
      const renderTrackList = (id, items) => {
        window.displayedTracks = items;
        $(id).innerHTML = items.map(t => `<div class="track-row"><span class="views-count">${t.plays}</span></div>`).join("");
      };
      window.calls = [];
      function api(path) {
        calls.push(path);
        if (path.includes("details=0")) return Promise.resolve(window.core);
        return new Promise((resolve, reject) => { window.resolveDetails = resolve; window.rejectDetails = reject; });
      }
    ''' + page_function)
    page.evaluate('(core) => { window.core = core; }', core)
    page.evaluate('renderAlbumPage({artist: core.artist, title: core.album, spotify_id:"album-id"})')
    assert page.locator('h1').inner_text() == core['album']
    assert page.locator('#albumTrackList .track-row').count() == 1
    assert page.locator('#albumGalleryNext').is_hidden()
    # Details are still pending, but the track list is already usable.
    page.evaluate('(details) => resolveDetails(details)', details)
    page.wait_for_function('document.querySelector(".views-count").textContent === "99"')
    assert page.locator('#albumGalleryNext').is_visible()
    page.locator('#albumGalleryNext').click()
    assert page.locator('#albumGalleryImage').get_attribute('src') == 'cover-two'
    assert page.locator('#discogsAttribution').is_visible()
    assert page.evaluate('displayedTracks[0].plays') == 99
    # A failed optional request cannot turn a loaded page into an error.
    page.evaluate('renderAlbumPage({artist: core.artist, title: core.album})')
    page.evaluate('rejectDetails(new Error("Artwork unavailable"))')
    assert page.locator('h1').inner_text() == core['album']
    assert page.locator('.error-state').count() == 0
    # A late details response cannot overwrite a different page.
    page.evaluate('renderAlbumPage({artist: core.artist, title: core.album})')
    page.evaluate('document.getElementById("pageContent").innerHTML = "<h1>Another page</h1>"')
    page.evaluate('(details) => resolveDetails(details)', details)
    assert page.locator('h1').inner_text() == 'Another page'
    # A late initial response cannot overwrite navigation either.
    page.evaluate('() => { api = () => new Promise(resolve => window.resolveCore = resolve); window.pendingAlbum = renderAlbumPage({title:"Pending"}); }')
    page.evaluate('document.getElementById("pageContent").innerHTML = "<h1>Another page</h1>"')
    page.evaluate('(core) => { resolveCore(core); return pendingAlbum; }', core)
    assert page.locator('h1').inner_text() == 'Another page'
    # The shared API helper gives timeout errors a readable explanation.
    page.add_script_tag(content='const API_BASE = ""; ' + api_function)
    page.evaluate('() => { fetch = (url, options) => new Promise((resolve, reject) => options.signal.addEventListener("abort", () => reject(new DOMException("Fetch is aborted", "AbortError")))); }')
    error = page.evaluate('api("/test", {timeout: 5}).catch(error => error.message)')
    assert error == 'The request took too long. Please try again.', error
    browser.close()
print('PASS: tracks before details; gallery enrichment; optional failure; navigation guards; readable timeout')
