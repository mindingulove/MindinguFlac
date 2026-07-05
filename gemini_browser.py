"""Long-running Gemini browser worker (subprocess).

Similar to ddg_browser.py, but for gemini.google.com.
Note: Gemini requires a Google account login. The user should run with 
MINDINGUFLAC_GEMINI_HEADED=1 once to log in manually if the session expires.
"""
from __future__ import annotations

import json
import os
import sys
import time
import re

def _default_ua() -> str:
    chrome = "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
    if sys.platform == "win32":
        plat = "Windows NT 10.0; Win64; x64"
    elif sys.platform == "darwin":
        plat = "Macintosh; Intel Mac OS X 10_15_7"
    else:
        plat = "X11; Linux x86_64"
    return f"Mozilla/5.0 ({plat}) {chrome}"

REAL_UA = os.environ.get("MINDINGUFLAC_GEMINI_UA") or _default_ua()

def _ensure_browsers_path():
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
    override = os.environ.get("MINDINGUFLAC_GEMINI_PROFILE")
    if override:
        return override
    try:
        import config
        return str(config.app_data_dir() / "gemini-profile")
    except Exception:
        import pathlib
        return str(pathlib.Path.home() / ".mindinguflac-gemini-profile")

_PROFILE_DIR = _default_profile()
_HEADED = os.environ.get("MINDINGUFLAC_GEMINI_HEADED", "0") == "1"
_DEBUG_TEXT = os.environ.get("MINDINGUFLAC_GEMINI_DEBUG", "0") == "1"
_NAV_TIMEOUT_MS = 90_000
_REPLY_TIMEOUT_S = float(os.environ.get("MINDINGUFLAC_GEMINI_REPLY_TIMEOUT", "180"))

def _log(*a):
    try:
        print("[gemini_browser]", *a, file=sys.stderr, flush=True)
    except OSError:
        pass

def _emit(obj: dict):
    try:
        sys.stdout.write(json.dumps(obj, ensure_ascii=True) + "\n")
        sys.stdout.flush()
    except OSError:
        pass

