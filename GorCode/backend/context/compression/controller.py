"""Compression controller for hooks and manual compaction."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from GorAI_LLMClient import HookResult

from .config import CompressionSettings
from .contracts import (
    CompressionAlgorithm,
    CompressionError,
    CompressionResult,
    CompressionRunResult,
)
from .token_counter import default_count_tokens

HOOK_NAME = "gorcode_compression"


def validate_system_message_position(messages: list[dict]) -> None:
    """Ensure system messages only appear at index 0."""
    for index, message in enumerate(messages):
        if message.get("role") != "system":
            continue
        if index != 0:
            raise CompressionError("system message is only allowed at position 0")


class CompressionController:
    """Owns compression threshold checks, algorithm calls, and hook wiring."""

    def __init__(
        self,
        *,
        settings: CompressionSettings,
        algorithm: CompressionAlgorithm,
        max_context_length: int,
        count_tokens=default_count_tokens,
    ):
        self.settings = settings
        self.algorithm = algorithm
        self.max_context_length = int(max_context_length)
        self.count_tokens = count_tokens

    @property
    def trigger_tokens(self) -> int:
        return int(self.max_context_length * self.settings.trigger.threshold_ratio)

    def should_compress(self, messages: list[dict]) -> bool:
        return self.count_tokens(messages) >= self.trigger_tokens

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.settings.enabled,
            "algorithm": self.settings.algorithm,
            "trigger_event": self.settings.trigger.event,
            "threshold_ratio": self.settings.trigger.threshold_ratio,
            "trigger_tokens": self.trigger_tokens,
        }

    def attach_to_model(self, connector) -> None:
        if not self.settings.enabled:
            return
        connector.remove_hook(
            self.settings.trigger.event,
            HOOK_NAME,
        )
        connector.add_hook(
            self.settings.trigger.event,
            self.handle_before_model_request,
            priority=0,
            name=HOOK_NAME,
        )

    def handle_before_model_request(self, context):
        messages = [copy.deepcopy(message) for message in context.messages]
        if not self.should_compress(messages):
            return None
        run = self._compress_messages(
            messages,
            force=False,
            source="before_model_request",
            metadata={"hook_context": self._hook_metadata(context)},
        )
        return HookResult(messages=run.messages, metadata=self._hook_result_metadata(run))

    def compress_now(
        self,
        messages: list[dict],
        *,
        force: bool = True,
        source: str = "manual",
        metadata: Mapping[str, Any] | None = None,
    ) -> CompressionRunResult:
        copied = [copy.deepcopy(message) for message in messages]
        return self._compress_messages(
            copied,
            force=force,
            source=source,
            metadata=dict(metadata or {}),
        )

    def _compress_messages(
        self,
        messages: list[dict],
        *,
        force: bool,
        source: str,
        metadata: Mapping[str, Any],
    ) -> CompressionRunResult:
        original_tokens = self.count_tokens(messages)
        if not force and original_tokens < self.trigger_tokens:
            return self._unchanged_run(messages, original_tokens)
        result = self._call_algorithm(messages, original_tokens, source, metadata)
        restored = self._restore_and_validate(messages, result)
        compacted_tokens = self.count_tokens(restored)
        self._validate_token_reduction(compacted_tokens)
        return CompressionRunResult(
            messages=restored,
            algorithm=self.settings.algorithm,
            original_tokens=original_tokens,
            compacted_tokens=compacted_tokens,
            trigger_tokens=self.trigger_tokens,
            metadata=dict(result.metadata),
        )

    def _call_algorithm(
        self,
        messages: list[dict],
        original_tokens: int,
        source: str,
        metadata: Mapping[str, Any],
    ) -> CompressionResult:
        request = self._build_request(messages, original_tokens, source, metadata)
        result = self.algorithm.compress(request)
        self._validate_result(result)
        return result

    def _build_request(
        self,
        messages: list[dict],
        original_tokens: int,
        source: str,
        metadata: Mapping[str, Any],
    ):
        from .contracts import CompressionRequest

        tools = self._extract_tools(metadata)
        request_metadata = {
            "source": source,
            "current_tokens": original_tokens,
            "trigger_tokens": self.trigger_tokens,
            "algorithm_id": self.settings.algorithm,
            "options": getattr(self.algorithm, "options", {}),
            "tools": tools,
            **dict(metadata),
        }
        return CompressionRequest(
            messages=tuple(messages),
            context_limit=self.max_context_length,
            threshold_ratio=self.settings.trigger.threshold_ratio,
            count_tokens=self.count_tokens,
            metadata=request_metadata,
        )

    @staticmethod
    def _extract_tools(metadata: Mapping[str, Any]) -> list[dict]:
        hook_ctx = metadata.get("hook_context")
        if isinstance(hook_ctx, Mapping):
            return list(hook_ctx.get("tools") or [])
        return []

    def _restore_and_validate(
        self,
        original_messages: list[dict],
        result: CompressionResult,
    ) -> list[dict]:
        validate_system_message_position(result.messages)
        return result.messages

    def _validate_result(self, result) -> None:
        if not isinstance(result, CompressionResult):
            raise CompressionError("compress(request) must return CompressionResult")
        if not isinstance(result.messages, list):
            raise CompressionError("CompressionResult.messages must be list[dict]")
        if not result.messages:
            raise CompressionError("CompressionResult.messages must not be empty")
        if not all(isinstance(message, dict) for message in result.messages):
            raise CompressionError("CompressionResult.messages must be list[dict]")
        if not isinstance(result.metadata, Mapping):
            raise CompressionError("CompressionResult.metadata must be a mapping")

    def _validate_token_reduction(self, compacted_tokens: int) -> None:
        if compacted_tokens >= self.trigger_tokens:
            raise CompressionError(
                "Compression failed to reduce tokens below threshold: "
                f"{compacted_tokens} >= {self.trigger_tokens}"
            )

    def _unchanged_run(self, messages: list[dict], tokens: int) -> CompressionRunResult:
        return CompressionRunResult(
            messages=messages,
            algorithm=self.settings.algorithm,
            original_tokens=tokens,
            compacted_tokens=tokens,
            trigger_tokens=self.trigger_tokens,
            metadata={"skipped": "below_threshold"},
        )

    def _hook_metadata(self, context) -> dict[str, Any]:
        return {
            "event": context.event,
            "router": context.router,
            "model_name": context.model_name,
            "loop_round": context.loop_round,
            "previous_round_had_tools": context.previous_round_had_tools,
            "tools": list(context.tool_info) if context.tool_info else [],
        }

    def _hook_result_metadata(self, run: CompressionRunResult) -> dict[str, Any]:
        return {
            "gorcode_compression": {
                "algorithm": run.algorithm,
                "original_tokens": run.original_tokens,
                "compacted_tokens": run.compacted_tokens,
                "trigger_tokens": run.trigger_tokens,
                **dict(run.metadata),
            }
        }
