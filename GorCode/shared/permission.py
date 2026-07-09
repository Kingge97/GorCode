"""Shared permission protocol contracts."""

from dataclasses import dataclass
from typing import Literal, Optional, Protocol


PermissionResponseValue = Literal["once", "always", "reject"]


@dataclass(frozen=True)
class PermissionResponsePayload:
    request_id: str
    response: PermissionResponseValue
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "response": self.response,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PermissionRespondResult:
    success: bool
    error: Optional[str] = None


class PermissionResponder(Protocol):
    def respond_permission(
        self,
        payload: PermissionResponsePayload,
    ) -> PermissionRespondResult:
        ...

