# GorAI LLM Client

A unified LLM client library supporting multiple providers (OpenAI, Anthropic, etc.) with advanced features like tool calling, streaming responses, and automatic conversation loops.

## Version

**Current Version: 0.4.1**

## Features

- 🔌 **Multiple LLM Providers**: Support for OpenAI, Anthropic, DeepSeek, and Minimax APIs
- 🔧 **Tool Calling**: Built-in support for function/tool calling with automatic execution
- 🌊 **Streaming Responses**: Real-time streaming for better user experience
- 🔄 **Conversation Loops**: Automatic multi-turn conversations with `chatToNextLoop`
- 🪝 **Lifecycle Hooks**: Insert external package-level logic around model requests and tool execution
- 💭 **Thinking Support**: Handle model reasoning/thinking content (Anthropic extended thinking)
- 🧠 **Interleaved Thinking Router**: Support for OpenAI-compatible and Anthropic-compatible interleaved thinking interactions
- 📡 **OpenAI Response API**: Full support for OpenAI's Response API (`openai-response` router)
- 🖼️ **Image Support**: Built-in support for image format handling
- 🎯 **Unified Interface**: Consistent API across different providers
- 🛠️ **Flexible Tool Execution**: Custom tool executors with `ToolExecutor` interface

## Examples

Check the `examples/` directory for complete examples:
- `chat_with_tools_example.py`: Comprehensive examples of tool calling
- `hooks_example.py`: Minimal lifecycle hook registration example

## Lifecycle Hooks

`GorAI_LLMClient` includes a package-local hook framework. It does not depend on any host project's context compaction, event, configuration, or session system. Integrations can register function-style or object-style hooks with `create_model(..., hooks=...)` or `model.add_hook(...)`.

```python
from GorAI_LLMClient import HookEvent, HookResult, create_model


def before_request(context):
    messages = list(context.messages)
    messages.append({"role": "system", "content": "added by hook"})
    return HookResult(messages=messages)


model = create_model(
    base_url="https://example.invalid/v1",
    api_key="your-api-key",
    model_name="your-model",
    router="openai-chat",
)
model.add_hook(HookEvent.BEFORE_MODEL_REQUEST.value, before_request)
```

Supported lifecycle events:

- `before_loop_start`
- `before_model_request`
- `after_model_response`
- `before_tool_execution`
- `after_tool_execution`
- `before_next_loop`
- `after_loop_end`
- `on_error`
- `on_interrupt`

Message replacement is allowed only during `before_loop_start`, `before_model_request`, `after_tool_execution`, and `before_next_loop`. A hook must explicitly return `HookResult(messages=[...])`; the manager validates `list[dict]` and applies the replacement with `messages[:] = new_messages`, preserving the original list reference held by the caller.

Hook exceptions and invalid return values are raised explicitly. They are not silently skipped and no fake success path is produced. Multiple hooks run by priority from high to low, with registration order preserved for equal priorities.

## Project Structure

```
GorAI_LLMClient/
├── hooks/
│   ├── __init__.py
│   ├── events.py
│   ├── context.py
│   ├── result.py
│   ├── protocols.py
│   └── manager.py
├── models/
│   ├── __init__.py                         # create_model factory function
│   ├── _model_base.py                      # Base model class
│   ├── _openai_model.py                    # OpenAI Chat Completions implementation
│   ├── _openai_response_model.py           # OpenAI Response API implementation
│   ├── _openai_chat_interleaved_model.py   # OpenAI-compatible interleaved thinking implementation
│   ├── _anthropic_model.py                 # Anthropic implementation
│   └── _anthropic_interleaved_model.py     # Anthropic-compatible interleaved thinking implementation
├── message/
│   ├── __init__.py
│   ├── _message_base.py      # MsgReturn message format
│   └── _usage.py             # Token usage tracking
├── executor.py               # Tool executor interfaces
└── examples/
    ├── chat_with_tools_example.py
    └── hooks_example.py
```

## License

MIT License
