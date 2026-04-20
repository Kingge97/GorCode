"""
Command Handler
===============

Handles user commands in the CLI.
"""

import argparse
from typing import Any, Dict, List, Optional, Callable
from pathlib import Path
from datetime import datetime

from GorCode.frontend.ui.renderer import UIRenderer
from GorCode.frontend.ui.init_render import render_init_result
from GorCode.bridge.inprocess import FrontendClient
from GorCode.frontend.commands.registry import COMMAND_SPECS


class CommandHandler:
    """
    Handler for user commands.

    Supports commands defined in frontend.commands.registry.COMMAND_SPECS.
    """
    
    def __init__(
        self,
        client: FrontendClient,
        ui_renderer: UIRenderer,
    ):
        """
        Initialize command handler.
        
        Args:
            client: Frontend client
            ui_renderer: UI renderer
        """
        self.client = client
        self.ui_renderer = ui_renderer
        self._config_cache: Optional[Dict[str, Any]] = None
        
        # Command registry (single source: COMMAND_SPECS)
        self._commands: Dict[str, Callable] = {}
        for spec in COMMAND_SPECS:
            handler = getattr(self, spec.handler)
            for key in spec.keys:
                self._commands[key] = handler
    
    def handle(self, command: str) -> bool:
        """
        Handle a user command.
        
        Args:
            command: Command string (with leading /)
            
        Returns:
            True to continue the REPL, False to exit
        """
        # Remove leading slash
        if command.startswith("/"):
            command = command[1:]
        
        # Parse command and arguments
        parts = command.strip().split(maxsplit=1)
        if not parts:
            self.ui_renderer.print_error("Empty command")
            return True
        
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        
        # Find and execute command
        handler = self._commands.get(cmd)
        if handler:
            return handler(args)
        else:
            self.ui_renderer.print_error(f"Unknown command: /{cmd}")
            self.ui_renderer.print("Type /help for available commands", style="dim")
            return True

    def _parse_args(self, parser: argparse.ArgumentParser, args: str) -> Optional[argparse.Namespace]:
        """Parse args with unified error handling."""
        try:
            return parser.parse_args(args.split() if args else [])
        except SystemExit:
            return None

    def _get_config(self, refresh: bool = False) -> Dict[str, Any]:
        """Fetch merged config from backend (cached)."""
        if self._config_cache is not None and not refresh:
            return self._config_cache
        resp = self.client.request("config.get", {"scope": "merged"})
        if resp.get("success"):
            self._config_cache = resp.get("payload", {}).get("config", {}) or {}
        else:
            self._config_cache = {}
        return self._config_cache
    
    def _cmd_help(self, args: str) -> bool:
        """Handle /help command."""
        self.ui_renderer.render_help()
        return True
    
    def _cmd_agent(self, args: str) -> bool:
        """Handle /agent command."""
        if not args:
            # List available agents
            response = self.client.request("agent.list", {"visibility": "visible"})
            agents = response.get("payload", {}).get("agents", []) if response.get("success") else []
            self.ui_renderer.render_agent_list(agents)
            return True
        
        agent_name = args.strip().lower()

        agent_resp = self.client.request("agent.get", {"name": agent_name})
        if not agent_resp.get("success"):
            self.ui_renderer.print_error(f"Agent not found: {agent_name}")
            list_resp = self.client.request("agent.list", {"visibility": "visible"})
            agents = list_resp.get("payload", {}).get("agents", []) if list_resp.get("success") else []
            names = [a.get("name", "") for a in agents if isinstance(a, dict)]
            if names:
                self.ui_renderer.print("Available agents: " + ", ".join(names), style="dim")
            return True

        response = self.client.request("agent.switch", {"name": agent_name})
        if response.get("success"):
            self.ui_renderer.print_success(f"Switched to agent: {agent_name}")
            agent = agent_resp.get("payload", {}).get("agent", {})
            description = agent.get("description") if isinstance(agent, dict) else None
            if description:
                self.ui_renderer.print(description, style="dim")
        else:
            self.ui_renderer.print_error(f"Failed to switch to agent: {agent_name}")
        
        return True
    
    def _cmd_model(self, args: str) -> bool:
        """Handle /model command."""
        if not args:
            # List available models
            config = self._get_config()
            self.ui_renderer.render_model_list(config.get("model_connections", {}))
            return True
        
        model_name = args.strip().lower()
        
        response = self.client.request("model.switch", {"model": model_name})
        if response.get("success"):
            self.ui_renderer.print_success(f"Switched to model: {model_name}")
        else:
            self.ui_renderer.print_error(f"Model not found: {model_name}")
            available = response.get("payload", {}).get("available") or []
            if not available:
                config = self._get_config()
                available = list((config.get("model_connections") or {}).keys())
            self.ui_renderer.print("Available models: " + ", ".join(available), style="dim")
        
        return True
    
    def _cmd_init(self, args: str) -> bool:
        """Handle /init command."""
        # Parse arguments
        parser = argparse.ArgumentParser(prog="/init", add_help=False)
        parser.add_argument("path", nargs="?", default="", help="Project path")
        parser.add_argument("-f", "--force", action="store_true", help="Force overwrite existing config")
        parser.add_argument("--user-only", action="store_true", help="Initialize user config only")
        parser.add_argument("--project-only", action="store_true", help="Initialize project config only")
        parser.add_argument("--gorcode", action="store_true", help="Generate GORCODE.md file for the project")
        
        parsed = self._parse_args(parser, args)
        if parsed is None:
            return True
        
        # Check if --gorcode flag is set
        if parsed.gorcode:
            # Generate GORCODE.md file
            self.ui_renderer.print()
            self.ui_renderer.print("[bold]Generating GORCODE.md[/bold]")
            self.ui_renderer.print()
            
            # Execute init command through protocol stream
            try:
                for event in self.client.stream("init.generate", {}):
                    self.ui_renderer.render_event(event)
            except Exception as e:
                self.ui_renderer.print_error(f"Failed to generate GORCODE.md: {e}")
            
            return True
        
        # Original init logic for configuration
        # Determine project path
        project_path = Path(parsed.path) if parsed.path else Path.cwd()
        
        self.ui_renderer.print()
        self.ui_renderer.print(f"[bold]Initializing GorCode[/bold]")
        self.ui_renderer.print(f"Project path: {project_path}", style="dim")
        self.ui_renderer.print()
        
        payload = {
            "path": str(project_path),
            "force": parsed.force,
            "user_only": parsed.user_only,
            "project_only": parsed.project_only,
        }
        response = self.client.request("config.initialize", payload)

        if not response.get("success"):
            self.ui_renderer.print_error(response.get("error") or "Failed to initialize config")
            return True
        
        # Refresh config cache after initialization
        self._config_cache = None

        data = response.get("payload", {})
        if parsed.user_only:
            render_init_result(self.ui_renderer, "User", data.get("result", {}))
        elif parsed.project_only:
            render_init_result(self.ui_renderer, "Project", data.get("result", {}))
        else:
            results = data.get("results", {}) if isinstance(data, dict) else {}
            render_init_result(self.ui_renderer, "User", results.get("user", {}))
            render_init_result(self.ui_renderer, "Project", results.get("project", {}))
        
        return True
    
    def _cmd_mcps(self, args: str) -> bool:
        """Handle /mcps command."""
        parser = argparse.ArgumentParser(prog="/mcps", add_help=False)
        parser.add_argument("action", nargs="?", default="list", help="Action: list, connect, disconnect, status")
        parser.add_argument("name", nargs="?", default="", help="Server name")
        parser.add_argument("--all", "-a", action="store_true", help="Apply to all servers")
        
        parsed = self._parse_args(parser, args)
        if parsed is None:
            return True

        action = parsed.action.lower()
        
        if action == "list":
            self.ui_renderer.print()
            self.ui_renderer.print("[bold]MCP Servers:[/bold]")
            response = self.client.request("mcp.list", {})
            status = response.get("payload", {}).get("status", {})
            if not status:
                self.ui_renderer.print("  [dim]No MCP servers configured.[/dim]")
                self.ui_renderer.print("  [dim]Add servers to ~/.gorcode/config.json[/dim]")
            else:
                for name, info in status.items():
                    st = info["status"]
                    if st == "connected":
                        status_str = "[green]connected[/green]"
                    elif st == "connecting":
                        status_str = "[yellow]connecting...[/yellow]"
                    elif st == "error":
                        status_str = f"[red]error: {info.get('error', 'unknown')}[/red]"
                    else:
                        status_str = "[dim]disconnected[/dim]"
                    
                    self.ui_renderer.print(f"  [cyan]{name}[/cyan] - {status_str}")
                    if info["tools_count"] > 0:
                        self.ui_renderer.print(f"    [dim]Tools: {info['tools_count']}[/dim]")
                    if info["resources_count"] > 0:
                        self.ui_renderer.print(f"    [dim]Resources: {info['resources_count']}[/dim]")
            
            self.ui_renderer.print()
            self.ui_renderer.print("[dim]Usage: /mcps connect <name> | /mcps disconnect <name>[/dim]")
            
        elif action == "connect":
            if parsed.all:
                self.ui_renderer.print("[dim]Connecting to all MCP servers...[/dim]")
                response = self.client.request("mcp.connect", {"all": True})
                results = response.get("payload", {}).get("results", {})
                errors = response.get("payload", {}).get("errors", {})
                for name, success in results.items():
                    if success:
                        self.ui_renderer.print_success(f"Connected to {name}")
                    else:
                        error_msg = errors.get(name, "Unknown error")
                        self.ui_renderer.print_error(f"Failed to connect to {name}: {error_msg}")
            elif parsed.name:
                self.ui_renderer.print(f"[dim]Connecting to {parsed.name}...[/dim]")
                response = self.client.request("mcp.connect", {"name": parsed.name})
                results = response.get("payload", {}).get("results", {})
                errors = response.get("payload", {}).get("errors", {})
                success = results.get(parsed.name, False)
                if success:
                    self.ui_renderer.print_success(f"Connected to {parsed.name}")
                else:
                    error_msg = errors.get(parsed.name, "Unknown error")
                    self.ui_renderer.print_error(f"Failed to connect to {parsed.name}: {error_msg}")
            else:
                self.ui_renderer.print_error("Specify server name or use --all")
                
        elif action == "disconnect":
            if parsed.all:
                response = self.client.request("mcp.disconnect", {"all": True})
                results = response.get("payload", {}).get("results", {})
                for name, success in results.items():
                    if success:
                        self.ui_renderer.print(f"[dim]Disconnected from {name}[/dim]")
            elif parsed.name:
                response = self.client.request("mcp.disconnect", {"name": parsed.name})
                results = response.get("payload", {}).get("results", {})
                if results.get(parsed.name):
                    self.ui_renderer.print(f"[dim]Disconnected from {parsed.name}[/dim]")
                else:
                    self.ui_renderer.print_error(f"Failed to disconnect from {parsed.name}")
            else:
                self.ui_renderer.print_error("Specify server name or use --all")
        
        elif action == "status":
            response = self.client.request("mcp.status", {})
            status = response.get("payload", {}).get("status", {})
            self.ui_renderer.print()
            self.ui_renderer.print("[bold]MCP Status:[/bold]")
            
            for name, info in status.items():
                self.ui_renderer.print(f"\n[cyan]{name}[/cyan]")
                self.ui_renderer.print(f"  Status: {info['status']}")
                self.ui_renderer.print(f"  Tools: {info['tools_count']}")
                self.ui_renderer.print(f"  Resources: {info['resources_count']}")
                if info.get("error"):
                    self.ui_renderer.print(f"  Error: {info['error']}")
        
        return True
    
    def _cmd_skills(self, args: str) -> bool:
        """Handle /skills command."""
        parser = argparse.ArgumentParser(prog="/skills", add_help=False)
        parser.add_argument("action", nargs="?", default="list", help="Action: list, enable, disable, reload, show")
        parser.add_argument("name", nargs="?", default="", help="Skill name")
        parser.add_argument("--all", "-a", action="store_true", help="Apply to all skills")
        
        parsed = self._parse_args(parser, args)
        if parsed is None:
            return True
        
        action = parsed.action.lower()
        
        if action == "list":
            self.ui_renderer.print()
            self.ui_renderer.print("[bold]Available Skills:[/bold]")
            response = self.client.request("skills.list", {})
            skills = response.get("payload", {}).get("skills", [])
            if not skills:
                self.ui_renderer.print("  [dim]No skills found.[/dim]")
                status = self.client.request("config.status", {})
                project_config = status.get("payload", {}).get("paths", {}).get("project") if status.get("success") else ""
                if project_config:
                    skills_dir = Path(project_config).parent / "skills"
                else:
                    skills_dir = Path(".gorcode") / "skills"
                self.ui_renderer.print(f"  [dim]Add skill directories to {skills_dir}[/dim]")
            else:
                for skill in skills:
                    status = "[green]enabled[/green]" if skill.get("enabled") else "[dim]disabled[/dim]"
                    name = skill.get("name", "unknown")
                    desc = skill.get("description", "")
                    self.ui_renderer.print(f"  [cyan]{name}[/cyan] - {status}")
                    if desc:
                        self.ui_renderer.print(f"    [dim]{desc[:100]}[/dim]")
            
            self.ui_renderer.print()
            self.ui_renderer.print("[dim]Usage: /skills show <name> | /skills enable <name> | /skills disable <name>[/dim]")
            
        elif action == "show":
            if not parsed.name:
                self.ui_renderer.print_error("Specify skill name")
                return True

            response = self.client.request("skills.show", {"name": parsed.name})
            if not response.get("success"):
                self.ui_renderer.print_error(f"Skill not found: {parsed.name}")
                return True

            skill = response.get("payload", {})
            self.ui_renderer.print()
            self.ui_renderer.print(f"[bold cyan]{skill.get('name', parsed.name)}[/bold cyan]")
            if skill.get("description"):
                self.ui_renderer.print(f"[dim]{skill.get('description')}[/dim]")
            self.ui_renderer.print()
            content = skill.get("content", "")
            self.ui_renderer.print(content[:500])
            if len(content) > 500:
                self.ui_renderer.print("[dim]... (truncated)[/dim]")
            self.ui_renderer.print()
            self.ui_renderer.print(f"[dim]Resources: {skill.get('resource_count', 0)}[/dim]")
            
        elif action == "enable":
            if parsed.name:
                response = self.client.request("skills.enable", {"name": parsed.name})
                if response.get("success"):
                    self.ui_renderer.print_success(f"Enabled skill: {parsed.name}")
                else:
                    self.ui_renderer.print_error(f"Skill not found: {parsed.name}")
            else:
                self.ui_renderer.print_error("Specify skill name")
                
        elif action == "disable":
            if parsed.name:
                response = self.client.request("skills.disable", {"name": parsed.name})
                if response.get("success"):
                    self.ui_renderer.print(f"[dim]Disabled skill: {parsed.name}[/dim]")
                else:
                    self.ui_renderer.print_error(f"Skill not found: {parsed.name}")
            else:
                self.ui_renderer.print_error("Specify skill name")
        
        elif action == "reload":
            if parsed.name:
                response = self.client.request("skills.reload", {"name": parsed.name})
                if response.get("success"):
                    self.ui_renderer.print_success(f"Reloaded skill: {parsed.name}")
                else:
                    self.ui_renderer.print_error(f"Failed to reload: {parsed.name}")
            else:
                response = self.client.request("skills.reload", {})
                if response.get("success"):
                    self.ui_renderer.print_success("Reloaded all skills")
        
        return True
    
    def _cmd_new(self, args: str) -> bool:
        """Handle /new command."""
        parser = argparse.ArgumentParser(prog="/new", add_help=False)
        parser.add_argument("-s", "--save", action="store_true", help="Save current session before creating new")
        parser.add_argument("-t", "--title", default="", help="Title for the new session")
        
        parsed = self._parse_args(parser, args)
        if parsed is None:
            return True
        
        # Save current session if requested or if it has messages
        if parsed.save:
            save_resp = self.client.request("session.save", {})
            if save_resp.get("success"):
                self.ui_renderer.print_success("Current session saved")
        
        response = self.client.request("session.new", {"title": parsed.title})
        if not response.get("success"):
            self.ui_renderer.print_error(response.get("error") or "Failed to start new session")
            return True

        session_id = response.get("payload", {}).get("session_id")
        if session_id:
            self.ui_renderer.print_success(f"Started new session: {session_id}")
        else:
            self.ui_renderer.print_success("Started new session")
        if parsed.title:
            self.ui_renderer.print(f"Title: {parsed.title}", style="dim")
        
        return True
    
    def _cmd_history(self, args: str) -> bool:
        """Handle /history command."""
        parser = argparse.ArgumentParser(prog="/history", add_help=False)
        parser.add_argument("action", nargs="?", default="list", help="Action: list, load, search, delete, info")
        parser.add_argument("target", nargs="?", default="", help="Session ID or search query")
        parser.add_argument("-l", "--limit", type=int, default=10, help="Number of results")
        parser.add_argument("-o", "--offset", type=int, default=0, help="Offset for pagination")
        
        parsed = self._parse_args(parser, args)
        if parsed is None:
            return True
        
        action = parsed.action.lower()
        
        if action == "list":
            self._history_list(parsed.limit, parsed.offset)
        elif action == "load":
            self._history_load(parsed.target)
        elif action == "search":
            self._history_search(parsed.target, parsed.limit)
        elif action == "delete":
            self._history_delete(parsed.target)
        elif action == "info":
            self._history_info(parsed.target)
        elif action == "clear":
            self._history_clear()
        else:
            # Try to load as session ID
            if parsed.action and len(parsed.action) == 8:
                self._history_load(parsed.action)
            else:
                self.ui_renderer.print_error(f"Unknown action: {action}")
                self.ui_renderer.print("Usage: /history list | /history load <id> | /history search <query>", style="dim")
        
        return True
    
    def _history_list(self, limit: int, offset: int) -> None:
        """List history sessions."""
        self.ui_renderer.print()
        self.ui_renderer.print("[bold]Session History[/bold]")

        response = self.client.request(
            "session.list",
            {"limit": limit, "offset": offset},
        )
        sessions = response.get("payload", {}).get("sessions", []) if response.get("success") else []

        if not sessions:
            self.ui_renderer.print("  [dim]No sessions found.[/dim]")
            self.ui_renderer.print("  [dim]Sessions are automatically saved when you start a new one.[/dim]")
            return
        
        for session in sessions:
            created_at = session.get("created_at", "")
            updated_at = session.get("updated_at", "")
            created = datetime.fromisoformat(created_at).strftime("%Y-%m-%d %H:%M") if created_at else "N/A"
            updated = datetime.fromisoformat(updated_at).strftime("%Y-%m-%d %H:%M") if updated_at else "N/A"

            title = session.get("title") or f"Session {session.get('session_id', 'unknown')}"
            if len(title) > 40:
                title = title[:37] + "..."
            
            self.ui_renderer.print()
            self.ui_renderer.print(f"  [cyan]{session.get('session_id', 'unknown')}[/cyan] - {title}")
            self.ui_renderer.print(
                f"    [dim]Agent: {session.get('agent', 'build')} | Messages: {session.get('message_count', 0)}[/dim]"
            )
            self.ui_renderer.print(f"    [dim]Created: {created} | Updated: {updated}[/dim]")
        
        # Show pagination info
        total = response.get("payload", {}).get("total", len(sessions))
        if total > limit:
            self.ui_renderer.print()
            self.ui_renderer.print(f"  [dim]Showing {offset + 1}-{min(offset + limit, total)} of {total} sessions[/dim]")
            self.ui_renderer.print(f"  [dim]Use --offset {offset + limit} to see more[/dim]")
        
        self.ui_renderer.print()
        self.ui_renderer.print("[dim]Usage: /history load <id> | /history search <query>[/dim]")
    
    def _history_load(self, session_id: str) -> None:
        """Load a history session."""
        if not session_id:
            self.ui_renderer.print_error("Specify session ID")
            self.ui_renderer.print("Usage: /history load <session_id>", style="dim")
            return

        response = self.client.request("session.load", {"session_id": session_id})
        if response.get("success"):
            metadata = response.get("payload", {}).get("metadata", {})
            title = metadata.get("title") or f"Session {metadata.get('session_id', session_id)}"
            message_count = metadata.get("message_count", 0)
            self.ui_renderer.print_success(f"Loaded session: {session_id}")
            self.ui_renderer.print(f"  Title: {title}", style="dim")
            self.ui_renderer.print(f"  Messages: {message_count}", style="dim")
        else:
            self.ui_renderer.print_error(f"Failed to load session: {session_id}")
    
    def _history_search(self, query: str, limit: int) -> None:
        """Search history sessions."""
        if not query:
            self.ui_renderer.print_error("Specify search query")
            self.ui_renderer.print("Usage: /history search <query>", style="dim")
            return
        
        self.ui_renderer.print()
        self.ui_renderer.print(f"[bold]Search Results for '{query}'[/bold]")

        response = self.client.request("session.search", {"query": query, "limit": limit})
        results = response.get("payload", {}).get("results", []) if response.get("success") else []

        if not results:
            self.ui_renderer.print("  [dim]No matching sessions found.[/dim]")
            return
        
        for result in results:
            title = result.get("title") or f"Session {result.get('session_id', 'unknown')}"
            self.ui_renderer.print()
            self.ui_renderer.print(f"  [cyan]{result.get('session_id', 'unknown')}[/cyan] - {title}")
            preview = result.get("preview")
            if preview:
                self.ui_renderer.print(f"    [dim]Preview: {preview}[/dim]")
            self.ui_renderer.print(f"    [dim]Messages: {result.get('message_count', 0)}[/dim]")
    
    def _history_delete(self, session_id: str) -> None:
        """Delete a history session."""
        if not session_id:
            self.ui_renderer.print_error("Specify session ID")
            return

        response = self.client.request("session.delete", {"session_id": session_id})
        if response.get("success"):
            self.ui_renderer.print_success(f"Deleted session: {session_id}")
        else:
            error = response.get("error") or "Failed to delete session"
            self.ui_renderer.print_error(error)
    
    def _history_info(self, session_id: str) -> None:
        """Show session info."""
        response = self.client.request(
            "session.info",
            {"session_id": session_id} if session_id else {},
        )
        if not response.get("success"):
            self.ui_renderer.print_error(response.get("error") or "Session not found")
            return

        info = response.get("payload", {}).get("metadata", {})
        
        self.ui_renderer.print()
        self.ui_renderer.print("[bold]Session Info[/bold]")
        self.ui_renderer.print(f"  ID: [cyan]{info.get('session_id', 'N/A')}[/cyan]")
        self.ui_renderer.print(f"  Title: {info.get('title', 'N/A')}")
        self.ui_renderer.print(f"  Agent: {info.get('agent', 'N/A')}")
        self.ui_renderer.print(f"  Model: {info.get('model', 'N/A')}")
        self.ui_renderer.print(f"  Messages: {info.get('message_count', 0)}")
        self.ui_renderer.print(f"  Created: {info.get('created_at', 'N/A')}")
        self.ui_renderer.print(f"  Updated: {info.get('updated_at', 'N/A')}")
    
    def _history_clear(self) -> None:
        """Clear all history (with confirmation)."""
        list_resp = self.client.request("session.list", {"limit": 10000, "offset": 0})
        sessions = list_resp.get("payload", {}).get("sessions", []) if list_resp.get("success") else []
        session_ids = [s.get("session_id") for s in sessions if isinstance(s, dict)]
        session_ids = [sid for sid in session_ids if sid]

        if not session_ids:
            self.ui_renderer.print("No sessions to clear", style="dim")
            return

        status = self.client.request("session.status", {})
        current_id = status.get("payload", {}).get("session_id") if status.get("success") else None

        deletable_ids = [session_id for session_id in session_ids if session_id != current_id]
        
        if not deletable_ids:
            self.ui_renderer.print("No sessions to clear (current session is active)", style="dim")
            return
        
        if not self.ui_renderer.confirm_history_clear(len(deletable_ids)):
            self.ui_renderer.print("Operation cancelled", style="dim")
            return
        
        deleted = 0
        failed = 0
        for session_id in deletable_ids:
            resp = self.client.request("session.delete", {"session_id": session_id})
            if resp.get("success"):
                deleted += 1
            else:
                failed += 1
        
        if deleted:
            self.ui_renderer.print_success(f"Deleted {deleted} session(s)")
        if failed:
            self.ui_renderer.print_warning(f"Failed to delete {failed} session(s)")
    
    def _cmd_debug(self, args: str) -> bool:
        """Handle /debug command."""
        parser = argparse.ArgumentParser(prog="/debug", add_help=False)
        parser.add_argument("action", nargs="?", default="status", help="Action: on, off, status, list, clean")
        
        parsed = self._parse_args(parser, args)
        if parsed is None:
            return True
        
        action = parsed.action.lower()
        
        if action == "on":
            response = self.client.request("debug.set", {"enabled": True})
            if response.get("success"):
                self.ui_renderer.print_success("Debug mode enabled")
                debug_dir = response.get("payload", {}).get("debug_dir")
                if debug_dir:
                    self.ui_renderer.print(f"Logs will be saved to: {debug_dir}", style="dim")
            else:
                self.ui_renderer.print_error("Failed to enable debug mode")
        
        elif action == "off":
            response = self.client.request("debug.set", {"enabled": False})
            if response.get("success"):
                self.ui_renderer.print("Debug mode disabled", style="dim")
                last_log = response.get("payload", {}).get("last_log")
                if last_log:
                    self.ui_renderer.print(f"Debug log saved: {last_log}", style="dim")
            else:
                self.ui_renderer.print_error("Failed to disable debug mode")
        
        elif action == "status":
            response = self.client.request("debug.status", {})
            status = response.get("payload", {}) if response.get("success") else {}
            self.ui_renderer.print()
            self.ui_renderer.print("[bold]Debug Status[/bold]")
            enabled = bool(status.get("enabled", False))
            self.ui_renderer.print(f"  Enabled: {'[green]Yes[/green]' if enabled else '[dim]No[/dim]'}")
            self.ui_renderer.print(f"  Log directory: {status.get('debug_dir', 'N/A')}")
            self.ui_renderer.print(f"  Log count: {status.get('log_count', 0)}")
            if status.get("current_log"):
                self.ui_renderer.print(f"  Current log: {status.get('current_log')}")
        
        elif action == "list":
            response = self.client.request("debug.list", {})
            logs = response.get("payload", {}).get("logs", []) if response.get("success") else []
            if not logs:
                self.ui_renderer.print("No debug logs found", style="dim")
                return True
            
            self.ui_renderer.print()
            self.ui_renderer.print("[bold]Debug Logs[/bold]")
            for log in logs[:20]:  # Show last 20
                self.ui_renderer.print(f"  {log['agent']} - {log['start_time']}")
                self.ui_renderer.print(f"    [dim]Messages: {log['message_count']}, Tools: {log['tool_call_count']}[/dim]")
        
        elif action == "clean":
            response = self.client.request("debug.clean", {"days": 7})
            removed = response.get("payload", {}).get("removed", 0) if response.get("success") else 0
            self.ui_renderer.print_success(f"Removed {removed} old debug log(s)")
        
        else:
            self.ui_renderer.print_error(f"Unknown action: {action}")
            self.ui_renderer.print("Usage: /debug on | off | status | list | clean", style="dim")
        
        return True
    
    def _cmd_compact(self, args: str) -> bool:
        """Handle /compact command."""
        parser = argparse.ArgumentParser(prog="/compact", add_help=False)
        parser.add_argument("--soft", action="store_true", help="Soft compaction only (clear tool results)")
        parser.add_argument("--hard", action="store_true", help="Hard compaction (restructure conversation)")
        parser.add_argument("--status", action="store_true", help="Show compaction status only")
        
        parsed = self._parse_args(parser, args)
        if parsed is None:
            return True
        
        # Show status only
        if parsed.status:
            response = self.client.request("context.status", {})
            usage = response.get("payload", {}) if response.get("success") else {}
            self.ui_renderer.print()
            self.ui_renderer.print("[bold]Context Status[/bold]")
            self.ui_renderer.print(f"  Current tokens: {usage.get('current_tokens', 0):,}")
            self.ui_renderer.print(f"  Context limit: {usage.get('context_limit', 0):,}")
            self.ui_renderer.print(f"  Usage: {usage.get('usage_percentage', 0)}%")
            
            if usage.get('should_hard_compact'):
                self.ui_renderer.print()
                self.ui_renderer.print("[red]Context exceeds hard threshold. Hard compaction recommended.[/red]")
            elif usage.get('should_soft_compact'):
                self.ui_renderer.print()
                self.ui_renderer.print("[yellow]Context exceeds soft threshold. Soft compaction recommended.[/yellow]")
            return True
        
        # Determine compaction mode
        # Default: auto (soft then hard if needed) - forces compaction
        # --soft: soft only
        # --hard: hard only
        force_soft = parsed.soft or (not parsed.soft and not parsed.hard)  # Default to force soft
        force_hard = parsed.hard
        
        # Perform compaction
        if parsed.soft:
            self.ui_renderer.print("[dim]Performing soft compaction...[/dim]")
        elif parsed.hard:
            self.ui_renderer.print("[dim]Performing hard compaction...[/dim]")
        else:
            self.ui_renderer.print("[dim]Compacting context (auto mode)...[/dim]")
        
        result = self.client.request(
            "context.compact",
            {"force": force_hard, "force_soft": force_soft},
        ).get("payload", {})
        
        if result.get("success"):
            compaction_type = result.get('compaction_type', 'none')
            if compaction_type == 'soft':
                self.ui_renderer.print_success("Soft compaction completed")
            elif compaction_type == 'hard':
                self.ui_renderer.print_success("Hard compaction completed")
            else:
                self.ui_renderer.print_success("Context compacted successfully")
            
            self.ui_renderer.print(f"  Original tokens: {result.get('original_tokens', 0):,}")
            self.ui_renderer.print(f"  Compacted tokens: {result.get('compacted_tokens', 0):,}")
            self.ui_renderer.print(f"  Compression ratio: {result.get('compression_ratio', 0):.2f}x")
            
            if result.get('cleared_tool_results', 0) > 0:
                self.ui_renderer.print(f"  Cleared tool results: {result.get('cleared_tool_results', 0)}")
            if result.get('protected_tool_calls'):
                self.ui_renderer.print(f"  Protected tool calls: {len(result.get('protected_tool_calls', []))}")
            
            # Print summary if available
            summary = result.get('summary')
            if summary:
                self.ui_renderer.print()
                self.ui_renderer.print("[bold]Summary:[/bold]")
                self.ui_renderer.print(summary)
        else:
            self.ui_renderer.print_error(f"Compaction failed: {result.get('error', 'Unknown error')}")
        
        return True
    
    def _cmd_context(self, args: str) -> bool:
        """Handle /context command."""
        parser = argparse.ArgumentParser(prog="/context", add_help=False)
        parser.add_argument("action", nargs="?", default="status", help="Action: status, stats, clear")
        
        parsed = self._parse_args(parser, args)
        if parsed is None:
            return True
        
        action = parsed.action.lower()
        
        if action == "status":
            response = self.client.request("context.status", {})
            usage = response.get("payload", {}) if response.get("success") else {}
            self.ui_renderer.print()
            self.ui_renderer.print("[bold]Context Information[/bold]")
            self.ui_renderer.print(f"  Current tokens: {usage.get('current_tokens', 0):,}")
            self.ui_renderer.print(f"  Context limit: {usage.get('context_limit', 128000):,}")
            self.ui_renderer.print(f"  Usable context: {usage.get('usable_context', 0):,}")
            self.ui_renderer.print(f"  Usage: {usage.get('usage_percentage', 0)}%")
            
            # Progress bar
            percentage = usage.get('usage_percentage', 0)
            bar_width = 30
            filled = int(bar_width * percentage / 100)
            bar = "█" * filled + "░" * (bar_width - filled)
            
            if percentage > 85:
                bar_color = "red"
            elif percentage > 70:
                bar_color = "yellow"
            else:
                bar_color = "green"
            
            self.ui_renderer.print(f"  [{bar_color}]{bar}[/{bar_color}] {percentage}%")
            
            # Messages count
            msg_count = usage.get("message_count", 0)
            self.ui_renderer.print(f"  Messages: {msg_count}")
            
            # Warning if approaching limit
            if usage.get('should_compact'):
                self.ui_renderer.print()
                self.ui_renderer.print("[yellow]Context is approaching limit.[/yellow]")
                self.ui_renderer.print("Use /compact to compress the context.", style="dim")
        
        elif action == "stats":
            # Show cache stats
            response = self.client.request("context.cache.stats", {})
            if response.get("success"):
                stats = response.get("payload", {})
                self.ui_renderer.print()
                self.ui_renderer.print("[bold]Cache Statistics[/bold]")
                self.ui_renderer.print(f"  Entries: {stats['entries']}/{stats['max_entries']}")
                self.ui_renderer.print(f"  Size: {stats['size_mb']}/{stats['max_size_mb']} MB")
                self.ui_renderer.print(f"  Total hits: {stats['total_hits']}")
            else:
                self.ui_renderer.print("Cache not initialized", style="dim")
        
        elif action == "clear":
            # Clear cache
            response = self.client.request("context.cache.clear", {})
            if response.get("success"):
                self.ui_renderer.print_success("Cache cleared")
            else:
                self.ui_renderer.print("Cache not initialized", style="dim")
        
        else:
            self.ui_renderer.print_error(f"Unknown action: {action}")
            self.ui_renderer.print("Usage: /context status | stats | clear", style="dim")
        
        return True
    
    def _cmd_permission(self, args: str) -> bool:
        """Handle /permission command."""
        parser = argparse.ArgumentParser(prog="/permission", add_help=False)
        parser.add_argument("action", nargs="?", default="status", help="Action: status, grant, revoke, clear")
        parser.add_argument("type", nargs="?", default="", help="Permission type: write, edit, bash, bash_delete")
        
        parsed = self._parse_args(parser, args)
        if parsed is None:
            return True
        
        action = parsed.action.lower()
        
        if action == "status":
            # Show current permission status
            response = self.client.request("permission.status", {})
            display_perms = response.get("payload", {}).get("permissions", {})
            
            # Show in UI
            self.ui_renderer.show_permission_status(display_perms)
        
        elif action == "grant":
            if not parsed.type:
                self.ui_renderer.print_error("Specify permission type")
                self.ui_renderer.print("Usage: /permission grant <write|edit|bash|bash_delete>", style="dim")
                return True
            
            response = self.client.request("permission.grant", {"type": parsed.type.lower()})
            if response.get("success"):
                self.ui_renderer.print_success(f"Granted session permission: {parsed.type}")
            else:
                self.ui_renderer.print_error(f"Invalid permission type: {parsed.type}")
                self.ui_renderer.print("Available types: write, edit, bash, bash_delete", style="dim")
        
        elif action == "revoke":
            if not parsed.type:
                self.ui_renderer.print_error("Specify permission type")
                self.ui_renderer.print("Usage: /permission revoke <write|edit|bash|bash_delete>", style="dim")
                return True
            
            response = self.client.request("permission.revoke", {"type": parsed.type.lower()})
            if response.get("success"):
                self.ui_renderer.print(f"[dim]Revoked session permission: {parsed.type}[/dim]")
            else:
                self.ui_renderer.print_error(f"Invalid permission type: {parsed.type}")
                self.ui_renderer.print("Available types: write, edit, bash, bash_delete", style="dim")
        
        elif action == "clear":
            # Clear all session permissions
            response = self.client.request("permission.clear", {})
            if response.get("success"):
                self.ui_renderer.print_success("Cleared all session permissions")
            else:
                self.ui_renderer.print_error("Failed to clear permissions")
        
        else:
            self.ui_renderer.print_error(f"Unknown action: {action}")
            self.ui_renderer.print("Usage: /permission status | grant <type> | revoke <type> | clear", style="dim")
        
        return True
    
    def _cmd_exit(self, args: str) -> bool:
        """Handle /exit command."""
        self.ui_renderer.print("Goodbye!", style="dim")
        return False
