"""Tests for OpenSSH-style wildcard host-pattern matching."""

from sshconfig.matcher import match_host_patterns, match_pattern


def test_star_matches_anything_including_empty():
    assert match_pattern("*", "web.example.com")
    assert match_pattern("*.example.com", "web.example.com")
    assert match_pattern("web.*", "web.")
    assert not match_pattern("*.example.com", "example.com")


def test_question_mark_matches_exactly_one_char():
    assert match_pattern("web?", "web1")
    assert not match_pattern("web?", "web")
    assert not match_pattern("web?", "web12")


def test_literal_match_is_case_insensitive():
    assert match_pattern("GitHub.com", "github.com")
    assert match_pattern("WEB", "web")


def test_star_does_not_cross_semantics():
    # '*' matches any characters, including dots — like OpenSSH.
    assert match_pattern("*.com", "a.b.com")
    assert not match_pattern("web.*.com", "web.com")


def test_no_match():
    assert not match_pattern("db-*", "web-01")
    assert not match_pattern("prod", "production")


def test_negation_excludes():
    assert match_host_patterns(["*", "!bastion"], "web")
    assert not match_host_patterns(["*", "!bastion"], "bastion")
    assert not match_host_patterns(["*.example.com", "!db.example.com"], "db.example.com")
    assert match_host_patterns(["*.example.com", "!db.example.com"], "web.example.com")


def test_negation_only_never_matches():
    assert not match_host_patterns(["!web"], "web")
    assert not match_host_patterns(["!web"], "db")


def test_empty_pattern_list_never_matches():
    assert not match_host_patterns([], "web")
