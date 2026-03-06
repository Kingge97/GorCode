# GorCode

> 支持多供应商多路由同时工作、多级智能体调用的 AI 驱动 CLI 编程助手

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## 概述

**GorCode** 是一款智能 CLI 编程助手，通过强大的多供应商 LLM 支持和先进的分层智能体架构，彻底改变了开发者的工作流程。专为追求灵活性、可扩展性和智能代码辅助的开发者打造。

## 核心特性

### 多供应商 LLM 支持

GorCode 通过统一接口无缝集成多个 LLM 供应商：

| 供应商 | 路由 | 特性 |
|--------|------|------|
| OpenAI | `openai-chat` | GPT-4、GPT-3.5、流式支持 |
| Anthropic | `anthropic` | Claude 3.5/3.7 Sonnet、扩展思考 |
| OpenAI Interleaved | `openai-chat-interleaved` | 支持交错内容的 OpenAI |
| Anthropic Interleaved | `anthropic-interleaved` | 支持交错内容的 Anthropic |
| OpenAI Responses | `openai-response` | OpenAI Responses API |

**多个路由可以同时工作**，让您在同一会话中为不同任务使用不同的模型。

### 分层多智能体系统

GorCode 采用强大的多级智能体架构：

```
┌─────────────────────────────────────────┐
│           主智能体 (Primary)             │
│    (build、plan - 主要协调器)            │
└─────────────────┬───────────────────────┘
                  │
        ┌─────────┼─────────┐
        ▼         ▼         ▼
┌───────────┐ ┌───────────┐ ┌───────────┐
│  子智能体  │ │  子智能体  │ │  子智能体  │
│ (explore) │ │ (general) │ │ (custom)  │
└─────┬─────┘ └───────────┘ └───────────┘
      │
      ▼
┌───────────┐
│  子子智能体 │  ← 智能体可以继续开启子智能体！
│  (Sub-Sub) │
└───────────┘
```

**智能体层级特性：**
- **主智能体**：主要协调器（`build`、`plan`），处理复杂任务
- **子智能体**：专业工作者（`explore`、`general`），专注于特定子任务
- **递归委派**：任何智能体都可以生成子智能体进行并行任务执行
- **自定义智能体**：定义具有自定义提示词和能力的专属智能体

### 可自定义的智能体配置

通过基于 Markdown 的配置完全自定义智能体：

```markdown
---
name: my-custom-agent
mode: subagent
description: 专门用于数据库操作的智能体
allowsubagents: ["explore", "general"]
tools:
  search_codebase: true
  file_tools: true
permissions:
  edit: allow
  bash:
    "*": ask
---

# 自定义系统提示词

你是一个专门的数据库优化智能体...
```

### MCP（模型上下文协议）支持

GorCode 支持模型上下文协议以扩展功能：

- **工具发现**：自动发现和使用 MCP 服务器的工具
- **资源访问**：通过标准化协议访问外部资源
- **多服务器**：同时连接多个 MCP 服务器
- **Claude Code 兼容**：兼容 Claude Code MCP 配置

### 技能系统

将专业知识注入对话：

- **技能目录**：在 `.gorcode/skills/` 中组织知识
- **YAML 前置元数据**：使用 YAML 定义技能元数据
- **资源嵌入**：包含代码示例、文档和模板
- **动态注入**：需要时将技能注入上下文

### 其他特性

- **流式响应**：实时流式响应，思考过程可见
- **工具调用**：内置文件操作、代码搜索、网页获取等工具
- **上下文管理**：智能上下文压缩和摘要
- **权限系统**：敏感操作的可配置权限级别
- **会话持久化**：保存和恢复对话

## 安装

### 1. 克隆仓库

```bash
git clone https://github.com/Kingge97/GorCode.git
cd GorCode/GorCode
```

### 2. 安装依赖

**方式 A：使用 requirements.txt（推荐普通用户）**
```bash
# 从 requirements.txt 安装依赖
pip install -r requirements.txt
```

**方式 B：使用 pip install -e（推荐开发者）**
```bash
# 以可编辑模式安装
pip install -e .

# 或安装开发依赖
pip install -e ".[dev]"
```

### 3. 设置 CLI 命令（可选）

运行设置脚本将 `gorcode` 命令添加到 PATH：

**Windows (PowerShell)：**
```powershell
.\scripts\setup-gorcode.ps1
```

