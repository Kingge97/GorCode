"""
Shell Utilities
===============

Cross-platform shell command handling utilities.
"""

import os
import re
import subprocess
import shlex
import threading
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple, Union

from .detector import PlatformDetector, PlatformType, ShellType


class ShellUtils:
    """
    Cross-platform shell command handling utilities.
    
    Handles differences between Windows CMD/PowerShell and Unix shells.
    """
    
    def __init__(self):
        """Initialize shell utilities."""
        self._detector = PlatformDetector()
    
    @property
    def shell_type(self) -> ShellType:
        """Get the current shell type."""
        return self._detector.detect().shell_type
    
    @property
    def is_powershell(self) -> bool:
        """Check if running in PowerShell."""
        return self.shell_type == ShellType.POWERSHELL
    
    @property
    def is_cmd(self) -> bool:
        """Check if running in CMD."""
        return self.shell_type == ShellType.CMD
    
    @property
    def is_bash(self) -> bool:
        """Check if running in Bash."""
        return self.shell_type == ShellType.BASH
    
    def parse_command(self, command: str) -> List[str]:
        """
        Parse a command string into arguments.
        
        Args:
            command: Command string
            
        Returns:
            List of arguments
        """
        if self._detector.is_windows:
            return self._parse_windows(command)
        else:
            return shlex.split(command)
    
    def _parse_windows(self, command: str) -> List[str]:
        """
        Parse a Windows command string.
        
        Windows has complex quoting rules that differ from POSIX.
        """
        # Use subprocess's list2cmdline in reverse (approximate)
        # This is a simplified implementation
        args = []
        current = ""
        in_quotes = False
        
        i = 0
        while i < len(command):
            char = command[i]
            
            if char == '"':
                in_quotes = not in_quotes
            elif char == ' ' and not in_quotes:
                if current:
                    args.append(current)
                    current = ""
            elif char == '\\' and i + 1 < len(command):
                # Handle escape sequences
                next_char = command[i + 1]
                if next_char in '"\\':
                    current += next_char
                    i += 1
                else:
                    current += char
            else:
                current += char
            
            i += 1
        
        if current:
            args.append(current)
        
        return args
    
    def quote_argument(self, arg: str) -> str:
        """
        Quote a single argument for the current shell.
        
        Args:
            arg: Argument to quote
            
        Returns:
            Quoted argument string
        """
        if self._detector.is_windows:
            return self._quote_windows(arg)
        else:
            return shlex.quote(arg)
    
    def _quote_windows(self, arg: str) -> str:
        """
        Quote an argument for Windows.
        
        Follows the rules for CommandLineToArgvW.
        """
        # No quoting needed if no special characters
        if not arg or ' ' not in arg and '"' not in arg and '\\' not in arg:
            return arg
        
        # Need to quote
        result = ['"']
        
        backslashes = 0
        for char in arg:
            if char == '\\':
                backslashes += 1
            elif char == '"':
                # Double backslashes before quote
                result.append('\\' * (backslashes * 2 + 1))
                result.append('"')
                backslashes = 0
            else:
                # Output pending backslashes
                if backslashes:
                    result.append('\\' * backslashes)
                    backslashes = 0
                result.append(char)
        
        # Close quote, doubling trailing backslashes
        result.append('\\' * (backslashes * 2))
        result.append('"')
        
        return ''.join(result)
    
    def build_command(self, args: List[str]) -> str:
        """
        Build a command string from arguments.
        
        Args:
            args: List of arguments
            
        Returns:
            Command string
        """
        return ' '.join(self.quote_argument(arg) for arg in args)
    
    def get_shell_command(self, command: str) -> Tuple[str, bool]:
        """
        Get the shell executable and whether to use shell=True.
        
        Args:
            command: Command to execute
            
        Returns:
            Tuple of (shell executable or command, use shell flag)
        """
        if self._detector.is_windows:
            # Windows: use cmd.exe or powershell
            if self.is_powershell:
                return ("powershell.exe", True)
            else:
                return ("cmd.exe", True)
        else:
            # Unix: use /bin/sh
            return ("/bin/sh", True)
    
    def execute(
        self,
        command: Union[str, List[str]],
        cwd: Optional[str] = None,
        env: Optional[dict] = None,
        capture_output: bool = True,
        timeout: Optional[float] = None,
    ) -> Tuple[int, str, str]:
        """
        Execute a shell command.
        
        Args:
            command: Command to execute (string or list)
            cwd: Working directory
            env: Environment variables
            capture_output: Whether to capture output
            timeout: Timeout in seconds
            
        Returns:
            Tuple of (return code, stdout, stderr)
        """
        # Prepare environment
        run_env = os.environ.copy()
        if env:
            run_env.update(env)
        
        # Ensure UTF-8 encoding on Windows
        if self._detector.is_windows:
            run_env['PYTHONIOENCODING'] = 'utf-8'
        
        # Determine if using shell
        if isinstance(command, str):
            use_shell = True
        else:
            use_shell = False
        
        try:
            if not use_shell or not capture_output:
                result = subprocess.run(
                    command,
                    shell=use_shell,
                    cwd=cwd,
                    env=run_env,
                    capture_output=capture_output,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    timeout=timeout,
                )
                return (result.returncode, result.stdout or "", result.stderr or "")

            exec_result = self.execute_with_timeout(
                command=str(command),
                timeout=timeout,
                cwd=cwd,
                encoding="utf-8",
                env=run_env,
            )
            return (exec_result.return_code, exec_result.stdout, exec_result.stderr)
        
        except subprocess.TimeoutExpired:
            return (-1, "", "Command timed out")
        except Exception as e:
            return (-1, "", str(e))
    
    def which(self, command: str) -> Optional[str]:
        """
        Find the full path to a command.
        
        Args:
            command: Command name
            
        Returns:
            Full path to command or None
        """
        # Use shutil.which which handles cross-platform
        import shutil
        return shutil.which(command)
    
    def get_path(self) -> List[str]:
        """
        Get the PATH environment variable as a list.
        
        Returns:
            List of paths
        """
        path_var = os.environ.get("PATH", "")
        sep = ";" if self._detector.is_windows else ":"
        return path_var.split(sep)
    
    def escape_for_display(self, command: str) -> str:
        """
        Escape a command for safe display.
        
        Args:
            command: Command string
            
        Returns:
            Escaped command string
        """
        # Remove potentially dangerous patterns
        dangerous = ['$', '`', '(', ')', '{', '}', '|', ';', '&']
        result = command
        
        if self._detector.is_windows:
            # Windows: escape % characters
            result = result.replace('%', '%%')
        
        return result
    
    def get_env_var_syntax(self, var_name: str) -> str:
        """
        Get the syntax for referencing an environment variable.
        
        Args:
            var_name: Variable name
            
        Returns:
            Variable reference syntax
        """
        if self._detector.is_windows:
            return f"%{var_name}%"
        else:
            return f"${var_name}"
    
    def get_set_env_command(self, var_name: str, value: str) -> str:
        """
        Get the command to set an environment variable.
        
        Args:
            var_name: Variable name
            value: Variable value
            
        Returns:
            Set command string
        """
        quoted_value = self.quote_argument(value)
        
        if self.is_powershell:
            return f"$env:{var_name} = {quoted_value}"
        elif self.is_cmd:
            return f"set {var_name}={quoted_value}"
        else:
            return f"export {var_name}={quoted_value}"

    def execute_with_timeout(
        self,
        command: str,
        timeout: Optional[float] = None,
        cwd: Optional[str] = None,
        encoding: str = "utf-8",
        env: Optional[dict] = None,
    ) -> "ShellExecutionResult":
        """
        Execute a command with strict timeout and process cleanup.

        Returns:
            ShellExecutionResult with stdout/stderr and timeout flag.
        """
        process = None
        try:
            platform_info = PlatformDetector().detect()
            shell_cmd = self._build_shell_command(command, platform_info, encoding)

            # Start the process with process group for better control
            if platform_info.platform_type.value != "windows":
                process = subprocess.Popen(
                    shell_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=cwd,
                    env=env,
                    encoding=encoding,
                    errors="replace",
                    preexec_fn=os.setsid,
                )
            else:
                process = subprocess.Popen(
                    shell_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=cwd,
                    env=env,
                    encoding=encoding,
                    errors="replace",
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                )

            stdout_buffer: List[str] = []
            stderr_buffer: List[str] = []
            completed = [False]
            exception_occurred = [None]

            def read_output() -> None:
                try:
                    while True:
                        ret = process.poll()

                        if platform_info.platform_type.value != "windows":
                            import select
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
                            line = process.stdout.readline()
                            if line:
                                stdout_buffer.append(line)
                            line = process.stderr.readline()
                            if line:
                                stderr_buffer.append(line)

                        if ret is not None:
                            remaining_stdout, remaining_stderr = process.communicate()
                            if remaining_stdout:
                                stdout_buffer.append(remaining_stdout)
                            if remaining_stderr:
                                stderr_buffer.append(remaining_stderr)
                            completed[0] = True
                            break

                        time.sleep(0.01)
                except Exception as e:
                    exception_occurred[0] = e
                    completed[0] = True

            output_thread = threading.Thread(target=read_output)
            output_thread.daemon = True
            output_thread.start()

            output_thread.join(timeout=timeout)

            if not completed[0]:
                self._kill_process_tree(process, platform_info)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
                return ShellExecutionResult(
                    return_code=-1,
                    stdout="".join(stdout_buffer),
                    stderr="".join(stderr_buffer),
                    timed_out=True,
                )

            if exception_occurred[0]:
                raise exception_occurred[0]

            return ShellExecutionResult(
                return_code=process.returncode,
                stdout="".join(stdout_buffer),
                stderr="".join(stderr_buffer),
                timed_out=False,
            )

        except Exception as e:
            if process is not None and process.poll() is None:
                try:
                    platform_info = PlatformDetector().detect()
                    self._kill_process_tree(process, platform_info)
                except Exception:
                    pass
            return ShellExecutionResult(
                return_code=-1,
                stdout="",
                stderr="",
                timed_out=False,
                error=str(e),
            )

    def _build_shell_command(
        self,
        command: str,
        platform_info,
        encoding: str,
    ) -> List[str]:
        """
        Build the platform-specific shell command list.
        """
        code_page = None
        if platform_info.platform_type.value == "windows":
            encoding_lower = encoding.lower()
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
            if platform_info.shell_type == ShellType.CMD:
                if code_page:
                    return ["cmd.exe", "/c", f"chcp {code_page} >nul 2>&1 & {command}"]
                return ["cmd.exe", "/c", command]

            if platform_info.shell_type == ShellType.POWERSHELL:
                cmd_specific_patterns = [
                    r'^\s*cd\s+/d\s+',
                    r'&&',
                    r'\|\|',
                    r'^\s*set\s+\w+=',
                    r'^\s*echo\s+off',
                    r'%\w+%',
                ]
                is_cmd_syntax = any(
                    re.search(pattern, command, re.IGNORECASE)
                    for pattern in cmd_specific_patterns
                )
                if is_cmd_syntax:
                    if code_page:
                        return ["cmd.exe", "/c", f"chcp {code_page} >nul 2>&1 & {command}"]
                    return ["cmd.exe", "/c", command]

                if code_page:
                    ps_command = f"[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; {command}"
                    return ["powershell.exe", "-NoProfile", "-Command", ps_command]
                return ["powershell.exe", "-NoProfile", "-Command", command]

            if code_page:
                return ["cmd.exe", "/c", f"chcp {code_page} >nul 2>&1 & {command}"]
            return ["cmd.exe", "/c", command]

        return ["/bin/bash", "-c", command]

    def _kill_process_tree(self, process: subprocess.Popen, platform_info) -> None:
        """
        Kill a process and all its children.
        """
        try:
            if platform_info.platform_type.value == "windows":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    capture_output=True,
                    timeout=5,
                )
            else:
                import signal
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                time.sleep(0.5)
                if process.poll() is None:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass


@dataclass
class ShellExecutionResult:
    """Result from executing a shell command."""

    return_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    error: Optional[str] = None


# Convenience instance
_shell_utils = ShellUtils()

def parse_command(command: str) -> List[str]:
    """Parse a command string into arguments."""
    return _shell_utils.parse_command(command)

def quote_arg(arg: str) -> str:
    """Quote an argument for the current shell."""
    return _shell_utils.quote_argument(arg)

def execute_command(
    command: Union[str, List[str]],
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    timeout: Optional[float] = None,
) -> Tuple[int, str, str]:
    """Execute a shell command."""
    return _shell_utils.execute(command, cwd, env, True, timeout)

def execute_command_with_timeout(
    command: str,
    timeout: Optional[float] = None,
    cwd: Optional[str] = None,
    encoding: str = "utf-8",
    env: Optional[dict] = None,
) -> ShellExecutionResult:
    """Execute a shell command with strict timeout handling."""
    return _shell_utils.execute_with_timeout(command, timeout, cwd, encoding, env)

def find_command(command: str) -> Optional[str]:
    """Find the full path to a command."""
    return _shell_utils.which(command)
