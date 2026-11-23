"""Tests for atomic add/remove editing."""

import textwrap

import pytest

from sshconfig.editor import add_host, remove_host
from sshconfig.parser import parse_file


def _write(tmp_path, text):
    path = tmp_path / "config"
    path.write_text(textwrap.dedent(text))
    return str(path)


def test_add_to_new_file_creates_it(tmp_path):
    path = str(tmp_path / "config")
    result = add_host(path, "web", [("HostName", "web.example.com"), ("User", "deploy")])
    assert result.changed
    assert result.backup_path is None  # nothing to back up
    config = parse_file(path)
    assert config.blocks[0].patterns == ["web"]
    assert config.blocks[0].get("HostName") == "web.example.com"


def test_add_appends_after_existing_blocks(tmp_path):
    path = _write(tmp_path, "Host web\n    HostName web.example.com\n")
    add_host(path, "db", [("HostName", "db.example.com")])
    text = open(path).read()
    assert text.index("Host web") < text.index("Host db")
    assert parse_file(path).blocks[1].get("HostName") == "db.example.com"


def test_add_refuses_duplicate_without_force(tmp_path):
    path = _write(tmp_path, "Host web\n    HostName web.example.com\n")
    with pytest.raises(ValueError, match="already defined"):
        add_host(path, "web", [("HostName", "other.example.com")])
    assert parse_file(path).blocks[0].get("HostName") == "web.example.com"


def test_add_with_force_allows_second_block(tmp_path):
    path = _write(tmp_path, "Host web\n    HostName web.example.com\n")
    add_host(path, "web", [("HostName", "second.example.com")], force=True)
    assert len(parse_file(path).blocks) == 2


def test_add_dry_run_writes_nothing(tmp_path):
    path = _write(tmp_path, "Host web\n    HostName web.example.com\n")
    before = open(path).read()
    result = add_host(path, "db", [("HostName", "db.example.com")], dry_run=True)
    assert not result.changed
    assert open(path).read() == before


def test_add_keeps_backup(tmp_path):
    path = _write(tmp_path, "Host web\n    HostName web.example.com\n")
    result = add_host(path, "db", [("HostName", "db.example.com")])
    assert result.backup_path == path + ".bak"
    assert open(result.backup_path).read() == "Host web\n    HostName web.example.com\n"


def test_remove_block_and_its_comment(tmp_path):
    path = _write(
        tmp_path,
        """\
        # My SSH config

        Host web
            HostName web.example.com

        # The database box
        Host db
            HostName db.example.com

        Host cache
            HostName cache.example.com
        """,
    )
    result = remove_host(path, "db")
    assert result.changed
    text = open(path).read()
    assert "Host db" not in text
    assert "The database box" not in text  # comment travels with its host
    assert "My SSH config" in text  # file header stays
    assert "Host web" in text and "Host cache" in text


def test_remove_unknown_host_errors(tmp_path):
    path = _write(tmp_path, "Host web\n    HostName web.example.com\n")
    with pytest.raises(ValueError, match="not defined"):
        remove_host(path, "db")


def test_remove_dry_run_writes_nothing(tmp_path):
    path = _write(tmp_path, "Host web\n    HostName web.example.com\n")
    before = open(path).read()
    result = remove_host(path, "web", dry_run=True)
    assert not result.changed
    assert open(path).read() == before


def test_remove_multi_pattern_block_by_one_name(tmp_path):
    path = _write(tmp_path, "Host web prod-web\n    HostName web.example.com\n")
    remove_host(path, "prod-web")
    assert parse_file(path).blocks == []
