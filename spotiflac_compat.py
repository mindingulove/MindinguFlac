from __future__ import annotations

import asyncio
import queue
import threading
from collections.abc import Awaitable, Callable
from typing import Any


def run_async_blocking(awaitable: Awaitable[Any]) -> Any:
    """Run an async SpotiFLAC API from existing synchronous Mindinguflac code."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    result_queue: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

    def _runner() -> None:
        try:
            result_queue.put((True, asyncio.run(awaitable)))
        except BaseException as exc:
            result_queue.put((False, exc))

    thread = threading.Thread(target=_runner, daemon=True, name="spotiflac-async-bridge")
    thread.start()
    ok, value = result_queue.get()
    thread.join()
    if ok:
        return value
    raise value


def call_sync_or_async(obj: object, sync_name: str, async_name: str, *args: Any, **kwargs: Any) -> Any:
    method = getattr(obj, sync_name, None)
    if callable(method):
        return method(*args, **kwargs)

    async_method = getattr(obj, async_name, None)
    if not callable(async_method):
        raise AttributeError(f"{type(obj).__name__} has neither {sync_name} nor {async_name}")
    return run_async_blocking(async_method(*args, **kwargs))


def has_sync_or_async(obj: object, sync_name: str, async_name: str) -> bool:
    return callable(getattr(obj, sync_name, None)) or callable(getattr(obj, async_name, None))
