"""process/http transports for the gorcode-hook-v1 protocol."""

from __future__ import annotations

import json
import shlex
import subprocess
import uuid
from typing import Any, Mapping

import httpx

from .context import HookContext
from .errors import HookProtocolError, HookTimeoutError

PROTOCOL = "gorcode-hook-v1"


def call_process_hook(
    *,
    command: str,
    timeout_seconds: int,
    hook_id: str,
    params: Mapping[str, Any],
    context: HookContext,
) -> dict[str, Any]:
    request = build_protocol_request(hook_id=hook_id, params=params, context=context)
    args = _split_command(command)
    try:
        completed = subprocess.run(
            args,
            input=json.dumps(request, ensure_ascii=False) + "\n",
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise HookTimeoutError(_timeout_message(hook_id, context.event, timeout_seconds, "process")) from exc
    if completed.returncode != 0:
        raise HookProtocolError(_process_error(hook_id, context.event, completed.stderr))
    response = _last_stdout_json(completed.stdout, hook_id, context.event)
    return validate_protocol_response(response, request["request_id"], hook_id, context.event)


def call_http_hook(
    *,
    url: str,
    timeout_seconds: int,
    hook_id: str,
    params: Mapping[str, Any],
    context: HookContext,
) -> dict[str, Any]:
    request = build_protocol_request(hook_id=hook_id, params=params, context=context)
    try:
        response = httpx.post(url, json=request, timeout=timeout_seconds)
    except httpx.TimeoutException as exc:
        raise HookTimeoutError(_timeout_message(hook_id, context.event, timeout_seconds, "http")) from exc
    except httpx.HTTPError as exc:
        raise HookProtocolError(f"http hook '{hook_id}' failed for '{context.event}': {exc}") from exc
    if response.status_code >= 400:
        raise HookProtocolError(
            f"http hook '{hook_id}' failed for '{context.event}' with status {response.status_code}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise HookProtocolError(f"http hook '{hook_id}' returned non-JSON response") from exc
    return validate_protocol_response(payload, request["request_id"], hook_id, context.event)


def build_protocol_request(
    *,
    hook_id: str,
    params: Mapping[str, Any],
    context: HookContext,
) -> dict[str, Any]:
    data = context.to_protocol_dict()
    data.update(
        {
            "protocol": PROTOCOL,
            "request_id": f"hook-{uuid.uuid4().hex}",
            "hook_id": hook_id,
            "params": dict(params or {}),
        }
    )
    return data


def validate_protocol_response(
    response: Any,
    request_id: str,
    hook_id: str,
    event: str,
) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise HookProtocolError(f"hook '{hook_id}' returned non-object response for '{event}'")
    if response.get("request_id") != request_id:
        raise HookProtocolError(f"hook '{hook_id}' response request_id mismatch for '{event}'")
    payload = dict(response)
    payload.pop("request_id", None)
    payload.pop("protocol", None)
    return payload


def _split_command(command: str) -> list[str]:
    args = shlex.split(command)
    if not args:
        raise HookProtocolError("process hook command must not be empty")
    return args


def _last_stdout_json(stdout: str, hook_id: str, event: str) -> dict[str, Any]:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise HookProtocolError(f"process hook '{hook_id}' produced no stdout JSON for '{event}'")
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise HookProtocolError(f"process hook '{hook_id}' returned invalid JSON for '{event}'") from exc
    if not isinstance(payload, dict):
        raise HookProtocolError(f"process hook '{hook_id}' JSON response must be object")
    return payload


def _timeout_message(hook_id: str, event: str, timeout: int, transport: str) -> str:
    return (
        f"{transport} hook '{hook_id}' timed out during '{event}' "
        f"after {timeout}s"
    )


def _process_error(hook_id: str, event: str, stderr: str) -> str:
    detail = stderr.strip() if stderr else "no stderr"
    return f"process hook '{hook_id}' failed for '{event}': {detail}"
