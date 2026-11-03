"""Telling a lost connection apart from a real download failure.

Every engine reports a dropped connection in its own words (yt-dlp, Node's
error codes in Mornye extensions, httpx, libtorrent). A job that failed that
way, or while the device was offline, says nothing about the song; the
download worker waits for the network and runs it again.
"""
from __future__ import annotations

import socket
import time

NETWORK_ERROR_MARKERS = (
    # yt-dlp / urllib / requests / httpx
    "Unable to download API page",
    "Unable to download webpage",
    "Failed to resolve",
    "nodename nor servname",
    "Name or service not known",
    "Temporary failure in name resolution",
    "No address associated with hostname",
    "Network is unreachable",
    "No route to host",
    "timed out",
    "Connection reset",
    "Connection refused",
    "Connection aborted",
    "RemoteDisconnected",
    "ConnectError",
    "ConnectTimeout",
    "ReadTimeout",
    # Node (Mornye extensions)
    "ETIMEDOUT",
    "ECONNRESET",
    "ECONNREFUSED",
    "ENOTFOUND",
    "EAI_AGAIN",
    "ENETUNREACH",
    "EHOSTUNREACH",
    "socket hang up",
)

#: Hosts any engine needs; one answering is enough to call the device online.
_PROBE_HOSTS = (("www.google.com", 443), ("1.1.1.1", 443), ("www.youtube.com", 443))


def is_network_error(message: object) -> bool:
    text = str(message or "")
    return any(marker in text for marker in NETWORK_ERROR_MARKERS)


def online(timeout: float = 3.0) -> bool:
    for host, port in _PROBE_HOSTS:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


def wait_until_online(should_stop=lambda: False, poll_seconds: float = 5.0,
                      max_seconds: float = 3600.0, settle_seconds: float = 2.0) -> bool:
    """Block until the network answers again; False if stopped or it never did."""
    deadline = time.monotonic() + max_seconds
    while time.monotonic() < deadline:
        if should_stop():
            return False
        if online():
            # Give DNS and routes a moment after the connection returns.
            time.sleep(settle_seconds)
            return not should_stop()
        time.sleep(poll_seconds)
    return False
