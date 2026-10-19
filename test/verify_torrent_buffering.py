"""Browser checks for buffering, pause intent, live-job recovery and prefetch."""
from pathlib import Path
from playwright.sync_api import sync_playwright
root = Path(__file__).resolve().parents[1]
s = (root / 'static/app.js').read_text()
helpers = s[s.index('function activeJobHasPlayableAudio('):s.index('function isVideoLibraryPath(')]
prefetch = s[s.index('function maybePrefetchUpcomingTracks('):s.index('async function prefetchNextTracks(')]
error = s[s.index('  audio.onerror = () => {'):s.index('  $("seekBar").oninput =', s.index('  audio.onerror = () => {'))]
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.add_script_tag(content='''
      const state={currentTrack:{duration_ms:100000}, activeJobId:'job', currentStreamUrl:'/api/library/stream_active_job?job_id=job',lastActiveReadyBytes:4000000, manualPauseRequested:false, prefetchedForRequestId:-1,playbackRequestId:1};
      let searches=0, pauses=0, prefetched=0, videos=0;
      const audio={src:state.currentStreamUrl,currentSrc:state.currentStreamUrl,currentTime:12,error:{code:3},pause(){pauses++}};
      const isActiveJobStreamUrl=url=>url.includes('stream_active_job');
      const selectMusicItem=()=>{searches++};
      const setPlayerStatus=()=>{};
      const prefetchNextTracks=async()=>{prefetched++};
      const prefetchNextVideos=()=>{videos++};
    ''' + helpers + prefetch + error)
    assert page.evaluate('activeJobHasPlayableAudio({active_audio_size:10000000,active_audio_ready_bytes:600000})') is False
    assert page.evaluate('activeJobHasPlayableAudio({active_audio_size:10000000,active_audio_ready_bytes:3000000})') is True
    page.evaluate('audio.onerror()')
    assert page.evaluate('searches') == 0
    assert page.evaluate('state.activeJobId') == 'job'
    assert page.evaluate('state.rebuffering') is True
    assert page.evaluate('state.rebufferPosition') == 12
    assert page.evaluate('activeJobHasPlayableAudio({active_audio_size:10000000,active_audio_ready_bytes:4500000})') is False
    page.evaluate('state.manualPauseRequested=true;audio.onerror()')
    assert page.evaluate('state.manualPauseRequested') is True
    assert page.evaluate('state.autoplayWanted') is False
    page.evaluate('state.manualPauseRequested=false;maybePrefetchUpcomingTracks(3);maybePrefetchUpcomingTracks(4)')
    assert page.evaluate('prefetched') == 1
    assert page.evaluate('videos') == 1
    assert page.evaluate('searches') == 0
    browser.close()
print('PASS: larger buffer, same-job recovery, manual pause preserved, active-stream prefetch starts once')
