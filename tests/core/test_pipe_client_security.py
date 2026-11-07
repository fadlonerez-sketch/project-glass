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


class _FakeKernel32:
    """Stands in for kernel32 so the Win32 failure paths can be exercised without touching real handles."""

    def __init__(self, pid_ok: bool, remote: bool):
        def get_pid(handle, pid_ref):
            if pid_ok:
                pid_ref._obj.value = 42
            return int(pid_ok)

        def get_name(handle, buf, size):
            if remote:
                buf.value = "OTHER-PC"
            return int(remote)
        self.GetNamedPipeClientProcessId = get_pid
        self.GetNamedPipeClientComputerNameW = get_name


@pytest.fixture
def fake_win32(monkeypatch):
    def install(pid_ok=True, remote=False, last_error=security.ERROR_PIPE_LOCAL):
        k32 = _FakeKernel32(pid_ok, remote)
        monkeypatch.setattr(security.ctypes, "WinDLL", lambda *a, **k: k32)
        monkeypatch.setattr(security.ctypes, "get_last_error", lambda: last_error)
        monkeypatch.setattr(security, "process_image", lambda pid: "app.exe")
    return install


def test_only_error_pipe_local_means_local(fake_win32):
    fake_win32(last_error=security.ERROR_PIPE_LOCAL)
    assert security.pipe_client_info(1) == {"pid": 42, "image": "app.exe", "remote": False, "computer": ""}


def test_remote_lookup_reports_remote(fake_win32):
    fake_win32(remote=True)
    assert security.pipe_client_info(1)["remote"] is True


def test_failed_locality_lookup_raises_instead_of_reporting_local(fake_win32):
    fake_win32(last_error=6)  # ERROR_INVALID_HANDLE
    with pytest.raises(OSError):
        security.pipe_client_info(1)


def test_failed_pid_lookup_raises(fake_win32):
    fake_win32(pid_ok=False, last_error=6)
    with pytest.raises(OSError):
        security.pipe_client_info(1)
