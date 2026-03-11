#!/usr/bin/env python
"""
GorCode Launcher
================

Simple launcher script for GorCode CLI.
"""

import sys
import os
from pathlib import Path

# Add repo root and GorCode dir to sys.path so imports work from any cwd
repo_root = Path(__file__).resolve().parent.parent
gorcode_dir = repo_root / "GorCode"
for p in (str(repo_root), str(gorcode_dir)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Import and run main
from frontend.cli.main import main

if __name__ == "__main__":
    main()
