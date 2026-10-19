from pathlib import Path
import re
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parents[1]
source=(root/'static/app.js').read_text()
controls=source[source.index('const SERVICE_LABELS ='):source.index('const STORAGE_KEYS =')]
render=source[source.index('async function renderSettings()'):source.index('let youtubeSettingsLoginPoll')]
save=source[source.index('async function saveSettings(e)'):source.index('// Player & Boot')]
html=re.sub(r'<script\b[^>]*>.*?</script>', '', (root/'static/index.html').read_text(), flags=re.S)
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    for android in (False, True):
        page=browser.new_page(viewport={'width':1100 if not android else 420,'height':1100})
        page.set_content(html+'<style>.hidden{display:none!important}#settingsView{display:block!important}</style>')
        page.add_script_tag(content='''
          const $=id=>document.getElementById(id);
          const esc=String;
          let IS_ANDROID=false;
          const state={settings:{}};
          let saved={download_engine:'torrent',download_service:'all',default_quality:'LOSSLESS',torrent_playback_candidates:5,torrent_prefetch_candidates:1};
          const setActiveView=()=>{}, startCacheLogPolling=()=>{}, setupYoutubeSignInSettings=()=>{}, refreshAndroidAdvisorStatus=()=>{}, refreshCodexStatus=()=>{}, loginCodex=()=>{}, hydrateTourLocationInputs=async()=>{}, setupTourLocationPicker=()=>{}, setupPairingSettings=()=>{};
          const showSettingsNotice=()=>{};
          async function api(path,opts={}) {
            if(path==='/api/settings') {if(opts.method==='POST'){saved=JSON.parse(opts.body);return {ok:true};}return {...saved};}
            if(path==='/api/runtime')return {engines:{torrent:{available:true,services:['all'],qualities:['LOSSLESS']},'ytp-dl':{available:true,services:['youtube'],qualities:['m4a']}}};
            return {bytes:0,files:0};
          }
        '''+controls+render+save)
        page.evaluate('(android)=>{IS_ANDROID=android;return renderSettings()}',android)
        assert page.evaluate('$("youtubeSignInRow").compareDocumentPosition($("downloadEngineRow")) & Node.DOCUMENT_POSITION_FOLLOWING')
        assert page.evaluate('$("downloadEngineRow").nextElementSibling.id') == 'torrentPlaybackCandidatesRow'
        assert page.locator('#torrentPlaybackCandidates').input_value()=='5'
        assert page.locator('#torrentPrefetchCandidates').input_value()=='1'
        assert page.evaluate('!document.getElementById("torrentPlaybackCandidatesRow").classList.contains("hidden")')
        page.evaluate('''() => {
          $("torrentPlaybackCandidates").value="7";
          $("torrentPrefetchCandidates").value="2";
          return saveSettings({preventDefault(){}});
        }''')
        assert page.evaluate('saved.torrent_playback_candidates')==7
        assert page.evaluate('saved.torrent_prefetch_candidates')==2
        page.evaluate('renderSettings()')
        assert page.locator('#torrentPlaybackCandidates').input_value()=='7'
        page.evaluate('updateEngineControls("ytp-dl","youtube","m4a")')
        assert page.evaluate('document.getElementById("torrentPlaybackCandidatesRow").classList.contains("hidden")')
        page.close()
    browser.close()
print('PASS: desktop and Android settings load, save separate numeric counts, reload, and hide for other engines')
