"""
Platform Module
===============

Cross-platform support for GorCode.

Provides platform detection, path handling, encoding, shell commands,
and permission utilities.
"""

from .detector import (
    PlatformType,
    ShellType,
    PlatformInfo,
    PlatformDetector,
    get_platform_info,
)
from .paths import (
    PathUtils,
    normalize_path,
    expand_path,
    safe_filename,
    get_config_dir,
    get_data_dir,
)
from .encoding import (
    EncodingUtils,
    decode_bytes,
    encode_string,
    get_preferred_encoding,
    setup_utf8,
)
from .shell import (
    ShellUtils,
    parse_command,
    quote_arg,
    execute_command,
    find_command,
)
from .permissions import (
    PermissionUtils,
    is_readable,
    is_writable,
    is_executable,
    make_executable,
    is_admin,
)

__all__ = [
    # Platform detection
    "PlatformType",
    "ShellType",
    "PlatformInfo",
    "PlatformDetector",
    "get_platform_info",
    # Path utilities
    "PathUtils",
    "normalize_path",
    "expand_path",
    "safe_filename",
    "get_config_dir",
    "get_data_dir",
    # Encoding utilities
    "EncodingUtils",
    "decode_bytes",
    "encode_string",
    "get_preferred_encoding",
    "setup_utf8",
    # Shell utilities
    "ShellUtils",
    "parse_command",
    "quote_arg",
    "execute_command",
    "find_command",
    # Permission utilities
    "PermissionUtils",
    "is_readable",
    "is_writable",
    "is_executable",
    "make_executable",
    "is_admin",
]
