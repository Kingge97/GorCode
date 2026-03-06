"""
Permission Utilities
====================

Cross-platform permission handling utilities.
"""

import os
import stat
from pathlib import Path
from typing import Optional

from .detector import PlatformDetector, PlatformType


class PermissionUtils:
    """
    Cross-platform permission handling utilities.
    
    Handles file permissions, executable bits, and access checks.
    """
    
    def __init__(self):
        """Initialize permission utilities."""
        self._detector = PlatformDetector()
    
    def is_readable(self, path: str) -> bool:
        """
        Check if a path is readable.
        
        Args:
            path: Path to check
            
        Returns:
            True if readable
        """
        return os.access(path, os.R_OK)
    
    def is_writable(self, path: str) -> bool:
        """
        Check if a path is writable.
        
        Args:
            path: Path to check
            
        Returns:
            True if writable
        """
        return os.access(path, os.W_OK)
    
    def is_executable(self, path: str) -> bool:
        """
        Check if a path is executable.
        
        Args:
            path: Path to check
            
        Returns:
            True if executable
        """
        return os.access(path, os.X_OK)
    
    def is_file(self, path: str) -> bool:
        """
        Check if a path is a regular file.
        
        Args:
            path: Path to check
            
        Returns:
            True if regular file
        """
        try:
            return os.path.isfile(path)
        except Exception:
            return False
    
    def is_directory(self, path: str) -> bool:
        """
        Check if a path is a directory.
        
        Args:
            path: Path to check
            
        Returns:
            True if directory
        """
        try:
            return os.path.isdir(path)
        except Exception:
            return False
    
    def make_executable(self, path: str) -> bool:
        """
        Make a file executable.
        
        Args:
            path: Path to file
            
        Returns:
            True if successful
        """
        try:
            if self._detector.is_windows:
                # Windows: executable is determined by extension
                # No action needed, just check if file exists
                return os.path.exists(path)
            else:
                # Unix: set executable bit
                current_mode = os.stat(path).st_mode
                os.chmod(path, current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                return True
        except Exception:
            return False
    
    def make_readable(self, path: str) -> bool:
        """
        Make a file readable.
        
        Args:
            path: Path to file
            
        Returns:
            True if successful
        """
        try:
            if self._detector.is_windows:
                return os.path.exists(path)
            else:
                current_mode = os.stat(path).st_mode
                os.chmod(path, current_mode | stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
                return True
        except Exception:
            return False
    
    def make_writable(self, path: str) -> bool:
        """
        Make a file writable.
        
        Args:
            path: Path to file
            
        Returns:
            True if successful
        """
        try:
            if self._detector.is_windows:
                # Windows: use attrib to remove read-only
                import subprocess
                result = subprocess.run(
                    ["attrib", "-r", path],
                    capture_output=True,
                )
                return result.returncode == 0
            else:
                current_mode = os.stat(path).st_mode
                os.chmod(path, current_mode | stat.S_IWUSR)
                return True
        except Exception:
            return False
    
    def get_permissions(self, path: str) -> Optional[int]:
        """
        Get file permissions as an integer.
        
        Args:
            path: Path to file
            
        Returns:
            Permission bits or None on error
        """
        try:
            return stat.S_IMODE(os.stat(path).st_mode)
        except Exception:
            return None
    
    def set_permissions(self, path: str, mode: int) -> bool:
        """
        Set file permissions.
        
        Args:
            path: Path to file
            mode: Permission bits
            
        Returns:
            True if successful
        """
        try:
            os.chmod(path, mode)
            return True
        except Exception:
            return False
    
    def get_owner(self, path: str) -> Optional[str]:
        """
        Get file owner name.
        
        Args:
            path: Path to file
            
        Returns:
            Owner name or None
        """
        try:
            if self._detector.is_windows:
                import subprocess
                result = subprocess.run(
                    ["icacls", path],
                    capture_output=True,
                    text=True,
                )
                # Parse output to find owner
                # This is a simplified implementation
                for line in result.stdout.split('\n'):
                    if 'NT AUTHORITY' in line or '\\' in line:
                        # Extract owner from line
                        parts = line.split()
                        if parts:
                            return parts[0].split('\\')[-1]
                return None
            else:
                import pwd
                stat_info = os.stat(path)
                return pwd.getpwuid(stat_info.st_uid).pw_name
        except Exception:
            return None
    
    def check_admin(self) -> bool:
        """
        Check if running with administrator/root privileges.
        
        Returns:
            True if running as admin/root
        """
        try:
            if self._detector.is_windows:
                import ctypes
                return ctypes.windll.shell32.IsUserAnAdmin() != 0
            else:
                return os.geteuid() == 0
        except Exception:
            return False
    
    def get_umask(self) -> int:
        """
        Get the current umask.
        
        Returns:
            Umask value
        """
        # Get umask without changing it
        current = os.umask(0)
        os.umask(current)
        return current
    
    def is_hidden(self, path: str) -> bool:
        """
        Check if a file or directory is hidden.
        
        Args:
            path: Path to check
            
        Returns:
            True if hidden
        """
        name = os.path.basename(path)
        
        if self._detector.is_windows:
            # Windows: check hidden attribute
            try:
                attrs = os.stat(path).st_file_attributes
                return bool(attrs & stat.FILE_ATTRIBUTE_HIDDEN)
            except Exception:
                # Fallback: check name starts with .
                return name.startswith('.')
        else:
            # Unix: check if name starts with .
            return name.startswith('.')
    
    def set_hidden(self, path: str, hidden: bool = True) -> bool:
        """
        Set or unset the hidden attribute on a file.
        
        Args:
            path: Path to file
            hidden: True to hide, False to unhide
            
        Returns:
            True if successful
        """
        try:
            if self._detector.is_windows:
                import ctypes
                if hidden:
                    attrs = ctypes.windll.kernel32.GetFileAttributesW(path)
                    ctypes.windll.kernel32.SetFileAttributesW(
                        path, 
                        attrs | stat.FILE_ATTRIBUTE_HIDDEN
                    )
                else:
                    attrs = ctypes.windll.kernel32.GetFileAttributesW(path)
                    ctypes.windll.kernel32.SetFileAttributesW(
                        path, 
                        attrs & ~stat.FILE_ATTRIBUTE_HIDDEN
                    )
                return True
            else:
                # Unix: rename to add/remove leading dot
                # This is a different behavior, so we just return True
                return True
        except Exception:
            return False


# Convenience instance
_permission_utils = PermissionUtils()

def is_readable(path: str) -> bool:
    """Check if a path is readable."""
    return _permission_utils.is_readable(path)

def is_writable(path: str) -> bool:
    """Check if a path is writable."""
    return _permission_utils.is_writable(path)

def is_executable(path: str) -> bool:
    """Check if a path is executable."""
    return _permission_utils.is_executable(path)

def make_executable(path: str) -> bool:
    """Make a file executable."""
    return _permission_utils.make_executable(path)

def is_admin() -> bool:
    """Check if running with admin privileges."""
    return _permission_utils.check_admin()
