"""
File Tool Settings
==================

Configuration container for file tool behaviors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .file_constants import (
    DEFAULT_IMAGE_MAX_BYTES,
    DEFAULT_PDF_MAX_PAGES,
    DEFAULT_READ_MAX_BYTES,
    DEFAULT_READ_MAX_TOKENS,
    MAX_FILE_BYTES,
)


@dataclass(frozen=True)
class FileToolSettings:
    max_file_bytes: int = MAX_FILE_BYTES
    read_max_bytes: int = DEFAULT_READ_MAX_BYTES
    read_max_tokens: int = DEFAULT_READ_MAX_TOKENS
    image_max_bytes: int = DEFAULT_IMAGE_MAX_BYTES
    pdf_max_pages: int = DEFAULT_PDF_MAX_PAGES
    enable_images: bool = True
    enable_pdf: bool = True
    enable_notebook: bool = True
    enforce_read_before_write: bool = True
    enforce_mtime_check: bool = True
    preserve_line_endings: bool = True
    edit_quote_normalization: bool = True
    edit_smart_find: bool = True
    edit_deserialize: bool = True
    edit_trim_trailing_whitespace: bool = False

    @classmethod
    def from_config(cls, config: Any) -> "FileToolSettings":
        return cls(
            max_file_bytes=_read_attr(config, "file_max_bytes", MAX_FILE_BYTES),
            read_max_bytes=_read_attr(config, "file_read_max_bytes", DEFAULT_READ_MAX_BYTES),
            read_max_tokens=_read_attr(config, "file_read_max_tokens", DEFAULT_READ_MAX_TOKENS),
            image_max_bytes=_read_attr(config, "file_image_max_bytes", DEFAULT_IMAGE_MAX_BYTES),
            pdf_max_pages=_read_attr(config, "file_pdf_max_pages", DEFAULT_PDF_MAX_PAGES),
            enable_images=_read_attr(config, "file_enable_images", True),
            enable_pdf=_read_attr(config, "file_enable_pdf", True),
            enable_notebook=_read_attr(config, "file_enable_notebook", True),
            enforce_read_before_write=_read_attr(config, "file_enforce_read_before_write", True),
            enforce_mtime_check=_read_attr(config, "file_enforce_mtime_check", True),
            preserve_line_endings=_read_attr(config, "file_preserve_line_endings", True),
            edit_quote_normalization=_read_attr(config, "file_edit_quote_normalization", True),
            edit_smart_find=_read_attr(config, "file_edit_smart_find", True),
            edit_deserialize=_read_attr(config, "file_edit_deserialize", True),
            edit_trim_trailing_whitespace=_read_attr(
                config,
                "file_edit_trim_trailing_whitespace",
                False,
            ),
        )


def _read_attr(config: Any, name: str, default: Any) -> Any:
    if config is None:
        return default
    settings = getattr(config, "file_tool_settings", None)
    if isinstance(settings, dict) and name in settings:
        return settings[name]
    return getattr(config, name, default)
