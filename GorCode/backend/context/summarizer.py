"""
Message Summarizer
==================

Generate summaries of message conversations.
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass
import re

from .token_estimator import TokenEstimator


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
            return "[Summary unavailable - no model connector]"
        
        # Build summarization prompt
        conversation_text = self._format_messages_for_summary(messages)
        
        prompt = f"""Summarize the following conversation concisely. Focus on:
1. What the user requested
2. What was done
3. Current state / what's being worked on
4. Files modified or created
5. Important decisions or constraints

Conversation:
{conversation_text}

Provide a detailed but concise summary (target {max_tokens} tokens):"""

        try:
            # Use the model to generate summary
            # chat() returns a generator, need to collect all responses
            response_generator = self.model_connector.chat([
                {"role": "user", "content": prompt}
            ])
            
            # Collect all content from streaming responses
            full_content = ""
            for response in response_generator:
                if response and hasattr(response, 'content'):
                    full_content += response.content
            
            if full_content:
                return full_content
        except Exception as e:
            pass
        
        # Return placeholder if model call fails
        return "[Summary generation failed]"
    
    def _format_messages_for_summary(self, messages: List[Dict[str, Any]]) -> str:
        """Format messages for summarization prompt."""
        lines = []
        for msg in messages[-30:]:  # Last 30 messages
            role = msg.get("role", "unknown")
            content = self._get_text_content(msg)
            if content:
                # Truncate long content
                if len(content) > 500:
                    content = content[:500] + "..."
                lines.append(f"[{role.upper()}]: {content}")
        return "\n\n".join(lines)
    
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
