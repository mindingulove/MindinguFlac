"""Request-scoped transports for the retained lyrics providers."""
from contextlib import asynccontextmanager
from contextvars import ContextVar
import os

import httpx

_client = ContextVar("mindinguflac_lyrics_http", default=None)


@asynccontextmanager
async def request_scope():
    async with httpx.AsyncClient(follow_redirects=True, timeout=10,
                                 headers={"Accept-Encoding": "identity"}) as client:
        token = _client.set(client)
        try:
            yield
        finally:
            _client.reset(token)


class NetworkManager:
    @classmethod
    async def get_async_client_safe(cls):
        client = _client.get()
        if client is None:
            raise RuntimeError("Lyrics HTTP requires a request scope")
        return client


def get_amazon_endpoint(_key):
    # Optional relay; the other providers do not need an endpoint registry.
    return os.getenv("MINDINGUFLAC_AMAZON_LYRICS_URL", "").rstrip("/")
