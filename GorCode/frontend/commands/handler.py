"""
Command Handler
===============

Handles user commands in the CLI.
"""

import argparse
import shlex
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
            payload = response.get("payload", {})
            if payload.get("model_changed"):
                self.ui_renderer.print_success(f"Switched to model: {payload.get('model')}")
            elif payload.get("model_switch_failed"):
                self.ui_renderer.print_error(
                    f"Failed to connect to model: {payload.get('target_model')}"
                )
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
        tokens = self._split_history_args(args)
        if tokens is None:
            return True
        if not tokens:
            self._history_list(10, 0, "project")
            return True

        action = tokens[0].lower()
        rest = tokens[1:]
        if action == "list":
            self._history_list_command(rest)
        elif action == "load":
            self._history_load_command(rest)
        elif action == "save":
            self._history_save_command(rest)
        elif action == "search":
            self._history_search_command(rest)
        elif action == "delete":
            self._history_delete_command(rest)
        elif action == "info":
            self._history_info_command(rest)
        elif action == "clear":
            self._history_clear_command(rest)
        elif len(action) == 8 and not rest:
            self._history_load(action, "project")
        else:
            self.ui_renderer.print_error(f"Unknown action: {action}")
            self._print_history_usage()
        return True

    def _split_history_args(self, args: str) -> Optional[List[str]]:
        try:
            tokens = shlex.split(args or "", posix=False)
        except ValueError as exc:
            self.ui_renderer.print_error(f"History parse error: {exc}")
            return None
        return [self._strip_history_quotes(token) for token in tokens]

    def _strip_history_quotes(self, token: str) -> str:
        if len(token) >= 2 and token[0] == token[-1] and token[0] in {"'", '"'}:
            return token[1:-1]
        return token

    def _parse_history_tokens(
        self,
        parser: argparse.ArgumentParser,
        tokens: List[str],
    ) -> Optional[argparse.Namespace]:
        try:
            return parser.parse_args(tokens)
        except SystemExit:
            return None

    def _history_scope(self, all_projects: bool) -> str:
        return "all" if all_projects else "project"

    def _history_list_command(self, tokens: List[str]) -> None:
        parser = argparse.ArgumentParser(prog="/history list", add_help=False)
        parser.add_argument("--all", "-a", action="store_true")
        parser.add_argument("-l", "--limit", type=int, default=10)
        parser.add_argument("-o", "--offset", type=int, default=0)
        parsed = self._parse_history_tokens(parser, tokens)
        if parsed:
            self._history_list(parsed.limit, parsed.offset, self._history_scope(parsed.all))

    def _history_load_command(self, tokens: List[str]) -> None:
        if tokens and tokens[0].lower() == "path":
            self._history_load_path_command(tokens[1:])
            return
        parser = argparse.ArgumentParser(prog="/history load", add_help=False)
        parser.add_argument("session_id", nargs="?", default="")
        parser.add_argument("--all", "-a", action="store_true")
        parsed = self._parse_history_tokens(parser, tokens)
        if parsed:
            self._history_load(parsed.session_id, self._history_scope(parsed.all))

    def _history_load_path_command(self, tokens: List[str]) -> None:
        parser = argparse.ArgumentParser(prog="/history load path", add_help=False)
        parser.add_argument("file_path", nargs="?", default="")
        parsed = self._parse_history_tokens(parser, tokens)
        if parsed:
            self._history_import(parsed.file_path)

    def _history_save_command(self, tokens: List[str]) -> None:
        parser = argparse.ArgumentParser(prog="/history save", add_help=False)
        parser.add_argument("file_path", nargs="?", default="")
        parser.add_argument("--force", "-f", action="store_true")
        parsed = self._parse_history_tokens(parser, tokens)
        if parsed:
            self._history_save(parsed.file_path, parsed.force)

    def _history_search_command(self, tokens: List[str]) -> None:
        parser = argparse.ArgumentParser(prog="/history search", add_help=False)
        parser.add_argument("query", nargs="?", default="")
        parser.add_argument("--all", "-a", action="store_true")
        parser.add_argument("-l", "--limit", type=int, default=10)
        parsed = self._parse_history_tokens(parser, tokens)
        if parsed:
            self._history_search(parsed.query, parsed.limit, self._history_scope(parsed.all))

    def _history_delete_command(self, tokens: List[str]) -> None:
        parser = argparse.ArgumentParser(prog="/history delete", add_help=False)
        parser.add_argument("session_id", nargs="?", default="")
        parser.add_argument("--all", "-a", action="store_true")
        parsed = self._parse_history_tokens(parser, tokens)
        if parsed:
            self._history_delete(parsed.session_id, self._history_scope(parsed.all))

    def _history_info_command(self, tokens: List[str]) -> None:
        parser = argparse.ArgumentParser(prog="/history info", add_help=False)
        parser.add_argument("session_id", nargs="?", default="")
        parser.add_argument("--all", "-a", action="store_true")
        parsed = self._parse_history_tokens(parser, tokens)
        if parsed:
            self._history_info(parsed.session_id, self._history_scope(parsed.all))

    def _history_clear_command(self, tokens: List[str]) -> None:
        parser = argparse.ArgumentParser(prog="/history clear", add_help=False)
        parser.add_argument("--all", "-a", action="store_true")
        parsed = self._parse_history_tokens(parser, tokens)
        if parsed:
            self._history_clear(self._history_scope(parsed.all))

    def _print_history_usage(self) -> None:
        self.ui_renderer.print(
            "Usage: /history list | /history load <id> | /history load path <file> | /history save <file>",
            style="dim",
        )

    def _history_list(self, limit: int, offset: int, scope: str) -> None:
        """List history sessions."""
        self.ui_renderer.print()
        title = "Session History (all projects)" if scope == "all" else "Session History (current project)"
        self.ui_renderer.print(f"[bold]{title}[/bold]")

        response = self.client.request(
            "session.list",
            {"limit": limit, "offset": offset, "scope": scope},
        )
        if not response.get("success"):
            self.ui_renderer.print_error(response.get("error") or "Failed to list sessions")
            return
        sessions = response.get("payload", {}).get("sessions", [])

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
            if scope == "all":
                self.ui_renderer.print(f"    [dim]Project: {session.get('project_path') or 'N/A'}[/dim]")
        
        # Show pagination info
        total = response.get("payload", {}).get("total", len(sessions))
        if total > limit:
            self.ui_renderer.print()
            self.ui_renderer.print(f"  [dim]Showing {offset + 1}-{min(offset + limit, total)} of {total} sessions[/dim]")
            self.ui_renderer.print(f"  [dim]Use --offset {offset + limit} to see more[/dim]")
        
        self.ui_renderer.print()
        self.ui_renderer.print("[dim]Usage: /history load <id> | /history search <query>[/dim]")

    def _history_load(self, session_id: str, scope: str) -> None:
        """Load a history session."""
        if not session_id:
            self.ui_renderer.print_error("Specify session ID")
            self.ui_renderer.print("Usage: /history load <session_id> [--all]", style="dim")
            return

        response = self.client.request("session.load", {"session_id": session_id, "scope": scope})
        if response.get("success"):
            payload = response.get("payload", {})
            metadata = payload.get("metadata", {})
            new_id = metadata.get("session_id") or payload.get("session_id", "")
            title = metadata.get("title") or f"Session {new_id}"
            message_count = metadata.get("message_count", 0)
            self.ui_renderer.print_success(f"Loaded session as new session: {new_id}")
            if session_id != new_id:
                self.ui_renderer.print(f"  Source session: {session_id}", style="dim")
            self.ui_renderer.print(f"  Title: {title}", style="dim")
            self.ui_renderer.print(f"  Messages: {message_count}", style="dim")
            for warning in payload.get("warnings", []):
                self.ui_renderer.print_warning(warning)
        else:
            self.ui_renderer.print_error(response.get("error") or f"Failed to load session: {session_id}")

    def _history_import(self, file_path: str) -> None:
        if not file_path:
            self.ui_renderer.print_error("Specify history file path")
            self.ui_renderer.print("Usage: /history load path <file_path>", style="dim")
            return
        response = self.client.request("session.import", {"path": file_path})
        if response.get("success"):
            payload = response.get("payload", {})
            self.ui_renderer.print_success(
                f"Loaded session as new session: {payload.get('session_id', 'unknown')}"
            )
            self.ui_renderer.print(f"  Source path: {file_path}", style="dim")
            for warning in payload.get("warnings", []):
                self.ui_renderer.print_warning(warning)
            return
        self.ui_renderer.print_error(response.get("error") or "Failed to import history file")

    def _history_save(self, file_path: str, force: bool) -> None:
        if not file_path:
            self.ui_renderer.print_error("Specify history file path")
            self.ui_renderer.print("Usage: /history save <file_path> [--force]", style="dim")
            return
        response = self.client.request("session.export", {"path": file_path, "force": force})
        if response.get("success"):
            path = response.get("payload", {}).get("path", file_path)
            self.ui_renderer.print_success(f"Saved current session: {path}")
            return
        self.ui_renderer.print_error(response.get("error") or "Failed to save history file")

    def _history_search(self, query: str, limit: int, scope: str) -> None:
        """Search history sessions."""
        if not query:
            self.ui_renderer.print_error("Specify search query")
            self.ui_renderer.print("Usage: /history search <query>", style="dim")
            return
        
        self.ui_renderer.print()
        scope_title = "all projects" if scope == "all" else "current project"
        self.ui_renderer.print(f"[bold]Search Results ({scope_title}) for '{query}'[/bold]")

        response = self.client.request("session.search", {"query": query, "limit": limit, "scope": scope})
        if not response.get("success"):
            self.ui_renderer.print_error(response.get("error") or "Search failed")
            return
        results = response.get("payload", {}).get("results", [])

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
            if scope == "all":
                self.ui_renderer.print(f"    [dim]Project: {result.get('project_path') or 'N/A'}[/dim]")

    def _history_delete(self, session_id: str, scope: str) -> None:
        """Delete a history session."""
        if not session_id:
            self.ui_renderer.print_error("Specify session ID")
            return

        response = self.client.request("session.delete", {"session_id": session_id, "scope": scope})
        if response.get("success"):
            self.ui_renderer.print_success(f"Deleted session: {session_id}")
        else:
            error = response.get("error") or "Failed to delete session"
            self.ui_renderer.print_error(error)

    def _history_info(self, session_id: str, scope: str) -> None:
        """Show session info."""
        response = self.client.request(
            "session.info",
            {"session_id": session_id, "scope": scope} if session_id else {},
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
        self.ui_renderer.print(f"  Project: {info.get('project_path') or 'N/A'}")
        self.ui_renderer.print(f"  Messages: {info.get('message_count', 0)}")
        self.ui_renderer.print(f"  Created: {info.get('created_at', 'N/A')}")
        self.ui_renderer.print(f"  Updated: {info.get('updated_at', 'N/A')}")
        self._print_history_source_info(info)

    def _print_history_source_info(self, info: Dict[str, Any]) -> None:
        if not info.get("source_kind"):
            return
        self.ui_renderer.print(f"  Source kind: {info.get('source_kind')}")
        if info.get("source_session_id"):
            self.ui_renderer.print(f"  Source session: {info.get('source_session_id')}")
        if info.get("source_path"):
            self.ui_renderer.print(f"  Source path: {info.get('source_path')}")
        if info.get("source_agent") and info.get("source_agent") != info.get("agent"):
            self.ui_renderer.print(f"  Source agent: {info.get('source_agent')}")
        if info.get("source_model") and info.get("source_model") != info.get("model"):
            self.ui_renderer.print(f"  Source model: {info.get('source_model')}")

    def _history_clear(self, scope: str) -> None:
        """Clear all history (with confirmation)."""
        list_resp = self.client.request("session.list", {"limit": 10000, "offset": 0, "scope": scope})
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

        scope_label = "all projects" if scope == "all" else "current project"
        if not self.ui_renderer.confirm_history_clear(len(deletable_ids), scope_label):
            self.ui_renderer.print("Operation cancelled", style="dim")
            return
        
        deleted = 0
        failed = 0
        for session_id in deletable_ids:
            resp = self.client.request("session.delete", {"session_id": session_id, "scope": scope})
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
            
            if usage.get('should_compact'):
                self.ui_renderer.print()
                self.ui_renderer.print("[yellow]Context exceeds threshold. Compaction recommended.[/yellow]")
            return True
        
        self.ui_renderer.print("[dim]Compacting context...[/dim]")
        
        result = self.client.request(
            "context.compact",
            {"force": True},
        ).get("payload", {})
        
        if result.get("success"):
            self.ui_renderer.print_success("Context compacted successfully")
            
            self.ui_renderer.print(f"  Original tokens: {result.get('original_tokens', 0):,}")
            self.ui_renderer.print(f"  Compacted tokens: {result.get('compacted_tokens', 0):,}")
            self.ui_renderer.print(f"  Compression ratio: {result.get('compression_ratio', 0):.2f}x")
            
            if result.get('protected_tool_count', 0) > 0:
                self.ui_renderer.print(f"  Protected tool calls: {result.get('protected_tool_count', 0)}")
            
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
            self._print_session_token_usage(usage)
            
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

    def _print_session_token_usage(self, usage: dict) -> None:
        self.ui_renderer.print()
        self.ui_renderer.print("[bold]Session Token Usage[/bold]")
        self.ui_renderer.print(f"  Input tokens: {usage.get('session_input_tokens', 0):,}")
        self.ui_renderer.print(f"  Output tokens: {usage.get('session_output_tokens', 0):,}")
        self.ui_renderer.print(f"  Total tokens: {usage.get('session_total_tokens', 0):,}")

        last_usage = usage.get("last_request_usage")
        if last_usage:
            self.ui_renderer.print(
                "  Last request: "
                f"input {last_usage.get('input_tokens', 0):,} / "
                f"output {last_usage.get('output_tokens', 0):,} / "
                f"total {last_usage.get('total_tokens', 0):,}"
            )
    
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

    def _cmd_sandbox(self, args: str) -> bool:
        """Handle /sandbox command."""
        parser = argparse.ArgumentParser(prog="/sandbox", add_help=False)
        parser.add_argument("action", nargs="?", default="status", help="Action: status, on, off, reload")

        parsed = self._parse_args(parser, args)
        if parsed is None:
            return True

        action = parsed.action.lower()
        if action == "status":
            response = self.client.request("sandbox.status", {})
        elif action == "on":
            response = self.client.request("sandbox.enable", {})
        elif action == "off":
            response = self.client.request("sandbox.disable", {})
        elif action == "reload":
            response = self.client.request("sandbox.reload", {})
        else:
            self.ui_renderer.print_error(f"Unknown action: {action}")
            self.ui_renderer.print("Usage: /sandbox status | on | off | reload", style="dim")
            return True

        if not response.get("success"):
            self.ui_renderer.print_error(response.get("error") or "Sandbox command failed")
            return True

        self._render_sandbox_status(response.get("payload", {}))
        return True

    def _render_sandbox_status(self, status: Dict[str, Any]) -> None:
        """Render sandbox status in the CLI."""
        enabled = bool(status.get("enabled", False))
        provider = status.get("provider") or {}
        provider_type = provider.get("type", "unknown")
        provider_name = provider.get("name") or provider.get("module") or provider.get("command")
        self.ui_renderer.print()
        self.ui_renderer.print("[bold]Sandbox Status[/bold]")
        self.ui_renderer.print(f"  Enabled: {'[green]Yes[/green]' if enabled else '[dim]No[/dim]'}")
        self.ui_renderer.print(f"  Provider: [cyan]{provider_type}[/cyan] {provider_name or ''}")
        self.ui_renderer.print(f"  Unknown mutation: {status.get('unknown_mutation', 'allow')}")
        self.ui_renderer.print(f"  Workspace: {status.get('workspace_root', 'N/A')}", style="dim")

    def _cmd_hook(self, args: str) -> bool:
        """Handle /hook command."""
        action = (args or "status").strip().lower()
        if action != "status":
            self.ui_renderer.print_error(f"Unknown action: {action}")
            self.ui_renderer.print("Usage: /hook status", style="dim")
            return True
        response = self.client.request("hook.status", {})
        if not response.get("success"):
            self.ui_renderer.print_error(response.get("error") or "Hook status failed")
            return True
        self._render_hook_status(response.get("payload", {}))
        return True

    def _render_hook_status(self, status: Dict[str, Any]) -> None:
        hooks = status.get("hooks") or []
        enabled = bool(status.get("enabled", True))
        self.ui_renderer.print()
        self.ui_renderer.print("[bold]Hook Status[/bold]")
        self.ui_renderer.print(f"  Enabled: {'[green]Yes[/green]' if enabled else '[dim]No[/dim]'}")
        self.ui_renderer.print(f"  Loaded hooks: {sum(1 for item in hooks if item.get('status') == 'loaded')}")
        if not hooks:
            self.ui_renderer.print("  [dim]No hooks configured.[/dim]")
            return
        for item in hooks:
            self._render_hook_item(item)

    def _render_hook_item(self, item: Dict[str, Any]) -> None:
        scope = item.get("scope") or {}
        tools = scope.get("tool_names") or []
        self.ui_renderer.print()
        self.ui_renderer.print(f"  [cyan]{item.get('id', 'unknown')}[/cyan]")
        self.ui_renderer.print(f"    Event: {item.get('event') or 'N/A'}")
        self.ui_renderer.print(f"    Type: {item.get('type') or 'N/A'}")
        self.ui_renderer.print(f"    Priority: {item.get('priority', 0)}")
        self.ui_renderer.print(f"    Timeout: {item.get('timeout_seconds', 0)}s")
        self.ui_renderer.print(f"    Scope: {', '.join(scope.get('sources') or [])}")
        if tools:
            self.ui_renderer.print(f"    Tools: {', '.join(tools)}")
        self.ui_renderer.print(f"    Status: {item.get('status', 'unknown')}")

    def _cmd_exit(self, args: str) -> bool:
        """Handle /exit command."""
        self.ui_renderer.print("Goodbye!", style="dim")
        return False
