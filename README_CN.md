# GorCode

> 一个实用的命令行 AI 编程助手，支持多模型配置、智能体、MCP 工具、技能、权限控制、沙箱检查和可配置的上下文压缩。

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

GorCode 是一个命令行 AI 编程助手。你可以连接一个或多个 LLM 供应商，为不同任务选择不同智能体，接入 MCP 工具，加载项目技能，并在终端里管理长时间的代码协作会话。

这份 README 重点说明首次安装、配置和日常使用。内部架构只做简要说明。

## 安装

下方命令都在仓库内的 `GorCode/` Python 项目目录中执行。

```bash
git clone https://github.com/Kingge97/GorCode.git
cd GorCode/GorCode
```

安装运行依赖：

```bash
python -m pip install -r requirements.txt
```

安装 `gorcode` 命令并创建默认用户配置：

Windows PowerShell：

```powershell
.\scripts\setup-gorcode.ps1
```

macOS / Linux：

```bash
bash scripts/setup-gorcode.sh
```

运行设置脚本后，打开一个新终端并检查：

```bash
gorcode --help
```

如果暂时不想安装 shell 命令，也可以在项目目录中直接运行：

```bash
python run_gorcode.py --help
```

## 快速开始

1. 创建或刷新默认配置：

```bash
gorcode init --user-only
```

2. 编辑用户配置：

```text
~/.gorcode/config.json
```

3. 至少添加一个模型连接：

```json
{
  "model_connections": {
    "main": {
      "name": "main",
      "base_url": "https://api.example.com/v1/",
      "api_key": "YOUR_API_KEY",
      "model_name": "your-model-name",
      "router": "openai-chat",
      "stream": true,
      "extra_args": {}
    }
  },
  "default_agent": "build",
  "agent_model_mapping": {
    "build": "main",
    "plan": "main",
    "explore": "main",
    "general": "main",
    "compaction": "main"
  }
}
```

4. 启动交互式会话：

```bash
gorcode
```

5. 或者执行单次提示词后退出：

```bash
gorcode --prompt "Summarize this project"
```

进入会话后，输入 `/help` 查看可用命令。

## 配置

GorCode 会读取以下配置：

| 范围 | 路径 |
|---|---|
| 用户 | `~/.gorcode/config.json` |
| 项目 | `./.gorcode/config.json` |
| 自定义 | `gorcode --config path/to/config.json` |

项目配置可以覆盖或扩展用户配置。使用 `gorcode status` 可以查看合并后的配置结果。

### 模型路由

在 `model_connections` 的每个连接里设置 `router`。

| Router | 适用场景 |
|---|---|
| `openai-chat` | 兼容 OpenAI Chat Completions 的供应商 |
| `anthropic` | Anthropic Messages API |
| `openai-response` | OpenAI Responses API |
| `openai-chat-interleaved` | 兼容 OpenAI 的交错内容格式 |
| `anthropic-interleaved` | Anthropic 交错内容格式 |

连接名，例如 `main`，就是传给 `--model` 以及写入 `agent_model_mapping` 的名字。

## 常用命令

| 命令 | 用途 |
|---|---|
| `gorcode` | 启动默认交互式会话 |
| `gorcode --agent plan` | 使用指定智能体启动 |
| `gorcode --model main` | 使用指定模型连接启动 |
| `gorcode --prompt "..."` | 执行单次提示词后退出 |
| `gorcode status` | 查看配置和模型映射状态 |
| `gorcode list-agents` | 列出可用智能体 |
| `gorcode --debug` | 启用 debug 模式启动 |
| `gorcode --permission ask` | 敏感操作前询问 |
| `gorcode --permission all` | 本会话内授予写入、编辑和 shell 权限 |
| `gorcode --permission exceptrm` | 授予较宽权限，但保留删除类 shell 操作限制 |
| `gorcode --sandbox on` | 本会话启用沙箱边界检查 |

会话内常用命令：

| 命令 | 用途 |
|---|---|
| `/agent <name>` | 切换智能体 |
| `/model <name>` | 切换模型连接 |
| `/mcps` | 管理 MCP 服务器 |
| `/skills` | 管理技能 |
| `/compact [--soft\|--hard\|--status]` | 压缩或查看上下文状态 |
| `/context status` | 查看上下文用量 |
| `/permission status` | 查看会话权限 |
| `/sandbox status` | 查看沙箱状态 |
| `/debug on\|off\|status` | 管理 debug 模式 |
| `/new` | 开始新会话 |
| `/history list [--all]` | 查看当前项目的历史会话，或查看全部项目 |
| `/history load <id> [--all]` | 将历史会话克隆为新的当前会话 |
| `/history load path <file>` | 从完整 session JSON 文件导入为新会话 |
| `/history save <file> [--force]` | 将当前会话导出为完整 session JSON |
| `/exit` | 退出 GorCode |

历史命令默认只作用于当前项目。需要跨项目查看、搜索、加载、删除、查看详情或清空时，使用
`--all` 或 `-a`。加载历史记录总会创建新的 session id，原始历史会话保持不变。

