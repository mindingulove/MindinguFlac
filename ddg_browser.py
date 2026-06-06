"""Long-running Duck.ai browser worker (subprocess).

Why a subprocess: DuckDuckGo's chat endpoint is gated by "RoboShield" (the
`418 / ERR_CHALLENGE / r:"brs"` anti-bot layer). That challenge is solved by
Duck.ai's own bundled frontend JS (it hashes the `x-vqd-hash-1` client hashes
*and* solves the brs proof-of-work). Re-implementing it is an arms race, and a
headless-shell browser is fingerprinted and blocked outright. The only reliable
path is to let a *real, headed* Chromium run the genuine frontend and send the
chat itself, then capture the response.

This process owns one persistent, stealthed, headed Chromium and exposes a
line-delimited JSON protocol on stdin/stdout (one message per line):

    <- {"id": 1, "prompt": "...", "model": "gpt-5-mini"}   (request, on stdin)
    -> {"id": 1, "ok": true, "text": "..."}                (reply, on stdout)

stdout carries ONLY protocol JSON; all logging goes to stderr. The very first
stdout line is a readiness banner: {"ready": true} or {"ready": false, ...}.

Playwright's sync API is single-threaded, so requests are processed serially.
"""
from __future__ import annotations

import json
import os
import sys
import time


def _default_ua() -> str:
    """A real desktop-Chrome UA matching the host OS.

    Must NOT say "HeadlessChrome" (auto-blocked) and must match the real
    platform — a Mac UA on a Windows Chromium is a fingerprint mismatch that
    RoboShield can flag (navigator.platform / Sec-CH-UA-Platform stay real).
    """
    chrome = "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
    if sys.platform == "win32":
        plat = "Windows NT 10.0; Win64; x64"
    elif sys.platform == "darwin":
        plat = "Macintosh; Intel Mac OS X 10_15_7"
    else:
        plat = "X11; Linux x86_64"
    return f"Mozilla/5.0 ({plat}) {chrome}"


REAL_UA = os.environ.get("MINDINGUFLAC_DDG_UA") or _default_ua()


def _ensure_browsers_path():
    """Point Playwright at the per-user ms-playwright cache.

    In a frozen (PyInstaller) app, bundled Playwright otherwise looks for the
    browser *inside* the app bundle. The browser actually lives in the standard
    per-user cache (where `playwright install chromium` puts it), so set
    PLAYWRIGHT_BROWSERS_PATH to that unless the user already overrode it.
    """
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return
    import pathlib

    home = pathlib.Path.home()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
        path = pathlib.Path(base) / "ms-playwright"
    elif sys.platform == "darwin":
        path = home / "Library" / "Caches" / "ms-playwright"
    else:
        base = os.environ.get("XDG_CACHE_HOME") or str(home / ".cache")
        path = pathlib.Path(base) / "ms-playwright"
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(path)


_ensure_browsers_path()


def _default_profile() -> str:
    override = os.environ.get("MINDINGUFLAC_DDG_PROFILE")
    if override:
        return override
    try:
        import config  # OS-aware app data dir (macOS/Windows/Linux)

        return str(config.app_data_dir() / "ddg-profile")
    except Exception:
        import pathlib

        return str(pathlib.Path.home() / ".mindinguflac-ddg-profile")


_PROFILE_DIR = _default_profile()
# RoboShield blocks the stripped-down "headless-shell" binary, but NOT Chromium's
# new headless mode (`--headless=new`), which uses the full headed rendering stack
# with no visible window. So we launch the full binary (headless=False so
# Playwright doesn't pick the shell) and add `--headless=new` ourselves -> no
# window, still passes. Set MINDINGUFLAC_DDG_HEADED=1 to show the window (debug).
_HEADED = os.environ.get("MINDINGUFLAC_DDG_HEADED", "0") == "1"
_NAV_TIMEOUT_MS = 45_000
_REPLY_TIMEOUT_S = float(os.environ.get("MINDINGUFLAC_DDG_REPLY_TIMEOUT", "75"))

