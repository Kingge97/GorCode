"""
Search Tools
============

Search tools including glob, grep, and bash.
"""

import re
from pathlib import Path
from typing import Any, Dict, List

from .core_tool_support.base import BaseTool, ToolResult
from .core_tool_support.path_validation import resolve_and_validate_path
from .core_tool_support.tool_utils import (
    build_parameters_schema,
    resolve_encoding,
    tool_error_result,
    truncate_output,
)
from ..platform.encoding import read_text_with_fallback
from ..platform.shell import execute_command_with_timeout


class GlobTool(BaseTool):
    """Tool for finding files using glob patterns."""
    
    name = "glob"
    description = "Find files matching a glob pattern. Supports ** for recursive matching."
    category = "search"
    needs_encoding = False
    
    def execute(
        self,
        pattern: str,
        path: str = ".",
    ) -> ToolResult:
        """
        Find files matching glob pattern.
        
        Args:
            pattern: Glob pattern (e.g., "**/*.py")
            path: Base directory to search from
            
        Returns:
            ToolResult with matching file paths
        """
        try:
            base_path, validation_error = resolve_and_validate_path(path, "dir")
            if validation_error:
                return validation_error
            
            # Use rglob for recursive patterns
            if "**" in pattern:
                matches = list(base_path.glob(pattern))
            else:
                matches = list(base_path.rglob(pattern))
            
            # Convert to relative paths and sort
            results = []
            for match in matches:
                if match.is_file():
                    rel_path = match.relative_to(base_path)
                    results.append(str(rel_path))
            
            results.sort()
            
            # Limit results
            max_results = 1000
            truncated = False
            if len(results) > max_results:
                results = results[:max_results]
                truncated = True
            
            output = "\n".join(results)
            if truncated:
                output += f"\n... (truncated, {len(matches)} total matches)"
            
            return ToolResult(
                success=True,
                output=output if output else "No files found",
                metadata={
                    "pattern": pattern,
                    "path": str(base_path),
                    "matches": len(results),
                }
            )
            
        except Exception as e:
            return tool_error_result(e)
    
    def get_parameters(self) -> Dict[str, Any]:
        """Get tool parameter schema."""
        return build_parameters_schema(
            properties={
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern (e.g., '**/*.py')"
                },
                "path": {
                    "type": "string",
                    "description": "Base directory to search from",
                    "default": "."
                }
            },
            required=["pattern"],
        )


class GrepTool(BaseTool):
    """Tool for searching file contents using regex."""
    
    name = "grep"
    description = "Search for text patterns in files using regular expressions."
    category = "search"
    needs_encoding = True
    
    def execute(
        self,
        pattern: str,
        path: str = ".",
        file_pattern: str = "*",
        case_insensitive: bool = False,
        encoding: str = None,
    ) -> ToolResult:
        """
        Search for pattern in files.
        
        Args:
            pattern: Regex pattern to search for
            path: Base directory or file to search
            file_pattern: Glob pattern for files to search (only for directory)
            case_insensitive: Case-insensitive search
            encoding: File encoding
            
        Returns:
            ToolResult with matching lines
        """
        try:
            base_path, validation_error = resolve_and_validate_path(path, "path")
            if validation_error:
                return validation_error
            
            # Compile regex
            flags = re.MULTILINE
            if case_insensitive:
                flags |= re.IGNORECASE
            
            try:
                regex = re.compile(pattern, flags)
            except re.error as e:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Invalid regex pattern: {e}"
                )
            
            results = []
            
            # Get files to search
            if base_path.is_file():
                files = [base_path]
            else:
                files = [
                    f for f in base_path.rglob(file_pattern)
                    if f.is_file() and not f.name.startswith(".")
                ]
            
            # Search in each file (use default_encoding if not specified)
            enc = resolve_encoding(encoding, self.default_encoding)
            for file_path in files[:500]:  # Limit files to search
                try:
                    content = read_text_with_fallback(file_path, enc)
                    if content is None:
                        continue
                    
                    for i, line in enumerate(content.splitlines()):
                        if regex.search(line):
                            rel_path = file_path.relative_to(base_path) if base_path.is_dir() else file_path.name
                            results.append(f"{rel_path}:{i+1}: {line[:200]}")
                            
                except Exception:
                    continue
            
            # Limit results
            max_results = 100
            truncated = False
            if len(results) > max_results:
                results = results[:max_results]
                truncated = True
            
            output = "\n".join(results)
            if not output:
                output = "No matches found"
            elif truncated:
                output += f"\n... (truncated)"
            
            return ToolResult(
                success=True,
                output=output,
                metadata={
                    "pattern": pattern,
                    "files_searched": len(files[:500]),
                    "matches": len(results),
                }
            )
            
        except Exception as e:
            return tool_error_result(e)
    
    def get_parameters(self) -> Dict[str, Any]:
        """Get tool parameter schema."""
        return build_parameters_schema(
            properties={
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for"
                },
                "path": {
                    "type": "string",
                    "description": "Base directory or file to search",
                    "default": "."
                },
                "file_pattern": {
                    "type": "string",
                    "description": "Glob pattern for files to search",
                    "default": "*"
                },
                "case_insensitive": {
                    "type": "boolean",
                    "description": "Case-insensitive search",
                    "default": False
                },
                "encoding": {
                    "type": "string",
                    "description": "File encoding",
                    "default": "utf-8"
                }
            },
            required=["pattern"],
        )