## 附加功能

### 智能体

智能体定义 GorCode 在会话或子任务中的角色和行为。

```bash
gorcode list-agents
gorcode --agent plan
```

在会话内切换：

```text
/agent build
/agent plan
```

在配置中把智能体映射到模型连接：

```json
{
  "default_agent": "build",
  "agent_model_mapping": {
    "build": "main",
    "plan": "main",
    "explore": "main",
    "general": "main"
  }
}
```

### MCP 服务器

在 `mcp_servers` 下添加 MCP 服务器：

```json
{
  "mcp_servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/project"]
    }
  }
}
```

在会话内管理 MCP：

```text
/mcps
/mcps connect filesystem
/mcps status
/mcps disconnect filesystem
```

也可以在启动前执行 MCP 命令，例如 `gorcode --mcps "connect filesystem"`。

### 技能

技能用于向对话注入可复用的项目知识或个人知识。

标准技能目录：

```text
~/.gorcode/skills/
./.gorcode/skills/
```

最小技能文件：

```md
---
name: project-style
description: Project conventions for code edits.
---

Follow the project's naming, testing, and error-handling conventions.
```

在会话内管理技能：

```text
/skills
/skills show project-style
/skills enable project-style
/skills disable project-style
/skills reload
```

### 权限与沙箱

权限配置决定助手在当前会话中可以执行哪些操作：

| 配置 | 含义 |
|---|---|
| `ask` | 写入、编辑或 shell 等敏感操作前询问 |
| `all` | 授予写入、编辑、shell 和删除类 shell 权限 |
| `exceptrm` | 授予较宽权限，但删除类 shell 操作仍受限制 |

启动时指定权限配置：

```bash
gorcode --permission ask
gorcode --permission exceptrm
```

沙箱检查可以在启动时或会话内控制：

```bash
gorcode --sandbox on
gorcode --sandbox off
```

```text
/sandbox status
/sandbox on
/sandbox off
/sandbox reload
```

### 上下文压缩

GorCode 可以在模型请求前压缩长对话。触发阈值来自 `max_context_length * compression_settings.trigger.threshold_ratio`。

内置压缩配置：

```json
{
  "max_context_length": 128000,
  "compression_settings": {
    "enabled": true,
    "algorithm": "gorcode_builtin",
    "trigger": {
      "event": "before_model_request",
      "threshold_ratio": 0.85
    },
    "algorithms": {
      "gorcode_builtin": {
        "type": "builtin",
        "name": "gorcode_builtin",
        "options": {
          "soft_enabled": true,
          "hard_enabled": true,
          "hard_keep_turns": 1,
          "protected_tools": ["skill", "Skill"]
        }
      }
    }
  }
}
```

最小自定义 Python 压缩算法注册：

```json
{
  "compression_settings": {
    "enabled": true,
    "algorithm": "my_compressor",
    "trigger": {
      "event": "before_model_request",
      "threshold_ratio": 0.85
    },
    "algorithms": {
      "my_compressor": {
        "type": "python",
        "module_path": ".gorcode/compression/my_compressor.py",
        "entrypoint": "compress",
        "options": {}
      }
    }
  }
}
```

入口函数会接收 compression request，并返回 compression result。配置无效或算法执行失败时应直接暴露错误，方便定位根因。

### Debug 与状态

查看配置路径、模型连接和智能体映射：

```bash
gorcode status
```

单次运行启用 debug 模式：

```bash
gorcode --debug
```

也可以写入配置：

```json
{
  "debug_mode": true
}
```

会话内命令：

```text
/debug status
/debug on
/debug off
```

## 项目组织

GorCode 将 CLI、后端运行时、智能体、工具、MCP、技能、沙箱、压缩和模型连接层分开组织。普通用户通常只需要修改 `~/.gorcode/` 或项目级 `.gorcode/` 下的配置。内部实现细节请直接查看源码或开发文档。

## 常见问题

- 找不到 `gorcode` 命令：在 `GorCode/` Python 项目目录中运行设置脚本，然后打开新终端。

```powershell
.\scripts\setup-gorcode.ps1
```

```bash
bash scripts/setup-gorcode.sh
```

也可以在项目目录中直接运行 `python run_gorcode.py`。

- 没有可用模型连接：检查 `~/.gorcode/config.json`。`model_connections` 中至少要有一个连接填写了非空的 `api_key`、`base_url`、`model_name` 和 `router`。

- 智能体无法切换模型：检查 `agent_model_mapping` 中的每个值是否都指向 `model_connections` 里已经存在的连接名。

- MCP 服务器不可用：先在终端里直接运行 MCP 配置中的命令。如果命令本身失败，先修正 command、args 或环境变量，再用 `/mcps connect <name>` 重新连接。

## 许可证

GorCode 基于 [MIT License](LICENSE) 发布。

---

[English Documentation](README_NEW.md)
