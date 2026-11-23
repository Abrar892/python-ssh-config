"""Command-line interface for ssh-config.

    ssh-config list [--config PATH] [--json]
    ssh-config resolve HOST [--config PATH] [--json]
    ssh-config add NAME [--hostname H] [--user U] [--port P]
                       [--identity-file F] [--option Key=Value ...]
                       [--config PATH] [--force] [--dry-run] [--no-backup]
    ssh-config remove NAME [--config PATH] [--dry-run] [--no-backup]
    ssh-config check [--config PATH] [--json]
    ssh-config probe HOST [--config PATH] [--timeout SECONDS]

Exit codes: 0 success, 1 the requested thing failed (host not found,
unreachable, validation errors, duplicate host), 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .editor import add_host, remove_host
from .parser import SshConfigError, parse_file
from .probe import probe as tcp_probe
from .resolver import first_host_pattern, resolve
from .validator import validate

DEFAULT_CONFIG = "~/.ssh/config"


def _load_config(path: str):
    try:
        return parse_file(path)
    except SshConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2))


def _cmd_list(args: argparse.Namespace) -> int:
    config = _load_config(args.config)
    hosts = []
    for block in config.host_blocks():
        hosts.append(
            {
                "name": first_host_pattern(block),
                "patterns": block.patterns,
                "hostname": block.get("HostName"),
                "user": block.get("User"),
                "port": block.get("Port"),
                "identity_files": block.get_all("IdentityFile"),
            }
        )
    if args.json:
        _print_json({"config": os.path.expanduser(args.config), "hosts": hosts})
        return 0
    if not hosts:
        print(f"no hosts defined in {args.config}")
        return 0
    width = max(len(h["name"]) for h in hosts)
    for host in hosts:
        detail = " ".join(
            part
            for part in (
                host["hostname"] or "",
                f"user={host['user']}" if host["user"] else "",
                f"port={host['port']}" if host["port"] else "",
            )
            if part
        )
        print(f"{host['name']:<{width}}  {detail}".rstrip())
    return 0


def _cmd_resolve(args: argparse.Namespace) -> int:
    config = _load_config(args.config)
    resolved = resolve(config, args.host)
    if args.json:
        _print_json(
            {
                "host": args.host,
                "options": resolved.options,
                "matched_blocks": resolved.matched_blocks,
                "defaults_applied": resolved.defaults,
            }
        )
        return 0
    print(f"effective config for {args.host}:")
    for key, value in resolved.options.items():
        if isinstance(value, list):
            for item in value:
                print(f"  {key} {item}")
        else:
            marker = " (default)" if key in resolved.defaults else ""
            print(f"  {key} {value}{marker}")
    if resolved.matched_blocks:
        matched = ", ".join(" ".join(b) for b in resolved.matched_blocks)
        print(f"matched blocks: {matched}")
    if resolved.match_blocks_present:
        print("note: Match blocks are parsed but not evaluated by resolve")
    return 0


def _cmd_add(args: argparse.Namespace) -> int:
    options: list[tuple[str, str]] = []
    if args.hostname:
        options.append(("HostName", args.hostname))
    if args.user:
        options.append(("User", args.user))
    if args.port:
        options.append(("Port", str(args.port)))
    if args.identity_file:
        options.append(("IdentityFile", args.identity_file))
    for raw in args.option or []:
        if "=" not in raw:
            print(f"error: --option expects Key=Value, got '{raw}'", file=sys.stderr)
            return 2
        key, _, value = raw.partition("=")
        options.append((key.strip(), value.strip()))
    try:
        result = add_host(
            args.config,
            args.name,
            options,
            dry_run=args.dry_run,
            backup=not args.no_backup,
            force=args.force,
        )
    except (ValueError, SshConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(result.details + (" (dry run — nothing written)" if args.dry_run else ""))
    if result.backup_path:
        print(f"backup saved to {result.backup_path}")
    return 0


def _cmd_remove(args: argparse.Namespace) -> int:
    try:
        result = remove_host(
            args.config, args.name, dry_run=args.dry_run, backup=not args.no_backup
        )
    except (ValueError, SshConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(result.details + (" (dry run — nothing written)" if args.dry_run else ""))
    if result.backup_path:
        print(f"backup saved to {result.backup_path}")
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    config = _load_config(args.config)
    issues = validate(config)
    if args.json:
        _print_json(
            {
                "config": os.path.expanduser(args.config),
                "issues": [
                    {"severity": i.severity, "message": i.message, "line": i.line}
                    for i in issues
                ],
            }
        )
    else:
        if not issues:
            print(f"{args.config}: OK — no issues found")
        for issue in issues:
            print(issue)
    errors = [i for i in issues if i.severity == "error"]
    return 1 if errors else 0


def _cmd_probe(args: argparse.Namespace) -> int:
    config = _load_config(args.config)
    resolved = resolve(config, args.host)
    hostname = resolved.options.get("HostName") or args.host
    try:
        port = int(resolved.options.get("Port", "22"))  # type: ignore[arg-type]
    except ValueError:
        print(f"error: resolved Port is not a number for host '{args.host}'", file=sys.stderr)
        return 1
    result = tcp_probe(str(hostname), port, timeout=args.timeout)
    if result.reachable:
        print(f"{args.host} ({hostname}:{port}) reachable in {result.latency_ms:.1f} ms")
        return 0
    print(f"{args.host} ({hostname}:{port}) unreachable: {result.error}")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ssh-config",
        description="Manage OpenSSH client config files (~/.ssh/config).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="list defined hosts")
    p_list.add_argument("--config", default=DEFAULT_CONFIG)
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=_cmd_list)

    p_resolve = sub.add_parser("resolve", help="show the effective config for a host")
    p_resolve.add_argument("host")
    p_resolve.add_argument("--config", default=DEFAULT_CONFIG)
    p_resolve.add_argument("--json", action="store_true")
    p_resolve.set_defaults(func=_cmd_resolve)

    p_add = sub.add_parser("add", help="add a Host block")
    p_add.add_argument("name")
    p_add.add_argument("--hostname")
    p_add.add_argument("--user")
    p_add.add_argument("--port", type=int)
    p_add.add_argument("--identity-file")
    p_add.add_argument("--option", action="append", default=[],
                       help="extra option as Key=Value (repeatable)")
    p_add.add_argument("--config", default=DEFAULT_CONFIG)
    p_add.add_argument("--force", action="store_true")
    p_add.add_argument("--dry-run", action="store_true")
    p_add.add_argument("--no-backup", action="store_true")
    p_add.set_defaults(func=_cmd_add)

    p_remove = sub.add_parser("remove", help="remove a Host block")
    p_remove.add_argument("name")
    p_remove.add_argument("--config", default=DEFAULT_CONFIG)
    p_remove.add_argument("--dry-run", action="store_true")
    p_remove.add_argument("--no-backup", action="store_true")
    p_remove.set_defaults(func=_cmd_remove)

    p_check = sub.add_parser("check", help="lint the config file")
    p_check.add_argument("--config", default=DEFAULT_CONFIG)
    p_check.add_argument("--json", action="store_true")
    p_check.set_defaults(func=_cmd_check)

    p_probe = sub.add_parser("probe", help="test TCP reachability of a host")
    p_probe.add_argument("host")
    p_probe.add_argument("--config", default=DEFAULT_CONFIG)
    p_probe.add_argument("--timeout", type=float, default=5.0)
    p_probe.set_defaults(func=_cmd_probe)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
