"""Scoped permission broker for gateway protocol waits and event buffering."""

from dataclasses import dataclass, field, replace
from enum import Enum
from threading import Event, Lock
from typing import Any, Callable, Dict, List, Optional, Tuple
import uuid

from GorCode.backend.permission import PermissionResponse
from GorCode.backend.permission.contracts import PermissionRequestInput, PermissionRequestResult


DEFAULT_FRONTEND_CHANNEL_ID = "cli"
DEFAULT_PERMISSION_EVENT_BUFFER_LIMIT = 100


class BrokerEventAction(Enum):
    EMIT_NOW = "emit_now"
    BUFFERED = "buffered"
    QUEUED_PERMISSION = "queued_permission"
    FLUSH_READY = "flush_ready"
    ERROR = "error"


@dataclass(frozen=True)
class PermissionScope:
    frontend_channel_id: str = DEFAULT_FRONTEND_CHANNEL_ID
    session_id: Optional[str] = None
    stream_id: Optional[str] = None

    def key(self) -> str:
        return self.frontend_channel_id or DEFAULT_FRONTEND_CHANNEL_ID


@dataclass(frozen=True)
class BrokerEventDecision:
    action: BrokerEventAction
    events: Tuple[Dict[str, Any], ...] = ()
    error: Optional[str] = None


@dataclass
class _PendingPermission:
    request: PermissionRequestInput
    ready: Event = field(default_factory=Event)
    result: Optional[PermissionRequestResult] = None
    error: Optional[str] = None

    def wait(self) -> PermissionRequestResult:
        self.ready.wait()
        if self.error:
            raise RuntimeError(self.error)
        if self.result is None:
            raise RuntimeError("Permission request completed without a result")
        return self.result


@dataclass
class _CompletedPermission:
    request_id: str
    tool_call_id: str


@dataclass
class _ScopeState:
    lock: Lock = field(default_factory=Lock)
    active_request_id: Optional[str] = None
    permission_queue: List[Dict[str, Any]] = field(default_factory=list)
    event_buffer: List[Dict[str, Any]] = field(default_factory=list)
    completed: List[_CompletedPermission] = field(default_factory=list)


@dataclass(frozen=True)
class PermissionRequestHandle:
    request_id: str
    payload: Dict[str, Any]
    pending: _PendingPermission

    def wait(self) -> PermissionRequestResult:
        return self.pending.wait()


class PermissionBroker:
    """Thread-safe broker scoped by frontend channel."""

    def __init__(self, buffer_limit: int = DEFAULT_PERMISSION_EVENT_BUFFER_LIMIT):
        self._buffer_limit = buffer_limit
        self._index_lock = Lock()
        self._request_scopes: Dict[str, str] = {}
        self._pending: Dict[str, _PendingPermission] = {}
        self._scope_states: Dict[str, _ScopeState] = {}

    def create_request(self, request: PermissionRequestInput) -> PermissionRequestHandle:
        request_id = request.request_id or f"perm_{uuid.uuid4().hex}"
        scoped = replace(request, request_id=request_id)
        pending = _PendingPermission(scoped)
        scope = _scope_from_request(scoped)
        state = self._state_for(scope)
        with self._index_lock:
            self._request_scopes[request_id] = scope.key()
            self._pending[request_id] = pending
        with state.lock:
            if state.active_request_id is None:
                state.active_request_id = request_id
        return PermissionRequestHandle(request_id, _payload_from_request(scoped), pending)

    def respond(
        self,
        request_id: str,
        response: Any,
        reason: Optional[str] = None,
    ) -> PermissionRequestResult:
        response_value = _parse_response(response)
        pending, state = self._lookup_active(request_id)
        result = PermissionRequestResult(response=response_value, reason=reason)
        with state.lock:
            state.active_request_id = None
            state.completed.append(
                _CompletedPermission(request_id, pending.request.tool_call_id)
            )
        with self._index_lock:
            self._request_scopes.pop(request_id, None)
            self._pending.pop(request_id, None)
        pending.result = result
        pending.ready.set()
        return result

    def classify_event(
        self,
        event: Dict[str, Any],
        scope: PermissionScope,
    ) -> BrokerEventDecision:
        event_type = str(event.get("type", ""))
        if event_type == "event.permission.request":
            return self._classify_permission_event(event, scope)
        if not _is_buffered_event_type(event_type):
            return BrokerEventDecision(BrokerEventAction.EMIT_NOW, (event,))
        state = self._state_for(scope)
        with state.lock:
            if state.active_request_id is None and not state.completed:
                return BrokerEventDecision(BrokerEventAction.EMIT_NOW, (event,))
            if len(state.event_buffer) >= self._buffer_limit:
                return BrokerEventDecision(BrokerEventAction.ERROR, error="Permission event buffer overflow")
            state.event_buffer.append(event)
            return BrokerEventDecision(BrokerEventAction.BUFFERED)

    def pop_ready_events(self, scope: PermissionScope) -> BrokerEventDecision:
        state = self._state_for(scope)
        with state.lock:
            if not state.completed:
                return BrokerEventDecision(BrokerEventAction.EMIT_NOW)
            completed = state.completed.pop(0)
            buffered = list(state.event_buffer)
            state.event_buffer.clear()
            next_permission = _pop_next_permission(state)
        events = _prioritize_related(buffered, completed.tool_call_id)
        if next_permission:
            events.append(next_permission)
        return BrokerEventDecision(BrokerEventAction.FLUSH_READY, tuple(events))

    def has_active_modal(self, scope: PermissionScope) -> bool:
        state = self._state_for(scope)
        with state.lock:
            return state.active_request_id is not None

    def _classify_permission_event(
        self,
        event: Dict[str, Any],
        scope: PermissionScope,
    ) -> BrokerEventDecision:
        request_id = str((event.get("payload") or {}).get("request_id", ""))
        if not request_id or not self._is_pending_request(request_id):
            return BrokerEventDecision(
                BrokerEventAction.ERROR,
                error=f"Unknown permission request event: {request_id}",
            )
        state = self._state_for(scope)
        with state.lock:
            if state.active_request_id in (None, request_id):
                state.active_request_id = request_id
                return BrokerEventDecision(BrokerEventAction.EMIT_NOW, (event,))
            state.permission_queue.append(event)
            return BrokerEventDecision(BrokerEventAction.QUEUED_PERMISSION)

    def _is_pending_request(self, request_id: str) -> bool:
        with self._index_lock:
            return request_id in self._pending

    def _lookup_active(self, request_id: str) -> Tuple[_PendingPermission, _ScopeState]:
        with self._index_lock:
            scope_key = self._request_scopes.get(request_id)
            pending = self._pending.get(request_id)
        if pending is None or scope_key is None:
            raise KeyError(f"Unknown permission request: {request_id}")
        state = self._state_for_key(scope_key)
        with state.lock:
            if state.active_request_id != request_id:
                raise RuntimeError(f"Permission request is not active: {request_id}")
        return pending, state

    def _state_for(self, scope: PermissionScope) -> _ScopeState:
        return self._state_for_key(scope.key())

    def _state_for_key(self, scope_key: str) -> _ScopeState:
        with self._index_lock:
            state = self._scope_states.get(scope_key)
            if state is None:
                state = _ScopeState()
                self._scope_states[scope_key] = state
            return state


