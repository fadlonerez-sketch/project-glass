"""A minimal blocking client for Glass pipes (request -> response, no notifications). Used by the recovery
command and tests; the Shell, the Control Center and Garvis use event-driven clients instead."""
from __future__ import annotations

import time

from glass.core import ipc, security


class PipeClient:
    def __init__(self, kind: str = "Shell", token: str | None = None, timeout: float = 3.0, client: str = "owner"):
        self.path = security.pipe_path(kind)
        self.timeout = timeout
        self._token = token if token is not None else security.read_secret("owner")
        self._client = client
        self._f = None
        self._dec = ipc.FrameDecoder()
        self._id = 0

    def __enter__(self):
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self._f = open(self.path, "r+b", buffering=0)
                break
            except FileNotFoundError:
                raise ConnectionError("not running") from None
            except OSError:
                if time.monotonic() > deadline:
                    raise ConnectionError("pipe busy") from None
                time.sleep(0.05)
        self.call("hello", {"protocol": ipc.PROTOCOL_VERSION, "client": self._client, "token": self._token or ""})
        return self

    def __exit__(self, *exc):
        if self._f:
            self._f.close()

    def call(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        self._f.write(ipc.encode(ipc.request(self._id, method, params)))
        while True:
            chunk = self._f.read(65536)
            if not chunk:
                raise ConnectionError("pipe closed")
            for msg in self._dec.feed(chunk):
                if msg.get("id") == self._id:
                    if "error" in msg:
                        err = msg["error"]
                        raise ipc.ProtocolError(err.get("code", "internal"), err.get("message", ""), err.get("data"))
                    return msg.get("result")
