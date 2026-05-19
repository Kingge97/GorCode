"""
Gateway Layer
=============

Backend service that exposes protocol-based requests and event streams.
"""

from typing import Any, Dict, Generator, Iterable, List, Optional
from pathlib import Path
import queue
import threading
import asyncio
import json

from GorCode.backend.core.events import Event, EventBus, EventType
from GorCode.backend.core.executor import BackendExecutor
from GorCode.backend.config.manager import ConfigManager, GorCodeConfig
from GorCode.backend.config.initializer import ProjectInitializer
from GorCode.backend.tools.core_tool_support.base import ToolRegistry
from GorCode.backend.agents.base import AgentRegistry
from GorCode.backend.permission import get_permission_manager, PermissionType
from GorCode.backend.mcp import MCPManager, create_mcp_tools
from GorCode.backend.skills import SkillLoader, SkillInjector
from GorCode.backend.session import Session, SessionCloneError

from .protocol import make_event, make_response


ERROR_SESSION_EXISTS_OUTSIDE_PROJECT = "SESSION_EXISTS_OUTSIDE_PROJECT"
ERROR_SESSION_MANAGER_UNAVAILABLE = "SESSION_MANAGER_UNAVAILABLE"
ERROR_SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
ERROR_HISTORY_FILE_EXISTS = "HISTORY_FILE_EXISTS"
ERROR_HISTORY_FILE_NOT_FOUND = "HISTORY_FILE_NOT_FOUND"
ERROR_HISTORY_FILE_INVALID = "HISTORY_FILE_INVALID"
ERROR_HISTORY_FILE_ENCODING_INVALID = "HISTORY_FILE_ENCODING_INVALID"
ERROR_HISTORY_PARENT_DIR_NOT_FOUND = "HISTORY_PARENT_DIR_NOT_FOUND"
ERROR_HISTORY_SAVE_FAILED = "HISTORY_SAVE_FAILED"
ERROR_HISTORY_IMPORT_FAILED = "HISTORY_IMPORT_FAILED"
ERROR_CURRENT_SESSION_SAVE_FAILED = "CURRENT_SESSION_SAVE_FAILED"


EVENT_TYPE_TO_PROTOCOL = {
    EventType.MODEL_THINKING: "event.model.thinking",
    EventType.MODEL_ANSWER: "event.model.answer",
    EventType.MODEL_TOOL_CALL: "event.model.tool_call",
    EventType.MODEL_END: "event.model.end",
    EventType.MODEL_ERROR: "event.model.error",
    EventType.TOOL_EXECUTION_START: "event.tool.start",
    EventType.TOOL_EXECUTION_END: "event.tool.end",
    EventType.TOOL_RESULT: "event.tool.result",
    EventType.AGENT_SWITCH: "event.agent.switch",
    EventType.AGENT_SUBAGENT_START: "event.agent.subagent.start",
    EventType.AGENT_SUBAGENT_END: "event.agent.subagent.end",
    EventType.SESSION_NEW: "event.session.new",
    EventType.SESSION_LOAD: "event.session.load",
    EventType.SESSION_SAVE: "event.session.save",
    EventType.UI_MESSAGE: "event.ui.message",
    EventType.UI_CLEAR: "event.ui.clear",
    EventType.UI_ANIMATION_START: "event.ui.animation.start",
    EventType.UI_ANIMATION_END: "event.ui.animation.end",
    EventType.COMMAND_INPUT: "event.command.input",
    EventType.COMMAND_OUTPUT: "event.command.output",
    EventType.PERMISSION_REQUEST: "event.permission.request",
    EventType.PERMISSION_RESPONSE: "event.permission.response",
    EventType.SYSTEM_START: "event.system.start",
    EventType.SYSTEM_SHUTDOWN: "event.system.shutdown",
    EventType.SYSTEM_INTERRUPT: "event.system.interrupt",
    EventType.USER_REJECTION: "event.user.rejection",
}


FORWARDED_BUS_EVENTS = {
    EventType.AGENT_SUBAGENT_START,
    EventType.AGENT_SUBAGENT_END,
    EventType.TOOL_EXECUTION_START,
    EventType.TOOL_RESULT,
    EventType.MODEL_ANSWER,
    EventType.UI_MESSAGE,
    EventType.PERMISSION_REQUEST,
    EventType.PERMISSION_RESPONSE,
    EventType.USER_REJECTION,
}


