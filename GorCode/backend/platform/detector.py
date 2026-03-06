"""
Platform Detector
=================

Detects and provides information about the current platform.
"""

import os
import sys
import platform
from enum import Enum
from dataclasses import dataclass
from typing import Optional


class PlatformType(Enum):
    """Supported platform types."""
    WINDOWS = "windows"
    LINUX = "linux"
    MACOS = "macos"
    UNKNOWN = "unknown"


class ShellType(Enum):
    """Supported shell types."""
    POWERSHELL = "powershell"
    CMD = "cmd"
    BASH = "bash"
    ZSH = "zsh"
    FISH = "fish"
    UNKNOWN = "unknown"


@dataclass
class PlatformInfo:
    """Information about the current platform."""
    
    platform_type: PlatformType
    shell_type: ShellType
    os_name: str
    os_version: str
    python_version: str
    is_64bit: bool
    home_dir: str
    temp_dir: str
    path_separator: str
    line_ending: str
    case_sensitive: bool


class PlatformDetector:
    """
    Detects and provides platform information.
    
    Usage:
        detector = PlatformDetector()
        info = detector.detect()
        print(f"Platform: {info.platform_type}")
    """
    
    _instance: Optional['PlatformDetector'] = None
    _info: Optional[PlatformInfo] = None
    
    def __new__(cls) -> 'PlatformDetector':
        """Singleton pattern for cached detection."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def detect(self) -> PlatformInfo:
        """
        Detect current platform information.
        
        Returns:
            PlatformInfo object with detected information
        """
        if self._info is not None:
            return self._info
        
        platform_type = self._detect_platform_type()
        shell_type = self._detect_shell_type()
        
        self._info = PlatformInfo(
            platform_type=platform_type,
            shell_type=shell_type,
            os_name=platform.system(),
            os_version=platform.version(),
            python_version=platform.python_version(),
            is_64bit=sys.maxsize > 2**32,
            home_dir=self._get_home_dir(),
            temp_dir=self._get_temp_dir(),
            path_separator=os.sep,
            line_ending="\r\n" if platform_type == PlatformType.WINDOWS else "\n",
            case_sensitive=platform_type != PlatformType.WINDOWS,
        )
        
        return self._info
    
    def _detect_platform_type(self) -> PlatformType:
        """Detect the platform type."""
        system = platform.system().lower()
        
        if system == "windows":
            return PlatformType.WINDOWS
        elif system == "linux":
            return PlatformType.LINUX
        elif system == "darwin":
            return PlatformType.MACOS
        else:
            return PlatformType.UNKNOWN
    
    def _detect_shell_type(self) -> ShellType:
        """Detect the shell type."""
        # Check environment variables
        shell = os.environ.get("SHELL", "")
        ps_module = os.environ.get("PSModulePath", "")
        
        # Windows checks
        if platform.system().lower() == "windows":
            if ps_module or "powershell" in shell.lower():
                return ShellType.POWERSHELL
            return ShellType.CMD
        
        # Unix checks
        if "bash" in shell.lower():
            return ShellType.BASH
        elif "zsh" in shell.lower():
            return ShellType.ZSH
        elif "fish" in shell.lower():
            return ShellType.FISH
        
        # Default for Unix
        return ShellType.BASH
    
    def _get_home_dir(self) -> str:
        """Get the user's home directory."""
        # Try multiple methods for cross-platform support
        if platform.system().lower() == "windows":
            # Windows: check USERPROFILE first
            home = os.environ.get("USERPROFILE")
            if home:
                return home
            # Fallback to HOMEDRIVE + HOMEPATH
            drive = os.environ.get("HOMEDRIVE", "C:")
            path = os.environ.get("HOMEPATH", "\\Users\\Default")
            return os.path.join(drive, path)
        else:
            # Unix: check HOME
            return os.environ.get("HOME", "/tmp")
    
    def _get_temp_dir(self) -> str:
        """Get the system temp directory."""
        # Use Python's tempdir which handles cross-platform
        import tempfile
        return tempfile.gettempdir()
    
    @property
    def is_windows(self) -> bool:
        """Check if running on Windows."""
        return self.detect().platform_type == PlatformType.WINDOWS
    
    @property
    def is_linux(self) -> bool:
        """Check if running on Linux."""
        return self.detect().platform_type == PlatformType.LINUX
    
    @property
    def is_macos(self) -> bool:
        """Check if running on macOS."""
        return self.detect().platform_type == PlatformType.MACOS
    
    @property
    def is_unix(self) -> bool:
        """Check if running on a Unix-like system."""
        info = self.detect()
        return info.platform_type in (PlatformType.LINUX, PlatformType.MACOS)


# Convenience function
def get_platform_info() -> PlatformInfo:
    """
    Get current platform information.
    
    Returns:
        PlatformInfo object
    """
    return PlatformDetector().detect()