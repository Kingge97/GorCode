"""
Shell Utilities
===============

Cross-platform shell command handling utilities.
"""

import os
import subprocess
import shlex
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

def find_command(command: str) -> Optional[str]:
    """Find the full path to a command."""
    return _shell_utils.which(command)
