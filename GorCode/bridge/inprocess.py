"""
In-Process Transport
====================

Default transport that runs frontend and backend in the same process.
"""

from dataclasses import dataclass
from typing import Any, Dict, Generator, Optional

from GorCode.backend.config.manager import ConfigManager
from GorCode.backend.tools import initialize_tools
from GorCode.backend.tools.core_tool_support.base import ToolRegistry
from GorCode.backend.agents.base import AgentRegistry

from .gateway import BackendService
from .protocol import make_request
from GorCode.shared.permission import PermissionResponsePayload, PermissionRespondResult


class InProcessTransport:
    """In-process transport connecting frontend to backend service."""

    def __init__(
        self,
        config_manager: ConfigManager,
        tool_registry: ToolRegistry,
        agent_registry: AgentRegistry,
    ):
        self._backend = BackendService(
            config_manager=config_manager,
            tool_registry=tool_registry,
            agent_registry=agent_registry,
        )

    @property
    def backend(self) -> BackendService:
        return self._backend

    def send_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        return self._backend.handle_request(request)

    def stream_request(self, request: Dict[str, Any]) -> Generator[Dict[str, Any], None, None]:
        request_type = request.get("type", "")
        payload = request.get("payload") or {}
        if request_type == "chat.send":
            return self._backend.stream_chat(payload.get("text", ""))
        if request_type == "init.generate":
            return self._backend.stream_init()
        return iter([])


class FrontendClient:
    """Frontend client that talks to backend via protocol."""

    def __init__(self, transport: InProcessTransport):
        self._transport = transport

    def set_permission_callback(self, callback) -> None:
        raise RuntimeError("permission_callback is obsolete; renderer sends permission.respond")

    def set_reconnect_callback(self, callback) -> None:
        self._transport.backend.set_reconnect_callback(callback)

    def request(self, msg_type: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        request = make_request(msg_type, payload or {})
        response = self._transport.send_request(request)
        resp_type = response.get("type", "")
        if resp_type == "response.ok":
            return {"success": True, "payload": response.get("payload", {})}
        return {
            "success": False,
            "payload": response.get("payload", {}),
            "error": (response.get("payload") or {}).get("error", "Unknown error"),
        }

    def respond_permission(
        self,
        payload: PermissionResponsePayload,
    ) -> PermissionRespondResult:
        response = self.request("permission.respond", payload.to_dict())
        return PermissionRespondResult(
            success=bool(response.get("success")),
            error=response.get("error"),
        )

    def stream(self, msg_type: str, payload: Optional[Dict[str, Any]] = None) -> Generator[Dict[str, Any], None, None]:
        request = make_request(msg_type, payload or {})
        stream = self._transport.stream_request(request)
        for event in stream:
            yield event


@dataclass
class InProcessRuntime:
    """Runtime bundle for in-process frontend usage."""

    client: FrontendClient
    config_manager: ConfigManager


def create_inprocess_client(
    config_path: Optional[str] = None,
    project_path: Optional[str] = None,
) -> InProcessRuntime:
    """
    Create an in-process frontend client with initialized backend components.

    Args:
        config_path: Optional config file path
        project_path: Optional project path for config/agents

    Returns:
        InProcessRuntime with client and config manager
    """
    config_manager = ConfigManager(project_path=project_path, config_path=config_path)
    config = config_manager.load_config()

    tool_registry = initialize_tools(config.default_encoding, config=config)
    agent_registry = AgentRegistry()

    transport = InProcessTransport(
        config_manager=config_manager,
        tool_registry=tool_registry,
        agent_registry=agent_registry,
    )
    client = FrontendClient(transport)
    return InProcessRuntime(client=client, config_manager=config_manager)
