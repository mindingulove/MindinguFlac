"""YouTube sign-in on the phone, the counterpart of desktop.py's login window.

YoutubeLoginActivity.java signs in in a WebView and passes the cookies from
Android's CookieManager to :func:`save`, which stores them the way the desktop
does (backend_ytpdl.import_youtube_webview_cookies), so yt-dlp downloads as the
signed-in user instead of hitting YouTube's "confirm you're not a bot" wall.
"""
from __future__ import annotations

from http.cookies import CookieError, Morsel

#: CookieManager returns only "name=value; ..." per URL, so each URL's
#: cookies are recorded for the domain they were read from.
_COOKIE_DOMAINS = (".youtube.com", ".google.com")


def _records(headers: list[str]) -> list[dict]:
    records = []
    for domain, header in zip(_COOKIE_DOMAINS, headers):
        record = {}
        for part in str(header or "").split(";"):
            name, _, value = part.strip().partition("=")
            if not name:
                continue
            morsel = Morsel()
            try:
                morsel.set(name, value, value)
            except CookieError:
                continue
            morsel["domain"] = domain
            morsel["path"] = "/"
            morsel["secure"] = True
            record[name] = morsel
        records.append(record)
    return records


def save(youtube_cookies: str, google_cookies: str) -> bool:
    """Store the WebView session; False until it holds a signed-in cookie."""
    import backend_ytpdl

    return backend_ytpdl.import_youtube_webview_cookies(_records([youtube_cookies, google_cookies]))


def _activity():
    from java import jclass  # type: ignore

    return jclass("com.mindinguflac.android.YoutubeLoginActivity")


def sign_out() -> bool:
    import backend_ytpdl

    _activity().clearSession()
    backend_ytpdl.clear_saved_youtube_session()
    return True


def install(app) -> None:
    """Give app.py's login hooks the phone's sign-in screen."""
    app._youtube_login_fn = lambda: bool(_activity().open())
    app._youtube_login_active_fn = lambda: bool(_activity().isOpen())
    app._youtube_login_outcome_fn = lambda: str(_activity().outcome())
    app._youtube_logout_fn = sign_out
