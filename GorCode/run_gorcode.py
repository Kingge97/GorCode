#!/usr/bin/env python
"""
GorCode Launcher
================

Simple launcher script for GorCode CLI.
"""

import sys
import os
from pathlib import Path


def _prepend_rg_path() -> None:
    """Prepend ~/.gorcode/gorpath/path to PATH when available."""
    rg_dir = Path.home() / ".gorcode" / "gorpath" / "path"
    if not rg_dir.is_dir():
        return

    rg_dir_str = str(rg_dir)
    current_path = os.environ.get("PATH", "")
    existing_entries = current_path.split(os.pathsep) if current_path else []

    normalized_rg = os.path.normcase(os.path.normpath(rg_dir_str))
    has_entry = any(
        os.path.normcase(os.path.normpath(entry)) == normalized_rg
        for entry in existing_entries
        if entry
    )
    if has_entry:
        return

    os.environ["PATH"] = (
        f"{rg_dir_str}{os.pathsep}{current_path}" if current_path else rg_dir_str
    )


_prepend_rg_path()

# Add repo root and GorCode dir to sys.path so imports work from any cwd
repo_root = Path(__file__).resolve().parent.parent
gorcode_dir = repo_root / "GorCode"
for p in (str(repo_root), str(gorcode_dir)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Import and run main
from GorCode.frontend.cli.main import main

if __name__ == "__main__":
    main()
