"""
External JSONL process sandbox provider.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import uuid
from typing import Any, Mapping, Optional

from ..tools.core_tool_support.base import ToolResult
from .types import SandboxDecision, SandboxError, SandboxRequest


class ProcessSandboxProvider:
    """Call an external sandbox process using gorcode-sandbox-v1 JSON."""

    def __init__(self, command: str, params: Optional[Mapping[str, Any]] = None, **_: Any) -> None:
        if not command:
            raise SandboxError("process sandbox provider requires command")
        self._command = command
        self._params = dict(params or {})

    def decide(self, request: SandboxRequest) -> SandboxDecision:
        payload = _request_payload(request, self._params)
        completed = subprocess.run(
            _command_args(self._command),
            input=json.dumps(payload, ensure_ascii=False) + "\n",
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise SandboxError(f"process sandbox exited {completed.returncode}: {completed.stderr}")
        line = completed.stdout.strip().splitlines()
        if not line:
            raise SandboxError("process sandbox returned no response")
        return _decision_from_payload(json.loads(line[-1]))


def _command_args(command: str) -> list[str]:
    args = shlex.split(command, posix=os.name != "nt")
    if os.name == "nt":
        return [arg.strip('"') for arg in args]
    return args


def _request_payload(request: SandboxRequest, params: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "protocol": "gorcode-sandbox-v1",
        "request_id": f"sandbox-{uuid.uuid4().hex}",
        "tool_name": request.tool_name,
        "operation": request.operation,
        "arguments": dict(request.arguments),
        "metadata": dict(request.metadata),
        "workspace_root": str(request.workspace_root),
        "cwd": str(request.cwd) if request.cwd else None,
        "params": dict(params),
    }


def _decision_from_payload(payload: dict[str, Any]) -> SandboxDecision:
    result = payload.get("result")
    tool_result = _tool_result_from(result) if isinstance(result, dict) else None
    return SandboxDecision(
        effect=str(payload.get("effect", "")),
        reason=str(payload.get("reason", "")),
        rule_id=payload.get("rule_id"),
        details=dict(payload.get("details") or {}),
        result=tool_result,
    )


def _tool_result_from(payload: dict[str, Any]) -> ToolResult:
    return ToolResult(
        success=bool(payload.get("success", False)),
        output=str(payload.get("output", "")),
        error=payload.get("error"),
        metadata=dict(payload.get("metadata") or {}),
    )
