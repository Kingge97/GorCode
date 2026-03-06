# GorCode

> An AI-Powered CLI Coding Assistant with Multi-Provider Support and Hierarchical Agent System

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## Overview

**GorCode** is an intelligent CLI coding assistant that revolutionizes developer workflows through its powerful multi-provider LLM support and sophisticated hierarchical agent architecture. Built for developers who demand flexibility, extensibility, and intelligent code assistance.

## Key Features

### Multi-Provider LLM Support

GorCode seamlessly integrates with multiple LLM providers through a unified interface:

| Provider | Router | Features |
|----------|--------|----------|
| OpenAI | `openai-chat` | GPT-4, GPT-3.5, streaming support |
| Anthropic | `anthropic` | Claude 3.5/3.7 Sonnet, extended thinking |
| OpenAI Interleaved | `openai-chat-interleaved` | OpenAI with interleaved content |
| Anthropic Interleaved | `anthropic-interleaved` | Anthropic with interleaved content |
| OpenAI Responses | `openai-response` | OpenAI Responses API |

**Multiple routers can work simultaneously**, allowing you to leverage different models for different tasks within the same session.

### Hierarchical Multi-Agent System

GorCode features a powerful multi-level agent architecture:

```
┌─────────────────────────────────────────┐
│           Primary Agent                 │
│    (build, plan - Main Orchestrators)   │
└─────────────────┬───────────────────────┘
                  │
        ┌─────────┼─────────┐
        ▼         ▼         ▼
┌───────────┐ ┌───────────┐ ┌───────────┐
│ Sub-Agent │ │ Sub-Agent │ │ Sub-Agent │
│ (explore) │ │ (general) │ │ (custom)  │
└─────┬─────┘ └───────────┘ └───────────┘
      │
      ▼
┌───────────┐
│  Sub-Sub  │  ← Agents can spawn more agents!
│   Agent   │
└───────────┘
```

**Agent Hierarchy Features:**
- **Primary Agents**: Main orchestrators (`build`, `plan`) that handle complex tasks
- **Sub-Agents**: Specialized workers (`explore`, `general`) for focused subtasks
- **Recursive Delegation**: Any agent can spawn sub-agents for parallel task execution
- **Custom Agents**: Define your own agents with custom prompts and capabilities

### Customizable Agent Configuration

Agents are fully customizable through Markdown-based configuration:

```markdown
---
name: my-custom-agent
mode: subagent
description: Specialized agent for database operations
allowsubagents: ["explore", "general"]
tools:
  search_codebase: true
  file_tools: true
permissions:
  edit: allow
  bash:
    "*": ask
---

# Custom System Prompt

You are a specialized database optimization agent...
```

### MCP (Model Context Protocol) Support

GorCode supports the Model Context Protocol for extended capabilities:

- **Tool Discovery**: Automatically discover and use tools from MCP servers
- **Resource Access**: Access external resources through standardized protocols
- **Multiple Servers**: Connect to multiple MCP servers simultaneously
- **Claude Code Compatible**: Compatible with Claude Code MCP configurations

### Skill System

Inject specialized knowledge into conversations:

- **Skill Directories**: Organize knowledge in `.gorcode/skills/`
- **YAML Frontmatter**: Define skill metadata with YAML
- **Resource Embedding**: Include code examples, documentation, and templates
- **Dynamic Injection**: Skills are injected into context when needed

### Additional Features

- **Streaming Responses**: Real-time response streaming with thinking visibility
- **Tool Calling**: Built-in tools for file operations, code search, web fetching
- **Context Management**: Intelligent context compaction and summarization
- **Permission System**: Configurable permission levels for sensitive operations
- **Session Persistence**: Save and resume conversations

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/Kingge97/GorCode.git
cd GorCode/GorCode
```

### 2. Install Dependencies

**Option A: Using requirements.txt (Recommended for users)**
```bash
# Install dependencies from requirements.txt
pip install -r requirements.txt
```

**Option B: Using pip install -e (Recommended for developers)**
```bash
# Install in editable mode
pip install -e .

# Or install with development dependencies
pip install -e ".[dev]"
```

### 3. Setup CLI Command (Optional)

Run the setup script to add `gorcode` command to your PATH:

**Windows (PowerShell):**
```powershell
.\scripts\setup-gorcode.ps1
```

**macOS/Linux:**
```bash
bash scripts/setup-gorcode.sh
```

After running the script, open a new terminal and you can use the `gorcode` command directly.

## Quick Start

### 1. Configure Models

Create `~/.gorcode/config.json`:

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

### 2. Start Coding

```bash
# Start GorCode with default agent
gorcode

# Use a specific agent
gorcode --agent plan

# Use a specific model
gorcode --model claude
```

## Architecture

```
GorCode/
├── GorAI_LLMClient/          # Unified LLM client library
│   ├── models/               # Provider-specific implementations
│   │   ├── _openai_model.py
│   │   ├── _anthropic_model.py
│   │   ├── _deepseek_openai_model.py
│   │   └── ...
│   └── executor.py           # Tool execution engine
├── backend/
│   ├── agents/               # Agent system
│   │   ├── base.py          # Base agent classes
│   │   └── loader.py        # Agent loading
│   ├── core/
│   │   ├── model_connector.py  # Multi-provider connector
│   │   └── executor.py      # Core execution logic
│   ├── mcp/                 # MCP protocol support
│   ├── skills/              # Skill system
│   └── tools/               # Built-in tools
├── frontend/
│   └── cli/                 # Command-line interface
└── agents/                  # Built-in agent definitions
    ├── build.md
    ├── plan.md
    ├── explore.md
    └── general.md
```

## Creating Custom Agents

Create a new agent by adding a `.md` file to `.gorcode/agents/`:

```markdown
---
name: security-audit
mode: subagent
description: Security-focused code review agent
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

# Security Audit Agent

You are a security-focused code reviewer. Your task is to:
1. Identify potential security vulnerabilities
2. Check for common security anti-patterns
3. Review authentication and authorization logic
4. Analyze input validation

Always provide specific line references and suggest fixes.
```

## MCP Configuration

Add MCP servers to your config:

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

## Supported Routers

| Router | Description | Best For |
|--------|-------------|----------|
| `openai-chat` | OpenAI Chat Completion API | GPT-4, GPT-3.5, DeepSeek, MiniMax |
| `anthropic` | Anthropic Messages API | Claude 3.5/3.7 Sonnet |
| `openai-chat-interleaved` | OpenAI with interleaved content | Complex multimodal tasks |
| `anthropic-interleaved` | Anthropic with interleaved content | Complex multimodal tasks |
| `openai-response` | OpenAI Responses API | Latest OpenAI features |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `GORCODE_CONFIG` | Path to custom config file |
| `GORCODE_WORKDIR` | Default working directory |
| `GORCODE_DEBUG` | Enable debug logging |

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

GorCode is released under the [MIT License](LICENSE).

## Acknowledgments

- Built with [GorAI_LLMClient](GorCode/GorAI_LLMClient/) for unified LLM access
- Inspired by Claude Code and other AI coding assistants
- MCP protocol support based on [Model Context Protocol](https://modelcontextprotocol.io/)

---

**[中文文档](README_CN.md)** | **[Documentation](docs/)** | **[Issues](https://github.com/Kingge97/GorCode/issues)**
