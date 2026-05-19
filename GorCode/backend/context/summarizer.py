"""
Message Summarizer
==================

Generate summaries of message conversations.
"""

from typing import Any, Dict, List
from dataclasses import dataclass
import copy
import re

from .token_estimator import TokenEstimator
from ..agents.loader import AgentLoader


class SummaryGenerationError(Exception):
    """Raised when the model does not provide a valid compaction summary."""


@dataclass
class SummaryResult:
    """Result of a summarization operation."""
    
    summary: str
    original_tokens: int
    summary_tokens: int
    compression_ratio: float
    key_points: List[str]
    files_mentioned: List[str]
    tools_used: List[str]


class MessageSummarizer:
    """
    Summarize message conversations for context compression.
    
    Can work standalone or with a model for intelligent summarization.
    """
    
    # Patterns for extracting key information
    FILE_PATTERN = re.compile(
        r'(?:file|path|directory|folder)[:\s]+[`"]?([a-zA-Z0-9_\-./\\]+\.[a-zA-Z0-9]+)[`"]?|'
        r'([a-zA-Z0-9_\-./\\]+\.[a-zA-Z0-9]{1,10})(?:\s|$|["\'])',
        re.IGNORECASE
    )
    
    TOOL_PATTERN = re.compile(
        r'(?:tool|function|command)[:\s]+([a-zA-Z_][a-zA-Z0-9_]*)',
        re.IGNORECASE
    )
    
    def __init__(self, model_connector=None):
        """
        Initialize summarizer.
        
        Args:
            model_connector: Optional model connector for AI summarization
        """
        self.model_connector = model_connector
    
    def summarize(
        self,
        messages: List[Dict[str, Any]],
        max_summary_tokens: int = 2000,
        use_model: bool = True,
    ) -> SummaryResult:
        """
        Summarize a list of messages using LLM.
        
        Args:
            messages: Messages to summarize
            max_summary_tokens: Target token count for summary
            use_model: Deprecated, always uses model
            
        Returns:
            SummaryResult with summary and metadata
        """
        original_tokens = TokenEstimator.estimate_messages(messages)
        
        # Extract key information first
        key_points = self._extract_key_points(messages)
        files_mentioned = self._extract_files(messages)
        tools_used = self._extract_tools(messages)
        
        # Generate summary using LLM
        summary = self._model_summarize(messages, max_summary_tokens)
        
        summary_tokens = TokenEstimator.estimate_text(summary)
        compression_ratio = original_tokens / max(summary_tokens, 1)
        
        return SummaryResult(
            summary=summary,
            original_tokens=original_tokens,
            summary_tokens=summary_tokens,
            compression_ratio=compression_ratio,
            key_points=key_points,
            files_mentioned=files_mentioned,
            tools_used=tools_used,
        )
    
    def _model_summarize(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: int,
    ) -> str:
        """
        Generate summary using the model.
        
        Args:
            messages: Messages to summarize
            max_tokens: Target token count
            
        Returns:
            Summary string
        """
        if not self.model_connector:
            raise SummaryGenerationError("Summary generation failed: no model connector")
        
        compaction_messages = self._build_compaction_messages(messages, max_tokens)
        return self._collect_final_summary(compaction_messages)

    def _build_compaction_messages(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: int,
    ) -> List[Dict[str, Any]]:
        prompt = self._load_compaction_prompt()
        return [
            {"role": "system", "content": prompt},
            *self._conversation_messages(messages),
            {"role": "user", "content": self._compression_request(max_tokens)},
        ]

    def _load_compaction_prompt(self) -> str:
        agent = AgentLoader().load_agent("compaction")
        if not agent or not agent.prompt:
            raise SummaryGenerationError("Summary generation failed: compaction agent not found")
        return agent.prompt

    def _conversation_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        result = []
        for index, message in enumerate(messages):
            if index == 0 and message.get("role") == "system":
                continue
            result.append(copy.deepcopy(message))
        if not result:
            raise SummaryGenerationError("Summary generation failed: no messages to summarize")
        return result

    def _compression_request(self, max_tokens: int) -> str:
        return (
            "请总结以上对话，生成用于继续当前任务的压缩上下文摘要。"
            f"目标长度不超过 {max_tokens} tokens。"
            "只输出最终摘要正文，不要输出分析过程、计划、寒暄、标题或 Markdown 代码块。"
        )

    def _collect_final_summary(self, messages: List[Dict[str, Any]]) -> str:
        full_content = ""
        for response in self.model_connector.chat(messages):
            self._validate_summary_response(response)
            if response and hasattr(response, "content"):
                full_content += response.content
        return self._validate_final_summary(full_content)

    def _validate_summary_response(self, response: Any) -> None:
        if not response:
            return
        if getattr(response, "is_error", False):
            message = getattr(response, "error_message", "") or "unknown model error"
            raise SummaryGenerationError(f"Summary generation model error: {message}")
        if getattr(response, "tool_calls", None):
            raise SummaryGenerationError("Summary generation attempted tool calls")

    def _validate_final_summary(self, content: str) -> str:
        if not content or not content.strip():
            raise SummaryGenerationError("Summary generation returned empty content")
        return content.strip()
    
    def _get_text_content(self, message: Dict[str, Any]) -> str:
        """Extract text content from a message."""
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text_parts.append(part.get("text", ""))
                elif isinstance(part, str):
                    text_parts.append(part)
            return " ".join(text_parts)
        return ""
    
    def _extract_key_points(self, messages: List[Dict[str, Any]]) -> List[str]:
        """Extract key points from messages."""
        key_points = []
        
        for msg in messages:
            content = self._get_text_content(msg)
            
            # Look for important statements
            patterns = [
                r'important[:\s]+([^.]+)',
                r'note[:\s]+([^.]+)',
                r'remember[:\s]+([^.]+)',
                r'decision[:\s]+([^.]+)',
                r'todo[:\s]+([^.]+)',
            ]
            
            for pattern in patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                key_points.extend(matches)
        
        return key_points[:10]  # Limit to 10
    
    def _extract_files(self, messages: List[Dict[str, Any]]) -> List[str]:
        """Extract file paths mentioned in messages."""
        files = set()
        
        for msg in messages:
            content = self._get_text_content(msg)
            matches = self.FILE_PATTERN.findall(content)
            for match in matches:
                # match is a tuple from findall
                file_path = match[0] or match[1]
                if file_path and len(file_path) > 3:  # Filter out short matches
                    files.add(file_path)
        
        return sorted(list(files))[:50]  # Limit to 50
    
    def _extract_tools(self, messages: List[Dict[str, Any]]) -> List[str]:
        """Extract tool names from messages."""
        tools = set()
        
        for msg in messages:
            # Check tool_calls
            if "tool_calls" in msg:
                for tc in msg["tool_calls"]:
                    if isinstance(tc, dict):
                        func = tc.get("function", {})
                        name = func.get("name", "")
                        if name:
                            tools.add(name)
            
            # Check for tool role
            if msg.get("role") == "tool":
                name = msg.get("name", "")
                if name:
                    tools.add(name)
        
        return sorted(list(tools))
    
    def _summarize_tools(self, messages: List[Dict[str, Any]]) -> str:
        """Create a summary of tool usage."""
        tool_counts: Dict[str, int] = {}
        
        for msg in messages:
            if "tool_calls" in msg:
                for tc in msg["tool_calls"]:
                    if isinstance(tc, dict):
                        name = tc.get("function", {}).get("name", "")
                        if name:
                            tool_counts[name] = tool_counts.get(name, 0) + 1
        
        if not tool_counts:
            return ""
        
        lines = []
        for name, count in sorted(tool_counts.items(), key=lambda x: -x[1]):
            lines.append(f"- {name}: {count} time(s)")
        
        return "\n".join(lines)
