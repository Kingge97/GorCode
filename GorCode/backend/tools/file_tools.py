"""
File Tools
==========

File operation tools including read, write, edit.
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
import difflib

from .base import BaseTool, ToolResult, ToolDefinition


def _generate_diff(old_content: str, new_content: str, file_path: str = "file") -> str:
    """
    Generate unified diff between old and new content.
    
    Args:
        old_content: Original content
        new_content: New content
        file_path: File path for diff header
        
    Returns:
        Unified diff string
    """
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
        lineterm=""
    )
    
    return "".join(diff)


class ReadTool(BaseTool):
    """Tool for reading file contents."""
    
    name = "read"
    description = "Read the contents of a file. Returns the file content as a string."
    category = "file"
    needs_encoding = True
    
    def execute(
        self,
        file_path: str,
        offset: int = 0,
        limit: int = None,
        encoding: str = None,
    ) -> ToolResult:
        """
        Read file contents.
        
        Args:
            file_path: Path to the file to read
            offset: Line offset to start reading from (0-indexed)
            limit: Maximum number of lines to read
            encoding: File encoding
            
        Returns:
            ToolResult with file contents
        """
        try:
            path = Path(file_path)
            
            if not path.exists():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"File not found: {file_path}"
                )
            
            if not path.is_file():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Not a file: {file_path}"
                )
            
            # Read file with fallback encodings (use default_encoding if not specified)
            encoding = encoding or self.default_encoding
            content = self._read_with_fallback(path, encoding)
            
            if content is None:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Failed to read file with encoding: {encoding}"
                )
            
            # Split into lines and apply offset/limit
            lines = content.splitlines()
            
            if offset > 0:
                lines = lines[offset:]
            
            if limit is not None and limit > 0:
                lines = lines[:limit]
            
            result = "\n".join(lines)
            
            # Truncate if too long
            max_chars = 50000
            if len(result) > max_chars:
                result = result[:max_chars] + "\n... (truncated)"
            
            return ToolResult(
                success=True,
                output=result,
                metadata={
                    "file_path": str(path),
                    "total_lines": len(content.splitlines()),
                    "returned_lines": len(lines),
                }
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e)
            )
    
    def _read_with_fallback(self, path: Path, encoding: str) -> Optional[str]:
        """Read file with fallback encodings."""
        encodings = [encoding, "utf-8", "gbk", "latin-1"]
        
        for enc in encodings:
            try:
                return path.read_text(encoding=enc)
            except (UnicodeDecodeError, UnicodeError):
                continue
        
        return None
    
    def get_definition(self) -> ToolDefinition:
        """Get tool definition."""
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file to read"
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Line offset to start reading from (0-indexed)",
                        "default": 0
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of lines to read"
                    },
                    "encoding": {
                        "type": "string",
                        "description": "File encoding",
                        "default": "utf-8"
                    }
                },
                "required": ["file_path"]
            },
            category=self.category,
        )


class WriteTool(BaseTool):
    """Tool for writing content to a file."""
    
    name = "write"
    description = "Write content to a file. Creates the file if it doesn't exist, overwrites if it does."
    category = "file"
    needs_encoding = True
    requires_permission = True  # Requires permission for write operations
    
    def execute(
        self,
        file_path: str,
        content: str,
        encoding: str = None,
    ) -> ToolResult:
        """
        Write content to file.
        
        Args:
            file_path: Path to the file to write
            content: Content to write to the file
            encoding: File encoding
            
        Returns:
            ToolResult with write status and permission metadata
        """
        try:
            path = Path(file_path)
            
            # Generate diff for permission check
            old_content = ""
            file_exists = path.exists()
            if file_exists:
                # Read existing file for diff (use default_encoding if not specified)
                try:
                    enc = encoding or self.default_encoding
                    old_content = path.read_text(encoding=enc)
                except Exception:
                    old_content = "(unable to read existing file)"
            
            # Generate diff
            diff = _generate_diff(old_content, content, str(path))
            
            # Return metadata for permission check (actual write happens in executor)
            return ToolResult(
                success=True,
                output=f"Ready to write {len(content)} characters to {file_path}",
                metadata={
                    "file_path": str(path),
                    "chars_to_write": len(content),
                    "file_exists": file_exists,
                    "diff": diff,
                    "content": content,  # Store for actual execution after permission
                    "encoding": encoding or self.default_encoding,
                    "requires_permission": True,
                }
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e)
            )
    
    def execute_with_permission(
        self,
        file_path: str,
        content: str,
        encoding: str = None,
    ) -> ToolResult:
        """
        Actually execute the write after permission is granted.
        
        Args:
            file_path: Path to the file to write
            content: Content to write to the file
            encoding: File encoding
            
        Returns:
            ToolResult with write status
        """
        try:
            path = Path(file_path)
            
            # Create parent directories if needed
            path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write file (use default_encoding if not specified)
            enc = encoding or self.default_encoding
            path.write_text(content, encoding=enc)
            
            return ToolResult(
                success=True,
                output=f"Successfully wrote {len(content)} characters to {file_path}",
                metadata={
                    "file_path": str(path),
                    "chars_written": len(content),
                }
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e)
            )
    
    def get_definition(self) -> ToolDefinition:
        """Get tool definition."""
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file to write"
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write to the file"
                    },
                    "encoding": {
                        "type": "string",
                        "description": "File encoding",
                        "default": "utf-8"
                    }
                },
                "required": ["file_path", "content"]
            },
            category=self.category,
        )


class EditTool(BaseTool):
    """Tool for editing files by replacing text."""
    
    name = "edit"
    description = "Edit a file by replacing exact text matches. Use this for precise modifications."
    category = "file"
    needs_encoding = True
    requires_permission = True  # Requires permission for edit operations
    
    def execute(
        self,
        file_path: str,
        old_text: str,
        new_text: str,
        replace_all: bool = False,
        encoding: str = None,
    ) -> ToolResult:
        """
        Edit file by replacing text.
        
        Args:
            file_path: Path to the file to edit
            old_text: Text to find and replace
            new_text: Text to replace with
            replace_all: Replace all occurrences if True
            encoding: File encoding
            
        Returns:
            ToolResult with edit status and permission metadata
        """
        try:
            path = Path(file_path)
            
            if not path.exists():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"File not found: {file_path}"
                )
            
            # Read file (use default_encoding if not specified)
            enc = encoding or self.default_encoding
            content = self._read_with_fallback(path, enc)
            if content is None:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Failed to read file with encoding: {enc}"
                )
            
            # Check if old_text exists
            if old_text not in content:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Text not found in file: {old_text[:100]}..."
                )
            
            # Count occurrences
            count = content.count(old_text)
            
            # Generate new content
            if replace_all:
                new_content = content.replace(old_text, new_text)
                replaced = count
            else:
                new_content = content.replace(old_text, new_text, 1)
                replaced = 1
            
            # Generate diff
            diff = _generate_diff(content, new_content, str(path))
            
            # Return metadata for permission check
            return ToolResult(
                success=True,
                output=f"Ready to replace {replaced} occurrence(s) in {file_path}",
                metadata={
                    "file_path": str(path),
                    "occurrences_found": count,
                    "occurrences_to_replace": replaced,
                    "diff": diff,
                    "new_content": new_content,  # Store for actual execution after permission
                    "encoding": encoding or self.default_encoding,
                    "requires_permission": True,
                }
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e)
            )
    
    def execute_with_permission(
        self,
        file_path: str,
        new_content: str,
        encoding: str = None,
    ) -> ToolResult:
        """
        Actually execute the edit after permission is granted.
        
        Args:
            file_path: Path to the file to edit
            new_content: New content to write
            encoding: File encoding
            
        Returns:
            ToolResult with edit status
        """
        try:
            path = Path(file_path)
            
            # Write new content (use default_encoding if not specified)
            enc = encoding or self.default_encoding
            path.write_text(new_content, encoding=enc)
            
            return ToolResult(
                success=True,
                output=f"Successfully edited {file_path}",
                metadata={
                    "file_path": str(path),
                }
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e)
            )
    
    def _read_with_fallback(self, path: Path, encoding: str) -> Optional[str]:
        """Read file with fallback encodings."""
        encodings = [encoding, "utf-8", "gbk", "latin-1"]
        
        for enc in encodings:
            try:
                return path.read_text(encoding=enc)
            except (UnicodeDecodeError, UnicodeError):
                continue
        
        return None
    
    def get_definition(self) -> ToolDefinition:
        """Get tool definition."""
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file to edit"
                    },
                    "old_text": {
                        "type": "string",
                        "description": "Text to find and replace"
                    },
                    "new_text": {
                        "type": "string",
                        "description": "Text to replace with"
                    },
                    "replace_all": {
                        "type": "boolean",
                        "description": "Replace all occurrences if True",
                        "default": False
                    },
                    "encoding": {
                        "type": "string",
                        "description": "File encoding",
                        "default": "utf-8"
                    }
                },
                "required": ["file_path", "old_text", "new_text"]
            },
            category=self.category,
        )


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
            dir_path = Path(path)
            
            if not dir_path.exists():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Directory not found: {path}"
                )
            
            if not dir_path.is_dir():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Not a directory: {path}"
                )
            
            # List contents
            entries = []
            
            if recursive:
                for item in dir_path.rglob("*"):
                    if not show_hidden and item.name.startswith("."):
                        continue
                    rel_path = item.relative_to(dir_path)
                    prefix = "[D] " if item.is_dir() else "[F] "
                    entries.append(f"{prefix}{rel_path}")
            else:
                for item in sorted(dir_path.iterdir()):
                    if not show_hidden and item.name.startswith("."):
                        continue
                    prefix = "[D] " if item.is_dir() else "[F] "
                    entries.append(f"{prefix}{item.name}")
            
            result = "\n".join(entries) if entries else "(empty directory)"
            
            return ToolResult(
                success=True,
                output=result,
                metadata={
                    "path": str(dir_path),
                    "total_items": len(entries),
                }
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e)
            )
    
    def get_definition(self) -> ToolDefinition:
        """Get tool definition."""
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path to list",
                        "default": "."
                    },
                    "show_hidden": {
                        "type": "boolean",
                        "description": "Show hidden files",
                        "default": False
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "List recursively",
                        "default": False
                    }
                },
                "required": []
            },
            category=self.category,
        )