# Injected before any page script: tees window.fetch so we can read the /chat
# SSE stream (CDP getResponseBody can't read streaming bodies).
_TEE_SCRIPT = r"""
(() => {
  const _f = window.fetch;
  window.__ddgChat = {};
  window.__ddgLatest = null;
  window.fetch = function (input, init) {
    const url = (typeof input === 'string') ? input : (input && input.url) || '';
    const pr = _f.apply(this, arguments);
    if (url.includes('/duckchat/v1/chat')) {
      pr.then((resp) => {
        const id = String(Date.now()) + Math.random();
        window.__ddgLatest = id;
        const rec = { status: resp.status, text: '', done: false };
        window.__ddgChat[id] = rec;
        try {
          const rd = resp.clone().body.getReader();
          const dec = new TextDecoder();
          (function pump() {
            rd.read().then(({ done, value }) => {
              if (done) { rec.done = true; return; }
              rec.text += dec.decode(value, { stream: true });
              pump();
            }).catch((e) => { rec.err = String(e); rec.done = true; });
          })();
        } catch (e) { rec.err = String(e); rec.done = true; }
      });
    }
    return pr;
  };
})();
"""


def _log(*a):
    print("[ddg_browser]", *a, file=sys.stderr, flush=True)


def _emit(obj: dict):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _flatten(messages: list, prompt: str) -> str:
    if prompt:
        return prompt
    parts = []
    for m in messages or []:
        content = (m or {}).get("content", "")
        if content:
            parts.append(content)
    return "\n\n".join(parts)


def _parse_sse(raw: str) -> str:
    out = []
    for line in raw.split("\n"):
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            obj = json.loads(data)
            if isinstance(obj, dict) and obj.get("message"):
                out.append(obj["message"])
        except Exception:
            continue
    return "".join(out)


