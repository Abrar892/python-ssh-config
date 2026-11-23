"""TCP reachability probe: can we open a socket to host:port?"""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass


@dataclass
class ProbeResult:
    host: str
    port: int
    reachable: bool
    latency_ms: float | None = None
    error: str | None = None


def probe(host: str, port: int, timeout: float = 5.0) -> ProbeResult:
    """Attempt a TCP connect and time it. Never raises for network errors."""
    started = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except socket.gaierror as exc:
        return ProbeResult(host, port, False, error=f"DNS resolution failed: {exc}")
    except (ConnectionRefusedError, socket.timeout, OSError) as exc:
        return ProbeResult(host, port, False, error=str(exc) or exc.__class__.__name__)
    latency = (time.monotonic() - started) * 1000
    return ProbeResult(host, port, True, latency_ms=latency)
