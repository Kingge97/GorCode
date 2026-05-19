"""Adapter for GorCode's existing builtin compaction algorithm."""

from __future__ import annotations

from typing import Any, Mapping

from ..contracts import CompressionError, CompressionRequest, CompressionResult
from ...compaction import CompactionConfig, CompactionManager


class GorCodeBuiltinCompressionAlgorithm:
    """Expose the legacy CompactionManager through the new contract."""

    def __init__(
        self,
        *,
        options: Mapping[str, Any],
        event_bus=None,
        model_manager=None,
        model_connector=None,
    ):
        self.options = dict(options or {})
        self._event_bus = event_bus
        self._model_manager = model_manager
        self._model_connector = model_connector

    def compress(self, request: CompressionRequest) -> CompressionResult:
        manager = self._create_manager(request)
        force = bool(request.metadata.get("force", False))
        force_soft = bool(request.metadata.get("force_soft", False))
        result = manager.compact(
            [dict(message) for message in request.messages],
            force=force,
            force_soft=force_soft,
        )
        if not result.success:
            raise CompressionError(result.error or "builtin compression failed")
        return CompressionResult(
            messages=result.messages,
            metadata=self._build_metadata(result),
        )

    def _create_manager(self, request: CompressionRequest) -> CompactionManager:
        return CompactionManager(
            event_bus=self._event_bus,
            config=self._build_config(request),
            model_manager=self._model_manager,
            model_connector=self._model_connector,
        )

    def _build_config(self, request: CompressionRequest) -> CompactionConfig:
        return CompactionConfig(
            context_limit=request.context_limit,
            auto_compact=True,
            soft_compact_threshold=request.threshold_ratio,
            hard_compact_threshold=request.threshold_ratio,
            soft_compact_enabled=bool(self.options.get("soft_enabled", True)),
            hard_compact_enabled=bool(self.options.get("hard_enabled", True)),
            hard_compact_keep_turns=int(self.options.get("hard_keep_turns", 1)),
            protected_tools=list(self.options.get("protected_tools", ["skill", "Skill"])),
        )

    def _build_metadata(self, result) -> dict[str, Any]:
        return {
            "compaction_type": result.compaction_type,
            "summary": result.summary,
            "cleared_tool_results": result.cleared_tool_results,
            "pruned_tool_results": result.pruned_tool_results,
            "protected_tool_calls": result.protected_tool_calls,
        }
