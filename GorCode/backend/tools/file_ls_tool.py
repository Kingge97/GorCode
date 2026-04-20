"""
LS Tool
=======

List directory contents.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from .core_tool_support.base import BaseTool, ToolResult
from .core_tool_support.path_validation import resolve_and_validate_path
from .core_tool_support.tool_utils import build_parameters_schema, tool_error_result


class LSTool(BaseTool):
    """Tool for listing directory contents."""

    name = "ls"
    description = "List contents of a directory. Returns file and directory names."
    category = "file"
    needs_encoding = False

    def execute(
        self,
        path: str = ".",
        show_hidden: bool = False,
        recursive: bool = False,
    ) -> ToolResult:
        """
        List directory contents.

        Args:
            path: Directory path to list
            show_hidden: Show hidden files
            recursive: List recursively

        Returns:
            ToolResult with directory listing
        """
        try:
            dir_path, validation_error = resolve_and_validate_path(path, "dir")
            if validation_error:
                return validation_error

            entries = _list_entries(dir_path, show_hidden, recursive)
            result = "\n".join(entries) if entries else "(empty directory)"

            return ToolResult(
                success=True,
                output=result,
                metadata={
                    "path": str(dir_path),
                    "total_items": len(entries),
                },
            )

        except Exception as exc:
            return tool_error_result(exc)

    def get_parameters(self) -> Dict[str, Any]:
        """Get tool parameter schema."""
        return build_parameters_schema(
            properties={
                "path": {
                    "type": "string",
                    "description": "Directory path to list",
                    "default": ".",
                },
                "show_hidden": {
                    "type": "boolean",
                    "description": "Show hidden files",
                    "default": False,
                },
                "recursive": {
                    "type": "boolean",
                    "description": "List recursively",
                    "default": False,
                },
            },
            required=[],
        )


def _list_entries(dir_path: Path, show_hidden: bool, recursive: bool) -> list[str]:
    entries = []
    if recursive:
        for item in dir_path.rglob("*"):
            if not show_hidden and item.name.startswith("."):
                continue
            rel_path = item.relative_to(dir_path)
            prefix = "[D] " if item.is_dir() else "[F] "
            entries.append(f"{prefix}{rel_path}")
        return entries

    for item in sorted(dir_path.iterdir()):
        if not show_hidden and item.name.startswith("."):
            continue
        prefix = "[D] " if item.is_dir() else "[F] "
        entries.append(f"{prefix}{item.name}")
    return entries
