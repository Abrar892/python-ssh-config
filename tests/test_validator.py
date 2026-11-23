"""Tests for the config validator."""

import textwrap

from sshconfig.parser import parse_config
from sshconfig.validator import validate


def _issues(text):
    return validate(parse_config(textwrap.dedent(text)))


def test_clean_config_has_no_issues(tmp_path):
    key = tmp_path / "id_ed25519"
    key.write_text("fake-key")
    issues = _issues(
        f"""\
        Host web
            HostName web.example.com
            User deploy
            Port 2222
            IdentityFile {key}
            ForwardAgent yes
        """
    )
    assert issues == []


def test_unknown_directive_is_a_warning():
    issues = _issues("Host web\n    HostNam web.example.com\n")
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert "HostNam" in issues[0].message


def test_non_numeric_port_is_an_error():
    issues = _issues("Host web\n    Port abc\n")
    assert any(i.severity == "error" and "not a number" in i.message for i in issues)


def test_out_of_range_port_is_an_error():
    issues = _issues("Host web\n    Port 70000\n")
    assert any(i.severity == "error" and "out of range" in i.message for i in issues)


def test_bad_boolean_is_an_error():
    issues = _issues("Host web\n    ForwardAgent maybe\n")
    assert any(i.severity == "error" and "yes/no" in i.message for i in issues)


def test_bad_strict_host_key_checking_is_an_error():
    issues = _issues("Host web\n    StrictHostKeyChecking sometimes\n")
    assert any(i.severity == "error" for i in issues)


def test_missing_identity_file_is_a_warning(tmp_path):
    issues = _issues("Host web\n    IdentityFile /nonexistent/id_ed25519\n")
    assert any(i.severity == "warning" and "does not exist" in i.message for i in issues)


def test_duplicate_host_is_a_warning():
    issues = _issues(
        "Host web\n    HostName a.example.com\nHost web\n    HostName b.example.com\n"
    )
    assert any(i.severity == "warning" and "more than once" in i.message for i in issues)


def test_shadowed_option_is_a_warning():
    issues = _issues("Host web\n    User first\n    User second\n")
    assert any(i.severity == "warning" and "first value wins" in i.message for i in issues)


def test_empty_block_is_a_warning():
    issues = _issues("Host web\nHost db\n    HostName db.example.com\n")
    assert any(i.severity == "warning" and "empty block" in i.message for i in issues)


def test_proxy_jump_to_undefined_host_is_a_warning():
    issues = _issues(
        "Host web\n    ProxyJump nowhere\n"
    )
    assert any(i.severity == "warning" and "ProxyJump" in i.message for i in issues)


def test_proxy_jump_to_defined_host_is_clean():
    issues = _issues(
        "Host bastion\n    HostName bastion.example.com\n"
        "Host web\n    ProxyJump bastion\n"
    )
    assert issues == []


def test_missing_include_is_a_warning(tmp_path):
    config = parse_config("Include missing.conf\nHost web\n    HostName example.com\n")
    config.path = str(tmp_path / "config")  # includes resolve against the file's dir
    issues = validate(config)
    assert any(i.severity == "warning" and "matches no file" in i.message for i in issues)


def test_multi_value_options_are_not_flagged_as_duplicates():
    issues = _issues(
        "Host web\n    IdentityFile ~/.ssh/a\n    IdentityFile ~/.ssh/b\n"
    )
    assert not any("duplicate option" in i.message for i in issues)
