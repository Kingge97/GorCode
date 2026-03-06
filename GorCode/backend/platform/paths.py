"""
Path Utilities
==============

Cross-platform path handling utilities.
"""

import os
import re
from pathlib import Path
from typing import List, Optional, Union

from .detector import PlatformDetector, PlatformType


class PathUtils:
    """
    Cross-platform path handling utilities.
    
    Handles the differences between Windows and Unix path conventions.
    """
    
    # Windows reserved names
    WINDOWS_RESERVED = {
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    }
    
    # Invalid characters for filenames
    WINDOWS_INVALID_CHARS = r'[<>:"/\\|?*\x00-\x1f]'
    UNIX_INVALID_CHARS = r'[\x00/]'
    
    def __init__(self):
        """Initialize path utilities."""
        self._detector = PlatformDetector()
    
    def normalize(self, path: Union[str, Path]) -> str:
        """
        Normalize a path for the current platform.
        
        Args:
            path: Path to normalize
            
        Returns:
            Normalized path string
        """
        path_str = str(path)
        
        # Convert to proper separators
        if self._detector.is_windows:
            # Windows: use backslashes
            path_str = path_str.replace("/", "\\")
        else:
            # Unix: use forward slashes
            path_str = path_str.replace("\\", "/")
        
        # Normalize the path
        return os.path.normpath(path_str)
    
    def to_posix(self, path: Union[str, Path]) -> str:
        """
        Convert path to POSIX format (forward slashes).
        
        Args:
            path: Path to convert
            
        Returns:
            POSIX-style path string
        """
        return str(path).replace("\\", "/")
    
    def to_windows(self, path: Union[str, Path]) -> str:
        """
        Convert path to Windows format (backslashes).
        
        Args:
            path: Path to convert
            
        Returns:
            Windows-style path string
        """
        return str(path).replace("/", "\\")
    
    def is_absolute(self, path: Union[str, Path]) -> bool:
        """
        Check if a path is absolute.
        
        Handles both platform-native and cross-platform paths.
        
        Args:
            path: Path to check
            
        Returns:
            True if path is absolute
        """
        path_str = str(path)
        
        # Check for Windows drive letter (C:\ or C:/)
        if re.match(r'^[a-zA-Z]:[/\\]', path_str):
            return True
        
        # Check for UNC path (\\server\share)
        if path_str.startswith("\\\\"):
            return True
        
        # Check for POSIX absolute path
        if path_str.startswith("/"):
            return True
        
        return False
    
    def make_absolute(
        self,
        path: Union[str, Path],
        base: Optional[Union[str, Path]] = None
    ) -> str:
        """
        Make a path absolute.
        
        Args:
            path: Path to make absolute
            base: Base directory (defaults to current working directory)
            
        Returns:
            Absolute path string
        """
        path_str = str(path)
        
        if self.is_absolute(path_str):
            return self.normalize(path_str)
        
        if base is None:
            base = os.getcwd()
        
        return self.normalize(os.path.join(str(base), path_str))
    
    def get_relative_path(
        self,
        path: Union[str, Path],
        base: Optional[Union[str, Path]] = None
    ) -> str:
        """
        Get the relative path from a base directory.
        
        Args:
            path: Target path
            base: Base directory (defaults to current working directory)
            
        Returns:
            Relative path string
        """
        if base is None:
            base = os.getcwd()
        
        abs_path = self.make_absolute(path, base)
        abs_base = self.make_absolute(base, base)
        
        try:
            return os.path.relpath(abs_path, abs_base)
        except ValueError:
            # Different drives on Windows
            return abs_path
    
    def safe_filename(self, name: str, replacement: str = "_") -> str:
        """
        Convert a string to a safe filename.
        
        Args:
            name: Original name
            replacement: Character to use for replacement
            
        Returns:
            Safe filename string
        """
        if self._detector.is_windows:
            # Windows-specific handling
            # Replace invalid characters
            safe = re.sub(self.WINDOWS_INVALID_CHARS, replacement, name)
            
            # Check for reserved names
            base = safe.upper().split(".")[0]
            if base in self.WINDOWS_RESERVED:
                safe = f"_{safe}"
            
            # Remove trailing spaces and dots
            safe = safe.rstrip(" .")
            
            # Ensure not empty
            if not safe:
                safe = "unnamed"
            
            return safe
        else:
            # Unix-specific handling
            safe = re.sub(self.UNIX_INVALID_CHARS, replacement, name)
            
            # Don't start with a dash (would be interpreted as option)
            if safe.startswith("-"):
                safe = f"_{safe}"
            
            return safe
    
    def expand_user(self, path: Union[str, Path]) -> str:
        """
        Expand user home directory (~) in a path.
        
        Args:
            path: Path to expand
            
        Returns:
            Expanded path string
        """
        path_str = str(path)
        
        if path_str.startswith("~"):
            home = self._detector.detect().home_dir
            return os.path.join(home, path_str[1:].lstrip("/\\"))
        
        return path_str
    
    def expand_env(self, path: Union[str, Path]) -> str:
        """
        Expand environment variables in a path.
        
        Args:
            path: Path to expand
            
        Returns:
            Expanded path string
        """
        path_str = str(path)
        
        if self._detector.is_windows:
            # Windows: expand %VAR% syntax
            def replace_env(match):
                var = match.group(1)
                return os.environ.get(var, match.group(0))
            
            path_str = re.sub(r'%([^%]+)%', replace_env, path_str)
        
        # Expand $VAR and ${VAR} syntax (works on all platforms)
        path_str = os.path.expandvars(path_str)
        
        return path_str
    
    def expand_all(self, path: Union[str, Path]) -> str:
        """
        Expand both user home directory and environment variables.
        
        Args:
            path: Path to expand
            
        Returns:
            Fully expanded path string
        """
        path_str = self.expand_user(path)
        path_str = self.expand_env(path_str)
        return self.normalize(path_str)
    
    def split_path(self, path: Union[str, Path]) -> List[str]:
        """
        Split a path into its components.
        
        Args:
            path: Path to split
            
        Returns:
            List of path components
        """
        path_str = self.normalize(path)
        parts = []
        
        while True:
            path_str, part = os.path.split(path_str)
            if not part:
                if path_str:
                    parts.insert(0, path_str)
                break
            parts.insert(0, part)
        
        return parts
    
    def ensure_dir(self, path: Union[str, Path]) -> bool:
        """
        Ensure a directory exists, creating it if necessary.
        
        Args:
            path: Directory path
            
        Returns:
            True if directory exists or was created
        """
        path_str = self.expand_all(path)
        
        try:
            Path(path_str).mkdir(parents=True, exist_ok=True)
            return True
        except Exception:
            return False
    
    def get_config_dir(self, app_name: str = "gorcode") -> str:
        """
        Get the configuration directory for the application.
        
        Args:
            app_name: Application name
            
        Returns:
            Configuration directory path
        """
        info = self._detector.detect()
        
        if self._detector.is_windows:
            # Windows: %APPDATA%\gorcode
            base = os.environ.get("APPDATA", info.home_dir)
        elif self._detector.is_macos:
            # macOS: ~/Library/Application Support/gorcode
            base = os.path.join(info.home_dir, "Library", "Application Support")
        else:
            # Linux: ~/.config/gorcode (XDG Base Directory Specification)
            base = os.environ.get("XDG_CONFIG_HOME", 
                                  os.path.join(info.home_dir, ".config"))
        
        return os.path.join(base, app_name)
    
    def get_data_dir(self, app_name: str = "gorcode") -> str:
        """
        Get the data directory for the application.
        
        Args:
            app_name: Application name
            
        Returns:
            Data directory path
        """
        info = self._detector.detect()
        
        if self._detector.is_windows:
            # Windows: %LOCALAPPDATA%\gorcode
            base = os.environ.get("LOCALAPPDATA", 
                                  os.path.join(info.home_dir, "AppData", "Local"))
        elif self._detector.is_macos:
            # macOS: ~/Library/Application Support/gorcode
            base = os.path.join(info.home_dir, "Library", "Application Support")
        else:
            # Linux: ~/.local/share/gorcode (XDG Base Directory Specification)
            base = os.environ.get("XDG_DATA_HOME",
                                  os.path.join(info.home_dir, ".local", "share"))
        
        return os.path.join(base, app_name)


# Convenience instance
_path_utils = PathUtils()

def normalize_path(path: Union[str, Path]) -> str:
    """Normalize a path for the current platform."""
    return _path_utils.normalize(path)

def expand_path(path: Union[str, Path]) -> str:
    """Expand user home directory and environment variables in a path."""
    return _path_utils.expand_all(path)

def safe_filename(name: str) -> str:
    """Convert a string to a safe filename."""
    return _path_utils.safe_filename(name)

def get_config_dir(app_name: str = "gorcode") -> str:
    """Get the configuration directory for the application."""
    return _path_utils.get_config_dir(app_name)

def get_data_dir(app_name: str = "gorcode") -> str:
    """Get the data directory for the application."""
    return _path_utils.get_data_dir(app_name)
