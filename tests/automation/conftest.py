"""Fixtures for the Glass.Automation tests.

The engine runs as a real separate process over a real named pipe, with an isolated data folder and its
own pipe name, and `--fake-input` so focus/keyboard/mouse requests are recorded instead of performed.
Test targets are created off-screen without activation; nothing appears on the user's screen and the
user's focus, keyboard, mouse and clipboard are never touched.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
DATA = tempfile.mkdtemp(prefix="glass-automation-tests-")
os.environ["GLASS_DATA_DIR"] = DATA

from glass.automation.aioclient import AsyncClient, RemoteError  # noqa: E402
from glass.core import security  # noqa: E402

PIPE = f"ProjectGlass.Automation.test-{os.getpid()}"
TARGETS = ROOT / "tools" / "testtarget"


class SyncClient:
    """Blocking facade over AsyncClient for readable tests (one private event loop)."""

    def __init__(self, loop: asyncio.AbstractEventLoop, pipe: str = PIPE):
        self.loop = loop
        self.c = AsyncClient("\\\\.\\pipe\\" + pipe)
        self.run(self.c.connect())

    def run(self, coro, timeout: float = 40):
        return self.loop.run_until_complete(asyncio.wait_for(coro, timeout))

    def hello(self, token: str, client: str = "test"):
        return self.run(self.c.hello(token, client))

    def call(self, method: str, params: dict | None = None, timeout: float = 30):
        return self.run(self.c.call(method, params or {}, timeout))

    def error(self, method: str, params: dict | None = None) -> RemoteError:
        with pytest.raises(RemoteError) as info:
            self.call(method, params)
        return info.value

    def notifications(self, wait: float = 0.0) -> list[dict]:
        if wait:
            self.run(asyncio.sleep(wait))
        out = []
        while not self.c.notifications.empty():
            out.append(self.c.notifications.get_nowait())
        return out

    def close(self):
        self.run(self.c.close())
        self.run(asyncio.sleep(0.05))


def _start(args: list[str], cwd: Path = ROOT, ready="READY") -> tuple[subprocess.Popen, str]:
    # Other Qt tests may set QT_QPA_PLATFORM=offscreen in this process; targets need real windows.
    env = {k: v for k, v in os.environ.items() if not k.startswith("QT_") and k != "GLASS_DATA_DIR"}
    proc = subprocess.Popen([sys.executable, *args], cwd=str(cwd), stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, env=env)  # never let a full pipe block it
    line = proc.stdout.readline().strip()
    if not line.startswith(ready):
        proc.kill()
        raise RuntimeError(f"{args[0]} did not start: {line!r} (see the engine log in the data folder)")
    return proc, line


@pytest.fixture(scope="session")
def engine():
    proc, line = _start(["-m", "glass.automation", "--data-dir", DATA, "--pipe-name", PIPE, "--fake-input",
                         "--parent-pid", str(os.getpid())])
    yield proc
    proc.kill()
    proc.wait(10)


@pytest.fixture(scope="session")
def loop():
    lp = asyncio.new_event_loop()  # Proactor on Windows: overlapped pipe I/O
    yield lp
    lp.close()


@pytest.fixture(scope="session")
def tokens(engine):
    # Read from the engine's own data folder explicitly: a parent conftest may point GLASS_DATA_DIR
    # at a per-test temp folder.
    secrets = Path(DATA) / "secrets"
    return {"owner": security.read_secret("owner", secrets), "garvis": security.read_secret("garvis", secrets)}


@pytest.fixture
def client(engine, loop, tokens):
    c = SyncClient(loop)
    c.hello(tokens["garvis"], "garvis")
    yield c
    c.close()


@pytest.fixture
def owner(engine, loop, tokens):
    c = SyncClient(loop)
    c.hello(tokens["owner"], "owner")
    yield c
    # leave the engine as we found it
    c.call("admin.resume")
    c.call("admin.permissions.set", {"client": "garvis", "scopes": ["inspect", "act", "text", "windows", "input"]})
    c.call("admin.permissions.set", {"deny_list": DEFAULT_DENY})
    c.close()


from glass.automation.store import DEFAULT_DENY_LIST as DEFAULT_DENY  # noqa: E402


def _target(args: list[str]):
    proc, line = _start(args)
    hwnd = int(line.split()[1])
    return proc, hwnd


@pytest.fixture
def qt_target():
    proc, hwnd = _target([str(TARGETS / "target.py")])
    yield hwnd
    proc.kill()
    proc.wait(10)


@pytest.fixture
def protected_target():
    proc, hwnd = _target([str(TARGETS / "target.py"), "--protected", "--title", "Glass Protected Target"])
    yield hwnd
    proc.kill()
    proc.wait(10)


@pytest.fixture
def win32_target():
    proc, hwnd = _target([str(TARGETS / "win32target.py")])
    yield hwnd
    proc.kill()
    proc.wait(10)


@pytest.fixture
def blank_target():
    proc, hwnd = _target([str(TARGETS / "win32target.py"), "--blank", "--title", "Glass Blank Target"])
    yield hwnd
    proc.kill()
    proc.wait(10)


def find_one(client: SyncClient, hwnd: int, **kw) -> dict:
    res = client.call("element.find", {"hwnd": hwnd, **kw})
    assert res["matches"], f"no element matching {kw}"
    return res["matches"][0]


def label(client: SyncClient, hwnd: int) -> str:
    return find_one(client, hwnd, aid="QApplication.Target.QWidget.lastAction")["name"]


def status(client: SyncClient, hwnd: int) -> str:
    """Status line of the Win32 target (first Text element)."""
    for m in client.call("element.find", {"hwnd": hwnd, "type": "Text"})["matches"]:
        if m.get("name", "").startswith("win32:"):
            return m["name"]
    raise AssertionError("no win32 status")


def wait_until(fn, timeout=3.0, step=0.1):
    import time
    end = time.monotonic() + timeout
    last = None
    while time.monotonic() < end:
        last = fn()
        if last:
            return last
        time.sleep(step)
    return last