class BackendService:
    """
    Backend service that exposes protocol-based request/response and event streams.
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        tool_registry: ToolRegistry,
        agent_registry: AgentRegistry,
    ):
        self._config_manager = config_manager
        self._event_bus = EventBus()
        self._executor = BackendExecutor(self._event_bus)
        self._executor.initialize(
            config_manager=config_manager,
            tool_registry=tool_registry,
            agent_registry=agent_registry,
        )

        self._event_queue: "queue.Queue[Event]" = queue.Queue()
        self._subscribe_bus_events()
        self._sync_task_tool()

        self._mcp_manager: Optional[MCPManager] = None
        self._skill_loader: Optional[SkillLoader] = None
        self._skill_injector: Optional[SkillInjector] = None

    @property
    def executor(self) -> BackendExecutor:
        return self._executor

    def set_permission_callback(self, callback) -> None:
        self._executor.set_permission_callback(callback)
        self._sync_task_tool()

    def set_reconnect_callback(self, callback) -> None:
        self._executor.set_reconnect_callback(callback)

    def _sync_task_tool(self) -> None:
        """Ensure TaskTool has the correct event bus and registries."""
        tool_registry = self._executor.tool_registry
        if not tool_registry:
            return
        task_tool = tool_registry.get("Task")
        if not task_tool:
            return
        if hasattr(task_tool, "set_event_bus"):
            task_tool.set_event_bus(self._event_bus)
        if hasattr(task_tool, "set_parent_agent_name"):
            task_tool.set_parent_agent_name(self._executor.state.current_agent)
        if hasattr(task_tool, "set_tool_registry"):
            task_tool.set_tool_registry(tool_registry)
        if hasattr(task_tool, "set_agent_registry") and getattr(self._executor, "_agent_registry", None):
            task_tool.set_agent_registry(self._executor._agent_registry)
        if hasattr(task_tool, "set_permission_manager"):
            task_tool.set_permission_manager(self._executor._permission_manager)
        if hasattr(task_tool, "set_permission_callback"):
            task_tool.set_permission_callback(self._executor._permission_callback)
        if hasattr(task_tool, "set_sandbox_manager"):
            task_tool.set_sandbox_manager(self._executor.sandbox_manager)
        if hasattr(task_tool, "set_hook_runtime"):
            task_tool.set_hook_runtime(self._executor.hook_runtime)
        if hasattr(task_tool, "set_hook_run_context"):
            task_tool.set_hook_run_context(
                self._executor.state.current_run_id,
                self._get_session_id(),
                self._executor.state.current_model,
            )

    def _subscribe_bus_events(self) -> None:
        for event_type in FORWARDED_BUS_EVENTS:
            self._event_bus.subscribe(event_type, self._on_bus_event)

    def _on_bus_event(self, event: Event) -> None:
        self._event_queue.put(event)

    def _drain_bus_events(self) -> Generator[Dict[str, Any], None, None]:
        while True:
            try:
                event = self._event_queue.get_nowait()
            except queue.Empty:
                break
            yield self._event_to_protocol(event)

    def _event_to_protocol(self, event: Event) -> Dict[str, Any]:
        event_type = EVENT_TYPE_TO_PROTOCOL.get(event.event_type)
        if not event_type:
            event_type = f"event.legacy.{event.event_type.name.lower()}"
        return make_event(
            event_type,
            payload=event.data or {},
            session_id=self._get_session_id(),
            source=event.source,
        )

    def _get_session_id(self) -> Optional[str]:
        session_manager = getattr(self._executor, "_session_manager", None)
        if session_manager and session_manager.current_session:
            return session_manager.current_session.session_id
        return None

    def _get_config_manager(self) -> Optional[ConfigManager]:
        return self._config_manager or getattr(self._executor, "_config_manager", None)

    def _get_session_manager(self):
        return getattr(self._executor, "_session_manager", None)

    def _get_debug_logger(self):
        return getattr(self._executor, "_debug_logger", None)

    def _get_agent_target_model(self, agent: str) -> Optional[str]:
        config_manager = self._get_config_manager()
        if not config_manager:
            return None
        connection = config_manager.get_agent_model(agent)
        return connection.name if connection else None

    def _error_response(
        self,
        request_id: str,
        error: str,
        error_code: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        data = dict(payload or {})
        data["error_code"] = error_code
        return make_response(
            request_id,
            payload=data,
            session_id=self._get_session_id(),
            success=False,
            error=error,
        )

    def _session_manager_error(self, request_id: str) -> Dict[str, Any]:
        return self._error_response(
            request_id,
            "Session manager not available",
            ERROR_SESSION_MANAGER_UNAVAILABLE,
        )

    def _history_scope(self, payload: Dict[str, Any]) -> str:
        scope = str(payload.get("scope", "project") or "project").strip().lower()
        return "all" if scope == "all" else "project"

    def _session_not_found_response(
        self,
        request_id: str,
        action: str,
        session_id: str,
        scope: str,
    ) -> Dict[str, Any]:
        manager = self._get_session_manager()
        outside = scope == "project" and manager.storage.exists_outside_project(
            session_id,
            manager.project_path,
        )
        if outside:
            return self._outside_project_response(request_id, action, session_id)
        return self._error_response(
            request_id,
            f"Session not found: {session_id}",
            ERROR_SESSION_NOT_FOUND,
        )

    def _outside_project_response(
        self,
        request_id: str,
        action: str,
        session_id: str,
    ) -> Dict[str, Any]:
        command = f"/history {action} {session_id} --all"
        error = (
            f"Session not found in current project: {session_id}\n"
            f"A matching session exists outside this project. Use {command} to {action} it."
        )
        return self._error_response(
            request_id,
            error,
            ERROR_SESSION_EXISTS_OUTSIDE_PROJECT,
        )

    def _history_agent_allowed(self, agent: str) -> bool:
        registry = getattr(self._executor, "_agent_registry", None)
        return bool(agent and registry and registry.get(agent))

    def _history_model_allowed(self, model: str) -> bool:
        model_manager = getattr(self._executor, "_model_manager", None)
        if model and model_manager:
            return model in model_manager.list_models()
        config_manager = self._get_config_manager()
        if model and config_manager:
            return model in config_manager.list_available_models()
        return False

    def _history_runtime_choice(self, source: Session) -> Dict[str, Any]:
        current_agent = self._executor.state.current_agent
        current_model = self._executor.state.current_model
        source_agent = str(source.metadata.agent or "").strip().lower()
        source_model = str(source.metadata.model or "").strip().lower()
        warnings: List[str] = []
        agent = self._choose_history_agent(source_agent, current_agent, warnings)
        model = self._choose_history_model(source_model, current_model, warnings)
        return {"agent": agent, "model": model, "warnings": warnings}

    def _choose_history_agent(
        self,
        source_agent: str,
        current_agent: str,
        warnings: List[str],
    ) -> str:
        if not source_agent or self._history_agent_allowed(source_agent):
            return source_agent or current_agent
        warnings.append(f"history agent is not allowed, use current agent {current_agent}")
        return current_agent

    def _choose_history_model(
        self,
        source_model: str,
        current_model: str,
        warnings: List[str],
    ) -> str:
        if not source_model or self._history_model_allowed(source_model):
            return source_model or current_model
        warnings.append(f"history model is not allowed, use current model {current_model}")
        return current_model

    def _apply_history_runtime(
        self,
        agent: str,
        model: str,
        warnings: List[str],
    ) -> Dict[str, str]:
        actual_agent = self._apply_history_agent(agent, warnings)
        actual_model = self._apply_history_model(model, warnings)
        self._sync_task_tool()
        return {"agent": actual_agent, "model": actual_model}

    def _apply_history_agent(self, agent: str, warnings: List[str]) -> str:
        current = self._executor.state.current_agent
        if not agent or agent == current:
            return current
        if self._executor.switch_agent(agent):
            return self._executor.state.current_agent
        warnings.append(f"history agent is not allowed, use current agent {current}")
        return current

    def _apply_history_model(self, model: str, warnings: List[str]) -> str:
        current = self._executor.state.current_model
        if not model or model == current:
            return current
        if self._executor.switch_model(model):
            return self._executor.state.current_model
        warnings.append(f"history model is not allowed, use current model {current}")
        return current

    def _clone_history_session(
        self,
        request_id: str,
        source_session: Session,
        source: Dict[str, str],
    ) -> Dict[str, Any]:
        manager = self._get_session_manager()
        runtime = self._history_runtime_choice(source_session)
        try:
            clone = manager.clone_session_for_current_project(
                source_session,
                source,
                agent=runtime["agent"],
                model=runtime["model"],
            )
        except SessionCloneError as exc:
            return self._clone_error_response(request_id, str(exc), source)
        actual = self._apply_history_runtime(
            runtime["agent"],
            runtime["model"],
            runtime["warnings"],
        )
        return self._finish_history_clone(request_id, clone, source, actual, runtime["warnings"])

    def _clone_error_response(
        self,
        request_id: str,
        error: str,
        source: Dict[str, str],
    ) -> Dict[str, Any]:
        code = ERROR_HISTORY_IMPORT_FAILED
        if "current session" in error.lower():
            code = ERROR_CURRENT_SESSION_SAVE_FAILED
        return self._error_response(request_id, error, code, payload={"source": source})

    def _finish_history_clone(
        self,
        request_id: str,
        clone: Session,
        source: Dict[str, str],
        actual: Dict[str, str],
        warnings: List[str],
    ) -> Dict[str, Any]:
        manager = self._get_session_manager()
        self._sync_clone_state(clone, actual)
        if not manager.save_current_session():
            return self._error_response(
                request_id,
                "Failed to save cloned session",
                ERROR_HISTORY_SAVE_FAILED,
            )
        self._start_clone_debug_session(clone, actual["agent"])
        return make_response(
            request_id,
            payload=self._clone_payload(clone, source, warnings),
            session_id=self._get_session_id(),
        )

    def _sync_clone_state(self, clone: Session, actual: Dict[str, str]) -> None:
        manager = self._get_session_manager()
        manager.update_agent(actual["agent"])
        manager.update_model(actual["model"])
        self._executor.state.messages = clone.get_messages_for_model()
        self._executor.reset_token_usage()

    def _start_clone_debug_session(self, clone: Session, agent: str) -> None:
        debug_logger = self._get_debug_logger()
        if debug_logger and debug_logger.enabled:
            debug_logger.end_session()
            debug_logger.start_session(agent, clone.session_id)

    def _clone_payload(
        self,
        clone: Session,
        source: Dict[str, str],
        warnings: List[str],
    ) -> Dict[str, Any]:
        return {
            "success": True,
            "session_id": clone.session_id,
            "source_session_id": source.get("session_id", ""),
            "source_path": source.get("path", ""),
            "messages": clone.get_messages_for_model(),
            "metadata": clone.metadata.to_dict(),
            "warnings": list(warnings),
        }

    def _resolve_history_path(self, path_value: str) -> Path:
        path = Path(str(path_value or "").strip()).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        return path.resolve(strict=False)

    def _load_session_from_history_file(self, path: Path) -> Session:
        try:
            with open(path, "r", encoding="utf-8") as file:
                data = json.load(file)
        except UnicodeDecodeError as exc:
            raise ValueError(ERROR_HISTORY_FILE_ENCODING_INVALID) from exc
        except json.JSONDecodeError as exc:
            raise ValueError(ERROR_HISTORY_FILE_INVALID) from exc
        except OSError as exc:
            raise ValueError(ERROR_HISTORY_FILE_INVALID) from exc
        self._validate_history_file_payload(data)
        return Session.from_dict(data)

    def _validate_history_file_payload(self, data: Any) -> None:
        if not isinstance(data, dict):
            raise ValueError(ERROR_HISTORY_FILE_INVALID)
        if "metadata" not in data or "messages" not in data:
            raise ValueError(ERROR_HISTORY_FILE_INVALID)
        if not isinstance(data.get("metadata"), dict):
            raise ValueError(ERROR_HISTORY_FILE_INVALID)
        self._validate_history_messages(data.get("messages"))

    def _validate_history_messages(self, messages: Any) -> None:
        if not isinstance(messages, list):
            raise ValueError(ERROR_HISTORY_FILE_INVALID)
        for message in messages:
            if not isinstance(message, dict):
                raise ValueError(ERROR_HISTORY_FILE_INVALID)
            if "role" not in message or "content" not in message:
                raise ValueError(ERROR_HISTORY_FILE_INVALID)

    def _handle_session_load(
        self,
        request_id: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        manager = self._get_session_manager()
        if not manager:
            return self._session_manager_error(request_id)
        session_id = str(payload.get("session_id", "")).strip()
        if not session_id:
            return self._handle_legacy_session_load(request_id, payload)
        scope = self._history_scope(payload)
        session = manager.storage.load_scoped(session_id, scope, manager.project_path)
        if not session:
            return self._session_not_found_response(request_id, "load", session_id, scope)
        source = {"kind": "session_id", "session_id": session_id, "path": ""}
        return self._clone_history_session(request_id, session, source)

    def _handle_legacy_session_load(
        self,
        request_id: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        messages = payload.get("messages")
        if messages is None:
            return self._error_response(
                request_id,
                "Session ID is required",
                ERROR_SESSION_NOT_FOUND,
            )
        self._executor.load_messages(messages or [])
        agent = payload.get("agent")
        model = payload.get("model")
        if agent:
            self._executor.switch_agent(str(agent).strip().lower())
            self._sync_task_tool()
        if model:
            self._executor.switch_model(str(model).strip().lower())
        return make_response(
            request_id,
            payload={"success": True},
            session_id=self._get_session_id(),
        )

    def _handle_session_save(self, request_id: str) -> Dict[str, Any]:
        success = self._executor.save_current_session()
        return make_response(
            request_id,
            payload={"success": success},
            session_id=self._get_session_id(),
            success=success,
            error=None if success else "Failed to save session",
        )

    def _handle_session_list(
        self,
        request_id: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        manager = self._get_session_manager()
        if not manager:
            return self._session_manager_error(request_id)
        limit = int(payload.get("limit", 20) or 20)
        offset = int(payload.get("offset", 0) or 0)
        sort_by = str(payload.get("sort_by", "updated_at") or "updated_at")
        scope = self._history_scope(payload)
        sessions = manager.list_sessions(limit, offset, sort_by, scope=scope)
        return make_response(
            request_id,
            payload={
                "sessions": [session.to_dict() for session in sessions],
                "total": manager.get_session_count(scope=scope),
                "scope": scope,
            },
            session_id=self._get_session_id(),
        )

    def _handle_session_search(
        self,
        request_id: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        manager = self._get_session_manager()
        if not manager:
            return self._session_manager_error(request_id)
        query = str(payload.get("query", "")).strip()
        if not query:
            return self._error_response(
                request_id,
                "Search query is required",
                ERROR_HISTORY_FILE_INVALID,
            )
        limit = int(payload.get("limit", 10) or 10)
        scope = self._history_scope(payload)
        results = manager.search_sessions(query, limit, scope=scope)
        return make_response(
            request_id,
            payload={"results": [result.to_dict() for result in results], "scope": scope},
            session_id=self._get_session_id(),
        )

    def _handle_session_delete(
        self,
        request_id: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        manager = self._get_session_manager()
        if not manager:
            return self._session_manager_error(request_id)
        session_id = str(payload.get("session_id", "")).strip()
        if not session_id:
            return self._error_response(request_id, "Session ID is required", ERROR_SESSION_NOT_FOUND)
        if manager.current_session and manager.current_session.session_id == session_id:
            return self._error_response(request_id, "Cannot delete current session", ERROR_SESSION_NOT_FOUND)
        scope = self._history_scope(payload)
        if not manager.storage.load_scoped(session_id, scope, manager.project_path):
            return self._session_not_found_response(request_id, "delete", session_id, scope)
        success = manager.delete_session(session_id, scope=scope)
        return make_response(
            request_id,
            payload={"success": success},
            session_id=self._get_session_id(),
            success=success,
            error=None if success else "Failed to delete session",
        )

    def _handle_session_info(
        self,
        request_id: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        manager = self._get_session_manager()
        if not manager:
            return self._session_manager_error(request_id)
        session_id = str(payload.get("session_id", "")).strip()
        if not session_id:
            session = manager.current_session
        else:
            scope = self._history_scope(payload)
            session = manager.storage.load_scoped(session_id, scope, manager.project_path)
            if not session:
                return self._session_not_found_response(request_id, "info", session_id, scope)
        if not session:
            return self._error_response(request_id, "Session not found", ERROR_SESSION_NOT_FOUND)
        return make_response(
            request_id,
            payload={"metadata": session.metadata.to_dict()},
            session_id=self._get_session_id(),
        )

    def _handle_session_export(
        self,
        request_id: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        manager = self._get_session_manager()
        if not manager:
            return self._session_manager_error(request_id)
        path_value = str(payload.get("path", "")).strip()
        if not path_value:
            return self._error_response(request_id, "History file path is required", ERROR_HISTORY_FILE_INVALID)
        path = self._resolve_history_path(path_value)
        if not path.parent.exists():
            return self._error_response(request_id, f"Parent directory not found: {path.parent}", ERROR_HISTORY_PARENT_DIR_NOT_FOUND)
        if path.exists() and not bool(payload.get("force", False)):
            return self._error_response(request_id, f"History file already exists: {path}", ERROR_HISTORY_FILE_EXISTS)
        if not manager.save_current_session():
            return self._error_response(request_id, "Failed to save current session", ERROR_CURRENT_SESSION_SAVE_FAILED)
        try:
            with open(path, "w", encoding="utf-8") as file:
                json.dump(manager.current_session.to_dict(), file, indent=2, ensure_ascii=False)
        except OSError as exc:
            return self._error_response(request_id, f"Failed to save history file: {exc}", ERROR_HISTORY_SAVE_FAILED)
        return make_response(
            request_id,
            payload={"success": True, "path": str(path)},
            session_id=self._get_session_id(),
        )

    def _handle_session_import(
        self,
        request_id: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        manager = self._get_session_manager()
        if not manager:
            return self._session_manager_error(request_id)
        path_value = str(payload.get("path", "")).strip()
        if not path_value:
            return self._error_response(request_id, "History file path is required", ERROR_HISTORY_FILE_INVALID)
        path = self._resolve_history_path(path_value)
        if not path.exists():
            return self._error_response(request_id, f"History file not found: {path}", ERROR_HISTORY_FILE_NOT_FOUND)
        try:
            source_session = self._load_session_from_history_file(path)
        except ValueError as exc:
            return self._history_file_error_response(request_id, str(exc), path)
        source = {"kind": "file_path", "session_id": "", "path": str(path)}
        return self._clone_history_session(request_id, source_session, source)

    def _history_file_error_response(
        self,
        request_id: str,
        code: str,
        path: Path,
    ) -> Dict[str, Any]:
        error_code = code if code in {
            ERROR_HISTORY_FILE_ENCODING_INVALID,
            ERROR_HISTORY_FILE_INVALID,
        } else ERROR_HISTORY_FILE_INVALID
        return self._error_response(
            request_id,
            f"Invalid history file: {path}",
            error_code,
        )

    def _init_result_payload(self, result) -> Dict[str, Any]:
        if hasattr(result, "to_dict"):
            return result.to_dict()
        return {
            "success": bool(getattr(result, "success", False)),
            "message": str(getattr(result, "message", "")),
            "created_paths": list(getattr(result, "created_paths", []) or []),
            "errors": list(getattr(result, "errors", []) or []),
        }

    def stream_chat(self, text: str) -> Generator[Dict[str, Any], None, None]:
        yield from self._stream_with_bus(self._executor.process_user_input(text))

    def stream_init(self) -> Generator[Dict[str, Any], None, None]:
        yield from self._stream_with_bus(self._executor.execute_init_command())

    def _stream_with_bus(
        self,
        generator: Iterable[Event],
        poll_interval: float = 0.05,
    ) -> Generator[Dict[str, Any], None, None]:
        """
        Stream executor events while interleaving event bus events.

        This ensures subagent/UI events emitted on the bus are flushed even
        while long-running tools are executing.
        """
        done = object()
        event_queue: "queue.Queue[Any]" = queue.Queue()
        exc_holder: Dict[str, Exception] = {}

        def _run() -> None:
            try:
                for event in generator:
                    event_queue.put(event)
            except Exception as exc:
                exc_holder["exc"] = exc
            finally:
                event_queue.put(done)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        while True:
            # Flush any bus events first (subagent/tool UI updates)
            yield from self._drain_bus_events()

            try:
                event = event_queue.get(timeout=poll_interval)
            except queue.Empty:
                # No executor event yet; keep draining bus events.
                continue

            if event is done:
                if "exc" in exc_holder:
                    raise exc_holder["exc"]
                break

            yield self._event_to_protocol(event)
            yield from self._drain_bus_events()

        # Final drain for any remaining bus events
        yield from self._drain_bus_events()

    def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        request_type = request.get("type", "")
        payload = request.get("payload") or {}
        request_id = request.get("request_id", "")

        try:
            if request_type == "config.get":
                config_manager = self._get_config_manager()
                if not config_manager:
                    return make_response(
                        request_id,
                        payload={},
                        session_id=self._get_session_id(),
                        success=False,
                        error="Config manager not available",
                    )

                scope = str(payload.get("scope", "merged")).strip().lower()
                config = None

                if scope in {"user", "project"}:
                    path = (
                        config_manager.get_user_config_path()
                        if scope == "user"
                        else config_manager.get_project_config_path()
                    )
                    if path.exists():
                        try:
                            with open(path, "r", encoding="utf-8") as f:
                                data = json.load(f)
                            config = GorCodeConfig.from_dict(data)
                        except (json.JSONDecodeError, OSError) as exc:
                            return make_response(
                                request_id,
                                payload={},
                                session_id=self._get_session_id(),
                                success=False,
                                error=f"Failed to read {scope} config: {exc}",
                            )
                else:
                    scope = "merged"
                    config = config_manager.load_config()

                return make_response(
                    request_id,
                    payload={
                        "config": config.to_dict() if config else {},
                        "source": scope,
                    },
                    session_id=self._get_session_id(),
                )

            if request_type == "config.status":
                config_manager = self._get_config_manager()
                if not config_manager:
                    return make_response(
                        request_id,
                        payload={},
                        session_id=self._get_session_id(),
                        success=False,
                        error="Config manager not available",
                    )

                user_path = config_manager.get_user_config_path()
                project_path = config_manager.get_project_config_path()
                custom_path = config_manager.config_path

                return make_response(
                    request_id,
                    payload={
                        "user_exists": user_path.exists(),
                        "project_exists": project_path.exists(),
                        "paths": {
                            "user": str(user_path),
                            "project": str(project_path),
                            "custom": str(custom_path) if custom_path else None,
                        },
                    },
                    session_id=self._get_session_id(),
                )

            if request_type == "config.initialize":
                config_manager = self._get_config_manager()
                project_path = str(payload.get("path") or "")
                initializer = ProjectInitializer(project_path=project_path or None)

                force = bool(payload.get("force", False))
                user_only = bool(payload.get("user_only", False))
                project_only = bool(payload.get("project_only", False))

                if user_only:
                    result = initializer.initialize_user_config(force=force)
                    payload_out = {"result": self._init_result_payload(result)}
                elif project_only:
                    result = initializer.initialize_project_config(force=force)
                    payload_out = {"result": self._init_result_payload(result)}
                else:
                    results = initializer.initialize_all(force=force)
                    payload_out = {
                        "results": {
                            "user": self._init_result_payload(results.get("user")),
                            "project": self._init_result_payload(results.get("project")),
                        }
                    }

                if config_manager:
                    config_manager._merged_config = None
                    config_manager.load_config()

                return make_response(
                    request_id,
                    payload=payload_out,
                    session_id=self._get_session_id(),
                )

            if request_type == "agent.list":
                visibility = str(payload.get("visibility", "all")).strip().lower()
                registry = getattr(self._executor, "_agent_registry", None)
                if not registry:
                    return make_response(
                        request_id,
                        payload={"agents": []},
                        session_id=self._get_session_id(),
                        success=False,
                        error="Agent registry not available",
                    )
                if visibility == "visible":
                    agents = registry.get_visible_agents()
                else:
                    agents = registry.get_all_agents()
                return make_response(
                    request_id,
                    payload={"agents": [agent.to_dict() for agent in agents]},
                    session_id=self._get_session_id(),
                )

            if request_type == "agent.get":
                name = str(payload.get("name", "")).strip().lower()
                registry = getattr(self._executor, "_agent_registry", None)
                if not registry:
                    return make_response(
                        request_id,
                        payload={},
                        session_id=self._get_session_id(),
                        success=False,
                        error="Agent registry not available",
                    )
                agent = registry.get(name)
                if not agent:
                    return make_response(
                        request_id,
                        payload={},
                        session_id=self._get_session_id(),
                        success=False,
                        error=f"Agent not found: {name}",
                    )
                return make_response(
                    request_id,
                    payload={"agent": agent.to_dict()},
                    session_id=self._get_session_id(),
                )

            if request_type == "agent.switch":
                agent = str(payload.get("name") or payload.get("agent") or "").strip().lower()
                previous_model = self._executor.state.current_model
                target_model = self._get_agent_target_model(agent)
                success = self._executor.switch_agent(agent)
                current_model = self._executor.state.current_model
                if success:
                    self._sync_task_tool()
                return make_response(
                    request_id,
                    payload={
                        "success": success,
                        "agent": self._executor.state.current_agent,
                        "model": current_model,
                        "target_model": target_model,
                        "model_changed": success and current_model != previous_model,
                        "model_switch_failed": success
                        and bool(target_model)
                        and current_model != target_model,
                    },
                    session_id=self._get_session_id(),
                    success=success,
                    error=None if success else f"Agent not found: {agent}",
                )

            if request_type == "agent.set":
                agent = str(payload.get("agent", "")).strip()
                if agent:
                    self._executor.state.current_agent = agent
                    manager = self._get_session_manager()
                    if manager:
                        manager.update_agent(agent)
                    self._sync_task_tool()
                    return make_response(
                        request_id,
                        payload={"success": True, "agent": self._executor.state.current_agent},
                        session_id=self._get_session_id(),
                    )
                return make_response(
                    request_id,
                    payload={},
                    session_id=self._get_session_id(),
                    success=False,
                    error="Agent name is required",
                )

            if request_type == "model.switch":
                model = str(payload.get("model", "")).strip().lower()
                success = self._executor.switch_model(model)
                available = []
                if self._executor._config_manager:
                    available = list(self._executor._config_manager.config.model_connections.keys())
                return make_response(
                    request_id,
                    payload={
                        "success": success,
                        "model": self._executor.state.current_model,
                        "available": available,
                    },
                    session_id=self._get_session_id(),
                    success=success,
                    error=None if success else f"Model not found: {model}",
                )

            if request_type == "session.status":
                return make_response(
                    request_id,
                    payload={
                        "agent": self._executor.state.current_agent,
                        "model": self._executor.state.current_model,
                        "message_count": len(self._executor.state.messages or []),
                        "session_id": self._get_session_id(),
                    },
                    session_id=self._get_session_id(),
                )

            if request_type == "session.new":
                session_manager = self._get_session_manager()
                agent = self._executor.state.current_agent
                model = self._executor.state.current_model
                title = str(payload.get("title", "")).strip()

                session_id = None
                if session_manager:
                    session = session_manager.create_session(
                        agent=agent,
                        model=model,
                        title=title,
                    )
                    session_id = session.session_id
                else:
                    self._executor.reset_messages()

                self._executor.state.messages = []
                self._executor.reset_token_usage()

                debug_logger = self._get_debug_logger()
                if debug_logger and debug_logger.enabled and session_id:
                    debug_logger.end_session()
                    debug_logger.start_session(agent, session_id)

                return make_response(
                    request_id,
                    payload={
                        "success": True,
                        "session_id": session_id,
                        "title": title,
                    },
                    session_id=self._get_session_id(),
                )

            if request_type == "session.load":
                return self._handle_session_load(request_id, payload)

            if request_type == "session.save":
                return self._handle_session_save(request_id)

            if request_type == "session.list":
                return self._handle_session_list(request_id, payload)

            if request_type == "session.search":
                return self._handle_session_search(request_id, payload)

            if request_type == "session.delete":
                return self._handle_session_delete(request_id, payload)

            if request_type == "session.info":
                return self._handle_session_info(request_id, payload)

            if request_type == "session.export":
                return self._handle_session_export(request_id, payload)

            if request_type == "session.import":
                return self._handle_session_import(request_id, payload)

            if request_type == "context.status":
                usage = self._executor.get_token_usage()
                usage["message_count"] = len(self._executor.state.messages or [])
                return make_response(
                    request_id,
                    payload=usage,
                    session_id=self._get_session_id(),
                )

            if request_type == "context.compact":
                force = bool(payload.get("force", False))
                force_soft = bool(payload.get("force_soft", False))
                result = self._executor.compact_context(force=force, force_soft=force_soft)
                return make_response(
                    request_id,
                    payload=result,
                    session_id=self._get_session_id(),
                    success=bool(result.get("success", False)),
                    error=None if result.get("success", False) else result.get("error", "Compaction failed"),
                )

            if request_type == "context.cache.stats":
                cache = self._executor.response_cache
                if not cache:
                    return make_response(
                        request_id,
                        payload={},
                        session_id=self._get_session_id(),
                        success=False,
                        error="Cache not initialized",
                    )
                return make_response(
                    request_id,
                    payload=cache.get_stats(),
                    session_id=self._get_session_id(),
                )

            if request_type == "context.cache.clear":
                cache = self._executor.response_cache
                if not cache:
                    return make_response(
                        request_id,
                        payload={},
                        session_id=self._get_session_id(),
                        success=False,
                        error="Cache not initialized",
                    )
                cache.clear()
                return make_response(
                    request_id,
                    payload={"success": True},
                    session_id=self._get_session_id(),
                )

            if request_type == "permission.status":
                perm_manager = get_permission_manager()
                permissions = perm_manager.get_session_permissions()
                display = {perm.value: granted for perm, granted in permissions.items()}
                return make_response(
                    request_id,
                    payload={
                        "permissions": display,
                        "sandbox": self._executor.get_sandbox_status(),
                    },
                    session_id=self._get_session_id(),
                )

            if request_type == "sandbox.status":
                return make_response(
                    request_id,
                    payload=self._executor.get_sandbox_status(),
                    session_id=self._get_session_id(),
                )

            if request_type == "hook.status":
                return make_response(
                    request_id,
                    payload=self._executor.get_hook_status(),
                    session_id=self._get_session_id(),
                )

            if request_type in {"sandbox.enable", "sandbox.disable"}:
                enabled = request_type == "sandbox.enable"
                return make_response(
                    request_id,
                    payload=self._executor.set_sandbox_enabled(enabled),
                    session_id=self._get_session_id(),
                )

            if request_type == "sandbox.reload":
                return make_response(
                    request_id,
                    payload=self._executor.reload_sandbox(),
                    session_id=self._get_session_id(),
                )

            if request_type in {"permission.grant", "permission.revoke"}:
                perm_value = str(payload.get("type", "")).strip().lower()
                try:
                    perm_type = PermissionType(perm_value)
                except ValueError:
                    return make_response(
                        request_id,
                        payload={},
                        session_id=self._get_session_id(),
                        success=False,
                        error=f"Invalid permission type: {perm_value}",
                    )
                perm_manager = get_permission_manager()
                if request_type == "permission.grant":
                    perm_manager.grant_session_permission(perm_type)
                else:
                    perm_manager.revoke_session_permission(perm_type)
                return make_response(
                    request_id,
                    payload={"success": True},
                    session_id=self._get_session_id(),
                )

            if request_type == "permission.clear":
                perm_manager = get_permission_manager()
                perm_manager.clear_session_permissions()
                return make_response(
                    request_id,
                    payload={"success": True},
                    session_id=self._get_session_id(),
                )

            if request_type in {"mcp.list", "mcp.status"}:
                status = self._get_mcp_manager().get_status()
                return make_response(
                    request_id,
                    payload={"status": status},
                    session_id=self._get_session_id(),
                )

            if request_type == "mcp.connect":
                return self._handle_mcp_connect(request_id, payload)

            if request_type == "mcp.disconnect":
                return self._handle_mcp_disconnect(request_id, payload)

            if request_type == "skills.list":
                loader = self._get_skill_loader()
                skills = []
                for name, skill in loader.get_all_skills().items():
                    skills.append({
                        "name": name,
                        "description": skill.description,
                        "enabled": skill.enabled,
                        "resource_count": len(skill.resources),
                    })
                return make_response(
                    request_id,
                    payload={"skills": skills},
                    session_id=self._get_session_id(),
                )

            if request_type == "skills.show":
                name = str(payload.get("name", "")).strip()
                loader = self._get_skill_loader()
                skill = loader.get_skill(name)
                if not skill:
                    return make_response(
                        request_id,
                        payload={},
                        session_id=self._get_session_id(),
                        success=False,
                        error=f"Skill not found: {name}",
                    )
                return make_response(
                    request_id,
                    payload={
                        "name": skill.name,
                        "description": skill.description,
                        "content": skill.content,
                        "enabled": skill.enabled,
                        "resource_count": len(skill.resources),
                    },
                    session_id=self._get_session_id(),
                )

            if request_type in {"skills.enable", "skills.disable"}:
                name = str(payload.get("name", "")).strip()
                loader = self._get_skill_loader()
                if request_type == "skills.enable":
                    success = loader.enable_skill(name)
                else:
                    success = loader.disable_skill(name)
                return make_response(
                    request_id,
                    payload={"success": success},
                    session_id=self._get_session_id(),
                    success=success,
                    error=None if success else f"Skill not found: {name}",
                )

            if request_type == "skills.reload":
                name = str(payload.get("name", "")).strip()
                loader = self._get_skill_loader()
                if name:
                    skill = loader.reload_skill(name)
                    success = skill is not None
                    return make_response(
                        request_id,
                        payload={"success": success},
                        session_id=self._get_session_id(),
                        success=success,
                        error=None if success else f"Failed to reload: {name}",
                    )
                loader.load_all_skills()
                return make_response(
                    request_id,
                    payload={"success": True},
                    session_id=self._get_session_id(),
                )

            if request_type == "debug.set":
                enabled = bool(payload.get("enabled", False))
                last_log = self._executor.set_debug_mode(enabled)
                debug_logger = self._get_debug_logger()
                status = debug_logger.get_status() if debug_logger else {}
                return make_response(
                    request_id,
                    payload={
                        "success": True,
                        "enabled": enabled,
                        "debug_dir": status.get("debug_dir"),
                        "current_log": status.get("current_log"),
                        "log_count": status.get("log_count"),
                        "last_log": last_log,
                    },
                    session_id=self._get_session_id(),
                )

            if request_type == "debug.status":
                debug_logger = self._get_debug_logger()
                status = debug_logger.get_status() if debug_logger else {}
                return make_response(
                    request_id,
                    payload=status,
                    session_id=self._get_session_id(),
                )

            if request_type == "debug.list":
                debug_logger = self._get_debug_logger()
                if not debug_logger:
                    return make_response(
                        request_id,
                        payload={"logs": []},
                        session_id=self._get_session_id(),
                        success=False,
                        error="Debug logger not available",
                    )
                logs = debug_logger.list_logs()
                return make_response(
                    request_id,
                    payload={"logs": logs},
                    session_id=self._get_session_id(),
                )

            if request_type == "debug.clean":
                debug_logger = self._get_debug_logger()
                if not debug_logger:
                    return make_response(
                        request_id,
                        payload={"removed": 0},
                        session_id=self._get_session_id(),
                        success=False,
                        error="Debug logger not available",
                    )
                days = int(payload.get("days", 7) or 7)
                removed = debug_logger.cleanup_old_logs(days=days)
                return make_response(
                    request_id,
                    payload={"removed": removed},
                    session_id=self._get_session_id(),
                )

            if request_type == "tools.init":
                registry = self._executor.tool_registry
                count = len(registry.get_all_tools()) if registry else 0
                return make_response(
                    request_id,
                    payload={
                        "success": registry is not None,
                        "tool_count": count,
                    },
                    session_id=self._get_session_id(),
                    success=registry is not None,
                    error=None if registry is not None else "Tool registry not available",
                )

            return make_response(
                request_id,
                payload={},
                session_id=self._get_session_id(),
                success=False,
                error=f"Unknown request type: {request_type}",
            )

        except Exception as e:
            return make_response(
                request_id,
                payload={},
                session_id=self._get_session_id(),
                success=False,
                error=str(e),
            )

    def _get_mcp_manager(self) -> MCPManager:
        if self._mcp_manager:
            return self._mcp_manager
        config = self._executor._config_manager.config if self._executor._config_manager else None
        encoding = getattr(config, "default_encoding", "utf-8") if config else "utf-8"
        manager = MCPManager(encoding=encoding)
        if config and config.mcp_servers:
            manager.load_from_config(config.mcp_servers)
        self._mcp_manager = manager
        return manager

    def _handle_mcp_connect(self, request_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        manager = self._get_mcp_manager()
        results: Dict[str, bool] = {}
        errors: Dict[str, str] = {}

        if payload.get("all"):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                results = loop.run_until_complete(manager.connect_all())
            finally:
                loop.close()
        else:
            name = str(payload.get("name", "")).strip()
            if not name:
                return make_response(
                    request_id,
                    payload={},
                    session_id=self._get_session_id(),
                    success=False,
                    error="Specify server name or set all=true",
                )
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                success = loop.run_until_complete(manager.connect(name))
                results[name] = success
            finally:
                loop.close()

        if any(results.values()):
            registered = self._register_mcp_tools(manager)
        else:
            registered = 0

        for name, success in results.items():
            if not success:
                connection = manager.get_connection(name)
                if connection and connection.error_message:
                    errors[name] = connection.error_message

        return make_response(
            request_id,
            payload={
                "results": results,
                "errors": errors,
                "registered": registered,
            },
            session_id=self._get_session_id(),
        )

    def _handle_mcp_disconnect(self, request_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        manager = self._get_mcp_manager()
        results: Dict[str, bool] = {}

        if payload.get("all"):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                names = loop.run_until_complete(manager.disconnect_all())
                for name in names:
                    results[name] = True
            finally:
                loop.close()
            unregistered = self._unregister_mcp_tools(manager)
        else:
            name = str(payload.get("name", "")).strip()
            if not name:
                return make_response(
                    request_id,
                    payload={},
                    session_id=self._get_session_id(),
                    success=False,
                    error="Specify server name or set all=true",
                )
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                success = loop.run_until_complete(manager.disconnect(name))
                results[name] = success
            finally:
                loop.close()
            unregistered = self._unregister_mcp_tools(manager, name)

        return make_response(
            request_id,
            payload={
                "results": results,
                "unregistered": unregistered,
            },
            session_id=self._get_session_id(),
        )

    def _register_mcp_tools(self, manager: MCPManager) -> int:
        if not self._executor.tool_registry:
            return 0
        registered_count = 0
        for tool in create_mcp_tools(manager):
            if self._executor.tool_registry.get(tool.name):
                self._executor.tool_registry.unregister(tool.name)
            self._executor.tool_registry.register(tool)
            registered_count += 1
        return registered_count

    def _unregister_mcp_tools(self, manager: MCPManager, server_name: Optional[str] = None) -> int:
        if not self._executor.tool_registry:
            return 0
        unregistered = 0
        if server_name:
            prefix = f"mcp_{server_name}_"
            names = [name for name in self._executor.tool_registry.tools.keys() if name.startswith(prefix)]
            for name in names:
                if self._executor.tool_registry.unregister(name):
                    unregistered += 1
            return unregistered

        if self._executor.tool_registry.get("mcp_tool"):
            if self._executor.tool_registry.unregister("mcp_tool"):
                unregistered += 1
        names = [name for name in self._executor.tool_registry.tools.keys() if name.startswith("mcp_")]
        for name in names:
            if self._executor.tool_registry.unregister(name):
                unregistered += 1
        return unregistered

    def _get_skill_loader(self) -> SkillLoader:
        if self._skill_loader:
            return self._skill_loader
        loader = getattr(self._executor, "_skill_loader", None)
        if loader:
            self._skill_loader = loader
            return loader
        loader = SkillLoader()
        if self._executor._config_manager:
            project_path = str(self._executor._config_manager.project_path)
            loader.initialize_default_paths(project_path)
            user_skills_dir = self._executor._config_manager.get_user_config_dir() / "skills"
            if user_skills_dir.exists():
                loader.add_search_path(str(user_skills_dir))
        loader.load_all_skills()
        self._executor._skill_loader = loader
        self._executor._skill_injector = SkillInjector(loader)
        self._skill_loader = loader
        return loader
