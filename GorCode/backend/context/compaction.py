"""
Compaction Manager
==================

Manages context compression/compaction for long conversations.
"""

from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
import copy

from .token_estimator import TokenEstimator
from .summarizer import MessageSummarizer, SummaryResult
from ..core.events import EventBus, Event, EventType
from ..agents.base import AgentRegistry


@dataclass
class CompactionConfig:
    """Configuration for context compaction."""
    
    # Token thresholds
    context_limit: int = 128000
    output_limit: int = 4096
    safety_margin: float = 0.1
    
    # Auto-compaction thresholds
    auto_compact: bool = True
    soft_compact_threshold: float = 0.85  # Soft compact when at 85% of limit
    hard_compact_threshold: float = 0.80  # Hard compact when still > 80% after soft
    
    # Soft compression settings (only affects unprotected tool results)
    soft_compact_enabled: bool = True
    soft_compact_clear_text: str = "[Old tool result content cleared]"
    
    # Hard compression settings (restructures entire conversation)
    hard_compact_enabled: bool = True
    hard_compact_keep_turns: int = 1  # Keep last N turns in full
    
    # Protected tools (won't prune their outputs in soft compression)
    protected_tools: List[str] = field(default_factory=lambda: ["skill", "Skill"])
    
    def calculate_usable_context(self) -> int:
        """Calculate usable context limit."""
        return TokenEstimator.calculate_usable_context(
            self.context_limit,
            self.output_limit,
            self.safety_margin
        )
    
    def get_soft_compact_threshold(self) -> int:
        """Get token threshold for soft compression."""
        return int(self.calculate_usable_context() * self.soft_compact_threshold)
    
    def get_hard_compact_threshold(self) -> int:
        """Get token threshold for hard compression."""
        return int(self.calculate_usable_context() * self.hard_compact_threshold)


class CompactionType:
    """Types of compaction operations."""
    NONE = "none"
    SOFT = "soft"
    HARD = "hard"


@dataclass
class CompactionResult:
    """Result of a compaction operation."""
    
    success: bool
    original_messages: int
    compacted_messages: int
    original_tokens: int
    compacted_tokens: int
    messages: List[Dict[str, Any]] = None
    summary: Optional[str] = None
    pruned_tool_results: int = 0
    cleared_tool_results: int = 0  # New: count of cleared tool results in soft compression
    compaction_type: str = CompactionType.NONE  # New: type of compaction performed
    protected_tool_calls: List[Dict[str, Any]] = field(default_factory=list)  # New: protected tool calls in hard compression
    error: Optional[str] = None
    
    @property
    def compression_ratio(self) -> float:
        """Calculate compression ratio."""
        if self.compacted_tokens == 0:
            return 0
        return self.original_tokens / self.compacted_tokens
    
    @property
    def is_soft_compaction(self) -> bool:
        """Check if soft compaction was performed."""
        return self.compaction_type == CompactionType.SOFT
    
    @property
    def is_hard_compaction(self) -> bool:
        """Check if hard compaction was performed."""
        return self.compaction_type == CompactionType.HARD


