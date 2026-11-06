"""Minimal asyncio client for the Automation pipe (overlapped I/O via the Proactor event loop).

Used by the test-suite and tools. Garvis has its own copy in `app/glass/client.py` so it stays
independent of this package.
"""
from __future__ import annotations

import asyncio
import itertools

from glass.core import ipc


class RemoteError(Exception):
    def __init__(self, err: dict):
        super().__init__(f"{err.get('code')}: {err.get('message')}")
        self.code = err.get("code")
        self.message = err.get("message")
        self.data = err.get("data")


class _Proto(asyncio.Protocol):
    def __init__(self, client: "AsyncClient"):
        self.client = client
        self.decoder = ipc.FrameDecoder()

    def connection_made(self, transport):
        self.client._transport = transport

    def data_received(self, data):
        for msg in self.decoder.feed(data):
            self.client._dispatch(msg)

    def connection_lost(self, exc):
        self.client._lost(exc)


class AsyncClient:
    def __init__(self, pipe_path: str):
        self.pipe_path = pipe_path
        self._transport = None
        self._pending: dict[int, asyncio.Future] = {}
        self._ids = itertools.count(1)
        self.notifications: asyncio.Queue = asyncio.Queue()
        self.connected = False

    async def connect(self) -> None:
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_pipe_connection(lambda: _Proto(self), self.pipe_path)
        self._transport = transport
        self.connected = True

    async def hello(self, token: str, client: str = "test") -> dict:
        return await self.call("hello", {"protocol": ipc.PROTOCOL_VERSION, "client": client, "token": token})

    async def call(self, method: str, params: dict | None = None, timeout: float = 30.0):
        if not self.connected or self._transport is None:
            raise ConnectionError("not connected")
        mid = next(self._ids)
        fut = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        self._transport.write(ipc.encode(ipc.request(mid, method, params)))
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(mid, None)

    async def send_raw(self, data: bytes) -> None:
        self._transport.write(data)

    def _dispatch(self, msg: dict) -> None:
        mid = msg.get("id")
        if mid is None and "method" in msg:
            self.notifications.put_nowait(msg)
            return
        fut = self._pending.get(mid)
        if fut is None:
            if "error" in msg:
                self.notifications.put_nowait(msg)
            return
        if fut.done():
            return
        if "error" in msg:
            fut.set_exception(RemoteError(msg["error"]))
        else:
            fut.set_result(msg.get("result"))

    def _lost(self, exc) -> None:
        self.connected = False
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError(f"pipe closed: {exc}"))

    async def close(self) -> None:
        if self._transport is not None:
            self._transport.close()
        self.connected = False
