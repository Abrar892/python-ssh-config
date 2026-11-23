"""Static checks for an SSH config file.

Finds the mistakes that cost an afternoon: typos in directive names,
ports that are not ports, identity files that do not exist, the same
host defined twice, and options silently shadowed by an earlier
``Host`` block (first-obtained-value semantics mean a later duplicate
never takes effect).
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass

from .parser import SshConfig
from .resolver import MULTI_VALUE_KEYS

# Directive names from ssh_config(5) (OpenSSH 9.x). Matching is
# case-insensitive; anything outside this set is flagged.
KNOWN_KEYWORDS = frozenset(
    {
        "host", "match", "include",
        "hostname", "user", "port", "identityfile", "identityagent",
        "identitiesonly", "addkeystoagent", "batchmode", "bindaddress",
        "bindinterface", "canonicalizefallback", "canonicalizehostname",
        "canonicalizemaxcnames", "canonicalizepermittedcnames",
        "casignaturealgorithms", "certificatefile",
        "challengeresponseauthentication", "checkhostip", "ciphers",
        "clearallforwardings", "compression", "connectionattempts",
        "connecttimeout", "controlmaster", "controlpath", "controlpersist",
        "dynamicforward", "enablesshkeysign", "exitonforwardfailure",
        "fingerprinthash", "forwardagent", "forwardx11",
        "forwardx11timeout", "forwardx11trusted", "gatewayports",
        "globalknownhostsfile", "gssapiauthentication",
        "gssapidelegatecredentials", "gssapikexalgorithms",
        "gssapirenewalforcesrekey", "gssapiserveridentity", "gssapitrustdns",
        "hashknownhosts", "hostbasedauthentication",
        "hostbasedacceptedalgorithms", "hostkeyalgorithms", "hostkeyalias",
        "ignoreunknown", "ipqos", "kbdinteractiveauthentication",
        "kbdinteractivedevices", "kexalgorithms", "knownhostscommand",
        "localcommand", "localforward", "loglevel", "logverbose", "macs",
        "nohostauthenticationforlocalhost", "numberofpasswordprompts",
        "passwordauthentication", "permitlocalcommand", "permitremoteopen",
        "pkcs11provider", "preferredauthentications", "proxycommand",
        "proxyjump", "proxyusefdpass", "pubkeyacceptedalgorithms",
        "pubkeyacceptedkeytypes", "pubkeyauthentication", "rekeylimit",
        "remotecommand", "remoteforward", "requesttty", "revokedhostkeys",
        "securitykeyprovider", "sendenv", "serveralivecountmax",
        "serveraliveinterval", "sessiontype", "setenv", "stdinnull",
        "streamlocalbindmask", "streamlocalbindunlink",
        "stricthostkeychecking", "syslogfacility", "tcpkeepalive", "tag",
        "tunnel", "tunneldevice", "updatehostkeys", "userknownhostsfile",
        "verifyhostkeydns", "visualhostkey", "xauthlocation",
    }
)

BOOLEAN_KEYS = frozenset(
    {
        "batchmode", "compression", "forwardagent", "forwardx11",
        "forwardx11trusted", "gssapiauthentication", "gssapidelegatecredentials",
        "gssapirenewalforcesrekey", "gssapitrustdns", "hashknownhosts",
        "hostbasedauthentication", "identitiesonly", "kbdinteractiveauthentication",
        "passwordauthentication", "permitlocalcommand", "pubkeyauthentication",
        "stdinnull", "tcpkeepalive", "visualhostkey", "addkeystoagent",
        "enablesshkeysign", "checkhostip", "exitonforwardfailure",
        "gatewayports", "nohostauthenticationforlocalhost",
        "proxyusefdpass", "streamlocalbindunlink", "updatehostkeys",
        "verifyhostkeydns", "clearallforwardings",
    }
)

YES_NO = {"yes", "no", "true", "false", "1", "0", "on", "off"}


@dataclass
class Issue:
    severity: str  # "error" or "warning"
    message: str
    line: int | None = None

    def __str__(self) -> str:
        where = f"line {self.line}: " if self.line else ""
        return f"{self.severity}: {where}{self.message}"


def validate(config: SshConfig) -> list[Issue]:
    """Check a parsed config and return every issue found."""
    issues: list[Issue] = []
    seen_hosts: dict[str, int] = {}

    def check_options(options: list[tuple[str, str]], where: str) -> None:
        seen: dict[str, int] = {}
        for key, value in options:
            lowered = key.lower()
            if lowered not in KNOWN_KEYWORDS:
                issues.append(
                    Issue("warning", f"unknown directive '{key}' {where} — ignored by ssh")
                )
                continue
            if lowered in seen and lowered not in MULTI_VALUE_KEYS:
                issues.append(
                    Issue(
                        "warning",
                        f"duplicate option '{key}' {where} — first value wins, this one is ignored",
                    )
                )
            seen.setdefault(lowered, 1)
            if lowered == "port":
                _check_port(value, where, issues)
            elif lowered in BOOLEAN_KEYS and value.lower() not in YES_NO:
                issues.append(
                    Issue("error", f"'{key}' expects yes/no, got '{value}' {where}")
                )
            elif lowered == "stricthostkeychecking" and value.lower() not in {
                "yes", "no", "ask", "accept-new",
            }:
                issues.append(
                    Issue(
                        "error",
                        f"'StrictHostKeyChecking' expects yes/no/ask/accept-new, got '{value}' {where}",
                    )
                )
            elif lowered == "identityfile":
                _check_identity_file(value, where, issues)

    check_options(config.global_options, "in the global section")
    for block in config.blocks:
        where = (
            f"in 'Match {block.match_criteria}'"
            if block.is_match
            else f"in 'Host {' '.join(block.patterns)}'"
        )
        if block.is_match:
            check_options(block.options, where)
            continue
        if not block.options:
            issues.append(Issue("warning", f"empty block {where}"))
        for pattern in block.patterns:
            if pattern.startswith("!"):
                continue
            if pattern in seen_hosts:
                issues.append(
                    Issue(
                        "warning",
                        f"host '{pattern}' is defined more than once "
                        f"(first at block {seen_hosts[pattern]}, again {where})",
                    )
                )
            else:
                seen_hosts[pattern] = len(seen_hosts) + 1
        check_options(block.options, where)
        _check_proxy_jump(block, config, issues, where)

    _check_includes(config, issues)
    return issues


def _check_port(value: str, where: str, issues: list[Issue]) -> None:
    try:
        port = int(value)
    except ValueError:
        issues.append(Issue("error", f"Port '{value}' is not a number {where}"))
        return
    if not 1 <= port <= 65535:
        issues.append(Issue("error", f"Port {port} is out of range (1-65535) {where}"))


def _check_identity_file(value: str, where: str, issues: list[Issue]) -> None:
    expanded = os.path.expanduser(value)
    if not os.path.isfile(expanded):
        issues.append(
            Issue("warning", f"IdentityFile '{value}' does not exist {where}")
        )


def _check_proxy_jump(block, config: SshConfig, issues: list[Issue], where: str) -> None:
    jump = block.get("ProxyJump")
    if not jump or jump == "none":
        return
    # "user@host:port" or a comma-separated chain of jump hosts.
    defined = set()
    for b in config.host_blocks():
        defined.update(p for p in b.patterns if not p.startswith("!"))
    for hop in jump.split(","):
        host = hop.strip().split("@")[-1].split(":")[0]
        if host and host not in defined and "*" not in host:
            issues.append(
                Issue(
                    "warning",
                    f"ProxyJump target '{host}' has no matching Host block {where}",
                )
            )


def _check_includes(config: SshConfig, issues: list[Issue]) -> None:
    # Re-scan the raw lines: includes are already expanded in the
    # parsed model, so their absence has to be checked from source.
    base_dir = os.path.dirname(os.path.abspath(config.path))
    for idx, raw in enumerate(config.lines):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "include":
            for token in parts[1].split():
                pattern = os.path.expanduser(token)
                if not os.path.isabs(pattern):
                    pattern = os.path.join(base_dir, pattern)
                if not glob.glob(pattern):
                    issues.append(
                        Issue(
                            "warning",
                            f"Include '{token}' matches no file",
                            line=idx + 1,
                        )
                    )
