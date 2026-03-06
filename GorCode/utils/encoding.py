"""
Encoding Utilities
==================

Utility functions for encoding handling.
"""

import sys
from typing import Optional


def get_default_encoding() -> str:
    """
    Get the default encoding for file operations.
    
    Returns:
        Default encoding string (e.g., 'utf-8')
    """
    # Try to get from system
    try:
        return sys.getdefaultencoding()
    except Exception:
        return "utf-8"


def get_preferred_encoding() -> str:
    """
    Get the preferred encoding for the current system.
    
    This considers platform-specific preferences.
    
    Returns:
        Preferred encoding string
    """
    # Windows often uses different encodings
    if sys.platform == "win32":
        try:
            import locale
            return locale.getpreferredencoding(False)
        except Exception:
            return "utf-8"
    
    return "utf-8"


def safe_decode(data: bytes, encoding: str = None) -> str:
    """
    Safely decode bytes to string.
    
    Args:
        data: Bytes to decode
        encoding: Target encoding, defaults to utf-8
        
    Returns:
        Decoded string
    """
    encoding = encoding or "utf-8"
    
    try:
        return data.decode(encoding)
    except UnicodeDecodeError:
        # Try fallback encodings
        for fallback in ["utf-8", "gbk", "latin-1"]:
            try:
                return data.decode(fallback)
            except UnicodeDecodeError:
                continue
        
        # Last resort: replace errors
        return data.decode(encoding, errors="replace")


def safe_encode(text: str, encoding: str = None) -> bytes:
    """
    Safely encode string to bytes.
    
    Args:
        text: String to encode
        encoding: Target encoding, defaults to utf-8
        
    Returns:
        Encoded bytes
    """
    encoding = encoding or "utf-8"
    
    try:
        return text.encode(encoding)
    except UnicodeEncodeError:
        # Replace problematic characters
        return text.encode(encoding, errors="replace")
