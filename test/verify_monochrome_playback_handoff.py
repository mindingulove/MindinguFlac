"""Exercise first-click autoplay recovery and instant default-device handoff."""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "static/app.js").read_text()
start = SOURCE.index("function tryStartAudio(")
end = SOURCE.index("// ---------------------------------------------------------------------------\n// Search & Suggestions", start)
try_start_audio = SOURCE[start:end]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.add_script_tag(content='''
      Object.defineProperty(navigator, "userAgent", {value: "Macintosh AppleWebKit"});
      const IS_ANDROID = false;
      const state = {
        currentStreamUrl: "https://tracks.monochrome.st/track/154140565313687552",
        playbackRequestId: 7,
        directStreamNativeFallbackAttempted: false,
        directStreamPosition: 0,
        manualPauseRequested: false,
        audioBuffering: false,
        autoplayWanted: true,
      };
      let nativeStartArgs = null;
      const track = {title: "Test track"};
      const audio = {
        currentTime: 0,
        play: () => Promise.reject(new DOMException("autoplay denied", "NotAllowedError")),
        pause() {}, removeAttribute() {}, load() {},
      };
      const isMonochromeDirectStreamUrl = url => String(url).includes("tracks.monochrome.st/track/");
      const logMonochromePlaybackActivity = () => {};
      const syncPlayPauseButton = () => {};
      const setPlayerStatusIcon = () => {};
      const setPlayerStatus = () => {};
      const startNativeAudio = (...args) => { nativeStartArgs = args; return Promise.resolve({ok: true}); };
    ''' + try_start_audio)
    page.evaluate('tryStartAudio(audio, track, state.playbackRequestId, null)')
    page.wait_for_function("nativeStartArgs !== null")
    assert page.evaluate("nativeStartArgs[0] === ''")
    assert page.evaluate("nativeStartArgs[1] === track")
    assert page.evaluate("nativeStartArgs[2] === 7")
    assert page.evaluate("nativeStartArgs[4] === state.currentStreamUrl")
    assert page.evaluate("nativeStartArgs[5] === true")
    assert page.evaluate("state.directStreamNativeFallbackAttempted")
    assert page.evaluate("state.audioBuffering")
    browser.close()

# The native Monochrome/default-output fast path must run before the browser
# device enumeration that may invoke getUserMedia or wait for permission.
click_start = SOURCE.index("li.onclick = async () => {", SOURCE.index("async function _renderConnectDevices"))
click_end = SOURCE.index("    list.appendChild(li);", click_start)
click_body = SOURCE[click_start:click_end]
assert 'targetId === "" && isMonochromeDirectStreamUrl(state.currentStreamUrl)' in click_body
assert click_body.index("setAudioOutputDevice(\"\", item.name)") < click_body.index("const freshDevs = await _getOutputDevices()")
assert click_body.index("await setAudioOutputDevice(\"\", item.name)") < click_body.index("closeConnectPanel();")
render_start = SOURCE.index("async function _renderConnectDevices(")
render_end = SOURCE.index("// Section: available output devices.", render_start)
assert "nativeAvailable ? [] : await _getOutputDevices()" in SOURCE[render_start:render_end]
print("PASS: autoplay denial hands first Monochrome play to native audio; native device picker avoids browser permission enumeration and closes only after a confirmed route")
