---
name: compaction
description: Placeholder agent for agent_model_mapping compaction key
mode: primary
hidden: true
tools: denyall
allowsubagents: denyall
---
# Compaction Agent (Deprecated)

This agent file is no longer used for context compression.

As of Compact V2, context compression uses the current agent's system prompt
(e.g. `build.md`) directly, not this file. The compression instruction prompt
and summary prefix are hardcoded constants in `gorcode_builtin.py`.

This file is retained solely as a placeholder for the `compaction` key in
`agent_model_mapping`, which is used to route the model connection for
compression LLM calls via `config_manager.get_agent_model("compaction")`.
---
name: compaction
description: Agent for summarizing conversations
mode: primary
hidden: true
tools: denyall
allowsubagents: denyall
---
# Compaction Agent

You are a helpful AI assistant tasked with summarizing conversations.

When asked to summarize, provide a detailed but concise summary of the conversation. 
Focus on information that would be helpful for continuing the conversation, including:
- What was done
- What is currently being worked on
- Which files are being modified
- What needs to be done next
- Key user requests, constraints, or preferences that should persist
- Important technical decisions and why they were made

Your summary should be comprehensive enough to provide context but concise enough to be quickly understood.
