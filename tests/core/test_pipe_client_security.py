"""The local-only pipe check fails closed: anything other than a positively identified local client is refused."""
import pytest

from glass.core import security


def _patch(monkeypatch, fn):
    monkeypatch.setattr(security, "pipe_client_info", fn)


def test_local_client_is_accepted(monkeypatch):
    info = {"pid": 7, "image": "app.exe", "remote": False, "computer": ""}
    _patch(monkeypatch, lambda h: info)
    assert security.local_pipe_client(5) == info


def test_remote_client_is_refused(monkeypatch):
    _patch(monkeypatch, lambda h: {"pid": 7, "image": "", "remote": True, "computer": "EVIL"})
    assert security.local_pipe_client(5) is None


def test_lookup_error_is_refused(monkeypatch):
    def boom(h):
        raise OSError("identification failed")
    _patch(monkeypatch, boom)
    assert security.local_pipe_client(5) is None


@pytest.mark.parametrize("bad", [None, [], "local", {}, {"pid": 7}, {"remote": None}, {"remote": "no"}, {"remote": 0}])
def test_malformed_info_is_refused(monkeypatch, bad):
    _patch(monkeypatch, lambda h: bad)
    assert security.local_pipe_client(5) is None


def test_unusable_handle_is_refused():
    assert security.local_pipe_client("not-a-handle") is None


def test_invalid_handle_raises_instead_of_reporting_local():
    # A failed Win32 lookup must not be mistaken for a local client.
    with pytest.raises(OSError):
        security.pipe_client_info(0x7FFFF0)
