"""Per-user secrets and pipe identity.

* Pipe names embed a hash of the current user's SID, and every Glass pipe is created with an ACL that
  admits only that user (Qt's UserAccessOption), plus an explicit check that the client is local.
* Client tokens are random 256-bit values. Servers keep only their SHA-256; the plain token is stored for
  the owning client DPAPI-protected (CurrentUser scope) under %LOCALAPPDATA%\\ProjectGlass\\secrets.

Honest limit: DPAPI CurrentUser data can be read by any process running as the same Windows user, so
the token separates *users* and *scopes*, not processes of the same user. Glass treats the logged-on user
as the trust boundary and adds scopes, deny lists, an audit log and an emergency stop on top.
"""
from __future__ import annotations

import ctypes
import hashlib
import os
import hmac
import logging
import secrets
import sys
from ctypes import wintypes
from pathlib import Path

from glass.core import paths

_ENTROPY = b"ProjectGlass.v1"
log = logging.getLogger(__name__)


# --------------------------------------------------------------------------------------------- SID

def current_user_sid() -> str:
    if sys.platform != "win32":
        return "S-test"
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                             ctypes.POINTER(wintypes.DWORD)]
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        size = wintypes.DWORD()
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))  # TokenUser
        buf = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(token, 1, buf, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        psid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
        out = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(psid, ctypes.byref(out)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return out.value
        finally:
            kernel32.LocalFree(out)
    finally:
        kernel32.CloseHandle(token)


def pipe_name(kind: str) -> str:
    """Local server name (QLocalServer/QLocalSocket form). The Windows path is \\\\.\\pipe\\<name>."""
    digest = hashlib.sha256(current_user_sid().encode()).hexdigest()[:16]
    suffix = os.environ.get("GLASS_PIPE_SUFFIX", "")   # isolates automated test instances from a running Glass
    return f"ProjectGlass.{kind}.{digest}" + (f".{suffix}" if suffix else "")


def pipe_path(kind: str) -> str:
    return "\\\\.\\pipe\\" + pipe_name(kind)


# --------------------------------------------------------------------------------------------- DPAPI

class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> tuple[_Blob, ctypes.Array]:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _crypt(protect: bool, data: bytes) -> bytes:
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    fn.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.POINTER(_Blob), ctypes.c_void_p,
                   ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    src, _keep1 = _blob(data)
    ent, _keep2 = _blob(_ENTROPY)
    out = _Blob()
    # CRYPTPROTECT_UI_FORBIDDEN = 0x1
    if not fn(ctypes.byref(src), None, ctypes.byref(ent), None, None, 0x1, ctypes.byref(out)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def protect(data: bytes) -> bytes:
    return _crypt(True, data)


def unprotect(data: bytes) -> bytes:
    return _crypt(False, data)


# --------------------------------------------------------------------------------------------- tokens

def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_matches(token: str, expected_hash: str) -> bool:
    return hmac.compare_digest(token_hash(token), expected_hash)


def secret_path(name: str) -> Path:
    return paths.secrets_dir() / f"{name}.dpapi"


def write_secret(name: str, value: str) -> Path:
    path = secret_path(name)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(protect(value.encode("utf-8")))
    tmp.replace(path)
    return path


def read_secret(name: str, directory: Path | None = None) -> str | None:
    path = (directory / f"{name}.dpapi") if directory else secret_path(name)
    try:
        return unprotect(path.read_bytes()).decode("utf-8")
    except FileNotFoundError:
        return None


# --------------------------------------------------------------------------------------------- pipe clients

ERROR_PIPE_LOCAL = 229


def pipe_client_info(handle: int) -> dict:
    """Process id, image path and locality of the client connected to a server pipe handle.

    Raises OSError when the client cannot be identified (for example an invalid handle): a failed
    lookup must never be mistaken for a local client.
    """
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetNamedPipeClientProcessId.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
    kernel32.GetNamedPipeClientComputerNameW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.ULONG]
    pid = wintypes.ULONG()
    if not kernel32.GetNamedPipeClientProcessId(wintypes.HANDLE(handle), ctypes.byref(pid)):
        raise ctypes.WinError(ctypes.get_last_error())
    name = ctypes.create_unicode_buffer(256)
    remote = bool(kernel32.GetNamedPipeClientComputerNameW(wintypes.HANDLE(handle), name, ctypes.sizeof(name)))
    if not remote:
        err = ctypes.get_last_error()
        if err != ERROR_PIPE_LOCAL:      # only "the client is local" counts as local; any other failure is unknown
            raise ctypes.WinError(err)
    return {"pid": pid.value, "image": process_image(pid.value), "remote": remote,
            "computer": name.value if remote else ""}


def local_pipe_client(handle: int) -> dict | None:
    """Identify a pipe client for a server that serves only local clients.

    Returns the client info, or None when the connection must be refused. Fails closed: a remote client,
    an error while identifying the client, or an answer of an unexpected shape all mean "refuse".
    """
    try:
        info = pipe_client_info(int(handle))
    except Exception as exc:  # noqa: BLE001 - any failure to identify the caller refuses it
        log.warning("refused pipe client: could not identify it (%s)", exc)
        return None
    if not isinstance(info, dict) or not isinstance(info.get("remote"), bool):
        log.warning("refused pipe client: unexpected client info %r", info)
        return None
    if info["remote"]:
        log.warning("refused remote pipe client from %s", info.get("computer"))
        return None
    return info


def process_image(pid: int) -> str:
    if not pid:
        return ""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                    ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(h)
