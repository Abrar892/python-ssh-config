"""Tests for effective-config resolution (first-obtained-value semantics)."""

import textwrap

from sshconfig.parser import parse_config
from sshconfig.resolver import resolve


def _config(text):
    return parse_config(textwrap.dedent(text))


def test_first_obtained_value_wins():
    config = _config(
        """\
        Host web
            User first
            HostName first.example.com
        Host *.example.com
            User second
            HostName second.example.com
        """
    )
    resolved = resolve(config, "web")
    assert resolved.options["User"] == "first"
    assert resolved.options["HostName"] == "first.example.com"


def test_later_block_fills_gaps_only():
    config = _config(
        """\
        Host web
            User deploy
        Host *
            User fallback
            Port 2222
            ServerAliveInterval 60
        """
    )
    resolved = resolve(config, "web")
    assert resolved.options["User"] == "deploy"
    assert resolved.options["Port"] == "2222"
    assert resolved.options["ServerAliveInterval"] == "60"


def test_multi_value_options_accumulate():
    config = _config(
        """\
        Host *
            IdentityFile ~/.ssh/id_ed25519
        Host web
            IdentityFile ~/.ssh/web_key
            IdentityFile ~/.ssh/backup_key
        """
    )
    resolved = resolve(config, "web")
    assert resolved.options["IdentityFile"] == [
        "~/.ssh/id_ed25519",
        "~/.ssh/web_key",
        "~/.ssh/backup_key",
    ]


def test_global_options_apply_first():
    config = _config(
        """\
        ServerAliveInterval 60
        Host web
            ServerAliveInterval 30
            HostName web.example.com
        """
    )
    resolved = resolve(config, "web")
    assert resolved.options["ServerAliveInterval"] == "60"


def test_builtin_defaults_applied_and_marked():
    config = _config("Host web\n    HostName web.example.com\n")
    resolved = resolve(config, "web")
    assert resolved.options["Port"] == "22"
    assert resolved.options["HostName"] == "web.example.com"
    assert resolved.defaults == {"Port": "22", "User": resolved.defaults["User"]}
    # HostName was explicit, so it is not a default.
    assert "HostName" not in resolved.defaults


def test_hostname_default_is_the_queried_host():
    config = _config("Host *\n    User deploy\n")
    resolved = resolve(config, "db.internal")
    assert resolved.options["HostName"] == "db.internal"
    assert resolved.defaults["HostName"] == "db.internal"


def test_explicit_values_beat_defaults():
    config = _config("Host web\n    Port 2222\n    User deploy\n")
    resolved = resolve(config, "web")
    assert resolved.options["Port"] == "2222"
    assert resolved.options["User"] == "deploy"
    # HostName was not set explicitly, so only it falls back to a default.
    assert resolved.defaults == {"HostName": "web"}


def test_negated_pattern_blocks_match():
    config = _config(
        """\
        Host *.example.com !db.example.com
            User app
        Host db.example.com
            User dba
        """
    )
    assert resolve(config, "db.example.com").options["User"] == "dba"
    assert resolve(config, "web.example.com").options["User"] == "app"


def test_unmatched_host_gets_only_globals_and_defaults():
    config = _config(
        """\
        Host web
            User deploy
        """
    )
    resolved = resolve(config, "other")
    assert "User" not in resolved.options or resolved.options["User"] != "deploy"
    assert resolved.options["Port"] == "22"
    assert resolved.matched_blocks == []


def test_matched_blocks_reported_in_order():
    config = _config(
        """\
        Host *
            ServerAliveInterval 60
        Host web
            User deploy
        """
    )
    resolved = resolve(config, "web")
    assert resolved.matched_blocks == [["*"], ["web"]]


def test_match_blocks_are_not_evaluated():
    config = _config(
        """\
        Match user deploy
            ForwardAgent yes
        Host web
            User deploy
        """
    )
    resolved = resolve(config, "web")
    assert "ForwardAgent" not in resolved.options
    assert resolved.match_blocks_present
