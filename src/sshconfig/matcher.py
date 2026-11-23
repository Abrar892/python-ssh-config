"""OpenSSH-style wildcard host-pattern matching.

A pattern is a non-whitespace string where ``*`` matches any sequence of
characters (including none) and ``?`` matches exactly one character.
Patterns may be negated with a leading ``!``.

A host matches a pattern list when it matches at least one non-negated
pattern and matches no negated pattern — the same rule OpenSSH applies
to ``Host`` and ``Match host`` lists.
"""

from __future__ import annotations


def match_pattern(pattern: str, hostname: str) -> bool:
    """Match one pattern against a hostname.

    Matching is case-insensitive: hostnames are case-insensitive, so
    ``Host GitHub.com`` should match ``github.com``. (OpenSSH itself
    matches case-sensitively; this is a deliberate, documented deviation.)
    """
    pattern = pattern.lower()
    hostname = hostname.lower()
    return _match_here(pattern, 0, hostname, 0)


def _match_here(pattern: str, pi: int, text: str, ti: int) -> bool:
    """Recursive glob match with memo-free backtracking.

    ``*`` tries every possible consumption length; ``?`` consumes one
    character. Hostnames are short, so the naive recursion is fine and
    far easier to audit than a compiled regex.
    """
    while pi < len(pattern):
        char = pattern[pi]
        if char == "*":
            # Collapse runs of '*' and try every split point.
            while pi < len(pattern) and pattern[pi] == "*":
                pi += 1
            if pi == len(pattern):
                return True
            for skip in range(len(text) - ti + 1):
                if _match_here(pattern, pi, text, ti + skip):
                    return True
            return False
        if ti >= len(text):
            return False
        if char == "?":
            pi += 1
            ti += 1
        elif char == text[ti]:
            pi += 1
            ti += 1
        else:
            return False
    return ti == len(text)


def match_host_patterns(patterns: list[str], hostname: str) -> bool:
    """Match a hostname against a list of patterns with ``!`` negation.

    Returns True when the host matches at least one positive pattern and
    no negated pattern. An all-negated list never matches.
    """
    matched_positive = False
    for pattern in patterns:
        if pattern.startswith("!"):
            if match_pattern(pattern[1:], hostname):
                return False
        elif match_pattern(pattern, hostname):
            matched_positive = True
    return matched_positive
