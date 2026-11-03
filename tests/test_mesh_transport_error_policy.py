"""mTLS tunnel boundaries must surface unexpected failures, not swallow them."""

import socket
import threading
from unittest.mock import Mock

import pytest

from runtime.network.mesh_transport import MeshTunnelClient, MeshTunnelServer


@pytest.mark.parametrize("tunnel_cls", [MeshTunnelServer, MeshTunnelClient])
def test_unexpected_pipe_programming_error_propagates(tunnel_cls: type) -> None:
    tunnel = tunnel_cls.__new__(tunnel_cls)
    tunnel._running = True
    source = Mock()
    source.recv_into.side_effect = RuntimeError("unexpected tunnel bug")
    destination = Mock()
    stopped = threading.Event()
    with pytest.raises(RuntimeError, match="unexpected tunnel bug"):
        tunnel._pipe(source, destination, "c2t", stopped)
    assert stopped.is_set()
    destination.shutdown.assert_called_once_with(socket.SHUT_WR)


@pytest.mark.parametrize("tunnel_cls", [MeshTunnelServer, MeshTunnelClient])
def test_expected_socket_disconnect_stops_pipe(tunnel_cls: type) -> None:
    tunnel = tunnel_cls.__new__(tunnel_cls)
    tunnel._running = True
    source = Mock()
    source.recv_into.side_effect = OSError("peer disconnected")
    destination = Mock()
    stopped = threading.Event()
    tunnel._pipe(source, destination, "c2t", stopped)
    assert stopped.is_set()
    destination.shutdown.assert_called_once_with(socket.SHUT_WR)


@pytest.mark.parametrize("tunnel_cls", [MeshTunnelServer, MeshTunnelClient])
def test_unexpected_stop_error_is_not_silenced(tunnel_cls: type) -> None:
    tunnel = tunnel_cls.__new__(tunnel_cls)
    tunnel._running = True
    tunnel._server_sock = Mock()
    tunnel._server_sock.close.side_effect = RuntimeError("bad socket state")
    with pytest.raises(RuntimeError, match="bad socket state"):
        tunnel.stop()
    assert tunnel._running is False


@pytest.mark.parametrize("tunnel_cls", [MeshTunnelServer, MeshTunnelClient])
def test_expected_socket_close_error_is_tolerated(tunnel_cls: type) -> None:
    tunnel = tunnel_cls.__new__(tunnel_cls)
    tunnel._running = True
    tunnel._server_sock = Mock()
    tunnel._server_sock.close.side_effect = OSError("socket already closed")
    tunnel.stop()
    assert tunnel._running is False
