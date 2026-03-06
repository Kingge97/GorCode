"""
Command Handler
===============

Handles user commands in the CLI.
"""

from typing import Any, Dict, List, Optional, Callable
from pathlib import Path
from datetime import datetime

from backend.core.executor import BackendExecutor
from backend.core.events import EventType
from backend.config.manager import ConfigManager
from backend.config.initializer import ProjectInitializer, InitResult
from backend.agents.base import AgentRegistry
from backend.session import SessionManager, SessionStorage, DebugLogger
from backend.mcp import create_mcp_tools
from frontend.ui.renderer import UIRenderer


class CommandHandler:
    """
    Handler for user commands.
    
    Supports commands:
    - /help - Show help
    - /agent - Switch agent
    - /model - Switch model
    - /init - Initialize project
    - /mcps - Manage MCPs
    - /skills - Manage skills
    - /new - New session
    - /history - View history
    - /debug - Toggle debug mode
    - /exit - Exit
    """
    
    def __init__(
        self,
        executor: BackendExecutor,
        config_manager: ConfigManager,
        ui_renderer: UIRenderer,
    ):
        """
        Initialize command handler.
        
        Args:
            executor: Backend executor
            config_manager: Configuration manager
            ui_renderer: UI renderer
        """
        self.executor = executor
        self.config_manager = config_manager
        self.ui_renderer = ui_renderer
        self.agent_registry = AgentRegistry()
        
        # Initialize session manager
        project_path = str(config_manager.project_path) if config_manager else ""
        self.session_manager = SessionManager(
            event_bus=executor.event_bus if executor else None,
            storage=SessionStorage(),
            project_path=project_path,
        )
        
        # Initialize debug logger
        self.debug_logger = DebugLogger(
            base_path=project_path,
            enabled=config_manager.config.debug_mode if config_manager else False,
        )
        
        # Command registry
        self._commands: Dict[str, Callable] = {
            "help": self._cmd_help,
            "agent": self._cmd_agent,
            "model": self._cmd_model,
            "init": self._cmd_init,
            "mcps": self._cmd_mcps,
            "skills": self._cmd_skills,
            "new": self._cmd_new,
            "history": self._cmd_history,
            "debug": self._cmd_debug,
            "compact": self._cmd_compact,
            "context": self._cmd_context,
            "permission": self._cmd_permission,
            "exit": self._cmd_exit,
            "quit": self._cmd_exit,
        }
    
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
    
    def _cmd_help(self, args: str) -> bool:
        """Handle /help command."""
        self.ui_renderer.render_help()
        return True
    
    def _cmd_agent(self, args: str) -> bool:
        """Handle /agent command."""
        if not args:
            # List available agents
            agents = self.agent_registry.get_visible_agents()
            self.ui_renderer.render_agent_list(agents)
            return True
        
        agent_name = args.strip().lower()
        agent = self.agent_registry.get(agent_name)
        
        if agent is None:
            self.ui_renderer.print_error(f"Agent not found: {agent_name}")
            self.ui_renderer.print("Available agents: " + 
                ", ".join(a.name for a in self.agent_registry.get_visible_agents()),
                style="dim")
            return True
        
        # Switch agent
        if self.executor.switch_agent(agent_name):
            self.ui_renderer.print_success(f"Switched to agent: {agent_name}")
            if agent.description:
                self.ui_renderer.print(agent.description, style="dim")
        else:
            self.ui_renderer.print_error(f"Failed to switch to agent: {agent_name}")
        
        return True
    
    def _cmd_model(self, args: str) -> bool:
        """Handle /model command."""
        if not args:
            # List available models
            config = self.config_manager.config
            self.ui_renderer.render_model_list(config.model_connections)
            return True
        
        model_name = args.strip().lower()
        
        if self.executor.switch_model(model_name):
            self.ui_renderer.print_success(f"Switched to model: {model_name}")
        else:
            self.ui_renderer.print_error(f"Model not found: {model_name}")
            config = self.config_manager.config
            available = list(config.model_connections.keys())
            self.ui_renderer.print("Available models: " + ", ".join(available), style="dim")
        
        return True
    
    def _cmd_init(self, args: str) -> bool:
        """Handle /init command."""
        import argparse
        
        # Parse arguments
        parser = argparse.ArgumentParser(prog="/init", add_help=False)
        parser.add_argument("path", nargs="?", default="", help="Project path")
        parser.add_argument("-f", "--force", action="store_true", help="Force overwrite existing config")
        parser.add_argument("--user-only", action="store_true", help="Initialize user config only")
        parser.add_argument("--project-only", action="store_true", help="Initialize project config only")
        parser.add_argument("--gorcode", action="store_true", help="Generate GORCODE.md file for the project")
        
        try:
            parsed = parser.parse_args(args.split() if args else [])
        except SystemExit:
            return True
        
        # Check if --gorcode flag is set
        if parsed.gorcode:
            # Generate GORCODE.md file
            self.ui_renderer.print()
            self.ui_renderer.print("[bold]Generating GORCODE.md[/bold]")
            self.ui_renderer.print()
            
            # Execute init command through executor
            try:
                for event in self.executor.execute_init_command():
                    # Handle events from executor
                    event_type = event.event_type
                    event_data = event.data
                    
                    if event_type == EventType.UI_MESSAGE:
                        self.ui_renderer.print(event_data.get("message", ""))
                    elif event_type == EventType.MODEL_ANSWER:
                        # Stream model answer directly to console
                        content = event_data.get("content", "")
                        if content:
                            self.ui_renderer.console.print(content, end="")
                    elif event_type == EventType.MODEL_TOOL_CALL:
                        tool_name = event_data.get("name", "unknown")
                        self.ui_renderer.print(f"[dim]Using tool: {tool_name}[/dim]")
                    elif event_type == EventType.TOOL_EXECUTION_START:
                        tool_name = event_data.get("tool_name", "unknown")
                        self.ui_renderer.print(f"[dim]Executing: {tool_name}[/dim]")
                    elif event_type == EventType.TOOL_RESULT:
                        # Show tool result summary
                        tool_name = event_data.get("tool_name", "unknown")
                        success = event_data.get("success", False)
                        if success:
                            self.ui_renderer.print(f"[dim]✓ {tool_name} completed[/dim]")
                    elif event_type == EventType.MODEL_ERROR:
                        self.ui_renderer.print_error(event_data.get("error", "Unknown error"))
                    elif event_type == EventType.MODEL_END:
                        self.ui_renderer.print()
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
        
        # Create initializer
        initializer = ProjectInitializer(project_path=str(project_path))
        
        # Get current status
        status = initializer.get_config_status()
        
        # Initialize based on flags
        if parsed.user_only:
            # Initialize user config only
            result = initializer.initialize_user_config(force=parsed.force)
            self._render_init_result("User", result, status["user_config"]["path"])
        elif parsed.project_only:
            # Initialize project config only
            result = initializer.initialize_project_config(force=parsed.force)
            self._render_init_result("Project", result, status["project_config"]["path"])
        else:
            # Initialize both
            results = initializer.initialize_all(force=parsed.force)
            self._render_init_result("User", results["user"], status["user_config"]["path"])
            self._render_init_result("Project", results["project"], status["project_config"]["path"])
        
        return True
    
    def _render_init_result(self, name: str, result: InitResult, path: str) -> None:
        """Render initialization result."""
        if result.success:
            self.ui_renderer.print_success(f"{name} configuration: {result.message}")
            if result.created_paths:
                self.ui_renderer.print(f"  Created:", style="dim")
                for p in result.created_paths:
                    self.ui_renderer.print(f"    • {p}", style="dim")
        else:
            self.ui_renderer.print_error(f"{name} configuration: {result.message}")
            for error in result.errors:
                self.ui_renderer.print(f"  Error: {error}", style="dim")
    
    def _cmd_mcps(self, args: str) -> bool:
        """Handle /mcps command."""
        import argparse
        
        parser = argparse.ArgumentParser(prog="/mcps", add_help=False)
        parser.add_argument("action", nargs="?", default="list", help="Action: list, connect, disconnect, status")
        parser.add_argument("name", nargs="?", default="", help="Server name")
        parser.add_argument("--all", "-a", action="store_true", help="Apply to all servers")
        
        try:
            parsed = parser.parse_args(args.split() if args else [])
        except SystemExit:
            return True
        
        from backend.mcp import MCPManager, MCPServerConfig, MCPConnectionStatus
        import asyncio
        
        mcp_manager = getattr(self.executor, '_mcp_manager', None)
        if not mcp_manager:
            # Get encoding from config (default to utf-8)
            config = self.config_manager.config
            encoding = getattr(config, 'default_encoding', 'utf-8') or 'utf-8'
            mcp_manager = MCPManager(encoding=encoding)
            # Load from config
            if config.mcp_servers:
                mcp_manager.load_from_config(config.mcp_servers)
            self.executor._mcp_manager = mcp_manager
        
        action = parsed.action.lower()
        
        if action == "list":
            self.ui_renderer.print()
            self.ui_renderer.print("[bold]MCP Servers:[/bold]")
            
            status = mcp_manager.get_status()
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
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    results = loop.run_until_complete(mcp_manager.connect_all())
                    for name, success in results.items():
                        if success:
                            self.ui_renderer.print_success(f"Connected to {name}")
                        else:
                            self.ui_renderer.print_error(f"Failed to connect to {name}")
                    
                    # Register MCP tools to tool registry after successful connections
                    if any(results.values()):
                        self._register_mcp_tools(mcp_manager)
                finally:
                    loop.close()
            elif parsed.name:
                self.ui_renderer.print(f"[dim]Connecting to {parsed.name}...[/dim]")
                
                # Debug: show server config
                connection = mcp_manager.get_connection(parsed.name)
                if connection:
                    self.ui_renderer.print(f"[dim]  Command: {connection.config.command}[/dim]")
                    self.ui_renderer.print(f"[dim]  Args: {connection.config.args}[/dim]")
                else:
                    self.ui_renderer.print_error(f"Server '{parsed.name}' not found in configuration")
                    self.ui_renderer.print(f"[dim]Available servers: {list(mcp_manager.get_all_connections().keys())}[/dim]")
                    return True
                
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    success = loop.run_until_complete(mcp_manager.connect(parsed.name))
                    if success:
                        self.ui_renderer.print_success(f"Connected to {parsed.name}")
                        # Register MCP tools after successful connection
                        self._register_mcp_tools(mcp_manager)
                    else:
                        error_msg = connection.error_message or "Unknown error"
                        self.ui_renderer.print_error(f"Failed to connect to {parsed.name}: {error_msg}")
                finally:
                    loop.close()
            else:
                self.ui_renderer.print_error("Specify server name or use --all")
                
        elif action == "disconnect":
            if parsed.all:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    results = loop.run_until_complete(mcp_manager.disconnect_all())
                    for name in results:
                        self.ui_renderer.print(f"[dim]Disconnected from {name}[/dim]")
                    
                    # Unregister all MCP tools after disconnecting all servers
                    if results:
                        self._unregister_mcp_tools(mcp_manager)
                finally:
                    loop.close()
            elif parsed.name:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    success = loop.run_until_complete(mcp_manager.disconnect(parsed.name))
                    if success:
                        self.ui_renderer.print(f"[dim]Disconnected from {parsed.name}[/dim]")
                        # Unregister MCP tools for this server
                        self._unregister_mcp_tools(mcp_manager, parsed.name)
                    else:
                        self.ui_renderer.print_error(f"Failed to disconnect from {parsed.name}")
                finally:
                    loop.close()
            else:
                self.ui_renderer.print_error("Specify server name or use --all")
        
        elif action == "status":
            status = mcp_manager.get_status()
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
        import argparse
        
        parser = argparse.ArgumentParser(prog="/skills", add_help=False)
        parser.add_argument("action", nargs="?", default="list", help="Action: list, enable, disable, reload, show")
        parser.add_argument("name", nargs="?", default="", help="Skill name")
        parser.add_argument("--all", "-a", action="store_true", help="Apply to all skills")
        
        try:
            parsed = parser.parse_args(args.split() if args else [])
        except SystemExit:
            return True
        
        from backend.skills import SkillLoader, SkillInjector
        
        skill_loader = getattr(self.executor, '_skill_loader', None)
        if not skill_loader:
            skill_loader = SkillLoader()
            # Add search paths
            skills_dir = self.config_manager.get_project_config_dir() / "skills"
            if skills_dir.exists():
                skill_loader.add_search_path(str(skills_dir))
            skill_loader.load_all_skills()
            self.executor._skill_loader = skill_loader
        
        action = parsed.action.lower()
        
        if action == "list":
            self.ui_renderer.print()
            self.ui_renderer.print("[bold]Available Skills:[/bold]")
            
            skills = skill_loader.get_all_skills()
            if not skills:
                self.ui_renderer.print("  [dim]No skills found.[/dim]")
                skills_dir = self.config_manager.get_project_config_dir() / "skills"
                self.ui_renderer.print(f"  [dim]Add skill directories to {skills_dir}[/dim]")
            else:
                for name, skill in skills.items():
                    status = "[green]enabled[/green]" if skill.enabled else "[dim]disabled[/dim]"
                    self.ui_renderer.print(f"  [cyan]{name}[/cyan] - {status}")
                    if skill.description:
                        self.ui_renderer.print(f"    [dim]{skill.description[:100]}[/dim]")
            
            self.ui_renderer.print()
            self.ui_renderer.print("[dim]Usage: /skills show <name> | /skills enable <name> | /skills disable <name>[/dim]")
            
        elif action == "show":
            if not parsed.name:
                self.ui_renderer.print_error("Specify skill name")
                return True
            
            skill = skill_loader.get_skill(parsed.name)
            if not skill:
                self.ui_renderer.print_error(f"Skill not found: {parsed.name}")
                return True
            
            self.ui_renderer.print()
            self.ui_renderer.print(f"[bold cyan]{skill.name}[/bold cyan]")
            if skill.description:
                self.ui_renderer.print(f"[dim]{skill.description}[/dim]")
            self.ui_renderer.print()
            self.ui_renderer.print(skill.content[:500])
            if len(skill.content) > 500:
                self.ui_renderer.print("[dim]... (truncated)[/dim]")
            self.ui_renderer.print()
            self.ui_renderer.print(f"[dim]Resources: {len(skill.resources)}[/dim]")
            
        elif action == "enable":
            if parsed.name:
                if skill_loader.enable_skill(parsed.name):
                    self.ui_renderer.print_success(f"Enabled skill: {parsed.name}")
                else:
                    self.ui_renderer.print_error(f"Skill not found: {parsed.name}")
            else:
                self.ui_renderer.print_error("Specify skill name")
                
        elif action == "disable":
            if parsed.name:
                if skill_loader.disable_skill(parsed.name):
                    self.ui_renderer.print(f"[dim]Disabled skill: {parsed.name}[/dim]")
                else:
                    self.ui_renderer.print_error(f"Skill not found: {parsed.name}")
            else:
                self.ui_renderer.print_error("Specify skill name")
        
        elif action == "reload":
            if parsed.name:
                skill = skill_loader.reload_skill(parsed.name)
                if skill:
                    self.ui_renderer.print_success(f"Reloaded skill: {parsed.name}")
                else:
                    self.ui_renderer.print_error(f"Failed to reload: {parsed.name}")
            else:
                # Reload all
                skill_loader.load_all_skills()
                self.ui_renderer.print_success("Reloaded all skills")
        
        return True
    
    def _cmd_new(self, args: str) -> bool:
        """Handle /new command."""
        import argparse
        
        parser = argparse.ArgumentParser(prog="/new", add_help=False)
        parser.add_argument("-s", "--save", action="store_true", help="Save current session before creating new")
        parser.add_argument("-t", "--title", default="", help="Title for the new session")
        
        try:
            parsed = parser.parse_args(args.split() if args else [])
        except SystemExit:
            return True
        
        # Save current session if requested or if it has messages
        if parsed.save and self.session_manager.has_session:
            if self.session_manager.save_current_session():
                self.ui_renderer.print_success("Current session saved")
        
        # End debug session if active
        if self.debug_logger.enabled:
            log_path = self.debug_logger.end_session()
            if log_path:
                self.ui_renderer.print(f"Debug log saved: {log_path}", style="dim")
        
        # Create new session
        agent = self.executor.state.current_agent if self.executor else "build"
        model = self.executor.state.current_model if self.executor else "main"
        
        session = self.session_manager.create_session(
            agent=agent,
            model=model,
            title=parsed.title,
        )
        
        # Reset executor messages
        self.executor.reset_messages()
        
        # Start debug session if enabled
        if self.debug_logger.enabled:
            self.debug_logger.start_session(agent, session.session_id)
        
        self.ui_renderer.print_success(f"Started new session: {session.session_id}")
        if parsed.title:
            self.ui_renderer.print(f"Title: {parsed.title}", style="dim")
        
        return True
    
    def _cmd_history(self, args: str) -> bool:
        """Handle /history command."""
        import argparse
        
        parser = argparse.ArgumentParser(prog="/history", add_help=False)
        parser.add_argument("action", nargs="?", default="list", help="Action: list, load, search, delete, info")
        parser.add_argument("target", nargs="?", default="", help="Session ID or search query")
        parser.add_argument("-l", "--limit", type=int, default=10, help="Number of results")
        parser.add_argument("-o", "--offset", type=int, default=0, help="Offset for pagination")
        
        try:
            parsed = parser.parse_args(args.split() if args else [])
        except SystemExit:
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
        
        sessions = self.session_manager.list_sessions(limit=limit, offset=offset)
        
        if not sessions:
            self.ui_renderer.print("  [dim]No sessions found.[/dim]")
            self.ui_renderer.print("  [dim]Sessions are automatically saved when you start a new one.[/dim]")
            return
        
        for session in sessions:
            # Format timestamps
            created = session.created_at.strftime("%Y-%m-%d %H:%M")
            updated = session.updated_at.strftime("%Y-%m-%d %H:%M")
            
            # Format title
            title = session.title or f"Session {session.session_id}"
            if len(title) > 40:
                title = title[:37] + "..."
            
            self.ui_renderer.print()
            self.ui_renderer.print(f"  [cyan]{session.session_id}[/cyan] - {title}")
            self.ui_renderer.print(f"    [dim]Agent: {session.agent} | Messages: {session.message_count}[/dim]")
            self.ui_renderer.print(f"    [dim]Created: {created} | Updated: {updated}[/dim]")
        
        # Show pagination info
        total = self.session_manager.get_session_count()
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
        
        # Check if session exists
        if not self.session_manager.storage.exists(session_id):
            self.ui_renderer.print_error(f"Session not found: {session_id}")
            return
        
        # Save current session
        if self.session_manager.has_session:
            self.session_manager.save_current_session()
        
        # End debug session
        if self.debug_logger.enabled:
            self.debug_logger.end_session()
        
        # Load session
        session = self.session_manager.load_session(session_id)
        
        if session:
            # Load messages into executor
            self.executor.load_messages(session.get_messages_for_model())
            
            # Switch to session's agent/model
            if session.metadata.agent:
                self.executor.switch_agent(session.metadata.agent)
            if session.metadata.model:
                self.executor.switch_model(session.metadata.model)
            
            # Start debug session
            if self.debug_logger.enabled:
                self.debug_logger.start_session(session.metadata.agent, session.session_id)
            
            self.ui_renderer.print_success(f"Loaded session: {session_id}")
            self.ui_renderer.print(f"  Title: {session.title}", style="dim")
            self.ui_renderer.print(f"  Messages: {len(session.messages)}", style="dim")
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
        
        results = self.session_manager.search_sessions(query, limit)
        
        if not results:
            self.ui_renderer.print("  [dim]No matching sessions found.[/dim]")
            return
        
        for result in results:
            title = result.title or f"Session {result.session_id}"
            self.ui_renderer.print()
            self.ui_renderer.print(f"  [cyan]{result.session_id}[/cyan] - {title}")
            if result.preview:
                self.ui_renderer.print(f"    [dim]Preview: {result.preview}[/dim]")
            self.ui_renderer.print(f"    [dim]Messages: {result.message_count}[/dim]")
    
    def _history_delete(self, session_id: str) -> None:
        """Delete a history session."""
        if not session_id:
            self.ui_renderer.print_error("Specify session ID")
            return
        
        # Check if trying to delete current session
        if (self.session_manager.current_session and 
            self.session_manager.current_session.session_id == session_id):
            self.ui_renderer.print_error("Cannot delete current session")
            self.ui_renderer.print("Start a new session first with /new", style="dim")
            return
        
        if self.session_manager.delete_session(session_id):
            self.ui_renderer.print_success(f"Deleted session: {session_id}")
        else:
            self.ui_renderer.print_error(f"Failed to delete session: {session_id}")
    
    def _history_info(self, session_id: str) -> None:
        """Show session info."""
        if not session_id:
            # Show current session info
            info = self.session_manager.get_session_info()
            if not info.get("active"):
                self.ui_renderer.print("No active session", style="dim")
                return
        else:
            # Load specific session info
            session = self.session_manager.storage.load(session_id)
            if not session:
                self.ui_renderer.print_error(f"Session not found: {session_id}")
                return
            info = {
                "session_id": session.session_id,
                "title": session.title,
                "agent": session.metadata.agent,
                "model": session.metadata.model,
                "message_count": len(session.messages),
                "created_at": session.metadata.created_at.isoformat(),
                "updated_at": session.metadata.updated_at.isoformat(),
            }
        
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
        count = self.session_manager.get_session_count()
        if count == 0:
            self.ui_renderer.print("No sessions to clear", style="dim")
            return
        
        self.ui_renderer.print(f"[yellow]This will delete {count} session(s).[/yellow]")
        self.ui_renderer.print("Type 'yes' to confirm: ", style="dim")
        
        # Note: In a real implementation, we'd get user input here
        # For now, just show the warning
        self.ui_renderer.print("Operation cancelled (confirmation required)", style="dim")
    
    def _cmd_debug(self, args: str) -> bool:
        """Handle /debug command."""
        import argparse
        
        parser = argparse.ArgumentParser(prog="/debug", add_help=False)
        parser.add_argument("action", nargs="?", default="status", help="Action: on, off, status, list, clean")
        
        try:
            parsed = parser.parse_args(args.split() if args else [])
        except SystemExit:
            return True
        
        action = parsed.action.lower()
        
        if action == "on":
            self.debug_logger.enable()
            self.config_manager.config.debug_mode = True
            self.ui_renderer.print_success("Debug mode enabled")
            self.ui_renderer.print(f"Logs will be saved to: {self.debug_logger.debug_dir}", style="dim")
            
            # Start debug session if there's an active session
            if self.session_manager.has_session:
                session = self.session_manager.current_session
                self.debug_logger.start_session(
                    self.executor.state.current_agent,
                    session.session_id if session else None
                )
        
        elif action == "off":
            # End current debug session
            log_path = self.debug_logger.end_session()
            if log_path:
                self.ui_renderer.print(f"Debug log saved: {log_path}", style="dim")
            
            self.debug_logger.disable()
            self.config_manager.config.debug_mode = False
            self.ui_renderer.print("Debug mode disabled", style="dim")
        
        elif action == "status":
            status = self.debug_logger.get_status()
            self.ui_renderer.print()
            self.ui_renderer.print("[bold]Debug Status[/bold]")
            self.ui_renderer.print(f"  Enabled: {'[green]Yes[/green]' if status['enabled'] else '[dim]No[/dim]'}")
            self.ui_renderer.print(f"  Log directory: {status['debug_dir']}")
            self.ui_renderer.print(f"  Log count: {status['log_count']}")
            if status['current_log']:
                self.ui_renderer.print(f"  Current log: {status['current_log']}")
        
        elif action == "list":
            logs = self.debug_logger.list_logs()
            if not logs:
                self.ui_renderer.print("No debug logs found", style="dim")
                return True
            
            self.ui_renderer.print()
            self.ui_renderer.print("[bold]Debug Logs[/bold]")
            for log in logs[:20]:  # Show last 20
                self.ui_renderer.print(f"  {log['agent']} - {log['start_time']}")
                self.ui_renderer.print(f"    [dim]Messages: {log['message_count']}, Tools: {log['tool_call_count']}[/dim]")
        
        elif action == "clean":
            removed = self.debug_logger.cleanup_old_logs(days=7)
            self.ui_renderer.print_success(f"Removed {removed} old debug log(s)")
        
        else:
            self.ui_renderer.print_error(f"Unknown action: {action}")
            self.ui_renderer.print("Usage: /debug on | off | status | list | clean", style="dim")
        
        return True
    
    def _cmd_compact(self, args: str) -> bool:
        """Handle /compact command."""
        import argparse
        
        parser = argparse.ArgumentParser(prog="/compact", add_help=False)
        parser.add_argument("--soft", action="store_true", help="Soft compaction only (clear tool results)")
        parser.add_argument("--hard", action="store_true", help="Hard compaction (restructure conversation)")
        parser.add_argument("--status", action="store_true", help="Show compaction status only")
        
        try:
            parsed = parser.parse_args(args.split() if args else [])
        except SystemExit:
            return True
        
        if not self.executor:
            self.ui_renderer.print_error("Executor not initialized")
            return True
        
        # Show status only
        if parsed.status:
            usage = self.executor.get_token_usage()
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
        
        result = self.executor.compact_context(force=force_hard, force_soft=force_soft)
        
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
        import argparse
        
        parser = argparse.ArgumentParser(prog="/context", add_help=False)
        parser.add_argument("action", nargs="?", default="status", help="Action: status, stats, clear")
        
        try:
            parsed = parser.parse_args(args.split() if args else [])
        except SystemExit:
            return True
        
        action = parsed.action.lower()
        
        if action == "status":
            if not self.executor:
                self.ui_renderer.print_error("Executor not initialized")
                return True
            
            usage = self.executor.get_token_usage()
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
            msg_count = len(self.executor.state.messages) if self.executor else 0
            self.ui_renderer.print(f"  Messages: {msg_count}")
            
            # Warning if approaching limit
            if usage.get('should_compact'):
                self.ui_renderer.print()
                self.ui_renderer.print("[yellow]Context is approaching limit.[/yellow]")
                self.ui_renderer.print("Use /compact to compress the context.", style="dim")
        
        elif action == "stats":
            # Show cache stats
            cache = self.executor.response_cache if self.executor else None
            if cache:
                stats = cache.get_stats()
                self.ui_renderer.print()
                self.ui_renderer.print("[bold]Cache Statistics[/bold]")
                self.ui_renderer.print(f"  Entries: {stats['entries']}/{stats['max_entries']}")
                self.ui_renderer.print(f"  Size: {stats['size_mb']}/{stats['max_size_mb']} MB")
                self.ui_renderer.print(f"  Total hits: {stats['total_hits']}")
            else:
                self.ui_renderer.print("Cache not initialized", style="dim")
        
        elif action == "clear":
            # Clear cache
            cache = self.executor.response_cache if self.executor else None
            if cache:
                cache.clear()
                self.ui_renderer.print_success("Cache cleared")
            else:
                self.ui_renderer.print("Cache not initialized", style="dim")
        
        else:
            self.ui_renderer.print_error(f"Unknown action: {action}")
            self.ui_renderer.print("Usage: /context status | stats | clear", style="dim")
        
        return True
    
    def _cmd_permission(self, args: str) -> bool:
        """Handle /permission command."""
        import argparse
        
        parser = argparse.ArgumentParser(prog="/permission", add_help=False)
        parser.add_argument("action", nargs="?", default="status", help="Action: status, grant, revoke, clear")
        parser.add_argument("type", nargs="?", default="", help="Permission type: write, edit, bash, bash_delete")
        
        try:
            parsed = parser.parse_args(args.split() if args else [])
        except SystemExit:
            return True
        
        # Get permission manager
        from backend.permission import get_permission_manager, PermissionType
        perm_manager = get_permission_manager()
        
        action = parsed.action.lower()
        
        if action == "status":
            # Show current permission status
            permissions = perm_manager.get_session_permissions()
            
            # Convert to display format
            display_perms = {}
            for perm_type, granted in permissions.items():
                display_perms[perm_type.value] = granted
            
            # Show in UI
            self.ui_renderer.show_permission_status(display_perms)
        
        elif action == "grant":
            if not parsed.type:
                self.ui_renderer.print_error("Specify permission type")
                self.ui_renderer.print("Usage: /permission grant <write|edit|bash|bash_delete>", style="dim")
                return True
            
            # Parse permission type
            try:
                perm_type = PermissionType(parsed.type.lower())
                perm_manager.grant_session_permission(perm_type)
                self.ui_renderer.print_success(f"Granted session permission: {parsed.type}")
            except ValueError:
                self.ui_renderer.print_error(f"Invalid permission type: {parsed.type}")
                self.ui_renderer.print("Available types: write, edit, bash, bash_delete", style="dim")
        
        elif action == "revoke":
            if not parsed.type:
                self.ui_renderer.print_error("Specify permission type")
                self.ui_renderer.print("Usage: /permission revoke <write|edit|bash|bash_delete>", style="dim")
                return True
            
            # Parse permission type
            try:
                perm_type = PermissionType(parsed.type.lower())
                perm_manager.revoke_session_permission(perm_type)
                self.ui_renderer.print(f"[dim]Revoked session permission: {parsed.type}[/dim]")
            except ValueError:
                self.ui_renderer.print_error(f"Invalid permission type: {parsed.type}")
                self.ui_renderer.print("Available types: write, edit, bash, bash_delete", style="dim")
        
        elif action == "clear":
            # Clear all session permissions
            perm_manager.clear_session_permissions()
            self.ui_renderer.print_success("Cleared all session permissions")
        
        else:
            self.ui_renderer.print_error(f"Unknown action: {action}")
            self.ui_renderer.print("Usage: /permission status | grant <type> | revoke <type> | clear", style="dim")
        
        return True
    
    def _register_mcp_tools(self, mcp_manager) -> None:
        """
        Register MCP tools to the tool registry.
        
        Args:
            mcp_manager: MCP manager instance with connected servers
        """
        if not self.executor or not self.executor.tool_registry:
            return
        
        # Create MCP tool wrappers
        mcp_tools = create_mcp_tools(mcp_manager)
        
        # Register each MCP tool to the tool registry
        registered_count = 0
        for tool in mcp_tools:
            # Unregister existing tool with same name if exists (for reconnection)
            if self.executor.tool_registry.get(tool.name):
                self.executor.tool_registry.unregister(tool.name)
            self.executor.tool_registry.register(tool)
            registered_count += 1
        
        if registered_count > 0:
            self.ui_renderer.print(f"[dim]Registered {registered_count} MCP tool(s)[/dim]")
    
    def _unregister_mcp_tools(self, mcp_manager, server_name: str = None) -> None:
        """
        Unregister MCP tools from the tool registry.
        
        Args:
            mcp_manager: MCP manager instance
            server_name: Optional specific server name to unregister tools for.
                        If None, unregisters all MCP tools.
        """
        if not self.executor or not self.executor.tool_registry:
            return
        
        unregistered_count = 0
        
        if server_name:
            # Unregister tools for specific server
            # Individual tools are named: mcp_{server_name}_{tool_name}
            prefix = f"mcp_{server_name}_"
            tools_to_remove = []
            
            for tool_name in list(self.executor.tool_registry.tools.keys()):
                if tool_name.startswith(prefix):
                    tools_to_remove.append(tool_name)
            
            for tool_name in tools_to_remove:
                if self.executor.tool_registry.unregister(tool_name):
                    unregistered_count += 1
        else:
            # Unregister all MCP tools
            # Remove the generic mcp_tool wrapper
            if self.executor.tool_registry.get("mcp_tool"):
                if self.executor.tool_registry.unregister("mcp_tool"):
                    unregistered_count += 1
            
            # Remove all individual MCP tools (those starting with "mcp_")
            tools_to_remove = []
            for tool_name in list(self.executor.tool_registry.tools.keys()):
                if tool_name.startswith("mcp_"):
                    tools_to_remove.append(tool_name)
            
            for tool_name in tools_to_remove:
                if self.executor.tool_registry.unregister(tool_name):
                    unregistered_count += 1
        
        if unregistered_count > 0:
            self.ui_renderer.print(f"[dim]Unregistered {unregistered_count} MCP tool(s)[/dim]")
    
    def _cmd_exit(self, args: str) -> bool:
        """Handle /exit command."""
        self.ui_renderer.print("Goodbye!", style="dim")
        return False
