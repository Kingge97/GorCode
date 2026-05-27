# GorAI LLM Client

一个支持多个提供商（OpenAI、Anthropic 等）的统一 LLM 客户端库，具备工具调用、流式响应和自动对话循环等高级功能。

## 版本

**当前版本：0.4.1**

## 功能特性

- 🔌 **多 LLM 提供商**：支持 OpenAI、Anthropic、DeepSeek 和 Minimax API
- 🔧 **工具调用**：内置函数/工具调用支持，可自动执行
- 🌊 **流式响应**：实时流式传输，提供更好的用户体验
- 🔄 **对话循环**：使用 `chatToNextLoop` 实现自动多轮对话
- 🪝 **生命周期 Hooks**：在模型请求、工具执行、下一轮循环前后插入包外扩展逻辑
- 💭 **思考支持**：处理模型推理/思考内容（Anthropic 扩展思考）
- 🧠 **交错思维交互路由**：支持 OpenAI 兼容和 Anthropic 兼容的交错思维交互
- 📡 **OpenAI Response API**：完整支持 OpenAI 的 Response API（`openai-response` 路由）
- 🖼️ **图片支持**：内置图片格式处理支持
- 🎯 **统一接口**：不同提供商之间的一致 API
- 🛠️ **灵活的工具执行**：通过 `ToolExecutor` 接口自定义工具执行器

## 示例

查看 `examples/` 目录获取完整示例：
- `chat_with_tools_example.py`：工具调用的综合示例
- `hooks_example.py`：生命周期 hook 的最小注册示例

## 生命周期 Hooks

`GorAI_LLMClient` 内置独立的 hook 框架，不依赖任何宿主项目的上下文压缩、事件、配置或 session 系统。外部接入方可以通过 `create_model(..., hooks=...)` 或 `model.add_hook(...)` 注册函数式或对象式 hook。

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

支持的生命周期节点包括：

- `before_loop_start`
- `before_model_request`
- `after_model_response`
- `before_tool_execution`
- `after_tool_execution`
- `before_next_loop`
- `after_loop_end`
- `on_error`
- `on_interrupt`

允许替换 `messages` 的节点是 `before_loop_start`、`before_model_request`、`after_tool_execution` 和 `before_next_loop`。hook 需要显式返回 `HookResult(messages=[...])`；管理器会校验其为 `list[dict]`，并通过 `messages[:] = new_messages` 替换内容，从而保留调用方持有的原列表引用。

hook 异常和非法返回值会显式抛出，不会静默跳过，也不会伪造成功。多个 hook 按 priority 从高到低执行，同优先级按注册顺序执行。

## 项目结构

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
│   ├── __init__.py                         # create_model 工厂函数
│   ├── _model_base.py                      # 模型基类
│   ├── _openai_model.py                    # OpenAI Chat Completions 实现
│   ├── _openai_response_model.py           # OpenAI Response API 实现
│   ├── _openai_chat_interleaved_model.py   # OpenAI 兼容交错思维实现
│   ├── _anthropic_model.py                 # Anthropic 实现
│   └── _anthropic_interleaved_model.py     # Anthropic 兼容交错思维实现
├── message/
│   ├── __init__.py
│   ├── _message_base.py      # MsgReturn 消息格式
│   └── _usage.py             # Token 用量追踪
├── executor.py               # 工具执行器接口
└── examples/
    ├── chat_with_tools_example.py
    └── hooks_example.py
```

## 许可证

MIT License
