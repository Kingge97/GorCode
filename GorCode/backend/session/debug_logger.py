"""
Debug Logger
============

Handles debug logging for sessions and messages.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import threading


class DebugLogger:
    """
    Debug logger for message inspection.
    
    Creates structured log files in message_debug_log folder
    with format: {agent_name}_{start_time}.json
    
    Log structure:
        message_debug_log/
            build_20260218_174500.json
            plan_20260218_180000.json
    """
    
    DEBUG_DIR = "message_debug_log"
    
    def __init__(
        self,
        base_path: str = None,
        enabled: bool = False,
    ):
        """
        Initialize debug logger.
        
        Args:
            base_path: Base path for logs (defaults to current directory)
            enabled: Whether logging is enabled
        """
        self.base_path = Path(base_path) if base_path else Path.cwd()
        self.enabled = enabled
        self._current_log: Optional[Dict[str, Any]] = None
        self._log_path: Optional[Path] = None
        self._lock = threading.Lock()
    
    @property
    def debug_dir(self) -> Path:
        """Get debug log directory."""
        return self.base_path / self.DEBUG_DIR
    
    def enable(self) -> None:
        """Enable debug logging."""
        self.enabled = True
    
    def disable(self) -> None:
        """Disable debug logging."""
        self.enabled = False
    
    def start_session(
        self,
        agent_name: str,
        session_id: str = None,
    ) -> str:
        """
        Start a new debug log session.
        
        Args:
            agent_name: Name of the agent
            session_id: Optional session ID
            
        Returns:
            Log file path
        """
        if not self.enabled:
            return ""
        
        with self._lock:
            # Ensure directory exists
            self.debug_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{agent_name}_{timestamp}.json"
            self._log_path = self.debug_dir / filename
            
            # Initialize log structure
            self._current_log = {
                "agent": agent_name,
                "session_id": session_id,
                "start_time": datetime.now().isoformat(),
                "messages": [],
                "model_calls": [],
                "tool_calls": [],
            }
            
            # Write initial file
            self._write_log()
            
            return str(self._log_path)
    
    def log_message(
        self,
        role: str,
        content: Any,
        metadata: Dict[str, Any] = None,
    ) -> None:
        """
        Log a message.
        
        Args:
            role: Message role (user, assistant, system, tool)
            content: Message content
            metadata: Additional metadata
        """
        if not self.enabled or not self._current_log:
            return
        
        with self._lock:
            entry = {
                "timestamp": datetime.now().isoformat(),
                "role": role,
                "content": content,
                "metadata": metadata or {},
            }
            self._current_log["messages"].append(entry)
            self._write_log()
    
    def log_model_call(
        self,
        model: str,
        request: Dict[str, Any],
        response: Dict[str, Any] = None,
        error: str = None,
    ) -> None:
        """
        Log a model API call.
        
        Args:
            model: Model name
            request: Request data
            response: Response data
            error: Error message if any
        """
        if not self.enabled or not self._current_log:
            return
        
        with self._lock:
            entry = {
                "timestamp": datetime.now().isoformat(),
                "model": model,
                "request": request,
                "response": response,
                "error": error,
            }
            self._current_log["model_calls"].append(entry)
            self._write_log()
    
    def log_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        result: Any = None,
        error: str = None,
    ) -> None:
        """
        Log a tool call.
        
        Args:
            tool_name: Tool name
            arguments: Tool arguments
            result: Tool result
            error: Error message if any
        """
        if not self.enabled or not self._current_log:
            return
        
        with self._lock:
            entry = {
                "timestamp": datetime.now().isoformat(),
                "tool": tool_name,
                "arguments": arguments,
                "result": result,
                "error": error,
            }
            self._current_log["tool_calls"].append(entry)
            self._write_log()
    
    def end_session(self) -> Optional[str]:
        """
        End current debug session.
        
        Returns:
            Path to log file
        """
        if not self.enabled or not self._current_log:
            return None
        
        with self._lock:
            self._current_log["end_time"] = datetime.now().isoformat()
            self._write_log()
            
            log_path = str(self._log_path)
            self._current_log = None
            self._log_path = None
            
            return log_path
    
    def _write_log(self) -> None:
        """Write current log to file."""
        if self._log_path and self._current_log:
            try:
                with open(self._log_path, "w", encoding="utf-8") as f:
                    json.dump(self._current_log, f, indent=2, ensure_ascii=False)
            except IOError as e:
                print(f"Error writing debug log: {e}")
    
    def list_logs(self) -> List[Dict[str, Any]]:
        """
        List all debug logs.
        
        Returns:
            List of log info dictionaries
        """
        if not self.debug_dir.exists():
            return []
        
        logs = []
        for log_file in sorted(self.debug_dir.glob("*.json"), reverse=True):
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                logs.append({
                    "path": str(log_file),
                    "agent": data.get("agent", "unknown"),
                    "start_time": data.get("start_time", ""),
                    "end_time": data.get("end_time", ""),
                    "message_count": len(data.get("messages", [])),
                    "model_call_count": len(data.get("model_calls", [])),
                    "tool_call_count": len(data.get("tool_calls", [])),
                })
            except (json.JSONDecodeError, IOError):
                continue
        
        return logs
    
    def get_log(self, path: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific debug log.
        
        Args:
            path: Path to log file
            
        Returns:
            Log data or None
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
    
    def cleanup_old_logs(self, days: int = 7) -> int:
        """
        Remove debug logs older than specified days.
        
        Args:
            days: Number of days
            
        Returns:
            Number of logs removed
        """
        if not self.debug_dir.exists():
            return 0
        
        cutoff = datetime.now().timestamp() - (days * 24 * 60 * 60)
        removed = 0
        
        for log_file in self.debug_dir.glob("*.json"):
            if log_file.stat().st_mtime < cutoff:
                try:
                    log_file.unlink()
                    removed += 1
                except IOError:
                    continue
        
        return removed
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get debug logger status.
        
        Returns:
            Status dictionary
        """
        return {
            "enabled": self.enabled,
            "debug_dir": str(self.debug_dir),
            "current_log": str(self._log_path) if self._log_path else None,
            "log_count": len(self.list_logs()) if self.debug_dir.exists() else 0,
        }