class CompactionManager:
    """
    Manages context compaction for long conversations.
    
    Features:
    - Automatic detection of context overflow
    - Tool result pruning
    - Message summarization
    - Integration with compaction agent
    """
    
    def __init__(
        self,
        event_bus: EventBus = None,
        config: CompactionConfig = None,
        model_connector=None,
        model_manager=None,
    ):
        """
        Initialize compaction manager.
        
        Args:
            event_bus: Event bus for notifications
            config: Compaction configuration
            model_connector: Model connector for AI summarization (optional)
            model_manager: Model manager to dynamically get current connector (optional)
        """
        self.event_bus = event_bus or EventBus()
        self.config = config or CompactionConfig()
        self._model_manager = model_manager
        self._model_connector = model_connector
        self.summarizer = MessageSummarizer(self._get_model_connector())
        self._last_compaction_time: Optional[datetime] = None
    
    def _get_model_connector(self):
        """Get the current model connector, either from manager or direct reference."""
        if self._model_manager:
            return self._model_manager.current()
        return self._model_connector
    
    def _update_summarizer_connector(self):
        """Update the summarizer's model connector to the current one."""
        self.summarizer.model_connector = self._get_model_connector()
    
    def check_soft_compact_needed(self, messages: List[Dict[str, Any]]) -> bool:
        """
        Check if soft compaction is needed (token usage > soft threshold).
        
        Args:
            messages: Current messages
            
        Returns:
            True if soft compaction should be triggered
        """
        if not self.config.auto_compact:
            return False
        
        tokens = TokenEstimator.estimate_messages(messages)
        return tokens > self.config.get_soft_compact_threshold()
    
    def check_hard_compact_needed(self, messages: List[Dict[str, Any]]) -> bool:
        """
        Check if hard compaction is needed (token usage > hard threshold).
        
        Args:
            messages: Current messages
            
        Returns:
            True if hard compaction should be triggered
        """
        if not self.config.auto_compact:
            return False
        
        tokens = TokenEstimator.estimate_messages(messages)
        return tokens > self.config.get_hard_compact_threshold()
    
    def get_token_usage(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Get token usage statistics.
        
        Args:
            messages: Current messages
            
        Returns:
            Token usage dictionary
        """
        tokens = TokenEstimator.estimate_messages(messages)
        usable = self.config.calculate_usable_context()
        
        return {
            "current_tokens": tokens,
            "context_limit": self.config.context_limit,
            "usable_context": usable,
            "usage_percentage": round(tokens / usable * 100, 1) if usable > 0 else 0,
            "is_overflow": tokens > usable,
            "should_soft_compact": tokens > self.config.get_soft_compact_threshold(),
            "should_hard_compact": tokens > self.config.get_hard_compact_threshold(),
            "soft_threshold": self.config.get_soft_compact_threshold(),
            "hard_threshold": self.config.get_hard_compact_threshold(),
        }
    
    def compact(
        self,
        messages: List[Dict[str, Any]],
        force: bool = False,
        force_soft: bool = False,
        generate_summary: bool = True,
    ) -> CompactionResult:
        """
        Compact messages using two-phase strategy (soft then hard).
        
        Phase 1 - Soft Compaction:
        - Only clears content of unprotected tool results
        - Replaces with placeholder text
        - Keeps conversation structure intact
        
        Phase 2 - Hard Compaction (if still needed after soft):
        - Summarizes old messages using compact agent
        - Restructures conversation to: protected tool calls -> summary -> recent turns
        
        Args:
            messages: Messages to compact
            force: Force hard compaction even if not needed
            force_soft: Force soft compaction even if not needed
            generate_summary: Whether to generate summary for hard compaction
            
        Returns:
            CompactionResult with compacted messages
        """
        # Update model connector before compaction (in case model changed)
        self._update_summarizer_connector()
        
        original_count = len(messages)
        original_tokens = TokenEstimator.estimate_messages(messages)
        
        # Check if any compaction is needed
        soft_needed = self.check_soft_compact_needed(messages)
        hard_needed = self.check_hard_compact_needed(messages)
        
        if not force and not force_soft and not soft_needed:
            return CompactionResult(
                success=True,
                original_messages=original_count,
                compacted_messages=original_count,
                original_tokens=original_tokens,
                compacted_tokens=original_tokens,
                messages=messages,
                compaction_type=CompactionType.NONE,
            )
        
        try:
            result_messages = copy.deepcopy(messages)
            compaction_type = CompactionType.NONE
            summary = None
            cleared_count = 0
            protected_calls = []
            
            # Phase 1: Soft Compaction
            if self.config.soft_compact_enabled and (soft_needed or force_soft or force):
                result_messages, cleared_count, summary = self._soft_compact(result_messages)
                compaction_type = CompactionType.SOFT
                
                # Check if hard compaction is needed
                current_tokens = TokenEstimator.estimate_messages(result_messages)
                hard_needed = current_tokens > self.config.get_hard_compact_threshold()
            
            # Phase 2: Hard Compaction (if still needed or forced)
            if self.config.hard_compact_enabled and (hard_needed or force):
                result_messages, summary, protected_calls = self._hard_compact(
                    result_messages, 
                    generate_summary=generate_summary
                )
                compaction_type = CompactionType.HARD
            
            compacted_tokens = TokenEstimator.estimate_messages(result_messages)
            self._last_compaction_time = datetime.now()
            
            # Emit event
            self.event_bus.emit(EventType.SESSION_SAVE, {
                "action": "compaction",
                "compaction_type": compaction_type,
                "original_tokens": original_tokens,
                "compacted_tokens": compacted_tokens,
            })
            
            return CompactionResult(
                success=True,
                original_messages=original_count,
                compacted_messages=len(result_messages),
                original_tokens=original_tokens,
                compacted_tokens=compacted_tokens,
                messages=result_messages,
                summary=summary,
                cleared_tool_results=cleared_count,
                compaction_type=compaction_type,
                protected_tool_calls=protected_calls,
            )
            
        except Exception as e:
            return CompactionResult(
                success=False,
                original_messages=original_count,
                compacted_messages=original_count,
                original_tokens=original_tokens,
                compacted_tokens=original_tokens,
                messages=messages,
                compaction_type=CompactionType.NONE,
                error=str(e),
            )
    
    def _soft_compact(
        self,
        messages: List[Dict[str, Any]],
    ) -> tuple[List[Dict[str, Any]], int, Optional[str]]:
        """
        Perform soft compaction - clear unprotected tool results and generate summary.
        
        Soft compaction:
        1. Clears content of unprotected tool results (replaces with placeholder)
        2. Uses LLM to generate summary of conversation
        3. Appends summary after the latest dialogue
        4. Keeps the message structure intact
        
        Args:
            messages: Messages to process
            
        Returns:
            Tuple of (processed messages, count of cleared tool results, summary)
        """
        result = copy.deepcopy(messages)
        cleared = 0
        
        # Generate summary using LLM for all messages
        summary = None
        if result:
            summary_result = self.summarizer.summarize(result, use_model=True)
            summary = summary_result.summary
        
        # Build tool_call_id to tool_name mapping from assistant messages
        tool_call_map = {}
        for msg in result:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    tc_id = tc.get("id", "")
                    tc_name = tc.get("function", {}).get("name", "")
                    if tc_id:
                        tool_call_map[tc_id] = tc_name
        
        # Clear unprotected tool results (regardless of position)
        for i in range(len(result)):
            msg = result[i]
            
            if msg.get("role") == "tool":
                # Get tool name from mapping using tool_call_id
                tool_call_id = msg.get("tool_call_id", "")
                tool_name = tool_call_map.get(tool_call_id, "")
                
                # Skip protected tools
                if tool_name in self.config.protected_tools:
                    continue
                
                # Skip already compacted
                if msg.get("_compacted"):
                    continue
                
                # Clear the content
                original_content = msg.get("content", "")
                msg["content"] = self.config.soft_compact_clear_text
                msg["_compacted"] = True
                msg["_original_length"] = len(original_content)
                cleared += 1
        
        # Append summary after the latest dialogue if available
        if summary:
            summary_msg = {
                "role": "user",
                "content": f"[对话摘要]\n{summary}",
                "_synthetic": True,
                "_soft_compaction_summary": True,
            }
            result.append(summary_msg)
        
        return result, cleared, summary
    
    def _hard_compact(
        self,
        messages: List[Dict[str, Any]],
        generate_summary: bool = True,
    ) -> tuple[List[Dict[str, Any]], Optional[str], List[Dict[str, Any]]]:
        """
        Perform hard compaction - restructure conversation with summary.
        
        Hard compaction:
        1. Collects protected tool calls from all messages
        2. Generates summary of entire conversation using compact agent
        3. Restructures messages to:
           - User: "The following are protected tool calls" (English)
           - Protected tool calls (if any)
           - User: summary
           - Recent turns (kept in full)
        
        Args:
            messages: Messages to process
            generate_summary: Whether to use AI for summary generation
            
        Returns:
            Tuple of (processed messages, summary, protected_tool_calls)
        """
        # Separate recent turns to keep (exclude synthetic messages from soft compaction)
        keep_turns = self.config.hard_compact_keep_turns
        recent_messages = []
        old_messages = []
        turn_count = 0
        
        # Filter out synthetic messages (from soft compaction) when separating
        non_synthetic_messages = [m for m in messages if not m.get("_synthetic")]
        
        for msg in reversed(non_synthetic_messages):
            recent_messages.insert(0, msg)
            if msg.get("role") == "user" and not msg.get("_synthetic"):
                turn_count += 1
                if turn_count >= keep_turns:
                    break
        
        old_messages = non_synthetic_messages[:-len(recent_messages)] if len(recent_messages) < len(non_synthetic_messages) else []
        
        # Build tool_call_id to tool_name mapping from all messages
        tool_call_map = {}
        for msg in messages:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    tc_id = tc.get("id", "")
                    tc_name = tc.get("function", {}).get("name", "")
                    if tc_id:
                        tool_call_map[tc_id] = tc_name
        
        # Collect protected tool call IDs
        protected_tool_call_ids = set()
        for msg in messages:
            if msg.get("role") == "tool":
                tool_call_id = msg.get("tool_call_id", "")
                tool_name = tool_call_map.get(tool_call_id, "")
                if tool_name in self.config.protected_tools:
                    protected_tool_call_ids.add(tool_call_id)
        
        # Collect complete protected tool call chains (assistant tool_calls + tool responses)
        protected_messages = []
        for msg in messages:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                # Check if any tool_call in this message is protected
                protected_calls_in_msg = [
                    tc for tc in msg["tool_calls"] 
                    if tc.get("id") in protected_tool_call_ids
                ]
                if protected_calls_in_msg:
                    # Create assistant message with only protected tool_calls
                    assistant_copy = {k: v for k, v in msg.items() if not k.startswith("_")}
                    assistant_copy["tool_calls"] = protected_calls_in_msg
                    protected_messages.append(assistant_copy)
            elif msg.get("role") == "tool":
                if msg.get("tool_call_id") in protected_tool_call_ids:
                    # Create a copy without internal flags
                    tool_copy = {k: v for k, v in msg.items() if not k.startswith("_")}
                    protected_messages.append(tool_copy)
        
        # Generate summary using compact agent (of non-synthetic messages)
        summary = ""
        if generate_summary and non_synthetic_messages:
            summary_result = self.summarizer.summarize(non_synthetic_messages, use_model=True)
            summary = summary_result.summary
        
        # Build new message structure
        new_messages = []
        
        # Add protected tool calls header if there are any
        if protected_messages:
            new_messages.append({
                "role": "user",
                "content": "The following are protected tool calls:",
                "_synthetic": True,
                "_compaction_header": True,
            })
            new_messages.extend(protected_messages)
        
        # Add summary
        new_messages.append({
            "role": "user",
            "content": summary,
            "_synthetic": True,
            "_compaction_summary": True,
        })
        
        # Add recent messages
        new_messages.extend(recent_messages)
        
        return new_messages, summary, protected_messages
    
    def should_compact(self, messages: List[Dict[str, Any]]) -> bool:
        """
        Check if compaction should be triggered.
        
        Args:
            messages: Current messages
            
        Returns:
            True if compaction recommended
        """
        usage = self.get_token_usage(messages)
        return usage["should_soft_compact"] or usage["should_hard_compact"]
