"""
GorAI LLM Client
================

A unified LLM client supporting multiple providers (OpenAI, Anthropic, etc.)

Version: 0.4.1

Example usage:
    >>> from GorAI_LLMCLient import create_model
    >>> model = create_model(
    ...     base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    ...     api_key="your-api-key",
    ...     model_name="qwen3-max",
    ...     router="openai-chat"
    ... )

    # Using chatToNextLoop with tools
    >>> from GorAI_LLMCLient.executor import ToolExecutor, SimpleFunctionExecutor
    >>> def add(a, b):
    ...     return a + b
    >>> executor = SimpleFunctionExecutor({"add": add})
    >>> messages = [{"role": "user", "content": "What's 1+2?"}]
    >>> for event in model.chatToNextLoop(messages, executor):
    ...     print(event)
"""

__version__ = "0.4.1"

# Re-export the main functions from models
from .models import (
    create_model, model_base,
    openai_chat_completetion_model, anthropic_model,
    openai_response_model,
    openai_chat_interleaved_model, openai_chat_interleaved_qwen35pmodel,
    anthropic_interleaved_model,
)
from .hooks import HookEvent, HookRegistration, HookResult

# Re-export executor interfaces
from .executor import ToolExecutor, SimpleFunctionExecutor

__all__ = [
    "create_model",
    "model_base",
    "openai_chat_completetion_model",
    "anthropic_model",
    "openai_response_model",
    "openai_chat_interleaved_model",
    "openai_chat_interleaved_qwen35pmodel",
    "anthropic_interleaved_model",
    "HookEvent",
    "HookRegistration",
    "HookResult",
    "ToolExecutor",
    "SimpleFunctionExecutor",
    "__version__",
]
