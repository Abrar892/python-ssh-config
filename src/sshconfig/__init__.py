"""sshconfig — a zero-dependency SSH client config manager.

Parse, resolve, lint and edit OpenSSH ``~/.ssh/config`` files with
faithful first-obtained-value semantics, wildcard host matching,
``Include`` expansion and atomic edits.
"""

from .matcher import match_host_patterns, match_pattern
from .parser import HostBlock, SshConfig, SshConfigError, parse_config, parse_file
from .resolver import ResolvedConfig, resolve

__version__ = "1.0.0"

__all__ = [
    "HostBlock",
    "ResolvedConfig",
    "SshConfig",
    "SshConfigError",
    "__version__",
    "match_host_patterns",
    "match_pattern",
    "parse_config",
    "parse_file",
    "resolve",
]
