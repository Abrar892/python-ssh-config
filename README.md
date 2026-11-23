# ssh-config — SSH Config Manager CLI

A zero-dependency Python CLI for managing OpenSSH client config files
(`~/.ssh/config`): list hosts, see the *effective* config for a host,
lint the file for the mistakes that cost an afternoon, test whether a
host is reachable, and add or remove hosts with atomic, backed-up edits.

## Why this exists

`~/.ssh/config` grows by copy-paste. After a while nobody knows which
`Host` block actually wins for `web`, whether the `IdentityFile` still
exists, or if that `Port 222` was a typo. This tool answers those
questions from the file itself, using the same rules `ssh` does.

## Install

Requires Python 3.9+ and nothing else — no third-party dependencies.

```bash
pip install .
ssh-config list
```

Or run it straight from a checkout:

```bash
PYTHONPATH=src python -m sshconfig list
```

## Usage

```bash
# List every host in ~/.ssh/config
ssh-config list

# Show the effective config for one host (first-wins merging applied)
ssh-config resolve web

# Add a host (refuses duplicates unless --force)
ssh-config add web --hostname 203.0.113.10 --user deploy --port 2222 \
    --identity-file ~/.ssh/id_ed25519

# Remove a host (its comment travels with it; the file header stays)
ssh-config remove web

# Lint the file: typos, bad ports, missing keys, shadowed options
ssh-config check

# Test TCP reachability of the resolved host:port
ssh-config probe web

# JSON output for scripting
ssh-config list --json
ssh-config resolve web --json
ssh-config check --json

# Work on a different file, preview an edit, skip the backup
ssh-config --config ~/other-config list
ssh-config add db --hostname db.example.com --dry-run
ssh-config remove db --no-backup
```

Every edit is atomic (write to a temp file in the same directory, then
`os.replace`) and keeps a `.bak` copy of the previous file.

## How resolution works

OpenSSH's rule is **first obtained value wins**: for a hostname, every
matching `Host` block is consulted in file order, and the first value
seen for an option is the one that applies. A small set of options
accumulates instead — `IdentityFile`, `LocalForward`, `RemoteForward`,
`DynamicForward`, `SendEnv`, and friends — because that is what `ssh`
does with them. `resolve` applies that rule and fills in the built-in
defaults (`Port 22`, `HostName` = the host you asked about, `User` =
your login name), marking them as defaults so you can tell an explicit
value from a fallback.

Patterns support OpenSSH wildcards: `*` matches any sequence,
`?` matches one character, and a leading `!` negates a pattern.
`Host *.staging.example.com !db.staging.example.com` does what you
would expect. One deliberate deviation: matching is case-insensitive,
because hostnames are — `Host GitHub.com` matches `github.com`.

## Design decisions

1. **Faithful first-wins semantics, not "last wins".** Most config
   tools merge with later values overriding earlier ones. `ssh` does
   the opposite, and getting this wrong makes `resolve` lie about
   which block is in charge.
2. **Comments belong to the host below them.** When `remove` deletes a
   block it also removes the comment and blank lines directly above
   it, because that comment describes the host. The header comment at
   the top of the file is treated as file header and always stays.
3. **`Match` blocks are parsed but not evaluated.** Their criteria can
   depend on the local user, the command being run, or the network —
   things a static resolver cannot know. `list` shows them and
   `resolve` tells you they were skipped, rather than silently
   pretending they applied.
4. **Edits never touch the file in place.** Atomic replace plus a
   `.bak` backup means a crashed or interrupted edit cannot leave a
   half-written config behind.
5. **The linter knows the directive list.** `check` flags typos such
   as `HostNam` (which `ssh` would silently ignore), ports that are
   not ports, identity files that do not exist, hosts defined twice,
   options shadowed by an earlier block, and `ProxyJump` targets with
   no matching `Host` block.

## What `check` catches

| Problem | Severity |
| --- | --- |
| Unknown directive (e.g. `HostNam`) | warning |
| `Port` not a number, or outside 1–65535 | error |
| Boolean option given a non yes/no value | error |
| `StrictHostKeyChecking` outside yes/no/ask/accept-new | error |
| `IdentityFile` path does not exist | warning |
| Same host defined in two blocks | warning |
| Option repeated in a block (later value ignored) | warning |
| Empty `Host` block | warning |
| `ProxyJump` target with no matching block | warning |
| `Include` matching no file | warning |

## Running the tests

```bash
pip install pytest
python -m pytest
```

The suite covers wildcard matching (including negation), parsing
(`=` forms, comments, `Include` globs and cycles), first-wins
resolution, atomic add/remove with backups, every validator rule,
TCP probing against a local server, and the CLI end to end.

## Project structure

```
src/sshconfig/
    matcher.py    wildcard pattern matching with '!' negation
    parser.py     ssh_config parser (blocks, globals, Include expansion)
    resolver.py   effective-config resolution, first-obtained-value
    editor.py     atomic add/remove with .bak backups
    validator.py  static checks (typos, ports, keys, shadowing)
    probe.py      TCP reachability probe
    cli.py        argparse interface (list/resolve/add/remove/check/probe)
tests/            pytest suite (matcher, parser, resolver, editor,
                  validator, probe, CLI)
examples/
    example_config   a sample config to try the CLI against
```

## License

MIT — see [LICENSE](LICENSE).
