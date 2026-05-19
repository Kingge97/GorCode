"""
HTTP sandbox provider adapter.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Mapping, Optional
from urllib.request import Request, urlopen

from ..tools.core_tool_support.base import ToolResult
from .types import SandboxDecision, SandboxError, SandboxRequest


class HttpSandboxProvider:
    """Call an HTTP sandbox service using gorcode-sandbox-v1 JSON."""

    def __init__(self, url: str, params: Optional[Mapping[str, Any]] = None, **_: Any) -> None:
        if not url:
            raise SandboxError("http sandbox provider requires url")
        self._url = url
        self._params = dict(params or {})

    def decide(self, request: SandboxRequest) -> SandboxDecision:
        body = json.dumps(_request_payload(request, self._params)).encode("utf-8")
        http_request = Request(
            self._url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(http_request) as response:
            if response.status >= 400:
                raise SandboxError(f"http sandbox returned status {response.status}")
            payload = json.loads(response.read().decode("utf-8"))
        return _decision_from_payload(payload)


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
    tool_result = None
    if isinstance(result, dict):
        tool_result = ToolResult(
            success=bool(result.get("success", False)),
            output=str(result.get("output", "")),
            error=result.get("error"),
            metadata=dict(result.get("metadata") or {}),
        )
    return SandboxDecision(
        effect=str(payload.get("effect", "")),
        reason=str(payload.get("reason", "")),
        rule_id=payload.get("rule_id"),
        details=dict(payload.get("details") or {}),
        result=tool_result,
    )