class _Worker:
    def __init__(self):
        self.browser = None
        self.ctx = None
        self.page = None
        self._sp_cm = None

    def start(self):
        try:
            self._start_with_retry()
        except Exception as e:
            if "Executable doesn't exist" in str(e) or "Please run" in str(e):
                if getattr(sys, "frozen", False):
                    raise RuntimeError(
                        "Gemini browser unavailable: bundled Playwright Chromium is missing. "
                        "Rebuild the Windows package after installing Playwright browsers."
                    ) from e
                _log("Chromium not found. Attempting automatic installation...")
                try:
                    import subprocess
                    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
                    _log("Chromium installed successfully. Retrying start...")
                    self._start_with_retry()
                except Exception as install_exc:
                    _log(f"Automatic Chromium installation failed: {install_exc}")
                    raise install_exc from e
            else:
                raise e

    def _start_with_retry(self):
        from playwright.sync_api import sync_playwright
        if not self._sp_cm:
            self._sp_cm = sync_playwright()
        p = self._sp_cm.__enter__()

        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        headless = not _HEADED
        if not _HEADED:
            # Use Chromium's new headless mode by default so Gemini never
            # needs to open a GUI browser window.
            args.append("--headless=new")

        # Use a persistent context like the working Duck.ai worker. Gemini's
        # browser flow is less tolerant of the launch()+new_context split.
        self.ctx = p.chromium.launch_persistent_context(
            _PROFILE_DIR,
            headless=headless,
            args=args,
            user_agent=REAL_UA,
            viewport={"width": 1280, "height": 900},
        )

        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.page.goto("https://gemini.google.com/app", wait_until="networkidle", timeout=_NAV_TIMEOUT_MS)
        
        # Give the page a moment to settle/check cookies
        self.page.wait_for_timeout(3000)
        
        # Check if we are on a sign-in page but continue anyway to see if guest mode works
        if "signin" in self.page.url or self.page.locator('text=Sign in').count() > 0:
            _log("Sign-in detected. Running in Guest Mode (Incognito).")
            
        # Handle "Stay signed out" or similar guest mode prompts if they appear
        try:
            guest_btn = self.page.get_by_role("button", name=re.compile(r"Stay signed out|Use without an account", re.I))
            if guest_btn.count() > 0:
                guest_btn.first.click(timeout=3000)
                self.page.wait_for_timeout(1000)
        except Exception:
            pass

    def _limit_reached(self) -> bool:
        """Detect when Gemini guest mode limit is reached."""
        try:
            # Check for common limit/sign-in enforcement strings
            return bool(self.page.evaluate(
                "() => /sign in to continue|reached your limit|chat trial has ended/i"
                ".test(document.body.innerText || '')"
            ))
        except Exception:
            return False

    def _ensure_ready(self):
        # Check limit first
        if self._limit_reached():
            _log("Gemini limit reached in this incognito session.")
            return False

        # Gemini prompt box is often a contenteditable div
        # In Guest Mode, it might take a moment to appear after dismissing popups
        try:
            self.page.wait_for_selector('[role="textbox"][aria-label="Enter a prompt for Gemini"]', timeout=15000)
            return True
        except Exception:
            # Try to see if there's a "Chat with Gemini" or "Get started" button first
            try:
                for btn_text in ["Chat with Gemini", "Get started", "I agree", "Accept", "Keep using Gemini"]:
                    btn = self.page.get_by_role("button", name=re.compile(btn_text, re.I))
                    if btn.count() > 0:
                        btn.first.click(timeout=2000)
                        self.page.wait_for_timeout(1000)
                
                self.page.wait_for_selector('[role="textbox"][aria-label="Enter a prompt for Gemini"]', timeout=10000)
                return True
            except Exception:
                return False

    def _ensure_model(self, model: str):
        if not model:
            return
        page = self.page
        try:
            # Look for the model picker button. It often contains text like "Gemini", "Flash", "Pro"
            # or version numbers. In the user's screenshot it's a pill with "Pro" and a chevron.
            picker = page.locator('button', has_text=re.compile(r"Flash|Pro|Gemini|3\.", re.I)).last
            if not picker.count():
                return
                
            current = picker.inner_text().lower()
            # Heuristic match
            target = model.lower()
            if target in current or (target == "flash" and "3.5" in current) or (target == "pro" and "3.1" in current):
                return
                
            picker.click(timeout=3000)
            page.wait_for_timeout(500)
            
            # Click the model in the menu
            menu_item = None
            if target == "flash-lite":
                menu_item = page.locator('text=Flash-Lite').first
            elif target == "flash":
                menu_item = page.locator('text=3.5 Flash').first
            elif target == "pro":
                menu_item = page.locator('text=3.1 Pro').first
            else:
                menu_item = page.get_by_text(model, exact=False).first
                
            if menu_item and menu_item.count():
                menu_item.click(timeout=3000)
                page.wait_for_timeout(500)
                _log(f"Model set to {model}")
        except Exception as exc:
            _log(f"Model select best-effort failed ({model}): {exc}")
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass

    def _new_chat(self):
        """Start a fresh Gemini chat for this request.

        The worker process stays alive, but each request should get its own
        conversation so stale context does not bleed across lookups.
        """
        page = self.page
        try:
            page.goto("https://gemini.google.com/app", wait_until="networkidle", timeout=_NAV_TIMEOUT_MS)
            page.wait_for_timeout(1000)
            page.wait_for_selector('[role="textbox"][aria-label="Enter a prompt for Gemini"]', timeout=15000)
        except Exception:
            pass

    def _extract_response_text(self, page) -> str:
        """Pull the latest Gemini response from the live page text.

        Gemini's DOM has shifted away from the old `message-content` shape. In
        the current UI, the useful text lives in the Quill editor wrapper and is
        surfaced in page text as a `Gemini said` section. Use that first, then
        fall back to visible response containers.
        """
        try:
            body_text = page.locator("body").inner_text(timeout=2000).strip()
        except Exception:
            body_text = ""

        if body_text:
            marker = "Gemini said"
            idx = body_text.rfind(marker)
            if idx != -1:
                chunk = body_text[idx + len(marker):].strip()
                # Stop at the next conversation chrome or footer noise.
                stop_markers = [
                    "\n\nNew\n",
                    "\nNew\n",
                    "\nGemini is AI and can make mistakes.",
                    "\nConversation with Gemini\n",
                ]
                for stop in stop_markers:
                    pos = chunk.find(stop)
                    if pos != -1:
                        chunk = chunk[:pos].strip()
                if chunk:
                    return chunk

        for sel in [
            'message-content',
            '.message-content',
            '[aria-label*="response"]',
            '.ql-editor',
            'main .ql-editor',
            'main',
        ]:
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    txt = loc.last.inner_text(timeout=2000).strip()
                    if txt:
                        return txt
            except Exception:
                continue
        return ""

    def ask(self, prompt: str, ensure_model: str = "", timeout_s: float = 0.0) -> dict:
        if not self._ensure_ready():
            if self._limit_reached():
                return {"ok": False, "rate_limited": True, "error": "Gemini guest limit reached. Restart worker for a fresh session."}
            return {"ok": False, "error": "Gemini interface not ready or login required."}

        page = self.page
        self._new_chat()
        if ensure_model:
            self._ensure_model(ensure_model)
            
        # Find prompt box
        box = page.get_by_role("textbox", name="Enter a prompt for Gemini").first
        box.click()
        box.fill(prompt)
        page.wait_for_timeout(200)
        page.keyboard.press("Enter")

        deadline = None if timeout_s <= 0 else time.time() + timeout_s
        
        last_text = ""
        stable_count = 0
        
        # Dead zone: wait for Gemini to acknowledge the prompt
        page.wait_for_timeout(4000)
        
        has_started_responding = False
        
        while deadline is None or time.time() < deadline:
            page.wait_for_timeout(2000)
            try:
                # 1. Detect "Searching" or "Thinking" state
                thinking_selectors = [
                    'text=Searching', 'text=Thinking', 'text=Checking',
                    '.progress-bar', '.loading-spinner', 'mat-progress-bar',
                    'button[aria-label*="Stop"]', 'button:has(svg path[d*="M6"])' # Square stop icon
                ]
                is_thinking = False
                for ts in thinking_selectors:
                    try:
                        if page.locator(ts).count() > 0:
                            is_thinking = True
                            break
                    except: pass
                
                # 2. Extract text from Gemini's visible response sections.
                current_text = self._extract_response_text(page)

                # 3. Check if we have a real response starting (not just our own prompt echo)
                if not has_started_responding:
                    if current_text.strip():
                        has_started_responding = True
                        _log("Detected start of assistant response.")
                    else:
                        # Still waiting for anything other than our prompt
                        stable_count = 0
                        continue

                # 4. Stability Logic
                if current_text == last_text and len(current_text) > 0:
                    stable_count += 1
                else:
                    stable_count = 0
                last_text = current_text
                
                if _HEADED:
                    _log(f"Stability: {stable_count}/6 (thinking={is_thinking}, chars={len(current_text)})")

                if is_thinking:
                    stable_count = 0 # Reset while it's still doing something
                    continue

                # If text is stable for 12 seconds (6 * 2s), assume truly done
                if stable_count >= 6:
                    break
            except Exception as e:
                if _HEADED: _log(f"Loop error: {e}")
                continue

        if deadline is not None and (not last_text or len(last_text.strip()) < 5):
            return {"ok": False, "error": "No response captured from Gemini (timeout)."}

        _log(f"Captured {len(last_text)} chars from Gemini.")
        if _HEADED or _DEBUG_TEXT:
            preview = last_text[:4000]
            _log("Captured text:", preview)
        return {"ok": True, "text": last_text}

    def close(self):
        try:
            if self.ctx:
                self.ctx.close()
        except Exception:
            pass
        if self._sp_cm:
            try:
                self._sp_cm.__exit__(None, None, None)
            except Exception:
                pass

def main():
    worker = _Worker()
    try:
        worker.start()
    except Exception as exc:
        _emit({"ready": False, "error": str(exc)})
        return
    _emit({"ready": True})

    for line in sys.stdin:
        line = line.strip()
        if not line: continue
        try:
            req = json.loads(line)
        except Exception: continue
        
        rid = req.get("id")
        if req.get("cmd") == "shutdown": break
        
        prompt = req.get("prompt", "")
        if not prompt and req.get("messages"):
            prompt = req.get("messages")[-1].get("content", "")
            
        if not prompt:
            _emit({"id": rid, "ok": False, "error": "empty prompt"})
            continue
            
        try:
            res = worker.ask(
                prompt, 
                ensure_model=req.get("ensure_model", "") or "",
                timeout_s=float(req.get("timeout_s") or 0)
            )
        except Exception as exc:
            res = {"ok": False, "error": str(exc)}
        
        res["id"] = rid
        _emit(res)
    worker.close()

if __name__ == "__main__":
    main()
