"""
File IO Helpers
===============

Shared IO helpers for file tools.
"""

from __future__ import annotations

from pathlib import Path


def write_text_file(
    path: Path,
    content: str,
    encoding: str,
    *,
    create_parents: bool = False,
) -> None:
    if create_parents:
        path.parent.mkdir(parents=True, exist_ok=True)
    # Preserve explicit line endings already normalized by callers.
    # Using Path.write_text (newline=None) on Windows will translate '\n' to '\r\n',
    # which would turn existing '\r\n' into '\r\r\n' and create blank lines.
    with path.open("w", encoding=encoding, newline="") as handle:
        handle.write(content)
