"""Effective-config resolution with OpenSSH first-obtained-value semantics.

For a hostname, every ``Host`` block whose patterns match is consulted
in file order. For most options the *first* value seen wins; a small
set of multi-valued options (``IdentityFile``, forwards, ...) accumulates
every value. ``Match`` blocks are parsed but deliberately not evaluated
here — their criteria can depend on the local user, the executed
command or the network, which a static resolver cannot know.
"""

from __future__ import annotations

import getpass
import os
from dataclasses import dataclass, field

from .matcher import match_host_patterns
from .parser import HostBlock, SshConfig

# Options that accumulate instead of first-wins (ssh_config(5)).
MULTI_VALUE_KEYS = frozenset(
    {
        "identityfile",
        "certificatefile",
        "localforward",
        "remoteforward",
        "dynamicforward",
        "sendenv",
        "setenv",
        "authorizedkeysfile",
        "canonicalizepermittedcnames",
        "kbdinteractivedevices",
        "listenaddress",
        "permitremoteopen",
        "revokedhostkeys",
        "userknownhostsfile",
        "globalknownhostsfile",
        "pubkeyacceptedalgorithms",
        "pubkeyacceptedkeytypes",
        "hostkeyalgorithms",
        "hostbasedacceptedalgorithms",
        "gssapikexalgorithms",
        "kexalgorithms",
        "ciphers",
        "macs",
        "securitykeyprovider",
    }
)


@dataclass
class ResolvedConfig:
    """The effective configuration for one hostname."""

    hostname: str
    options: dict[str, str | list[str]] = field(default_factory=dict)
    matched_blocks: list[list[str]] = field(default_factory=list)
    defaults: dict[str, str] = field(default_factory=dict)
    match_blocks_present: bool = False

    def get(self, key: str, default: str | None = None) -> str | list[str] | None:
        return self.options.get(key, default)


def _default_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return os.environ.get("USER", os.environ.get("LOGNAME", "user"))


def resolve(config: SshConfig, hostname: str) -> ResolvedConfig:
    """Compute the effective options for ``hostname``."""
    result = ResolvedConfig(hostname=hostname)
    seen: set[str] = set()

    def apply(options: list[tuple[str, str]]) -> None:
        for key, value in options:
            lowered = key.lower()
            if lowered in MULTI_VALUE_KEYS:
                existing = result.options.get(key)
                if existing is None:
                    result.options[key] = [value]
                elif isinstance(existing, list):
                    existing.append(value)
            elif lowered not in seen:
                seen.add(lowered)
                result.options[key] = value

    apply(config.global_options)
    for block in config.blocks:
        if block.is_match:
            result.match_blocks_present = True
            continue
        if match_host_patterns(block.patterns, hostname):
            result.matched_blocks.append(list(block.patterns))
            apply(block.options)

    # OpenSSH built-in defaults, recorded separately so callers can
    # tell a default from an explicit value.
    if "hostname" not in seen:
        result.defaults["HostName"] = hostname
    if "port" not in seen:
        result.defaults["Port"] = "22"
    if "user" not in seen:
        result.defaults["User"] = _default_user()
    result.options.update({k: v for k, v in result.defaults.items() if k not in result.options})
    return result


def first_host_pattern(block: HostBlock) -> str:
    """A block's display name: its first non-negated pattern, or ``*``."""
    for pattern in block.patterns:
        if not pattern.startswith("!"):
            return pattern
    return block.patterns[0] if block.patterns else "*"
