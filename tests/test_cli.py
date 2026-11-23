"""End-to-end tests for the ssh-config CLI (run as a subprocess)."""

import json
import os
import subprocess
import sys
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = {**os.environ, "PYTHONPATH": os.path.join(ROOT, "src")}


def _run(tmp_path, *argv, config_text=None):
    config = tmp_path / "config"
    if config_text is not None:
        config.write_text(textwrap.dedent(config_text))
    args = [sys.executable, "-m", "sshconfig", *argv]
    # Rewrite a literal {config} placeholder to the temp config path.
    args = [a.replace("{config}", str(config)) for a in args]
    return subprocess.run(args, capture_output=True, text=True, env=ENV)


def test_list_shows_hosts(tmp_path):
    result = _run(
        tmp_path, "list", "--config", "{config}",
        config_text="Host web\n    HostName web.example.com\nHost db\n    HostName db.example.com\n",
    )
    assert result.returncode == 0
    assert "web" in result.stdout and "db" in result.stdout
    assert "web.example.com" in result.stdout


def test_list_json(tmp_path):
    result = _run(
        tmp_path, "list", "--config", "{config}", "--json",
        config_text="Host web\n    HostName web.example.com\n    Port 2222\n",
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["hosts"][0]["name"] == "web"
    assert payload["hosts"][0]["port"] == "2222"


def test_resolve_json_applies_first_wins(tmp_path):
    result = _run(
        tmp_path, "resolve", "web", "--config", "{config}", "--json",
        config_text=(
            "Host web\n    User first\n"
            "Host *\n    User second\n    Port 2222\n"
        ),
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["options"]["User"] == "first"
    assert payload["options"]["Port"] == "2222"
    assert payload["matched_blocks"] == [["web"], ["*"]]


def test_add_then_list_roundtrip(tmp_path):
    result = _run(
        tmp_path, "add", "web", "--hostname", "web.example.com",
        "--user", "deploy", "--port", "2222", "--config", "{config}",
    )
    assert result.returncode == 0, result.stderr
    assert "added host 'web'" in result.stdout
    listed = _run(tmp_path, "list", "--config", "{config}")
    assert "web" in listed.stdout and "web.example.com" in listed.stdout


def test_add_duplicate_fails(tmp_path):
    _run(tmp_path, "add", "web", "--config", "{config}")
    result = _run(tmp_path, "add", "web", "--config", "{config}")
    assert result.returncode == 1
    assert "already defined" in result.stderr


def test_add_bad_option_format_fails(tmp_path):
    result = _run(tmp_path, "add", "web", "--option", "NoEqualsHere", "--config", "{config}")
    assert result.returncode == 2


def test_remove_roundtrip(tmp_path):
    _run(tmp_path, "add", "web", "--config", "{config}")
    _run(tmp_path, "add", "db", "--config", "{config}")
    result = _run(tmp_path, "remove", "web", "--config", "{config}")
    assert result.returncode == 0
    assert "removed 1 block(s)" in result.stdout
    listed = _run(tmp_path, "list", "--config", "{config}")
    assert "web" not in listed.stdout and "db" in listed.stdout


def test_check_clean_and_dirty(tmp_path):
    clean = _run(
        tmp_path, "check", "--config", "{config}",
        config_text="Host web\n    HostName web.example.com\n",
    )
    assert clean.returncode == 0
    assert "OK" in clean.stdout
    dirty = _run(
        tmp_path, "check", "--config", "{config}",
        config_text="Host web\n    Port notaport\n",
    )
    assert dirty.returncode == 1
    assert "error" in dirty.stdout


def test_missing_config_file_errors(tmp_path):
    result = _run(tmp_path, "list", "--config", "{config}")
    assert result.returncode == 1
    assert "not found" in result.stderr


def test_probe_reachable_and_unreachable(tmp_path):
    import socket
    import threading

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    def serve():
        with socket.socket() as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("127.0.0.1", port))
            server.listen(1)
            conn, _ = server.accept()
            conn.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    reachable = _run(
        tmp_path, "probe", "local", "--config", "{config}",
        config_text=f"Host local\n    HostName 127.0.0.1\n    Port {port}\n",
    )
    assert reachable.returncode == 0
    assert "reachable" in reachable.stdout
    closed_port = port + 1 if port < 65534 else port - 1
    unreachable = _run(
        tmp_path, "probe", "closed", "--config", "{config}",
        config_text=f"Host closed\n    HostName 127.0.0.1\n    Port {closed_port}\n",
    )
    assert unreachable.returncode == 1
    assert "unreachable" in unreachable.stdout
