"""Backend-side permission request contracts."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Protocol

from .manager import PermissionResponse, PermissionType


@dataclass(frozen=True)
class PermissionRequestInput:
    request_id: Optional[str]
    tool_call_id: str
    tool_name: str
    permission_type: PermissionType
    metadata: Dict[str, Any] = field(default_factory=dict)
    session_id: Optional[str] = None
    stream_id: Optional[str] = None
    frontend_channel_id: str = "cli"
    agent_name: Optional[str] = None
    agent_run_id: Optional[str] = None


@dataclass(frozen=True)
class PermissionRequestResult:
    response: PermissionResponse
    reason: Optional[str] = None


class PermissionRequester(Protocol):
    def request_permission(
        self,
        request: PermissionRequestInput,
    ) -> PermissionRequestResult:
        ...

