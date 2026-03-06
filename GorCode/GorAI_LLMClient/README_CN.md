# GorAI LLM Client

一个支持多个提供商（OpenAI、Anthropic 等）的统一 LLM 客户端库，具备工具调用、流式响应和自动对话循环等高级功能。

## 版本

**当前版本：0.3.2**

## 功能特性

- 🔌 **多 LLM 提供商**：支持 OpenAI、Anthropic、DeepSeek 和 Minimax API
- 🔧 **工具调用**：内置函数/工具调用支持，可自动执行
- 🌊 **流式响应**：实时流式传输，提供更好的用户体验
- 🔄 **对话循环**：使用 `chatToNextLoop` 实现自动多轮对话
- 💭 **思考支持**：处理模型推理/思考内容（Anthropic 扩展思考）
- 🧠 **交错思维交互路由**：支持 OpenAI 兼容和 Anthropic 兼容的交错思维交互
- 🖼️ **图片支持**：内置图片格式处理支持
- 🎯 **统一接口**：不同提供商之间的一致 API
- 🛠️ **灵活的工具执行**：通过 `ToolExecutor` 接口自定义工具执行器

## 示例

查看 `examples/` 目录获取完整示例：
- `chat_with_tools_example.py`：工具调用的综合示例

## 项目结构

```
GorAI_LLMClient/
├── models/
│   ├── __init__.py                    # create_model 工厂函数
│   ├── _model_base.py                 # 模型基类
│   ├── _openai_model.py               # OpenAI 实现
│   ├── _anthropic_model.py            # Anthropic 实现
│   ├── _openai_chat_interleaved_model.py  # OpenAI 兼容交错思维实现
│   └── _anthropic_interleaved_model.py    # Anthropic 兼容交错思维实现
├── message/
│   ├── __init__.py
│   └── _message_base.py      # MsgReturn 消息格式
├── executor.py               # 工具执行器接口
└── examples/
    └── chat_with_tools_example.py
```

## 许可证

MIT License
