"""Parser for OpenSSH client configuration files (``ssh_config``).

Faithful to the parts of the format that matter for tooling:

* keywords are case-insensitive; a value may be separated from its key
  by whitespace, ``=``, or whitespace around ``=``;
* ``#`` starts a comment when it begins a line or follows whitespace;
* options before the first ``Host``/``Match`` block are global defaults;
* ``Include`` directives are expanded in place (globs supported,
  relative paths resolve against the including file's directory,
  include cycles are skipped);
* every block records its line span so the editor can splice it out
  without touching the rest of the file. Comments and blank lines
  directly above a ``Host`` line are treated as part of that block —
  that is where a human puts the comment describing the host.
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field


class SshConfigError(ValueError):
    """Raised when a config file cannot be parsed."""


@dataclass
class HostBlock:
    """One ``Host`` (or ``Match``) block plus its options."""

    patterns: list[str] = field(default_factory=list)
    options: list[tuple[str, str]] = field(default_factory=list)
    is_match: bool = False
    match_criteria: str = ""
    start_line: int = 0  # first line of the block (incl. its header comment)
    end_line: int = 0  # line after the last line of the block (exclusive)

    def get(self, key: str) -> str | None:
        """First value for ``key`` (case-insensitive), or None."""
        wanted = key.lower()
        for k, v in self.options:
            if k.lower() == wanted:
                return v
        return None

    def get_all(self, key: str) -> list[str]:
        """Every value for ``key`` (case-insensitive), in file order."""
        wanted = key.lower()
        return [v for k, v in self.options if k.lower() == wanted]


@dataclass
class SshConfig:
    """A parsed config file."""

    path: str
    global_options: list[tuple[str, str]] = field(default_factory=list)
    blocks: list[HostBlock] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)

    def host_blocks(self) -> list[HostBlock]:
        return [b for b in self.blocks if not b.is_match]

    def match_blocks(self) -> list[HostBlock]:
        return [b for b in self.blocks if b.is_match]

    def find_blocks(self, name: str) -> list[HostBlock]:
        """Blocks that list ``name`` as one of their patterns (exact)."""
        return [b for b in self.host_blocks() if name in b.patterns]


def _strip_comment(line: str) -> str:
    """Remove a ``#`` comment: ``#`` at line start or after whitespace."""
    for i, ch in enumerate(line):
        if ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i]
    return line


def _split_key_value(text: str) -> tuple[str, str]:
    """Split ``Key value``, ``Key=value`` or ``Key = value``.

    The value keeps its internal spacing (e.g. a ProxyCommand), but
    surrounding whitespace is stripped.
    """
    stripped = text.strip()
    if "=" in stripped:
        key, _, rest = stripped.partition("=")
        key = key.strip()
        if key and not any(c.isspace() for c in key):
            return key, rest.strip()
    parts = stripped.split(None, 1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1].strip()


def parse_config(text: str, path: str = "<string>") -> SshConfig:
    """Parse config text. ``Include`` directives are *not* expanded here;
    use :func:`parse_file` for a file on disk."""
    lines = text.splitlines()
    return _parse_lines(lines, path, base_dir=None, chain=())


def parse_file(path: str) -> SshConfig:
    """Parse a config file from disk, expanding ``Include`` directives."""
    expanded = os.path.expanduser(path)
    if not os.path.isfile(expanded):
        raise SshConfigError(f"config file not found: {path}")
    with open(expanded, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()
    base_dir = os.path.dirname(os.path.abspath(expanded))
    return _parse_lines(lines, expanded, base_dir=base_dir, chain=(os.path.abspath(expanded),))


def _parse_lines(
    lines: list[str],
    path: str,
    base_dir: str | None,
    chain: tuple[str, ...],
) -> SshConfig:
    config = SshConfig(path=path, lines=list(lines))
    current: HostBlock | None = None
    # First blank/comment line after the last option line. An
    # interstitial run like this usually holds the comment describing
    # the *next* host, so it belongs to the next block's span.
    interstitial_start: int | None = None

    def close_block(end: int) -> None:
        nonlocal current
        if current is not None:
            current.end_line = end
            config.blocks.append(current)
            current = None

    for idx, raw in enumerate(lines):
        stripped = _strip_comment(raw).strip()
        if not stripped:
            if interstitial_start is None:
                interstitial_start = idx
            continue
        key, value = _split_key_value(stripped)
        lowered = key.lower()

        if lowered == "include" and base_dir is not None:
            close_block(interstitial_start if interstitial_start is not None else idx)
            interstitial_start = None
            _expand_include(config, value, base_dir, chain)
            continue

        if lowered in ("host", "match"):
            first_block = not config.blocks and current is None
            # Comments above the first block are file-header comments
            # and stay put; comments above later blocks describe the
            # host below them and move with it.
            span_start = idx if first_block else (
                interstitial_start if interstitial_start is not None else idx
            )
            close_block(span_start)
            interstitial_start = None
            current = HostBlock(start_line=span_start, end_line=idx + 1)
            if lowered == "host":
                if not value:
                    raise SshConfigError(f"{path}:{idx + 1}: 'Host' needs at least one pattern")
                current.patterns = value.split()
            else:
                current.is_match = True
                current.match_criteria = value
                if not value:
                    raise SshConfigError(f"{path}:{idx + 1}: 'Match' needs criteria")
            continue

        # A regular option line: any blank/comment run before it was
        # inside the current block (or the global section), not a
        # separator, so forget the interstitial marker.
        interstitial_start = None
        if current is None:
            config.global_options.append((key, value))
        else:
            current.options.append((key, value))

    close_block(len(lines))
    return config


def _expand_include(
    config: SshConfig, value: str, base_dir: str, chain: tuple[str, ...]
) -> None:
    """Inline the files matched by an ``Include`` directive."""
    if not value:
        return
    for token in value.split():
        pattern = os.path.expanduser(token)
        if not os.path.isabs(pattern):
            pattern = os.path.join(base_dir, pattern)
        matches = sorted(glob.glob(pattern))
        # A missing literal file (no glob characters, no match) is
        # silently ignored, matching OpenSSH behaviour; the validator
        # reports it as a warning instead.
        for match in matches:
            real = os.path.abspath(match)
            if real in chain:
                continue  # include cycle — skip rather than recurse forever
            if not os.path.isfile(real):
                continue
            with open(real, "r", encoding="utf-8", errors="replace") as fh:
                sub_lines = fh.read().splitlines()
            sub_dir = os.path.dirname(real)
            sub = _parse_lines(sub_lines, real, base_dir=sub_dir, chain=chain + (real,))
            config.global_options.extend(sub.global_options)
            config.blocks.extend(sub.blocks)
