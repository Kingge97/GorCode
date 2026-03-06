"""
Token Estimation
================

Estimate token counts for messages and text.
"""

from typing import Any, Dict, List, Optional
import re


class TokenEstimator:
    """
    Estimate token counts without requiring tiktoken.
    
    Uses a simple heuristic-based approach that provides
    reasonable approximations for most use cases.
    """
    
    # Average characters per token (rough estimates)
    # These vary by model and language
    CHARS_PER_TOKEN_ENGLISH = 4
    CHARS_PER_TOKEN_CODE = 3.5
    CHARS_PER_TOKEN_CHINESE = 2
    
    # Token overhead for message structure
    MESSAGE_OVERHEAD = 4  # role, content keys
    TOOL_CALL_OVERHEAD = 10  # tool call structure
    
    @classmethod
    def estimate_text(cls, text: str) -> int:
        """
        Estimate token count for a text string.
        
        Args:
            text: Text to estimate
            
        Returns:
            Estimated token count
        """
        if not text:
            return 0
        
        # Count different types of content
        # Chinese/Japanese/Korean characters
        cjk_chars = len(re.findall(r'[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]', text))
        
        # Code-like content (has brackets, semicolons, etc.)
        code_chars = len(re.findall(r'[{}()\[\];:,.<>!=&|+\-*/]', text))
        
        # Remaining characters
        remaining = len(text) - cjk_chars - code_chars
        
        # Estimate tokens
        tokens = (
            cjk_chars / cls.CHARS_PER_TOKEN_CHINESE +
            code_chars / cls.CHARS_PER_TOKEN_CODE +
            remaining / cls.CHARS_PER_TOKEN_ENGLISH
        )
        
        return int(tokens) + 1  # Round up
    
    @classmethod
    def estimate_message(cls, message: Dict[str, Any]) -> int:
        """
        Estimate token count for a message.
        
        Args:
            message: Message dictionary
            
        Returns:
            Estimated token count
        """
        tokens = cls.MESSAGE_OVERHEAD
        
        # Content
        content = message.get("content", "")
        if isinstance(content, str):
            tokens += cls.estimate_text(content)
        elif isinstance(content, list):
            # Multimodal content
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        tokens += cls.estimate_text(part.get("text", ""))
                    elif part.get("type") == "image":
                        # Rough estimate for images
                        tokens += 85  # Low-res image token count
                elif isinstance(part, str):
                    tokens += cls.estimate_text(part)
        
        # Tool calls
        if "tool_calls" in message:
            tokens += cls.TOOL_CALL_OVERHEAD
            for tool_call in message["tool_calls"]:
                if isinstance(tool_call, dict):
                    func = tool_call.get("function", {})
                    tokens += cls.estimate_text(func.get("name", ""))
                    tokens += cls.estimate_text(func.get("arguments", ""))
        
        # Tool call ID
        if "tool_call_id" in message:
            tokens += 2  # ID overhead
        
        return tokens
    
    @classmethod
    def estimate_messages(cls, messages: List[Dict[str, Any]]) -> int:
        """
        Estimate total token count for a list of messages.
        
        Args:
            messages: List of message dictionaries
            
        Returns:
            Total estimated token count
        """
        return sum(cls.estimate_message(msg) for msg in messages)
    
    @classmethod
    def estimate_tool_result(cls, result: str, tool_name: str = "") -> int:
        """
        Estimate token count for a tool result.
        
        Args:
            result: Tool result string
            tool_name: Tool name
            
        Returns:
            Estimated token count
        """
        tokens = cls.TOOL_CALL_OVERHEAD
        tokens += cls.estimate_text(result)
        if tool_name:
            tokens += cls.estimate_text(tool_name)
        return tokens
    
    @classmethod
    def calculate_usable_context(
        cls,
        context_limit: int,
        output_limit: int = 4096,
        safety_margin: float = 0.1,
    ) -> int:
        """
        Calculate usable context limit.
        
        Args:
            context_limit: Model's context limit
            output_limit: Maximum output tokens
            safety_margin: Safety margin as fraction
            
        Returns:
            Usable context for input
        """
        usable = context_limit - output_limit
        usable = int(usable * (1 - safety_margin))
        return max(usable, 0)
    
    @classmethod
    def is_overflow(
        cls,
        current_tokens: int,
        context_limit: int,
        output_limit: int = 4096,
        safety_margin: float = 0.1,
    ) -> bool:
        """
        Check if current token count exceeds usable context.
        
        Args:
            current_tokens: Current token count
            context_limit: Model's context limit
            output_limit: Maximum output tokens
            safety_margin: Safety margin
            
        Returns:
            True if overflow
        """
        usable = cls.calculate_usable_context(context_limit, output_limit, safety_margin)
        return current_tokens > usable
