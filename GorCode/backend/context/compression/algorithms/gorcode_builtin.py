"""GorCode builtin compression algorithm (Compact V2).

Implements a Codex-style single-threshold compression strategy:
build a handoff summary via LLM, then replace the conversation with
``[system_prompt] + [recent user messages] + [protected tool calls] + [summary]``.
"""

from __future__ import annotations

import copy
from typing import Any, Mapping

from ..contracts import CompressionError, CompressionRequest, CompressionResult
from ..token_counter import default_count_tokens

RECENT_MESSAGES_MAX_TOKENS = 20000

SUMMARY_PREFIX = (
    "Another language model started to solve this problem and produced a summary "
    "of its thinking process. You also have access to the state of the tools that "
    "were used by that language model. Use this to build on the work that has "
    "already been done and avoid duplicating work. Here is the summary produced by "
    "the other language model, use this information in this summary to assist with "
    "your own analysis:\n"
)

COMPACTION_INSTRUCTION = (
    "You are performing a CONTEXT CHECKPOINT COMPACTION. Create a handoff summary "
    "for another LLM that will resume the task.\n\n"
    "Include:\n"
    "- Current progress and key decisions made\n"
    "- Important context, constraints, or user preferences\n"
    "- What remains to be done (clear next steps)\n"
    "- Any critical data, examples, or references needed to continue\n\n"
    "Be concise, structured, and focused on helping the next LLM seamlessly "
    "continue the work."
)

DEFAULT_PROTECTED_TOOLS = ["skill", "Skill"]