class _Worker:
    def __init__(self):
        self._sp = None
        self.ctx = None
        self.page = None

    def start(self):
        from playwright_stealth import Stealth
        from playwright.sync_api import sync_playwright

        try:
            self._start_with_retry()
        except Exception as e:
            if "Executable doesn't exist" in str(e) or "Please run" in str(e):
                _log("Chromium not found. Attempting automatic installation...")
                try:
                    import subprocess
                    # Run the playwright install command using the current python interpreter
                    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
                    _log("Chromium installed successfully. Retrying start...")
                    self._start_with_retry()
                except Exception as install_exc:
                    _log(f"Automatic Chromium installation failed: {install_exc}")
                    raise install_exc from e
            else:
                raise e

    def _start_with_retry(self):
        from playwright_stealth import Stealth
        from playwright.sync_api import sync_playwright

        if not hasattr(self, "_stealth_cm"):
            self._stealth_cm = Stealth().use_sync(sync_playwright())
        
        p = self._stealth_cm.__enter__()
        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        if not _HEADED:
            # Full Chromium in new-headless mode: no window, full rendering stack.
            args.append("--headless=new")
        self.ctx = p.chromium.launch_persistent_context(
            _PROFILE_DIR,
            headless=False,  # never the blocked headless-shell binary
            args=args,
            user_agent=REAL_UA,
            locale="en-GB",
            viewport={"width": 1280, "height": 900},
        )
        self.ctx.add_init_script(_TEE_SCRIPT)
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.page.goto("https://duck.ai/", wait_until="networkidle", timeout=_NAV_TIMEOUT_MS)
        self.page.wait_for_timeout(1200)
        # Sanity: the prompt box must exist.
        self.page.wait_for_selector('textarea[name="user-prompt"]', timeout=10_000)

    def _new_chat(self):
        try:
            self.page.keyboard.press("Meta+Shift+KeyO")
            self.page.wait_for_timeout(300)
        except Exception:
            pass

    def _ensure_model(self, model: str):
        """Best-effort select a specific Duck.ai model (e.g. "GPT-5").

        The selected model is sticky in the persistent profile, so this is
        usually a no-op verification. Failures are non-fatal: the chat still
        works with whatever model is currently active.
        """
        if not model:
            return
        page = self.page
        want = model.lower().replace("-", "").replace(" ", "").replace(".", "")
        try:
            current = page.evaluate(
                "() => { const ta=document.querySelector('textarea[name=\"user-prompt\"]');"
                " const f=ta?ta.closest('form'):document.body;"
                " const b=[...f.querySelectorAll('button')].find(x=>/gpt|claude|llama|mistral|o[34]/i.test(x.innerText||''));"
                " return b?b.innerText.trim():''; }"
            ) or ""
            if want and want in current.lower().replace("-", "").replace(" ", "").replace(".", ""):
                return
            # Open the model picker (the composer button showing the model name) and choose.
            page.locator('textarea[name="user-prompt"]').wait_for(timeout=4000)
            picker = page.locator('button', has_text=__import__("re").compile(r"gpt|claude|llama|mistral", __import__("re").I)).last
            picker.click(timeout=3000)
            page.wait_for_timeout(350)
            page.get_by_text(model, exact=False).first.click(timeout=3000)
            page.wait_for_timeout(300)
            _log(f"model set to {model}")
        except Exception as exc:
            _log(f"model select best-effort failed ({model}): {exc}")
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass

    def _enable_web_search(self) -> bool:
        """Turn on Duck.ai's per-conversation "Web Search" tool (idempotent).

        Web Search is a `menuitemradio` under the composer "Tools" menu and
        resets to off on every new chat, so we enable it on each request that
        needs live data. Only clicks when currently off (clicking when on would
        disable it).
        """
        page = self.page
        try:
            page.get_by_role("button", name="Tools").first.click(timeout=4000)
            page.wait_for_timeout(350)
            radio = page.locator('button[role="menuitemradio"]').filter(has_text="Web Search").first
            checked = None
            try:
                checked = radio.get_attribute("aria-checked")
            except Exception:
                checked = None
            if checked != "true":
                radio.click(timeout=4000)
                page.wait_for_timeout(300)
            else:
                page.keyboard.press("Escape")
            page.wait_for_timeout(200)
            return True
        except Exception as exc:
            _log(f"web search enable failed: {exc}")
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            return False

    def ask(self, prompt: str, web_search: bool = False, ensure_model: str = "", timeout_s: float = 0.0) -> dict:
        page = self.page
        # Reset capture + start a fresh conversation each call (no context bleed).
        page.evaluate("() => { window.__ddgChat = {}; window.__ddgLatest = null; }")
        self._new_chat()
        if ensure_model:
            self._ensure_model(ensure_model)
        if web_search:
            self._enable_web_search()
        ta = page.locator('textarea[name="user-prompt"]')
        ta.click()
        ta.fill(prompt)
        page.wait_for_timeout(120)
        for _btn in ("Send", "Ask"):
            try:
                page.get_by_role("button", name=_btn).first.click(timeout=3000)
                break
            except Exception:
                continue
        else:
            ta.press("Enter")

        deadline = time.time() + (timeout_s if timeout_s and timeout_s > 0 else _REPLY_TIMEOUT_S)
        rec = None
        while time.time() < deadline:
            page.wait_for_timeout(300)
            rec = page.evaluate(
                "() => { const id = window.__ddgLatest; return id ? window.__ddgChat[id] : null; }"
            )
            if rec and rec.get("done"):
                break
        if not rec:
            return {"ok": False, "error": "no /chat request observed (UI may have changed)"}
        status = rec.get("status")
        raw = rec.get("text", "") or ""
        if status != 200:
            return {"ok": False, "status": status, "error": f"HTTP {status}", "body": raw[:400]}
        return {"ok": True, "status": 200, "text": _parse_sse(raw)}

    def close(self):
        try:
            if self.ctx:
                self.ctx.close()
        except Exception:
            pass
        try:
            self._stealth_cm.__exit__(None, None, None)
        except Exception:
            pass


def main():
    worker = _Worker()
    try:
        worker.start()
    except Exception as exc:  # readiness failure
        _emit({"ready": False, "error": f"{type(exc).__name__}: {exc}"})
        return
    _emit({"ready": True})
    _log("ready; headed=%s profile=%s" % (_HEADED, _PROFILE_DIR))

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        rid = req.get("id")
        if req.get("cmd") == "shutdown":
            break
        prompt = _flatten(req.get("messages", []), req.get("prompt", ""))
        if not prompt:
            _emit({"id": rid, "ok": False, "error": "empty prompt"})
            continue
        try:
            res = worker.ask(
                prompt,
                web_search=bool(req.get("web_search")),
                ensure_model=req.get("ensure_model", "") or "",
                timeout_s=float(req.get("timeout_s") or 0),
            )
        except Exception as exc:
            res = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        res["id"] = rid
        _emit(res)

    worker.close()


if __name__ == "__main__":
    main()