class BashTool(BaseTool):
    """Tool for executing shell commands."""
    
    name = "bash"
    description = "Execute a shell command. Use with caution."
    category = "system"
    needs_encoding = False
    requires_permission = True  # Requires permission for bash commands
    
    # Skill script path patterns - these indicate paths relative to skill directory
    SKILL_SCRIPT_PATTERNS = [
        r'python\s+scripts/([^\s]+)',
        r'python3\s+scripts/([^\s]+)',
        r'\.\/scripts/([^\s]+)',
    ]
    
    # Dangerous commands that should be blocked completely
    DANGEROUS_PATTERNS = [
        r"rm\s+-rf\s+/",
        r"rm\s+-rf\s+~",
        r">\s*/dev/sd",
        r"mkfs",
        r"dd\s+if=",
        r":(){ :|:& };:",
        r"shutdown",
        r"reboot",
        r"init\s+0",
    ]
    
    # Delete command patterns (require extra permission)
    DELETE_PATTERNS = [
        r"\brm\b",           # rm command
        r"\bdel\b",          # del command (Windows)
        r"\berase\b",        # erase command (Windows)
        r"\bRemove-Item\b",  # PowerShell Remove-Item
        r"\brm-rf\b",
        r"--delete",         # rsync --delete
        r"-delete",          # find -delete
    ]
    
    def _has_delete_command(self, command: str) -> bool:
        """
        Check if command contains delete operations.
        
        Args:
            command: Command string to check
            
        Returns:
            True if command has delete operations
        """
        for pattern in self.DELETE_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return True
        return False
    
    def resolve_skill_paths(self, command: str, skill_dir: str) -> str:
        """
        Resolve relative paths in command to absolute paths based on skill directory.
        
        Only resolves paths that point to skill's internal scripts/ directory.
        User file paths (like document.docx) are left as-is (relative to cwd).
        
        Args:
            command: Shell command to process
            skill_dir: Skill base directory path
            
        Returns:
            Command with resolved absolute paths for skill scripts
        """
        if not skill_dir:
            return command
        
        skill_path = Path(skill_dir)
        resolved_command = command
        
        for pattern in self.SKILL_SCRIPT_PATTERNS:
            def replace_path(match):
                script_rel_path = match.group(1)
                # Check if this script exists in the skill directory
                full_script_path = skill_path / 'scripts' / script_rel_path
                if full_script_path.exists():
                    # Replace scripts/... with absolute path
                    original = match.group(0)
                    return original.replace(f'scripts/{script_rel_path}', str(full_script_path))
                return match.group(0)
            
            resolved_command = re.sub(pattern, replace_path, resolved_command, flags=re.IGNORECASE)
        
        return resolved_command
    
    def execute_with_skill_context(
        self,
        command: str,
        timeout: int = 60,
        cwd: str = None,
        skill_dir: str = None,
    ) -> ToolResult:
        """
        Execute command with skill context awareness.
        
        Args:
            command: Shell command to execute
            timeout: Timeout in seconds
            cwd: Working directory for command
            skill_dir: Skill directory for resolving relative script paths
            
        Returns:
            ToolResult with command output
        """
        # Resolve skill script paths if skill context is provided
        if skill_dir:
            command = self.resolve_skill_paths(command, skill_dir)
        
        return self.execute(command, timeout, cwd)
    
    def execute(
        self,
        command: str,
        timeout: int = 60,
        cwd: str = None,
    ) -> ToolResult:
        """
        Execute a shell command.
        
        Args:
            command: Shell command to execute
            timeout: Timeout in seconds
            cwd: Working directory for command
            
        Returns:
            ToolResult with command output and permission metadata
        """
        try:
            # Check for dangerous commands (always blocked)
            for pattern in self.DANGEROUS_PATTERNS:
                if re.search(pattern, command, re.IGNORECASE):
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Dangerous command blocked: {command}"
                    )
            
            # Check if command has delete operations
            has_delete = self._has_delete_command(command)
            
            # Return metadata for permission check (no output in preview mode)
            return ToolResult(
                success=True,
                output="",  # Empty output in preview mode
                metadata={
                    "command": command,
                    "timeout": timeout,
                    "cwd": cwd,
                    "has_delete": has_delete,
                    "requires_permission": True,
                }
            )
            
        except Exception as e:
            return tool_error_result(e)
    
    def execute_with_permission(
        self,
        command: str,
        timeout: int = 60,
        cwd: str = None,
    ) -> ToolResult:
        """
        Actually execute the command after permission is granted.
        
        Uses a strict timeout mechanism that forcefully terminates the process
        and all its children when timeout is reached.
        
        Args:
            command: Shell command to execute
            timeout: Timeout in seconds (hard limit, cannot exceed)
            cwd: Working directory for command
            
        Returns:
            ToolResult with command output
        """
        try:
            exec_result = execute_command_with_timeout(
                command=command,
                timeout=timeout,
                cwd=cwd,
                encoding=self.default_encoding,
            )

            if exec_result.error:
                return ToolResult(success=False, output="", error=exec_result.error)

            if exec_result.timed_out:
                partial_stdout = exec_result.stdout or ""
                partial_stderr = exec_result.stderr or ""

                output_parts = []
                if partial_stdout.strip():
                    output_parts.append("[STDOUT]\n" + partial_stdout)
                if partial_stderr.strip():
                    output_parts.append("[STDERR]\n" + partial_stderr)

                output_parts.append(
                    f"\n[TIMEOUT] Command timed out after {timeout} seconds and was forcefully terminated."
                )
                output_parts.append(
                    "[NOTE] The command was running for too long. If this is a server command (like runserver), consider using a background process instead."
                )

                full_output = "\n\n".join(output_parts)
                full_output = truncate_output(full_output)

                return ToolResult(
                    success=False,
                    output=full_output,
                    error=None,
                )

            return_code = exec_result.return_code
            output = exec_result.stdout or ""
            error_msg = None
            if exec_result.stderr:
                stderr_content = exec_result.stderr
                output = f"{output}\n{stderr_content}" if output else stderr_content
                error_msg = stderr_content.strip()

            output = output.strip() or "(no output)"
            output = truncate_output(output)

            if return_code != 0:
                if error_msg:
                    pass
                elif output and output != "(no output)":
                    error_msg = output
                else:
                    error_msg = f"Command failed with exit code {return_code}"

            return ToolResult(
                success=return_code == 0,
                output=output,
                error=error_msg if return_code != 0 else None,
                metadata={
                    "command": command,
                    "return_code": return_code,
                }
            )

        except Exception as e:
            return tool_error_result(e)
    
    def get_parameters(self) -> Dict[str, Any]:
        """Get tool parameter schema."""
        return build_parameters_schema(
            properties={
                "command": {
                    "type": "string",
                    "description": "Shell command to execute"
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds. Default: 60s. For long-running commands like tests/builds, increase as needed. For server commands that don't exit (e.g., runserver), use short timeout (5-10s) or the command will be forcefully terminated when timeout is reached.",
                    "default": 60
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory for command"
                }
            },
            required=["command"],
        )
