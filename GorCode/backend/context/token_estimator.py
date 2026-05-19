"""
Token Counting
==============

Count token usage for text and message payloads with OpenAI's tiktoken.
"""

import json
from functools import lru_cache
from typing import Any, Dict, List

import tiktoken


JSON_SEPARATORS = (",", ":")
DEFAULT_ENCODING_NAME = "cl100k_base"


@lru_cache(maxsize=8)
def _load_encoding(encoding_name: str):
    return tiktoken.get_encoding(encoding_name)


def _to_token_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=JSON_SEPARATORS,
        sort_keys=True,
    )


class TokenEstimator:
    """
    Count token usage with tiktoken.

    The public method names remain `estimate_*` for API compatibility, but
    counts are produced by the configured tiktoken encoding rather than by
    character-ratio heuristics.
    """

    encoding_name = DEFAULT_ENCODING_NAME

    @classmethod
    def _encoding(cls):
        return _load_encoding(cls.encoding_name)

    @classmethod
    def _count_tokens(cls, value: Any) -> int:
        text = _to_token_text(value)
        if not text:
            return 0
        return len(cls._encoding().encode(text))

    @classmethod
    def estimate_text(cls, text: str) -> int:
        """
        Count tokens for a text string.

        Args:
            text: Text to count

        Returns:
            Token count from tiktoken
        """
        return cls._count_tokens(text)

    @classmethod
    def estimate_message(cls, message: Dict[str, Any]) -> int:
        """
        Count tokens for one message payload.

        Args:
            message: Message dictionary

        Returns:
            Token count from tiktoken
        """
        return cls._count_tokens(message)

    @classmethod
    def estimate_messages(cls, messages: List[Dict[str, Any]]) -> int:
        """
        Count total tokens for a list of messages.

        Args:
            messages: List of message dictionaries

        Returns:
            Total token count from tiktoken
        """
        return sum(cls.estimate_message(msg) for msg in messages)

    @classmethod
    def estimate_tool_result(cls, result: str, tool_name: str = "") -> int:
        """
        Count tokens for a tool result.

        Args:
            result: Tool result string
            tool_name: Tool name

        Returns:
            Token count from tiktoken
        """
        if not tool_name:
            return cls.estimate_text(result)
        return cls._count_tokens({"result": result, "tool_name": tool_name})

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
