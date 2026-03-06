"""
Search Tools
============

Search tools including glob, grep, and bash.
"""

import os
import re
import subprocess
import fnmatch
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import BaseTool, ToolResult, ToolDefinition
from ..platform.detector import PlatformDetector, ShellType


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
            base_path = Path(path)
            
            if not base_path.exists():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Directory not found: {path}"
                )
            
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
                "required": ["pattern"]
            },
            category=self.category,
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
            base_path = Path(path)
            
            if not base_path.exists():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Path not found: {path}"
                )
            
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
            enc = encoding or self.default_encoding
            for file_path in files[:500]:  # Limit files to search
                try:
                    content = self._read_with_fallback(file_path, enc)
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
                "required": ["pattern"]
            },
            category=self.category,
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
            return ToolResult(
                success=False,
                output="",
                error=str(e)
            )
    
    def _kill_process_tree(self, process: subprocess.Popen, platform_info) -> None:
        """
        Kill a process and all its children.
        
        Args:
            process: The process to kill
            platform_info: Platform information
        """
        try:
            if platform_info.platform_type.value == "windows":
                # On Windows, use taskkill to kill the process tree
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    capture_output=True,
                    timeout=5
                )
            else:
                # On Unix, kill the process group
                import signal
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                # Give it a moment to terminate gracefully
                time.sleep(0.5)
                # Force kill if still running
                if process.poll() is None:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except Exception:
            # If group kill fails, try killing just the process
            try:
                process.kill()
            except Exception:
                pass
    
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
        process = None
        try:
            platform_info = PlatformDetector().detect()
            
            # 根据 default_encoding 获取对应的 Windows 代码页
            code_page = None
            if platform_info.platform_type.value == "windows":
                encoding_lower = self.default_encoding.lower()
                code_page_map = {
                    "utf-8": "65001",
                    "utf-8-sig": "65001",
                    "gbk": "936",
                    "gb2312": "936",
                    "gb18030": "54936",
                    "big5": "950",
                    "shift_jis": "932",
                    "euc-jp": "20932",
                    "latin-1": "1252",
                    "cp1252": "1252",
                }
                code_page = code_page_map.get(encoding_lower)
            
            if platform_info.platform_type.value == "windows":
                # Windows: detect actual shell type
                if platform_info.shell_type == ShellType.CMD:
                    # Use cmd.exe for CMD commands, with code page switch if needed
                    if code_page:
                        shell_cmd = ["cmd.exe", "/c", f"chcp {code_page} >nul 2>&1 & {command}"]
                    else:
                        shell_cmd = ["cmd.exe", "/c", command]
                elif platform_info.shell_type == ShellType.POWERSHELL:
                    # Check if command uses CMD-specific syntax
                    cmd_specific_patterns = [
                        r'^\s*cd\s+/d\s+',  # cd /d
                        r'&&',               # command chaining
                        r'\|\|',             # or chaining
                        r'^\s*set\s+\w+=',  # set VAR=
                        r'^\s*echo\s+off',  # echo off
                        r'%\w+%',            # variable expansion %VAR%
                    ]
                    
                    # If command has CMD-specific syntax, use cmd.exe
                    is_cmd_syntax = any(
                        re.search(pattern, command, re.IGNORECASE)
                        for pattern in cmd_specific_patterns
                    )
                    
                    if is_cmd_syntax:
                        if code_page:
                            shell_cmd = ["cmd.exe", "/c", f"chcp {code_page} >nul 2>&1 & {command}"]
                        else:
                            shell_cmd = ["cmd.exe", "/c", command]
                    else:
                        # PowerShell: use [Console]::OutputEncoding to set encoding
                        if code_page:
                            ps_command = f"[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; {command}"
                            shell_cmd = ["powershell.exe", "-NoProfile", "-Command", ps_command]
                        else:
                            shell_cmd = ["powershell.exe", "-NoProfile", "-Command", command]
                else:
                    # Default to cmd.exe on Windows
                    if code_page:
                        shell_cmd = ["cmd.exe", "/c", f"chcp {code_page} >nul 2>&1 & {command}"]
                    else:
                        shell_cmd = ["cmd.exe", "/c", command]
            else:
                # Unix-like
                shell_cmd = ["/bin/bash", "-c", command]
            
            # Start the process with process group for better control
            if platform_info.platform_type.value != "windows":
                # Create new process group on Unix
                process = subprocess.Popen(
                    shell_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=cwd,
                    encoding=self.default_encoding,
                    errors='replace',
                    preexec_fn=os.setsid
                )
            else:
                process = subprocess.Popen(
                    shell_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=cwd,
                    encoding=self.default_encoding,
                    errors='replace',
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                )
            
            # Use threading to implement strict timeout with partial output capture
            stdout_buffer = []
            stderr_buffer = []
            completed = [False]
            exception_occurred = [None]
            
            def read_output():
                try:
                    # Read output line by line to capture partial output
                    while True:
                        # Check if process has finished
                        ret = process.poll()
                        
                        # Read available output (non-blocking)
                        import select
                        if platform_info.platform_type.value != "windows":
                            # Unix: use select to check for available data
                            readable, _, _ = select.select(
                                [process.stdout, process.stderr], [], [], 0.1
                            )
                            if process.stdout in readable:
                                line = process.stdout.readline()
                                if line:
                                    stdout_buffer.append(line)
                            if process.stderr in readable:
                                line = process.stderr.readline()
                                if line:
                                    stderr_buffer.append(line)
                        else:
                            # Windows: read directly (may block briefly)
                            line = process.stdout.readline()
                            if line:
                                stdout_buffer.append(line)
                            line = process.stderr.readline()
                            if line:
                                stderr_buffer.append(line)
                        
                        # Check if process has finished
                        if ret is not None:
                            # Read any remaining output
                            remaining_stdout, remaining_stderr = process.communicate()
                            if remaining_stdout:
                                stdout_buffer.append(remaining_stdout)
                            if remaining_stderr:
                                stderr_buffer.append(remaining_stderr)
                            completed[0] = True
                            break
                        
                        # Small sleep to prevent busy waiting
                        time.sleep(0.01)
                        
                except Exception as e:
                    exception_occurred[0] = e
                    completed[0] = True
            
            # Start output reading thread
            output_thread = threading.Thread(target=read_output)
            output_thread.daemon = True
            output_thread.start()
            
            # Wait for completion with timeout
            output_thread.join(timeout=timeout)
            
            # Check if still running (timeout occurred)
            if not completed[0]:
                # Timeout! Kill the process tree
                self._kill_process_tree(process, platform_info)
                
                # Wait a bit for the process to die
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
                
                # Get partial output collected so far
                partial_stdout = "".join(stdout_buffer)
                partial_stderr = "".join(stderr_buffer)
                
                # Build output with timeout message and partial logs
                output_parts = []
                if partial_stdout.strip():
                    output_parts.append("[STDOUT]\n" + partial_stdout)
                if partial_stderr.strip():
                    output_parts.append("[STDERR]\n" + partial_stderr)
                
                output_parts.append(f"\n[TIMEOUT] Command timed out after {timeout} seconds and was forcefully terminated.")
                output_parts.append("[NOTE] The command was running for too long. If this is a server command (like runserver), consider using a background process instead.")
                
                full_output = "\n\n".join(output_parts)
                
                # Truncate if too long
                max_chars = 50000
                if len(full_output) > max_chars:
                    full_output = full_output[:max_chars] + "\n... (truncated)"
                
                return ToolResult(
                    success=False,
                    output=full_output,
                    error=None  # No error - timeout is expected behavior
                )
            
            # Check if exception occurred during output reading
            if exception_occurred[0]:
                raise exception_occurred[0]
            
            # Get return code
            return_code = process.returncode
            
            # Combine stdout and stderr
            output = "".join(stdout_buffer) or ""
            error_msg = None
            if stderr_buffer:
                stderr_content = "".join(stderr_buffer)
                output += "\n" + stderr_content
                error_msg = stderr_content.strip()
            
            output = output.strip() or "(no output)"
            
            # Truncate if too long
            max_chars = 50000
            if len(output) > max_chars:
                output = output[:max_chars] + "\n... (truncated)"
            
            # Build error message for failed commands
            if return_code != 0:
                if error_msg:
                    # Use stderr as error message
                    pass
                elif output and output != "(no output)":
                    # Use stdout as error message if stderr is empty
                    error_msg = output
                else:
                    # Provide a descriptive error with return code
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
            
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error=f"Command timed out after {timeout} seconds"
            )
        except Exception as e:
            # Ensure process is killed if something goes wrong
            if process is not None and process.poll() is None:
                try:
                    platform_info = PlatformDetector().detect()
                    self._kill_process_tree(process, platform_info)
                except Exception:
                    pass
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
                "required": ["command"]
            },
            category=self.category,
        )
