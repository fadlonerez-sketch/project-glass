"""Unit tests that need no engine process: framing, store, key parsing, policy, ref parsing."""
from __future__ import annotations

import os
import struct

import pytest

from glass.automation import win
from glass.automation.engine import Ctx, Engine
from glass.automation.inputs import FakeInput, _utf16, parse_keys
from glass.automation.store import ALL_SCOPES, DEFAULT_DENY_LIST, Store
from glass.automation.uia import Uia
from glass.core import ipc, security
from glass.core.ipc import ErrorCode, ProtocolError


# ----------------------------------------------------------------------------- framing
def test_frame_round_trip_and_partial_delivery():
    msgs = [ipc.request(1, "a", {"x": "ü"}), ipc.notification("event", {"n": 1})]
    data = b"".join(ipc.encode(m) for m in msgs)
    dec = ipc.FrameDecoder()
    out = []
    for i in range(len(data)):  # one byte at a time
        out += dec.feed(data[i:i + 1])
    assert out == msgs


def test_frame_rejects_oversize_malformed_and_non_object():
    with pytest.raises(ProtocolError):
        ipc.FrameDecoder().feed(struct.pack("<I", ipc.MAX_FRAME + 1))
    with pytest.raises(ProtocolError) as e:
        ipc.FrameDecoder().feed(struct.pack("<I", 3) + b"{x}")
    assert e.value.code == ErrorCode.INVALID_PARAMS
    with pytest.raises(ProtocolError):
        ipc.FrameDecoder().feed(struct.pack("<I", 2) + b"[]")
    with pytest.raises(ValueError):
        ipc.encode({"x": "a" * (ipc.MAX_FRAME + 10)})


def test_error_shape():
    err = ProtocolError(ErrorCode.STALE_REFERENCE, "gone", {"ref": "1:2"})
    assert ipc.error(5, err) == {"id": 5, "error": {"code": "stale_reference", "message": "gone", "data": {"ref": "1:2"}}}


# ----------------------------------------------------------------------------- store
@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("GLASS_DATA_DIR", str(tmp_path))
    s = Store(tmp_path / "automation" / "automation.db")
    s.ensure_client_tokens()
    yield s
    s.close()


def test_tokens_created_hashed_and_dpapi_protected(store, tmp_path):
    owner = security.read_secret("owner")
    garvis = security.read_secret("garvis")
    assert owner and garvis and owner != garvis
    raw = (tmp_path / "secrets" / "garvis.dpapi").read_bytes()
    assert garvis.encode() not in raw  # stored encrypted
    db = (tmp_path / "automation" / "automation.db").read_bytes()
    assert garvis.encode() not in db  # only the hash is stored
    assert store.authenticate(garvis) == ("garvis", ALL_SCOPES)
    assert store.authenticate(owner)[0] == "owner"
    assert store.authenticate("nope") is None and store.authenticate("") is None


def test_tokens_rotate_when_secret_missing(store, tmp_path):
    old = security.read_secret("garvis")
    (tmp_path / "secrets" / "garvis.dpapi").unlink()
    store.ensure_client_tokens()
    new = security.read_secret("garvis")
    assert new and new != old
    assert store.authenticate(old) is None and store.authenticate(new)[0] == "garvis"
    # an unchanged secret is kept
    store.ensure_client_tokens()
    assert security.read_secret("garvis") == new


def test_scopes_deny_list_stop_and_audit(store):
    assert store.set_scopes("garvis", ["inspect", "bogus", "act"]) == ["inspect", "act"]
    assert store.set_scopes("owner", []) == ALL_SCOPES  # the owner always keeps everything
    with pytest.raises(KeyError):
        store.set_scopes("nobody", ["inspect"])
    assert store.deny_list() == DEFAULT_DENY_LIST
    assert store.set_deny_list([" Foo.EXE ", "", "bar.exe", "foo.exe"]) == ["bar.exe", "foo.exe"]
    assert not store.stopped()
    store.set_stopped(True)
    assert store.stopped()
    ids = [store.audit("garvis", "element.act", "App — Win", "ok", "invoke") for _ in range(3)]
    entries = store.read_audit(limit=2)
    assert [e["id"] for e in entries] == ids[::-1][:2]
    assert store.read_audit(since_id=ids[0])[0]["id"] == ids[1]


