"""
Subagent tool executor.

This adapter lets model-specific GorAI_LLMClient chatToNextLoop
implementations drive subagent tool calls while GorCode keeps its
permission and agent tool policy checks.
"""

from typing import Any, Callable, Dict, Optional

from ...sandbox import protocol_error_result
from ..core_tool_support.base import ToolResult
from .permission_exec import execute_with_permissions


class SubagentToolExecutor:
    """Tool executor used by GorAI_LLMClient subagent loops."""

    def __init__(
        self,
        *,
        agent_type: str,
        tool_registry: Any,
        is_tool_allowed: Callable[[str, str], bool],
        permission_manager: Any = None,
        permission_requester: Any = None,
        sandbox_manager: Any = None,
        access_policy: Any = None,
        max_tool_calls: Optional[int] = None,
        hook_runtime: Optional[Any] = None,
        hook_base: Any = None,
    ) -> None:
        self.agent_type = agent_type
        self.tool_registry = tool_registry
        self.is_tool_allowed = is_tool_allowed
        self.permission_manager = permission_manager
        self.permission_requester = permission_requester
        self.sandbox_manager = sandbox_manager
        self.access_policy = access_policy
        self.max_tool_calls = max_tool_calls
        self.hook_runtime = hook_runtime
        self.hook_base = hook_base
        self.tool_calls = 0
        self.limit_reached = False
        self._current_tool_context: Dict[str, Any] = {}

    def set_current_tool_context(self, context: Optional[Dict[str, Any]]) -> None:
        self._current_tool_context = dict(context or {})

    def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Execute one tool call for a subagent."""
        limit_error = self._check_tool_limit()
        if limit_error:
            return limit_error

        policy_error = self._check_tool_policy(tool_name)
        if policy_error:
            return policy_error

        tool = self.tool_registry.get(tool_name) if self.tool_registry else None
        if tool is None:
            return f"Error: Tool '{tool_name}' not found"

        before = self._run_before_tool_hook(tool_name, arguments)
        arguments = before.arguments
        if before.action == "deny":
            result = ToolResult(False, "", before.reason or "Tool execution denied by hook")
            return self._format_result(self._run_after_tool_hook(tool_name, arguments, result))
        if before.action == "handled" and before.tool_result is not None:
            result = self._run_after_tool_hook(
                tool_name,
                arguments,
                before.tool_result,
                handled_by_hook=True,
            )
            return self._format_result(result)

        pre_result = self._evaluate_pre_execution(tool_name, arguments)
        if pre_result is not None:
            result = self._run_after_tool_hook(
                tool_name,
                arguments,
                pre_result,
                handled_by_sandbox=True,
            )
            return self._format_result(result)

        result = self._execute_registered_tool(tool_name, arguments, tool)
        result = self._run_after_tool_hook(tool_name, arguments, result)
        return self._format_result(result)

    def _run_before_tool_hook(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ):
        if not self.hook_runtime or not self.hook_base:
            from ...hooks.runtime import ToolBeforeHookResult

            return ToolBeforeHookResult(arguments=dict(arguments))
        try:
            return self.hook_runtime.before_tool_execute(
                tool_name,
                arguments,
                "",
                self.hook_base,
            )
        except Exception as exc:
            self.hook_runtime.notify_error(exc, self.hook_base, "tool.before_execute")
            raise

    def _run_after_tool_hook(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        result: ToolResult,
        *,
        handled_by_hook: bool = False,
        handled_by_sandbox: bool = False,
    ) -> ToolResult:
        if not self.hook_runtime or not self.hook_base:
            return result
        try:
            return self.hook_runtime.after_tool_execute(
                tool_name,
                arguments,
                result,
                self.hook_base,
                handled_by_hook=handled_by_hook,
                handled_by_sandbox=handled_by_sandbox,
            )
        except Exception as exc:
            self.hook_runtime.notify_error(exc, self.hook_base, "tool.after_execute")
            raise

    def _check_tool_limit(self) -> Optional[str]:
        if self.max_tool_calls is None:
            return None
        if self.tool_calls < self.max_tool_calls:
            return None
        self.limit_reached = True
        return f"Error: Subagent reached max tool calls ({self.max_tool_calls})"

    def _check_tool_policy(self, tool_name: str) -> Optional[str]:
        if self.is_tool_allowed(self.agent_type, tool_name):
            return None
        return f"Tool '{tool_name}' is not allowed for agent type '{self.agent_type}'"

    def _evaluate_pre_execution(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Optional[ToolResult]:
        if not self.sandbox_manager:
            return None
        try:
            return self.sandbox_manager.evaluate_pre_execution(tool_name, arguments)
        except Exception as exc:
            return protocol_error_result(exc)

    def _execute_registered_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        tool: Any,
    ) -> ToolResult:
        result = self.tool_registry.execute(
            tool_name,
            agent_name=self.agent_type,
            access_policy=self.access_policy,
            **arguments,
        )
        self.tool_calls += 1
        result, _ = execute_with_permissions(
            tool_name,
            tool,
            result,
            self.permission_manager,
            self.permission_requester,
            sandbox_manager=self.sandbox_manager,
            arguments=arguments,
            request_context=self._permission_request_context(),
        )
        return result

    def _permission_request_context(self) -> Dict[str, Any]:
        context = dict(self._current_tool_context)
        if self.hook_base:
            context.setdefault("session_id", self.hook_base.session_id)
            context.setdefault("agent_run_id", self.hook_base.agent_run_id)
            context.setdefault("agent_name", self.hook_base.agent_name)
        else:
            context.setdefault("agent_name", self.agent_type)
        return context

    def _format_result(self, result: ToolResult) -> str:
        if result.success:
            return result.output if result.output else "Command executed successfully"
        if result.error:
            return f"Error: {result.error}"
        if result.output:
            return result.output
        return "Error: Tool execution failed"
