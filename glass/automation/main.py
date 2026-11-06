"""Glass.Automation entry point: `python -m glass.automation [--parent-pid PID] [--data-dir DIR]`.

Headless (QCoreApplication). Exit codes: 0 normal, 3 another engine already owns the pipe, 4 UIA failed.
"""
from __future__ import annotations

import argparse
import ctypes
import logging
import logging.handlers
import os
import signal
import sys
import threading
from ctypes import wintypes


def _parse(argv):
    ap = argparse.ArgumentParser(prog="glass.automation")
    ap.add_argument("--parent-pid", type=int, default=0, help="exit when this process exits")
    ap.add_argument("--data-dir", default="", help="data folder (tokens, automation.db, logs)")
    ap.add_argument("--pipe-name", default="", help="override the pipe name (tests)")
    ap.add_argument("--fake-input", action="store_true",
                    help="record synthetic input / focus requests instead of performing them (tests)")
    ap.add_argument("--log-level", default="INFO")
    return ap.parse_args(argv)


def _watch_parent(pid: int, on_exit) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    h = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if not h:
        on_exit()
        return

    def wait():
        kernel32.WaitForSingleObject(h, 0xFFFFFFFF)
        on_exit()

    threading.Thread(target=wait, name="parent-watch", daemon=True).start()


def main(argv=None) -> int:
    args = _parse(sys.argv[1:] if argv is None else argv)
    if args.data_dir:
        os.environ["GLASS_DATA_DIR"] = os.path.abspath(args.data_dir)

    import comtypes  # noqa: F401  -- initialises COM (STA) on the Qt thread; workers use the MTA

    from PySide6.QtCore import QCoreApplication, QMetaObject, Qt, QTimer

    from glass.automation import win
    from glass.automation.engine import Engine
    from glass.automation.inputs import FakeInput, RealInput
    from glass.automation.server import AutomationServer
    from glass.automation.store import Store
    from glass.core import paths, security

    win.enable_dpi_awareness()
    log_path = paths.logs_dir() / "automation.log"
    handler = logging.handlers.RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(args.log_level.upper())

    app = QCoreApplication(sys.argv[:1])
    app.setApplicationName("Glass.Automation")
    store = Store(paths.automation_db())
    store.ensure_client_tokens()
    name = args.pipe_name or security.pipe_name("Automation")
    try:
        server = AutomationServer(Engine, store, name, FakeInput() if args.fake_input else RealInput())
    except Exception:
        logging.getLogger("glass.automation").exception("UI Automation could not start")
        print("ERROR UI Automation could not start", flush=True)
        return 4
    if not server.listen():
        print("ERROR pipe in use", flush=True)
        return 3

    def quit_soon():
        QMetaObject.invokeMethod(app, "quit", Qt.ConnectionType.QueuedConnection)

    if args.parent_pid:
        _watch_parent(args.parent_pid, quit_soon)
    signal.signal(signal.SIGINT, lambda *_: quit_soon())
    keepalive = QTimer()
    keepalive.start(500)  # lets Python handle Ctrl+C between Qt events
    keepalive.timeout.connect(lambda: None)
    print(f"READY {name}", flush=True)
    code = app.exec()
    server.close()
    store.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