class BrokerPermissionRequester:
    """PermissionRequester adapter that publishes protocol requests to the event stream."""

    def __init__(
        self,
        broker: PermissionBroker,
        publish_request: Callable[[Dict[str, Any]], None],
    ):
        self._broker = broker
        self._publish_request = publish_request

    def request_permission(
        self,
        request: PermissionRequestInput,
    ) -> PermissionRequestResult:
        handle = self._broker.create_request(request)
        self._publish_request(handle.payload)
        return handle.wait()


def _scope_from_request(request: PermissionRequestInput) -> PermissionScope:
    return PermissionScope(
        frontend_channel_id=request.frontend_channel_id,
        session_id=request.session_id,
        stream_id=request.stream_id,
    )


def _payload_from_request(request: PermissionRequestInput) -> Dict[str, Any]:
    return {
        "request_id": request.request_id,
        "tool_call_id": request.tool_call_id,
        "tool_name": request.tool_name,
        "permission_type": request.permission_type.value,
        "metadata": dict(request.metadata or {}),
        "session_id": request.session_id,
        "stream_id": request.stream_id,
        "frontend_channel_id": request.frontend_channel_id,
        "agent_name": request.agent_name,
        "agent_run_id": request.agent_run_id,
    }


def _parse_response(response: Any) -> PermissionResponse:
    if isinstance(response, PermissionResponse):
        return response
    try:
        return PermissionResponse(str(response).strip().lower())
    except ValueError as exc:
        raise ValueError(f"Invalid permission response: {response}") from exc


def _is_buffered_event_type(event_type: str) -> bool:
    return event_type in {
        "event.tool.start",
        "event.tool.result",
        "event.model.answer",
        "event.ui.message",
        "event.agent.subagent.start",
        "event.agent.subagent.end",
    }


def _pop_next_permission(state: _ScopeState) -> Optional[Dict[str, Any]]:
    if not state.permission_queue:
        return None
    event = state.permission_queue.pop(0)
    payload = event.get("payload") or {}
    state.active_request_id = str(payload.get("request_id", ""))
    return event


def _prioritize_related(
    events: List[Dict[str, Any]],
    tool_call_id: str,
) -> List[Dict[str, Any]]:
    if not tool_call_id:
        return events
    related = [event for event in events if _event_tool_call_id(event) == tool_call_id]
    unrelated = [event for event in events if _event_tool_call_id(event) != tool_call_id]
    return related + unrelated


def _event_tool_call_id(event: Dict[str, Any]) -> str:
    payload = event.get("payload") or {}
    return str(payload.get("tool_call_id", ""))
