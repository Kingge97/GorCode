#!/usr/bin/env python3
"""Download ripgrep into ~/.gorcode/gorpath/path for GorCode runtime."""

import argparse
import platform
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

GORCODE_ROOT = Path.home() / ".gorcode"
RG_INSTALL_DIR = GORCODE_ROOT / "gorpath" / "path"
DOWNLOAD_TIMEOUT_SECS = 60
DEFAULT_RG_VERSION = "14.1.1"


@dataclass(frozen=True)
class AssetSpec:
    """Ripgrep release asset metadata."""

    triple: str
    archive_suffix: str
    binary_name: str


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Download ripgrep binary into ~/.gorcode/gorpath/path.",
    )
    parser.add_argument(
        "--version",
        default=DEFAULT_RG_VERSION,
        help=f"Ripgrep version tag (default: {DEFAULT_RG_VERSION})",
    )
    parser.add_argument(
        "--target-dir",
        type=Path,
        default=RG_INSTALL_DIR,
        help=f"Target installation directory (default: {RG_INSTALL_DIR})",
    )
    return parser.parse_args()


def detect_asset_spec() -> AssetSpec:
    """Detect current platform and return matching ripgrep asset spec."""
    system_name = platform.system().lower()
    machine = platform.machine().lower()

    if machine in {"x86_64", "amd64"}:
        arch = "x86_64"
    elif machine in {"aarch64", "arm64"}:
        arch = "aarch64"
    else:
        raise RuntimeError(f"Unsupported CPU architecture: {machine}")

    if system_name == "windows":
        return AssetSpec(
            triple=f"{arch}-pc-windows-msvc",
            archive_suffix=".zip",
            binary_name="rg.exe",
        )
    if system_name == "linux":
        linux_triples = {
            "x86_64": "x86_64-unknown-linux-musl",
            "aarch64": "aarch64-unknown-linux-musl",
        }
        return AssetSpec(
            triple=linux_triples[arch],
            archive_suffix=".tar.gz",
            binary_name="rg",
        )
    if system_name == "darwin":
        return AssetSpec(
            triple=f"{arch}-apple-darwin",
            archive_suffix=".tar.gz",
            binary_name="rg",
        )

    raise RuntimeError(f"Unsupported operating system: {system_name}")


def build_download_url(version: str, spec: AssetSpec) -> tuple[str, str]:
    """Build release URL and asset file name."""
    asset_name = f"ripgrep-{version}-{spec.triple}{spec.archive_suffix}"
    url = f"https://github.com/BurntSushi/ripgrep/releases/download/{version}/{asset_name}"
    return url, asset_name


def download_file(url: str, dest: Path) -> None:
    """Download a file from URL to destination path."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_SECS) as response, open(dest, "wb") as out:
        shutil.copyfileobj(response, out)


def extract_binary(archive_path: Path, spec: AssetSpec, install_path: Path) -> None:
    """Extract rg binary from archive into install path."""
    if spec.archive_suffix == ".zip":
        extract_from_zip(archive_path, spec.binary_name, install_path)
        return

    if spec.archive_suffix == ".tar.gz":
        extract_from_tar_gz(archive_path, spec.binary_name, install_path)
        return

    raise RuntimeError(f"Unsupported archive format: {spec.archive_suffix}")


def extract_from_zip(archive_path: Path, binary_name: str, install_path: Path) -> None:
    """Extract binary from zip archive."""
    install_path.unlink(missing_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        member_name = find_archive_member(archive.namelist(), binary_name)
        with archive.open(member_name) as src, open(install_path, "wb") as out:
            shutil.copyfileobj(src, out)


def extract_from_tar_gz(archive_path: Path, binary_name: str, install_path: Path) -> None:
    """Extract binary from tar.gz archive."""
    install_path.unlink(missing_ok=True)
    with tarfile.open(archive_path, "r:gz") as archive:
        member_name = find_archive_member([m.name for m in archive.getmembers()], binary_name)
        member = archive.getmember(member_name)
        source = archive.extractfile(member)
        if source is None:
            raise RuntimeError(f"Failed to read member from archive: {member_name}")
        with source, open(install_path, "wb") as out:
            shutil.copyfileobj(source, out)


def find_archive_member(names: list[str], binary_name: str) -> str:
    """Find archive member path for target binary."""
    suffix = f"/{binary_name.lower()}"
    for name in names:
        normalized = name.replace("\\", "/").rstrip("/")
        if normalized.lower().endswith(suffix):
            return name
    raise RuntimeError(f"Binary '{binary_name}' not found in downloaded archive.")


def main() -> int:
    """Entry point."""
    args = parse_args()
    target_dir = args.target_dir.expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    spec = detect_asset_spec()
    url, asset_name = build_download_url(args.version, spec)
    install_path = target_dir / spec.binary_name

    print(f"Target platform triple: {spec.triple}")
    print(f"Download URL: {url}")
    print(f"Install directory: {target_dir}")

    with tempfile.TemporaryDirectory(prefix="gorcode-rg-") as tmp:
        archive_path = Path(tmp) / asset_name
        download_file(url, archive_path)
        extract_binary(archive_path, spec, install_path)

    if spec.binary_name == "rg":
        install_path.chmod(0o755)

    print(f"Installed ripgrep binary: {install_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
