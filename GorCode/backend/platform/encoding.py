"""
Encoding Utilities
==================

Cross-platform encoding handling utilities.
"""

import locale
import sys
from pathlib import Path
from typing import Optional, Tuple

from .detector import PlatformDetector


class EncodingUtils:
    """
    Cross-platform encoding handling utilities.
    
    Ensures consistent UTF-8 handling across platforms.
    """
    
    # Default encoding
    DEFAULT_ENCODING = "utf-8"
    
    # Fallback encodings for different platforms
    WINDOWS_FALLBACKS = ["utf-8", "cp1252", "cp936", "latin-1"]
    UNIX_FALLBACKS = ["utf-8", "latin-1"]
    
    def __init__(self):
        """Initialize encoding utilities."""
        self._detector = PlatformDetector()
        self._preferred_encoding: Optional[str] = None
    
    @property
    def preferred_encoding(self) -> str:
        """
        Get the preferred encoding for the current platform.
        
        Returns:
            Encoding name string
        """
        if self._preferred_encoding is not None:
            return self._preferred_encoding
        
        # Try to detect system encoding
        try:
            encoding = locale.getpreferredencoding(False)
            if encoding:
                self._preferred_encoding = encoding
                return encoding
        except Exception:
            pass
        
        # Fallback to UTF-8
        self._preferred_encoding = self.DEFAULT_ENCODING
        return self._preferred_encoding
    
    @property
    def filesystem_encoding(self) -> str:
        """
        Get the filesystem encoding.
        
        Returns:
            Filesystem encoding name
        """
        return sys.getfilesystemencoding() or self.DEFAULT_ENCODING
    
    @property
    def stdout_encoding(self) -> str:
        """
        Get the stdout encoding.
        
        Returns:
            Stdout encoding name
        """
        return sys.stdout.encoding or self.DEFAULT_ENCODING
    
    @property
    def stdin_encoding(self) -> str:
        """
        Get the stdin encoding.
        
        Returns:
            Stdin encoding name
        """
        return sys.stdin.encoding or self.DEFAULT_ENCODING
    
    @property
    def stderr_encoding(self) -> str:
        """
        Get the stderr encoding.
        
        Returns:
            Stderr encoding name
        """
        return sys.stderr.encoding or self.DEFAULT_ENCODING
    
    def decode(
        self,
        data: bytes,
        encoding: Optional[str] = None,
        errors: str = "strict"
    ) -> str:
        """
        Decode bytes to string with fallback support.
        
        Args:
            data: Bytes to decode
            encoding: Target encoding (None for auto-detect)
            errors: Error handling mode
            
        Returns:
            Decoded string
        """
        if encoding:
            return data.decode(encoding, errors=errors)
        
        # Try preferred encoding first
        try:
            return data.decode(self.preferred_encoding, errors=errors)
        except UnicodeDecodeError:
            pass
        
        # Try fallback encodings
        fallbacks = (self.WINDOWS_FALLBACKS if self._detector.is_windows 
                    else self.UNIX_FALLBACKS)
        
        for enc in fallbacks:
            try:
                return data.decode(enc, errors=errors)
            except UnicodeDecodeError:
                continue
        
        # Last resort: decode with replacement
        return data.decode(self.DEFAULT_ENCODING, errors="replace")
    
    def encode(
        self,
        text: str,
        encoding: Optional[str] = None,
        errors: str = "strict"
    ) -> bytes:
        """
        Encode string to bytes.
        
        Args:
            text: String to encode
            encoding: Target encoding (None for UTF-8)
            errors: Error handling mode
            
        Returns:
            Encoded bytes
        """
        enc = encoding or self.DEFAULT_ENCODING
        return text.encode(enc, errors=errors)
    
    def safe_decode(self, data: bytes) -> Tuple[str, str]:
        """
        Safely decode bytes, returning the encoding used.
        
        Args:
            data: Bytes to decode
            
        Returns:
            Tuple of (decoded string, encoding used)
        """
        # Try preferred encoding first
        try:
            return data.decode(self.preferred_encoding), self.preferred_encoding
        except UnicodeDecodeError:
            pass
        
        # Try fallback encodings
        fallbacks = (self.WINDOWS_FALLBACKS if self._detector.is_windows 
                    else self.UNIX_FALLBACKS)
        
        for enc in fallbacks:
            try:
                return data.decode(enc), enc
            except UnicodeDecodeError:
                continue
        
        # Last resort
        return data.decode(self.DEFAULT_ENCODING, errors="replace"), self.DEFAULT_ENCODING
    
    def is_valid_encoding(self, encoding: str) -> bool:
        """
        Check if an encoding name is valid.
        
        Args:
            encoding: Encoding name to check
            
        Returns:
            True if encoding is valid
        """
        try:
            "".encode(encoding)
            return True
        except (LookupError, TypeError):
            return False
    
    def normalize_encoding(self, encoding: str) -> str:
        """
        Normalize an encoding name.
        
        Args:
            encoding: Encoding name to normalize
            
        Returns:
            Normalized encoding name
        """
        # Common aliases
        aliases = {
            "utf8": "utf-8",
            "utf-8-bom": "utf-8-sig",
            "utf8-bom": "utf-8-sig",
            "gb2312": "gbk",
            "chinese": "gbk",
            "gb18030": "gb18030",
        }
        
        normalized = encoding.lower().replace("_", "-")
        return aliases.get(normalized, normalized)
    
    def setup_utf8_default(self) -> None:
        """
        Set up UTF-8 as default encoding for I/O operations.
        
        This is particularly important on Windows where the default
        might be a legacy encoding.
        """
        if self._detector.is_windows:
            # On Windows, reconfigure stdout/stdin/stderr for UTF-8
            import io
            
            if hasattr(sys.stdout, 'buffer'):
                sys.stdout = io.TextIOWrapper(
                    sys.stdout.buffer, 
                    encoding=self.DEFAULT_ENCODING,
                    errors='replace'
                )
            
            if hasattr(sys.stdin, 'buffer'):
                sys.stdin = io.TextIOWrapper(
                    sys.stdin.buffer,
                    encoding=self.DEFAULT_ENCODING,
                    errors='replace'
                )
            
            if hasattr(sys.stderr, 'buffer'):
                sys.stderr = io.TextIOWrapper(
                    sys.stderr.buffer,
                    encoding=self.DEFAULT_ENCODING,
                    errors='replace'
                )


# Convenience instance
_encoding_utils = EncodingUtils()

def decode_bytes(data: bytes, encoding: Optional[str] = None) -> str:
    """Decode bytes to string."""
    return _encoding_utils.decode(data, encoding)

def encode_string(text: str, encoding: Optional[str] = None) -> bytes:
    """Encode string to bytes."""
    return _encoding_utils.encode(text, encoding)

def get_preferred_encoding() -> str:
    """Get the preferred encoding."""
    return _encoding_utils.preferred_encoding

def setup_utf8() -> None:
    """Set up UTF-8 as default encoding."""
    _encoding_utils.setup_utf8_default()


def read_text_with_fallback(path: Path, encoding: Optional[str] = None) -> Optional[str]:
    """
    Read file text with encoding fallback support.

    Args:
        path: File path to read
        encoding: Preferred encoding to try first

    Returns:
        File content as string, or None on read failure
    """
    try:
        data = path.read_bytes()
    except Exception:
        return None

    if encoding:
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            pass

    try:
        return _encoding_utils.decode(data)
    except Exception:
        return None