# ----------------------------------------------------------------------------- input parsing
def test_parse_keys():
    assert parse_keys("ctrl+s") == [[0x11, ord("S")]]
    assert parse_keys("Ctrl+Shift+Esc, enter") == [[0x11, 0x10, 0x1B], [0x0D]]
    with pytest.raises(ValueError):
        parse_keys("ctrl+banana")
    with pytest.raises(ValueError):
        parse_keys("  ")
    assert _utf16("😀") == "\ud83d\ude00"


def test_fake_input_records():
    f = FakeInput()
    assert f.focus(5) and f.foreground() == 5
    f.keys([[1]])
    f.text("hi")
    f.click(1, 2)
    assert [c[0] for c in f.log()] == ["focus", "keys", "text", "click"]


# ----------------------------------------------------------------------------- refs and policy
def test_ref_round_trip_and_bad_refs():
    ref = Uia.make_ref(0x1A2B, (42, 6699, -5))
    assert ref == "1a2b:42.6699.-5"
    assert Uia.parse_ref(ref) == (0x1A2B, [42, 6699, -5])
    for bad in ("", "zz", "xyz:1", None):
        with pytest.raises(ProtocolError):
            Uia.parse_ref(bad)


class _Store:
    def __init__(self, deny):
        self._deny = deny

    def deny_list(self):
        return self._deny


def _engine_stub(deny=()):
    eng = Engine.__new__(Engine)  # policy checks only; no UIA needed
    eng.store = _Store(list(deny))
    return eng


def test_check_target_policy(monkeypatch):
    monkeypatch.setattr(win, "is_window", lambda h: h != 999)
    monkeypatch.setattr(win, "pid_of", lambda h: 4242 if h == 1 else 7)
    monkeypatch.setattr(win, "image_of", lambda pid: r"C:\Apps\KeePass.exe" if pid == 7 else r"C:\x\app.exe")
    monkeypatch.setattr(win, "is_protected", lambda h: h == 2)
    monkeypatch.setattr(win, "is_elevated", lambda pid: False)
    eng = _engine_stub(deny=["keepass.exe"])
    ctx = Ctx(session="s", client="garvis", scopes=ALL_SCOPES, pid=4242)
    with pytest.raises(ProtocolError) as e:
        eng.check_target(ctx, 999, acting=False)
    assert e.value.code == ErrorCode.STALE_REFERENCE
    with pytest.raises(ProtocolError) as e:  # deny list applies even to reading
        eng.check_target(ctx, 3, acting=False)
    assert e.value.code == ErrorCode.DENIED_APP
    monkeypatch.setattr(win, "image_of", lambda pid: r"C:\x\app.exe")
    assert eng.check_target(ctx, 1, acting=False)["pid"] == 4242  # reading its own window is fine
    with pytest.raises(ProtocolError) as e:  # ...but a client may not drive its own windows
        eng.check_target(ctx, 1, acting=True)
    assert e.value.code == ErrorCode.DENIED_APP and "own windows" in e.value.message
    with pytest.raises(ProtocolError) as e:  # Glass's protected windows
        eng.check_target(ctx, 2, acting=True)
    assert "Project Glass" in e.value.message
    monkeypatch.setattr(win, "is_elevated", lambda pid: True)
    with pytest.raises(ProtocolError) as e:
        eng.check_target(ctx, 3, acting=True)
    assert e.value.code == ErrorCode.ELEVATED_TARGET


def test_self_not_elevated_and_window_helpers():
    assert win.is_elevated(os.getpid()) is False
    assert win.is_window(0) is False
    assert isinstance(win.list_windows(), list)


def test_pipe_names_are_per_user(monkeypatch):
    monkeypatch.delenv("GLASS_PIPE_SUFFIX", raising=False)   # the real, unsuffixed name
    name = security.pipe_name("Automation")
    assert name.startswith("ProjectGlass.Automation.") and len(name.rsplit(".", 1)[1]) == 16
    assert security.pipe_path("Automation") == "\\\\.\\pipe\\" + name
