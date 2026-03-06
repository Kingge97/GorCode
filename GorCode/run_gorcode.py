#!/usr/bin/env python
"""
GorCode Launcher
================

Simple launcher script for GorCode CLI.
"""

import sys
import os
from pathlib import Path

# Add the GorCode directory to path
gorcode_dir = Path(__file__).parent
sys.path.insert(0, str(gorcode_dir))

# Import and run main
from frontend.cli.main import main

if __name__ == "__main__":
    main()
