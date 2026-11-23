"""Tests for the ssh_config parser."""

import textwrap

import pytest

from sshconfig.parser import SshConfigError, parse_config, parse_file


def test_basic_host_block():
    config = parse_config(
        textwrap.dedent(
            """\
            Host web
                HostName 203.0.113.10
                User deploy
                Port 2222
            """
        )
    )
    assert len(config.blocks) == 1
    block = config.blocks[0]
    assert block.patterns == ["web"]
    assert block.get("hostname") == "203.0.113.10"
    assert block.get("USER") == "deploy"
    assert block.get("Port") == "2222"


def test_multiple_patterns_and_case_insensitive_keys():
    config = parse_config("Host web prod-web\n    HOSTNAME example.com\n    user deploy\n")
    assert config.blocks[0].patterns == ["web", "prod-web"]
    assert config.blocks[0].get("hostname") == "example.com"


def test_global_options_before_first_host():
    config = parse_config(
        "ServerAliveInterval 60\n\nHost web\n    HostName example.com\n"
    )
    assert config.global_options == [("ServerAliveInterval", "60")]
    assert len(config.blocks) == 1


def test_equals_forms():
    config = parse_config(
        "Host web\n    HostName=example.com\n    Port = 2222\n    User=deploy\n"
    )
    block = config.blocks[0]
    assert block.get("HostName") == "example.com"
    assert block.get("Port") == "2222"
    assert block.get("User") == "deploy"


def test_comments_and_blank_lines():
    config = parse_config(
        textwrap.dedent(
            """\
            # File header
            Host web  # trailing comment
                HostName example.com # also a comment
                # a full-line comment inside the block
                User deploy
            """
        )
    )
    block = config.blocks[0]
    assert block.get("HostName") == "example.com"
    assert block.get("User") == "deploy"
    assert len(block.options) == 2


def test_hash_inside_value_is_not_a_comment():
    # '#' only starts a comment at line start or after whitespace.
    config = parse_config("Host web\n    HostName host#1.example.com\n")
    assert config.blocks[0].get("HostName") == "host#1.example.com"


def test_proxy_command_value_keeps_spaces():
    config = parse_config(
        "Host web\n    ProxyCommand ssh -W %h:%p bastion\n"
    )
    assert config.blocks[0].get("ProxyCommand") == "ssh -W %h:%p bastion"


def test_match_block_parsed_not_applied():
    config = parse_config("Match user deploy\n    ForwardAgent yes\n")
    assert len(config.blocks) == 1
    block = config.blocks[0]
    assert block.is_match
    assert block.match_criteria == "user deploy"
    assert block.get("ForwardAgent") == "yes"


def test_host_without_pattern_is_an_error():
    with pytest.raises(SshConfigError, match="needs at least one pattern"):
        parse_config("Host\n    HostName example.com\n")


def test_include_expands_in_place(tmp_path):
    shared = tmp_path / "shared"
    shared.write_text("Host shared\n    HostName shared.example.com\n")
    main = tmp_path / "config"
    main.write_text(f"Include {shared}\n\nHost local\n    HostName local.example.com\n")
    config = parse_file(str(main))
    assert [b.patterns for b in config.blocks] == [["shared"], ["local"]]


def test_include_glob_and_relative_paths(tmp_path):
    (tmp_path / "extra.conf").write_text("Host extra\n    HostName extra.example.com\n")
    main = tmp_path / "config"
    main.write_text("Include extra*.conf\n")
    config = parse_file(str(main))
    assert [b.patterns for b in config.blocks] == [["extra"]]


def test_include_cycle_does_not_recurse(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_text(f"Include {b}\nHost a\n    HostName a.example.com\n")
    b.write_text(f"Include {a}\nHost b\n    HostName b.example.com\n")
    config = parse_file(str(a))
    patterns = [p for block in config.blocks for p in block.patterns]
    assert patterns == ["b", "a"]


def test_include_missing_file_is_silently_skipped(tmp_path):
    main = tmp_path / "config"
    main.write_text("Include does-not-exist.conf\nHost web\n    HostName example.com\n")
    config = parse_file(str(main))
    assert len(config.blocks) == 1


def test_block_line_spans_keep_header_comments(tmp_path):
    text = textwrap.dedent(
        """\
        # My SSH config

        Host web
            HostName web.example.com

        # The database box
        Host db
            HostName db.example.com
        """
    )
    config = parse_config(text)
    assert config.blocks[0].start_line == 2  # header comment stays with the file
    # The blank line + comment above 'Host db' travel with the db block.
    assert config.blocks[1].start_line == 4
    assert config.blocks[0].end_line == 4
    assert config.blocks[1].end_line == 8


def test_parse_file_missing_raises():
    with pytest.raises(SshConfigError, match="not found"):
        parse_file("/nonexistent/ssh_config")