**macOS/Linux：**
```bash
bash scripts/setup-gorcode.sh
```

运行脚本后，打开新的终端即可直接使用 `gorcode` 命令。

## 快速开始

### 1. 配置模型

创建 `~/.gorcode/config.json`：

```json
{
  "models": {
    "claude": {
      "name": "claude",
      "model_name": "claude-3-5-sonnet-20241022",
      "base_url": "https://api.anthropic.com/v1/",
      "api_key": "your-anthropic-api-key",
      "router": "anthropic",
      "stream": true
    },
    "gpt4": {
      "name": "gpt4",
      "model_name": "gpt-4-turbo",
      "base_url": "https://api.openai.com/v1/",
      "api_key": "your-openai-api-key",
      "router": "openai-chat",
      "stream": true
    }
  }
}
```

### 2. 开始编程

```bash
# 使用默认智能体启动 GorCode
gorcode

# 使用特定智能体
gorcode --agent plan

# 使用特定模型
gorcode --model claude
```

## 架构

```
GorCode/
├── GorAI_LLMClient/          # 统一 LLM 客户端库
│   ├── models/               # 供应商特定实现
│   │   ├── _openai_model.py
│   │   ├── _anthropic_model.py
│   │   ├── _deepseek_openai_model.py
│   │   └── ...
│   └── executor.py           # 工具执行引擎
├── backend/
│   ├── agents/               # 智能体系统
│   │   ├── base.py          # 基础智能体类
│   │   └── loader.py        # 智能体加载器
│   ├── core/
│   │   ├── model_connector.py  # 多供应商连接器
│   │   └── executor.py      # 核心执行逻辑
│   ├── mcp/                 # MCP 协议支持
│   ├── skills/              # 技能系统
│   └── tools/               # 内置工具
├── frontend/
│   └── cli/                 # 命令行界面
└── agents/                  # 内置智能体定义
    ├── build.md
    ├── plan.md
    ├── explore.md
    └── general.md
```

## 创建自定义智能体

通过向 `.gorcode/agents/` 添加 `.md` 文件创建新智能体：

```markdown
---
name: security-audit
mode: subagent
description: 专注于安全的代码审查智能体
is_native: false
allowsubagents: ["explore"]
tools:
  search_codebase: true
  file_tools: true
  webfetch: true
permissions:
  edit: ask
  bash:
    "*": deny
---

# 安全审计智能体

你是一个专注于安全的代码审查员。你的任务是：
1. 识别潜在的安全漏洞
2. 检查常见的安全反模式
3. 审查认证和授权逻辑
4. 分析输入验证

始终提供具体的行号引用并建议修复方案。
```

## MCP 配置

向配置中添加 MCP 服务器：

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/allowed/dir"]
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "your-token"
      }
    }
  }
}
```

## 支持的路由

| 路由 | 描述 | 适用场景 |
|------|------|----------|
| `openai-chat` | OpenAI Chat Completion API | GPT-4、GPT-3.5、DeepSeek、MiniMax |
| `anthropic` | Anthropic Messages API | Claude 3.5/3.7 Sonnet |
| `openai-chat-interleaved` | 支持交错内容的 OpenAI | 复杂多模态任务 |
| `anthropic-interleaved` | 支持交错内容的 Anthropic | 复杂多模态任务 |
| `openai-response` | OpenAI Responses API | 最新 OpenAI 特性 |

## 环境变量

| 变量 | 描述 |
|------|------|
| `GORCODE_CONFIG` | 自定义配置文件路径 |
| `GORCODE_WORKDIR` | 默认工作目录 |
| `GORCODE_DEBUG` | 启用调试日志 |

## 贡献

我们欢迎贡献！请参阅 [CONTRIBUTING.md](CONTRIBUTING.md) 了解指南。

## 许可证

GorCode 基于 [MIT 许可证](LICENSE) 发布。

## 致谢

- 基于 [GorAI_LLMClient](GorCode/GorAI_LLMClient/) 构建统一 LLM 访问
- 灵感来自 Claude Code 和其他 AI 编程助手
- MCP 协议支持基于 [Model Context Protocol](https://modelcontextprotocol.io/)

---

**[English Documentation](README.md)** | **[文档](docs/)** | **[Issues](https://github.com/Kingge97/GorCode/issues)**
