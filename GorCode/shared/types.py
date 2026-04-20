"""
Shared Types
============

Data structures shared between frontend, bridge, and backend.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class InitResult:
    """Result of initialization process."""

    success: bool
    message: str
    created_paths: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "created_paths": list(self.created_paths),
            "errors": list(self.errors),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InitResult":
        payload = data or {}
        return cls(
            success=bool(payload.get("success", False)),
            message=str(payload.get("message", "")),
            created_paths=list(payload.get("created_paths") or []),
            errors=list(payload.get("errors") or []),
        )
