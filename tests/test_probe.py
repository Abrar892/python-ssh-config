"""Tests for the TCP reachability probe (local servers only)."""

import socket
import threading

from sshconfig.probe import probe


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _serve_once(port: int) -> threading.Thread:
    def run():
        with socket.socket() as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("127.0.0.1", port))
            server.listen(1)
            conn, _ = server.accept()
            conn.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def test_reachable_local_server():
    port = _free_port()
    _serve_once(port)
    result = probe("127.0.0.1", port, timeout=2.0)
    assert result.reachable
    assert result.latency_ms is not None and result.latency_ms >= 0
    assert result.error is None


def test_closed_port_is_unreachable():
    port = _free_port()  # nothing listening on it
    result = probe("127.0.0.1", port, timeout=2.0)
    assert not result.reachable
    assert result.error is not None


def test_unresolvable_host_reports_dns_error():
    # A hostname with spaces fails at getaddrinfo before any DNS
    # lookup, so the test is deterministic even where a resolver
    # answers for every well-formed name (e.g. behind a proxy).
    result = probe("bad host name", 22, timeout=2.0)
    assert not result.reachable
    assert "DNS" in (result.error or "")