class GorCodeBuiltinCompressionAlgorithm:
    """Codex-style single-threshold compression algorithm."""

    def __init__(
        self,
        *,
        options: Mapping[str, Any],
        config_manager=None,
        model_manager=None,
        event_bus=None,
        model_connector=None,
    ):
        self.options = dict(options or {})
        self._config_manager = config_manager
        self._model_manager = model_manager
        self._event_bus = event_bus
        self._model_connector = model_connector
        self._model_connectors: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Model connector resolution
    # ------------------------------------------------------------------

    def _get_model_connector(self):
        """Resolve the model connector for compaction.

        Uses ``config_manager.get_agent_model("compaction")`` when available,
        caching the resulting connector. Falls back to ``model_manager.current()``.
        """
        cache_key = "compaction"
        if cache_key in self._model_connectors:
            return self._model_connectors[cache_key]

        if self._config_manager:
            model_conn = self._config_manager.get_agent_model("compaction")
            if model_conn:
                from ....core.model_connector import ModelConnector

                connector = ModelConnector(model_conn, self._event_bus)
                if connector.connect():
                    self._model_connectors[cache_key] = connector
                    return connector

        if self._model_manager:
            return self._model_manager.current()

        return self._model_connector

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compress(self, request: CompressionRequest) -> CompressionResult:
        messages = list(request.messages)
        if not messages:
            raise CompressionError("Cannot compress an empty message list")

        compaction_input = self._build_compaction_input(messages)
        connector = self._get_model_connector()
        if connector is None:
            raise CompressionError("No model connector available for compression")

        tools = request.metadata.get("tools") or None
        summary_text = self._generate_summary(connector, compaction_input, tools)

        user_messages = self._extract_recent_user_messages(messages, request)
        protected_messages = self._extract_protected_tools(messages)

        result_messages = self._assemble_result(
            messages, user_messages, protected_messages, summary_text,
        )
        return CompressionResult(
            messages=result_messages,
            metadata={
                "summary": summary_text,
                "protected_tool_count": len(protected_messages),
                "user_message_count": len(user_messages),
            },
        )

    # ------------------------------------------------------------------
    # Step 1 - build compaction input
    # ------------------------------------------------------------------

    def _build_compaction_input(self, messages: list[dict]) -> list[dict]:
        compaction_input: list[dict] = []
        for msg in messages:
            if msg.get("_synthetic"):
                continue
            compaction_input.append(copy.deepcopy(msg))
        compaction_input.append({"role": "user", "content": COMPACTION_INSTRUCTION})
        return compaction_input

    # ------------------------------------------------------------------
    # Step 2 - call LLM and collect summary
    # ------------------------------------------------------------------

    def _generate_summary(self, connector, compaction_input: list[dict], tools) -> str:
        summary_text = ""
        for response in connector.chat(compaction_input, tools=tools):
            self._validate_response(response)
            summary_text += getattr(response, "content", "") or ""
        summary_text = summary_text.strip()
        if not summary_text:
            raise CompressionError("Summary generation returned empty content")
        return summary_text

    def _validate_response(self, response) -> None:
        if response is None:
            return
        if getattr(response, "is_error", False):
            msg = getattr(response, "error_message", "") or "unknown model error"
            raise CompressionError(f"Summary generation model error: {msg}")
        if getattr(response, "tool_calls", None):
            raise CompressionError("Summary generation attempted tool calls")

    # ------------------------------------------------------------------
    # Step 3 - extract recent user messages (new -> old, <= 20000 tokens)
    # ------------------------------------------------------------------

    def _extract_recent_user_messages(
        self,
        messages: list[dict],
        request: CompressionRequest,
    ) -> list[dict]:
        count_tokens = request.count_tokens or default_count_tokens
        selected: list[dict] = []
        for msg in reversed(messages):
            if msg.get("role") != "user" or msg.get("_synthetic"):
                continue
            selected.insert(0, copy.deepcopy(msg))
            if count_tokens(selected) > RECENT_MESSAGES_MAX_TOKENS:
                selected.pop(0)
                break
        return selected

    # ------------------------------------------------------------------
    # Step 4 - extract protected tool call chains (entire history)
    # ------------------------------------------------------------------

    def _extract_protected_tools(self, messages: list[dict]) -> list[dict]:
        protected_tools = list(
            self.options.get("protected_tools", DEFAULT_PROTECTED_TOOLS)
        )
        tool_call_map = self._build_tool_call_map(messages)
        protected_ids = self._collect_protected_ids(messages, tool_call_map, protected_tools)
        return self._collect_protected_chains(messages, protected_ids)

    def _build_tool_call_map(self, messages: list[dict]) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for msg in messages:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    tc_id = tc.get("id", "")
                    tc_name = tc.get("function", {}).get("name", "")
                    if tc_id:
                        mapping[tc_id] = tc_name
        return mapping

    def _collect_protected_ids(
        self,
        messages: list[dict],
        tool_call_map: dict[str, str],
        protected_tools: list[str],
    ) -> set[str]:
        ids: set[str] = set()
        for msg in messages:
            if msg.get("role") != "tool":
                continue
            tool_call_id = msg.get("tool_call_id", "")
            tool_name = tool_call_map.get(tool_call_id, "")
            if tool_name in protected_tools:
                ids.add(tool_call_id)
        return ids

    def _collect_protected_chains(
        self,
        messages: list[dict],
        protected_ids: set[str],
    ) -> list[dict]:
        chains: list[dict] = []
        for msg in messages:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                protected_calls = [
                    tc for tc in msg["tool_calls"]
                    if tc.get("id") in protected_ids
                ]
                if protected_calls:
                    assistant_copy = {k: v for k, v in msg.items() if not k.startswith("_")}
                    assistant_copy["tool_calls"] = protected_calls
                    chains.append(assistant_copy)
            elif msg.get("role") == "tool" and msg.get("tool_call_id") in protected_ids:
                tool_copy = {k: v for k, v in msg.items() if not k.startswith("_")}
                chains.append(tool_copy)
        return chains

    # ------------------------------------------------------------------
    # Step 5 - assemble final message list
    # ------------------------------------------------------------------

    def _assemble_result(
        self,
        messages: list[dict],
        user_messages: list[dict],
        protected_messages: list[dict],
        summary_text: str,
    ) -> list[dict]:
        result: list[dict] = []
        result.append(copy.deepcopy(messages[0]))
        result.extend(user_messages)
        result.extend(protected_messages)
        result.append({
            "role": "user",
            "content": SUMMARY_PREFIX + summary_text,
            "_synthetic": True,
            "_compaction_summary": True,
        })
        return result
