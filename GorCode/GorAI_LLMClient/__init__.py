"""
GorAI LLM Client
================

A unified LLM client supporting multiple providers (OpenAI, Anthropic, etc.)

Version: 0.3.4

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

__version__ = "0.3.5"

# Re-export the main functions from models
from .models import (
    create_model, model_base, 
    openai_chat_completetion_model, anthropic_model,
    openai_response_model
)

# Re-export executor interfaces
from .executor import ToolExecutor, SimpleFunctionExecutor

__all__ = [
    "create_model",
    "model_base",
    "openai_chat_completetion_model",
    "anthropic_model",
    "openai_response_model",
    "ToolExecutor",
    "SimpleFunctionExecutor",
    "__version__",
]