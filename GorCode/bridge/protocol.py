"""
Protocol Layer
==============

Defines the protocol envelope and helpers for frontend-backend communication.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import uuid

PROTOCOL_VERSION = "1.0"

# Protocol definitions (request/response payload examples)
PROTOCOL_DEFINITIONS = {
    "config.get": {
        "request": {"scope": "merged"},
        "response": {"config": {}, "source": "merged"},
    },
    "config.status": {
        "request": {},
        "response": {
            "user_exists": True,
            "project_exists": True,
            "paths": {"user": "~/.gorcode/config.json", "project": "./.gorcode/config.json"},
        },
    },
    "config.initialize": {
        "request": {"path": ".", "force": False, "user_only": False, "project_only": False},
        "response": {"results": {"user": {}, "project": {}}},
    },
    "agent.list": {
        "request": {"visibility": "visible"},
        "response": {"agents": []},
    },
    "agent.get": {
        "request": {"name": "build"},
        "response": {"agent": {}},
    },
    "agent.switch": {
        "request": {"name": "build"},
        "response": {"success": True, "agent": "build"},
    },
    "session.list": {
        "request": {"limit": 10, "offset": 0},
        "response": {"sessions": [], "total": 0},
    },
    "session.load": {
        "request": {"session_id": "abcd1234"},
        "response": {"messages": [], "metadata": {}},
    },
    "session.delete": {
        "request": {"session_id": "abcd1234"},
        "response": {"success": True},
    },
    "session.search": {
        "request": {"query": "search", "limit": 10},
        "response": {"results": []},
    },
    "debug.set": {
        "request": {"enabled": True},
        "response": {"success": True, "enabled": True, "debug_dir": ""},
    },
    "debug.status": {
        "request": {},
        "response": {"enabled": False, "log_count": 0, "current_log": None},
    },
    "tools.init": {
        "request": {"encoding": "utf-8"},
        "response": {"success": True, "tool_count": 0},
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


@dataclass
class ProtocolMessage:
    """Protocol message envelope."""

    type: str
    payload: Dict[str, Any] = field(default_factory=dict)
    protocol_version: str = PROTOCOL_VERSION
    request_id: Optional[str] = None
    event_id: Optional[str] = None
    session_id: Optional[str] = None
    timestamp: str = field(default_factory=_now_iso)
    source: str = "backend"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "type": self.type,
            "request_id": self.request_id,
            "event_id": self.event_id,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "source": self.source,
            "payload": self.payload,
        }


def make_request(
    msg_type: str,
    payload: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
    source: str = "frontend",
) -> Dict[str, Any]:
    return ProtocolMessage(
        type=msg_type,
        payload=payload or {},
        request_id=request_id or _new_id("req"),
        session_id=session_id,
        source=source,
    ).to_dict()


def make_event(
    msg_type: str,
    payload: Optional[Dict[str, Any]] = None,
    event_id: Optional[str] = None,
    session_id: Optional[str] = None,
    source: str = "backend",
) -> Dict[str, Any]:
    return ProtocolMessage(
        type=msg_type,
        payload=payload or {},
        event_id=event_id or _new_id("evt"),
        session_id=session_id,
        source=source,
    ).to_dict()


def make_response(
    request_id: str,
    payload: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
    success: bool = True,
    error: Optional[str] = None,
    source: str = "backend",
) -> Dict[str, Any]:
    msg_type = "response.ok" if success else "response.error"
    resp_payload = payload or {}
    if not success and error:
        resp_payload = dict(resp_payload)
        resp_payload["error"] = error
    return ProtocolMessage(
        type=msg_type,
        payload=resp_payload,
        request_id=request_id,
        session_id=session_id,
        source=source,
    ).to_dict()
