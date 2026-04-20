#!/usr/bin/env python3
"""Create ~/.gorcode and seed default configuration from reference template."""

import argparse
import shutil
from pathlib import Path

GORCODE_DIR_NAME = ".gorcode"
DEFAULT_CONFIG_NAME = "config.json"
REQUIRED_SUBDIRS = ("sessions", "gorpath", "gorpath/path")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Create ~/.gorcode and copy default config template.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite ~/.gorcode/config.json when it already exists.",
    )
    return parser.parse_args()


def resolve_paths() -> tuple[Path, Path, Path]:
    """Resolve source and target paths for configuration generation."""
    script_dir = Path(__file__).resolve().parent
    source_config = script_dir / DEFAULT_CONFIG_NAME
    gorcode_root = Path.home() / GORCODE_DIR_NAME
    target_config = gorcode_root / DEFAULT_CONFIG_NAME
    return source_config, gorcode_root, target_config


def ensure_directories(gorcode_root: Path) -> list[Path]:
    """Ensure required ~/.gorcode subdirectories exist."""
    created: list[Path] = []
    if not gorcode_root.exists():
        gorcode_root.mkdir(parents=True, exist_ok=True)
        created.append(gorcode_root)

    for subdir in REQUIRED_SUBDIRS:
        path = gorcode_root / subdir
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            created.append(path)
    return created


def copy_default_config(source_config: Path, target_config: Path, force: bool) -> bool:
    """Copy config template into ~/.gorcode/config.json."""
    if not source_config.exists():
        raise FileNotFoundError(f"Reference config not found: {source_config}")

    should_copy = force or not target_config.exists()
    if should_copy:
        shutil.copyfile(source_config, target_config)
    return should_copy


def main() -> int:
    """Entry point."""
    args = parse_args()
    source_config, gorcode_root, target_config = resolve_paths()

    created_dirs = ensure_directories(gorcode_root)
    copied = copy_default_config(source_config, target_config, force=args.force)

    for created_dir in created_dirs:
        print(f"Created directory: {created_dir}")

    if copied:
        print(f"Config written: {target_config}")
    else:
        print(f"Config already exists, skip copy: {target_config}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
