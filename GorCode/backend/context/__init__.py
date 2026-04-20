"""
Context Module
==============

Context management including token estimation, compaction, and caching.
"""

from .token_estimator import TokenEstimator
from .summarizer import MessageSummarizer, SummaryResult
from .compaction import (
    CompactionManager,
    CompactionConfig,
    CompactionResult,
    build_compaction_config,
    create_compaction_manager,
    build_compaction_status_message,
    build_compaction_summary_message,
)
from .cache import ResponseCache, CacheEntry
from .streaming import StreamingOptimizer, StreamBuffer, StreamChunk
from .prompt_loader import load_custom_prompt, get_custom_prompt_file_path, get_default_prompt_file_path

__all__ = [
    "TokenEstimator",
    "MessageSummarizer",
    "SummaryResult",
    "CompactionManager",
    "CompactionConfig",
    "CompactionResult",
    "build_compaction_config",
    "create_compaction_manager",
    "build_compaction_status_message",
    "build_compaction_summary_message",
    "ResponseCache",
    "CacheEntry",
    "StreamingOptimizer",
    "StreamBuffer",
    "StreamChunk",
    "load_custom_prompt",
    "get_custom_prompt_file_path",
    "get_default_prompt_file_path",
]
