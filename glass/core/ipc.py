"""Wire format shared by every Project Glass pipe (Shell <-> Control Center, Automation <-> clients).

Each message is a UTF-8 JSON object prefixed by its length as a 4-byte little-endian unsigned int.

    request       {"id": 7, "method": "windows.list", "params": {...}}
    response      {"id": 7, "result": {...}}
    error         {"id": 7, "error": {"code": "stale_reference", "message": "...", "data": {...}}}
    notification  {"method": "event", "params": {...}}          (no id; server -> client)

See docs/PROTOCOL.md for the method catalogue.
"""
from __future__ import annotations

import json
import struct
from typing import Any

PROTOCOL_VERSION = 1
MAX_FRAME = 8 * 1024 * 1024
_HEADER = struct.Struct("<I")


class ErrorCode:
    UNAUTHORIZED = "unauthorized"            # no/invalid token or hello not done
    FORBIDDEN_SCOPE = "forbidden_scope"      # the token lacks the scope this method needs
    DENIED_APP = "denied_app"                # the target app is on the deny list
    STOPPED = "stopped"                      # emergency stop is active
    STALE_REFERENCE = "stale_reference"      # the element no longer exists; re-query, nothing was redirected
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"                  # a query matched several windows/elements; candidates in data
    UNSUPPORTED = "unsupported_pattern"      # the element does not support the requested action
    INSUFFICIENT_SEMANTICS = "insufficient_semantics"  # app exposes too little UI Automation information
    ELEVATED_TARGET = "elevated_target"      # UIPI: the window runs elevated; a normal process cannot drive it
    INVALID_PARAMS = "invalid_params"
    TIMEOUT = "timeout"
    VERSION = "unsupported_version"
    INTERNAL = "internal"
    UNKNOWN_METHOD = "unknown_method"
    BUSY = "busy"


class ProtocolError(Exception):
    """Raised by handlers; becomes an error response."""

    def __init__(self, code: str, message: str, data: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_dict(self) -> dict:
        err = {"code": self.code, "message": self.message}
        if self.data is not None:
            err["data"] = self.data
        return err


def encode(message: dict) -> bytes:
    body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_FRAME:
        raise ValueError(f"message too large ({len(body)} bytes)")
    return _HEADER.pack(len(body)) + body


class FrameDecoder:
    """Incremental decoder: feed raw bytes, get complete messages back."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[dict]:
        self._buf += data
        out: list[dict] = []
        while len(self._buf) >= _HEADER.size:
            (length,) = _HEADER.unpack_from(self._buf, 0)
            if length > MAX_FRAME:
                raise ProtocolError(ErrorCode.INVALID_PARAMS, f"frame of {length} bytes exceeds the limit")
            if len(self._buf) < _HEADER.size + length:
                break
            body = bytes(self._buf[_HEADER.size:_HEADER.size + length])
            del self._buf[:_HEADER.size + length]
            try:
                msg = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProtocolError(ErrorCode.INVALID_PARAMS, f"malformed JSON frame: {exc}") from exc
            if not isinstance(msg, dict):
                raise ProtocolError(ErrorCode.INVALID_PARAMS, "a frame must contain a JSON object")
            out.append(msg)
        return out


def request(msg_id: int, method: str, params: dict | None = None) -> dict:
    return {"id": msg_id, "method": method, "params": params or {}}


def response(msg_id: Any, result: Any) -> dict:
    return {"id": msg_id, "result": result}


def error(msg_id: Any, err: ProtocolError) -> dict:
    return {"id": msg_id, "error": err.to_dict()}


def notification(method: str, params: dict) -> dict:
    return {"method": method, "params": params}
