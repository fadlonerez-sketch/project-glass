"""The Shell's local API for the Control Center (pipe ``ProjectGlass.Shell.<user>``).

Same framing and handshake as the automation pipe (glass.core.ipc). Only clients presenting the owner token
are served; the ACL admits only the current user and remote clients are refused. The Shell stays the only
writer of the settings store -- the Control Center edits through here and receives ``settings.changed`` and
``theme.changed`` notifications, which is what makes its previews live.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from glass.core import ipc, security
from glass.core.ipc import ErrorCode, ProtocolError

log = logging.getLogger(__name__)


class _Client:
    def __init__(self, sock: QLocalSocket):
        self.sock = sock
        self.decoder = ipc.FrameDecoder()
        self.authed = False


class ShellServer(QObject):
    _deferred = Signal(object, object, object)   # client, msg id, result-or-error (from worker threads)

    def __init__(self, handlers: dict[str, Callable[[dict], Any]], async_handlers: dict[str, Callable[[dict], Any]] | None = None,
                 token_reader: Callable[[], str | None] = lambda: security.read_secret("owner"), parent=None):
        super().__init__(parent)
        self.handlers = handlers
        self.async_handlers = async_handlers or {}
        self._token_reader = token_reader
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._on_connection)
        self._clients: list[_Client] = []
        self._deferred.connect(self._send_deferred)
        self.name = security.pipe_name("Shell")

    def listen(self) -> bool:
        QLocalServer.removeServer(self.name)
        ok = self._server.listen(self.name)
        if not ok:
            log.error("Shell API could not listen: %s", self._server.errorString())
        return ok

    def close(self) -> None:
        for c in list(self._clients):
            try:
                c.sock.disconnected.disconnect()
                c.sock.abort()
            except RuntimeError:
                pass
        self._clients.clear()
        self._server.close()

    def broadcast(self, method: str, params: dict) -> None:
        frame = ipc.encode(ipc.notification(method, params))
        for c in list(self._clients):
            if c.authed and c.sock.state() == QLocalSocket.LocalSocketState.ConnectedState:
                c.sock.write(frame)

    @Slot()
    def _on_connection(self) -> None:
        while self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            # Fail closed: a remote client, or one that cannot be identified, is refused.
            if security.local_pipe_client(sock.socketDescriptor()) is None:
                log.warning("refused Shell API client")
                sock.abort()
                sock.deleteLater()
                continue
            client = _Client(sock)
            self._clients.append(client)
            sock.readyRead.connect(lambda c=client: self._on_ready(c))
            sock.disconnected.connect(lambda c=client: self._drop(c))

    def _drop(self, client: _Client) -> None:
        if client in self._clients:
            self._clients.remove(client)
        try:
            client.sock.deleteLater()
        except RuntimeError:  # Qt already deleted it (server shutting down)
            pass

    def _on_ready(self, client: _Client) -> None:
        try:
            messages = client.decoder.feed(bytes(client.sock.readAll()))
        except ProtocolError as exc:
            client.sock.write(ipc.encode(ipc.error(None, exc)))
            client.sock.disconnectFromServer()
            return
        for msg in messages:
            self._handle(client, msg)

    def _handle(self, client: _Client, msg: dict) -> None:
        mid, method, params = msg.get("id"), msg.get("method", ""), msg.get("params") or {}
        try:
            if method == "hello":
                if params.get("protocol") != ipc.PROTOCOL_VERSION:
                    raise ProtocolError(ErrorCode.VERSION, "unsupported protocol", {"supported": [ipc.PROTOCOL_VERSION]})
                token = self._token_reader() or ""
                if not token or not security.token_matches(str(params.get("token", "")), security.token_hash(token)):
                    raise ProtocolError(ErrorCode.UNAUTHORIZED, "invalid token")
                client.authed = True
                result: Any = {"protocol": ipc.PROTOCOL_VERSION, "server": "Glass.Shell"}
            elif not client.authed:
                raise ProtocolError(ErrorCode.UNAUTHORIZED, "say hello first")
            elif method in self.async_handlers:
                fn = self.async_handlers[method]

                def run():
                    try:
                        self._deferred.emit(client, mid, fn(params))
                    except ProtocolError as exc:
                        self._deferred.emit(client, mid, exc)
                    except Exception as exc:  # noqa: BLE001
                        self._deferred.emit(client, mid, ProtocolError(ErrorCode.INTERNAL, str(exc)))
                threading.Thread(target=run, daemon=True).start()
                return
            elif method in self.handlers:
                result = self.handlers[method](params)
            else:
                raise ProtocolError(ErrorCode.UNKNOWN_METHOD, f"unknown method {method}")
            reply = ipc.response(mid, result)
        except ProtocolError as exc:
            reply = ipc.error(mid, exc)
        except Exception as exc:  # noqa: BLE001
            log.exception("Shell API %s failed", method)
            reply = ipc.error(mid, ProtocolError(ErrorCode.INTERNAL, str(exc)))
        client.sock.write(ipc.encode(reply))

    @Slot(object, object, object)
    def _send_deferred(self, client: _Client, mid, outcome) -> None:
        if client not in self._clients:
            return
        reply = ipc.error(mid, outcome) if isinstance(outcome, ProtocolError) else ipc.response(mid, outcome)
        client.sock.write(ipc.encode(reply))
