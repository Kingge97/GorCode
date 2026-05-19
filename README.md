# GorCode

> A practical CLI coding assistant with multi-model configuration, agents, MCP tools, skills, permissions, sandbox checks, and configurable context compression.

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

GorCode is a command-line AI coding assistant. It lets you connect one or more LLM providers, choose different agents for different kinds of work, attach MCP tools, load project skills, and manage long coding sessions from the terminal.

This README focuses on first-time setup and day-to-day usage. Internal architecture details are intentionally kept short.

## Install

The commands below are run from the `GorCode/` Python project directory inside the repository.

```bash
git clone https://github.com/Kingge97/GorCode.git
cd GorCode/GorCode
```

Install runtime dependencies:

```bash
python -m pip install -r requirements.txt
```

Install the `gorcode` command and create the default user configuration:

Windows PowerShell:

```powershell
.\scripts\setup-gorcode.ps1
```

macOS / Linux:

```bash
bash scripts/setup-gorcode.sh
```

Open a new terminal after running the setup script, then check:

```bash
gorcode --help
```

If you do not want to install the shell command yet, you can run GorCode from the project directory:

```bash
python run_gorcode.py --help
```

## Quick Start

1. Create or refresh the default configuration:

```bash
gorcode init --user-only
```

2. Edit the user config:

```text
~/.gorcode/config.json
```

3. Add at least one model connection:

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

4. Start an interactive session:

```bash
gorcode
```

5. Or run one prompt and exit:

```bash
gorcode --prompt "Summarize this project"
```

Inside the session, type `/help` to see available commands.

## Configuration

GorCode reads configuration from:

| Scope | Path |
|---|---|
| User | `~/.gorcode/config.json` |
| Project | `./.gorcode/config.json` |
| Custom | `gorcode --config path/to/config.json` |

Project configuration can override or extend user configuration. Use `gorcode status` to inspect the merged result.

### Model Routers

Set `router` on each item in `model_connections`.

| Router | Use case |
|---|---|
| `openai-chat` | OpenAI-compatible Chat Completions providers |
| `anthropic` | Anthropic Messages API |
| `openai-response` | OpenAI Responses API |
| `openai-chat-interleaved` | OpenAI-compatible interleaved content |
| `anthropic-interleaved` | Anthropic interleaved content |

The connection name, such as `main`, is what you pass to `--model` and use in `agent_model_mapping`.

## Daily Commands

| Command | Purpose |
|---|---|
| `gorcode` | Start the default interactive session |
| `gorcode --agent plan` | Start with a specific agent |
| `gorcode --model main` | Start with a specific model connection |
| `gorcode --prompt "..."` | Run one prompt and exit |
| `gorcode status` | Show configuration and model mapping status |
| `gorcode list-agents` | List available agents |
| `gorcode --debug` | Start with debug mode enabled |
| `gorcode --permission ask` | Ask before sensitive actions |
| `gorcode --permission all` | Grant write, edit, and shell permissions for the session |
| `gorcode --permission exceptrm` | Grant broad permissions except delete-style shell actions |
| `gorcode --sandbox on` | Enable sandbox boundary checks for the session |

Useful in-session commands:

| Command | Purpose |
|---|---|
| `/agent <name>` | Switch agent |
| `/model <name>` | Switch model connection |
| `/mcps` | Manage MCP servers |
| `/skills` | Manage skills |
| `/compact [--soft\|--hard\|--status]` | Compact or inspect context |
| `/context status` | Show context usage |
| `/permission status` | Show session permissions |
| `/sandbox status` | Show sandbox status |
| `/debug on\|off\|status` | Manage debug mode |
| `/new` | Start a new session |
| `/history list [--all]` | List saved sessions for the current project, or all projects |
| `/history load <id> [--all]` | Clone a saved session into a new active session |
| `/history load path <file>` | Import a full session JSON file as a new session |
| `/history save <file> [--force]` | Export the current session as full session JSON |
| `/exit` | Exit GorCode |

History commands are scoped to the current project by default. Use `--all` or
`-a` to search, list, load, delete, info, or clear sessions across all projects.
Loading history always creates a fresh session id; the original saved
conversation remains unchanged.

## Additional Features

### Agents

Agents define the role and behavior GorCode uses for a session or subtask.

```bash
gorcode list-agents
gorcode --agent plan
```

Switch inside a session:

```text
/agent build
/agent plan
```

Map agents to model connections in config:

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

### MCP Servers

Add MCP servers under `mcp_servers`:

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

Manage them inside a session:

```text
/mcps
/mcps connect filesystem
/mcps status
/mcps disconnect filesystem
```

You can also run MCP commands before startup with `gorcode --mcps "connect filesystem"`.

### Skills

Skills inject reusable project or personal knowledge into conversations.

Standard skill locations:

```text
~/.gorcode/skills/
./.gorcode/skills/
```

Minimal skill file:

```md
---
name: project-style
description: Project conventions for code edits.
---

Follow the project's naming, testing, and error-handling conventions.
```

Manage skills inside a session:

```text
/skills
/skills show project-style
/skills enable project-style
/skills disable project-style
/skills reload
```

### Permissions And Sandbox

Permission profiles control what the assistant may do during the current session:

| Profile | Meaning |
|---|---|
| `ask` | Ask before sensitive write, edit, or shell operations |
| `all` | Grant write, edit, shell, and delete-style shell permissions |
| `exceptrm` | Grant broad permissions but keep delete-style shell actions restricted |

Start with a profile:

```bash
gorcode --permission ask
gorcode --permission exceptrm
```

Sandbox checks can be controlled at startup or during a session:

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

### Context Compression

GorCode can compress long conversations before model requests. The trigger is based on `max_context_length * compression_settings.trigger.threshold_ratio`.

Built-in compression configuration:

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

Minimal custom Python compression registration:

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

The entrypoint function receives a compression request and returns a compression result. Keep failures explicit: invalid configuration or algorithm errors should surface during startup or compression.

### Debug And Status

Use status output to inspect config paths, model connections, and agent mapping:

```bash
gorcode status
```

Enable debug mode for one run:

```bash
gorcode --debug
```

Or set it in config:

```json
{
  "debug_mode": true
}
```

Inside a session:

```text
/debug status
/debug on
/debug off
```

## Project Organization

GorCode keeps the CLI, backend runtime, agents, tools, MCP, skills, sandbox, compression, and model connectors separated. Most users only need to edit configuration under `~/.gorcode/` or project-level `.gorcode/`. Internal implementation details live in the source tree and development docs.

## Troubleshooting

- `gorcode` command not found: run the setup script from the `GorCode/` Python project directory, then open a new terminal.

```powershell
.\scripts\setup-gorcode.ps1
```

```bash
bash scripts/setup-gorcode.sh
```

You can also run `python run_gorcode.py` from the project directory.

- No usable model connection: check `~/.gorcode/config.json`. At least one item in `model_connections` needs a non-empty `api_key`, `base_url`, `model_name`, and `router`.

- Agent cannot switch models: check that every value in `agent_model_mapping` points to an existing key in `model_connections`.

- MCP server does not work: run the configured MCP command directly in your terminal first. If that fails, fix the command, args, or environment variables before reconnecting with `/mcps connect <name>`.

## License

GorCode is released under the [MIT License](LICENSE).

---

[中文文档](README_CN_NEW.md)
