"""Safe editing: add and remove ``Host`` blocks.

Edits are atomic — the new file is written to a temporary file in the
same directory and moved over the original with :func:`os.replace` —
and a ``.bak`` copy of the previous file is kept unless the caller opts
out. Nothing is ever edited in place.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass

from .parser import SshConfig, parse_file


@dataclass
class EditResult:
    path: str
    action: str
    details: str
    changed: bool
    backup_path: str | None = None


def _atomic_write(path: str, lines: list[str], backup: bool) -> str | None:
    """Write ``lines`` to ``path`` atomically; return the backup path."""
    backup_path = None
    if backup and os.path.isfile(path):
        backup_path = path + ".bak"
        shutil.copyfile(path, backup_path)
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".ssh-config-", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
            if lines:
                fh.write("\n")
    except BaseException:
        os.unlink(tmp_path)
        raise
    os.replace(tmp_path, path)
    return backup_path


def add_host(
    path: str,
    name: str,
    options: list[tuple[str, str]],
    *,
    dry_run: bool = False,
    backup: bool = True,
    force: bool = False,
) -> EditResult:
    """Append a ``Host <name>`` block.

    Refuses when a block already lists ``name`` exactly, unless
    ``force`` is given. With ``dry_run`` nothing is written.
    """
    config: SshConfig | None = None
    if os.path.isfile(os.path.expanduser(path)):
        config = parse_file(path)
        if config.find_blocks(name) and not force:
            raise ValueError(
                f"host '{name}' is already defined in {path} "
                "(use --force to add a second block)"
            )
    lines = list(config.lines) if config is not None else []
    block_lines = [f"Host {name}"]
    block_lines.extend(f"    {key} {value}" for key, value in options)
    if lines and lines[-1].strip():
        lines.append("")
    lines.extend(block_lines)
    if dry_run:
        return EditResult(path, "add", f"would add host '{name}'", changed=False)
    parent = os.path.dirname(os.path.abspath(os.path.expanduser(path)))
    os.makedirs(parent, exist_ok=True)
    backup_path = _atomic_write(os.path.expanduser(path), lines, backup)
    return EditResult(
        path, "add", f"added host '{name}'", changed=True, backup_path=backup_path
    )


def remove_host(
    path: str,
    name: str,
    *,
    dry_run: bool = False,
    backup: bool = True,
) -> EditResult:
    """Remove every block that lists ``name`` as one of its patterns.

    The comment and blank lines directly above a removed block go with
    it (see the parser); the file header above the first block stays.
    """
    config = parse_file(path)
    matches = config.find_blocks(name)
    if not matches:
        raise ValueError(f"host '{name}' is not defined in {path}")
    doomed = sorted({(b.start_line, b.end_line) for b in matches})
    keep = list(config.lines)
    for start, end in reversed(doomed):
        del keep[start:end]
    # Collapse runs of 3+ blank lines left behind by the removal.
    cleaned: list[str] = []
    blanks = 0
    for line in keep:
        if line.strip():
            blanks = 0
            cleaned.append(line)
        else:
            blanks += 1
            if blanks <= 2:
                cleaned.append(line)
    # Drop leading blank lines if the first block was removed.
    while cleaned and not cleaned[0].strip():
        cleaned.pop(0)
    if dry_run:
        return EditResult(
            path, "remove", f"would remove {len(matches)} block(s) for '{name}'", changed=False
        )
    backup_path = _atomic_write(os.path.expanduser(path), cleaned, backup)
    return EditResult(
        path,
        "remove",
        f"removed {len(matches)} block(s) for '{name}'",
        changed=True,
        backup_path=backup_path,
    )
