"""Slash command system for Amplifier TUI.

Provides a command parser and handlers for TUI slash commands like:
- /bundle list, /bundle install, /bundle use
- /reset
- /help
- /clear
- /quit
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from .app import AmplifierTUI
    from .bridge import RuntimeBridge


class CommandResult(Enum):
    """Result of command execution."""

    SUCCESS = "success"
    ERROR = "error"
    QUIT = "quit"  # Signal to exit the TUI


@dataclass
class CommandResponse:
    """Response from a command execution."""

    result: CommandResult
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Command:
    """Parsed slash command."""

    name: str
    subcommand: str | None = None
    args: list[str] = field(default_factory=list)
    flags: dict[str, str | bool] = field(default_factory=dict)

    @classmethod
    def parse(cls, text: str) -> Command | None:
        """Parse a slash command from text.

        Returns None if text is not a slash command.

        Examples:
            /bundle list -> Command(name="bundle", subcommand="list")
            /bundle install git+https://... -> Command(name="bundle", subcommand="install", args=["git+..."])
            /reset --bundle recipes -> Command(name="reset", flags={"bundle": "recipes"})
        """
        text = text.strip()
        if not text.startswith("/"):
            return None

        try:
            parts = shlex.split(text[1:])  # Remove leading /
        except ValueError:
            # Malformed quotes, fall back to simple split
            parts = text[1:].split()

        if not parts:
            return None

        name = parts[0].lower()
        subcommand = None
        args = []
        flags: dict[str, str | bool] = {}

        i = 1
        while i < len(parts):
            part = parts[i]

            if part.startswith("--"):
                # Long flag
                flag_name = part[2:]
                if "=" in flag_name:
                    key, value = flag_name.split("=", 1)
                    flags[key] = value
                elif i + 1 < len(parts) and not parts[i + 1].startswith("-"):
                    flags[flag_name] = parts[i + 1]
                    i += 1
                else:
                    flags[flag_name] = True
            elif part.startswith("-"):
                # Short flag
                flag_name = part[1:]
                if i + 1 < len(parts) and not parts[i + 1].startswith("-"):
                    flags[flag_name] = parts[i + 1]
                    i += 1
                else:
                    flags[flag_name] = True
            elif subcommand is None and not args:
                # First non-flag after command is subcommand
                subcommand = part.lower()
            else:
                # Remaining are args
                args.append(part)

            i += 1

        return cls(name=name, subcommand=subcommand, args=args, flags=flags)


class CommandHandler:
    """Handles slash command execution."""

    def __init__(self, app: AmplifierTUI, bridge: RuntimeBridge) -> None:
        """Initialize command handler.

        Args:
            app: The TUI application instance
            bridge: The runtime bridge for SDK access
        """
        self.app = app
        self.bridge = bridge
        self._handlers: dict[str, Callable[[Command], Awaitable[CommandResponse]]] = {
            "help": self._handle_help,
            "h": self._handle_help,
            "?": self._handle_help,
            "bundle": self._handle_bundle,
            "b": self._handle_bundle,
            "reset": self._handle_reset,
            "clear": self._handle_clear,
            "quit": self._handle_quit,
            "exit": self._handle_quit,
            "q": self._handle_quit,
            "session": self._handle_session,
            "config": self._handle_config,
            "agents": self._handle_agents,
            "agent": self._handle_agents,
            "a": self._handle_agents,
            "init": self._handle_init,
            "tools": self._handle_tools,
            "status": self._handle_status,
            "mode": self._handle_mode,
            "modes": self._handle_modes,
        }

    def is_command(self, text: str) -> bool:
        """Check if text is a slash command."""
        return text.strip().startswith("/")

    async def execute(self, text: str) -> CommandResponse:
        """Execute a slash command.

        Args:
            text: The command text (including leading /)

        Returns:
            CommandResponse with result and message
        """
        cmd = Command.parse(text)
        if not cmd:
            return CommandResponse(
                result=CommandResult.ERROR,
                message="Invalid command format",
            )

        handler = self._handlers.get(cmd.name)
        if not handler:
            return CommandResponse(
                result=CommandResult.ERROR,
                message=f"Unknown command: /{cmd.name}\nType /help for available commands.",
            )

        try:
            return await handler(cmd)
        except Exception as e:
            return CommandResponse(
                result=CommandResult.ERROR,
                message=f"Command error: {e}",
            )

    # =========================================================================
    # Command Handlers
    # =========================================================================

    async def _handle_help(self, cmd: Command) -> CommandResponse:
        """Handle /help command."""
        if cmd.subcommand:
            # Help for specific command
            return self._get_command_help(cmd.subcommand)

        # Try to fetch commands from runtime
        commands_list = await self._fetch_runtime_commands()

        if commands_list:
            # Build dynamic help from runtime commands
            # Box width is 64 chars (62 inner + 2 for borders)
            BOX_WIDTH = 62
            lines = ["╭─ Available Commands " + "─" * (BOX_WIDTH - 21) + "╮"]
            lines.append("│" + " " * BOX_WIDTH + "│")

            for cmd_info in commands_list:
                name = cmd_info.get("name", "")
                desc = cmd_info.get("description", "")
                aliases = cmd_info.get("aliases", [])

                # Format: /command [aliases]   description
                alias_str = f" ({', '.join(aliases)})" if aliases else ""
                cmd_str = f"/{name}{alias_str}"
                # Truncate if needed
                if len(cmd_str) > 20:
                    cmd_str = cmd_str[:17] + "..."
                if len(desc) > 35:
                    desc = desc[:32] + "..."
                # Pad to exact width
                content = f"  {cmd_str:<20} {desc:<38}"
                lines.append(f"│{content}│")

            lines.append("│" + " " * BOX_WIDTH + "│")
            footer = "  Type /help <command> for detailed help on a command."
            lines.append(f"│{footer:<{BOX_WIDTH}}│")
            lines.append("╰" + "─" * BOX_WIDTH + "╯")

            help_text = "\n".join(lines)
        else:
            # Fallback to static help if runtime unavailable
            help_text = """
╭─ Available Commands ─────────────────────────────────────────╮
│                                                              │
│  /help [cmd]           Show help (or help for command)       │
│  /bundle <action>      Manage bundles                        │
│  /reset [--bundle]     Reset current session                 │
│  /session              Show session info                     │
│  /config               Show configuration                    │
│  /clear                Clear the conversation                │
│  /quit                 Exit the TUI                          │
│                                                              │
│  Type /help <command> for detailed help on a command.        │
╰──────────────────────────────────────────────────────────────╯
"""
        return CommandResponse(result=CommandResult.SUCCESS, message=help_text.strip())

    async def _fetch_runtime_commands(self) -> list[dict]:
        """Fetch available commands from the runtime."""
        if not self.bridge or not self.bridge.is_connected:
            return []

        try:
            data = await self.bridge._client.slash_commands.list()
            return data.get("commands", [])
        except Exception:
            return []

    def _get_command_help(self, command: str) -> CommandResponse:
        """Get detailed help for a specific command."""
        help_texts = {
            "bundle": """
╭─ /bundle - Bundle Management ────────────────────────────────╮
│                                                              │
│  /bundle list                  List available bundles        │
│  /bundle info <name>           Show bundle details           │
│  /bundle install <source>      Install from git URL/path     │
│  /bundle add <path> <name>     Register local bundle         │
│  /bundle remove <name>         Remove a bundle               │
│  /bundle use <name>            Reset session with bundle     │
│                                                              │
│  Examples:                                                   │
│    /bundle list                                              │
│    /bundle install git+https://github.com/.../recipes        │
│    /bundle use recipes                                       │
╰──────────────────────────────────────────────────────────────╯
""",
            "reset": """
╭─ /reset - Reset Session ─────────────────────────────────────╮
│                                                              │
│  /reset                        Reset current session         │
│  /reset --bundle <name>        Reset with different bundle   │
│  /reset --preserve             Preserve conversation history │
│                                                              │
│  Examples:                                                   │
│    /reset                                                    │
│    /reset --bundle amplifier-dev                             │
╰──────────────────────────────────────────────────────────────╯
""",
            "session": """
╭─ /session - Session Info ────────────────────────────────────╮
│                                                              │
│  /session                      Show current session info     │
│  /session list                 List all sessions             │
╰──────────────────────────────────────────────────────────────╯
""",
            "config": """
╭─ /config - Configuration ────────────────────────────────────╮
│                                                              │
│  /config                       Show current configuration    │
│  /config providers             List available providers      │
╰──────────────────────────────────────────────────────────────╯
""",
        }

        if command in help_texts:
            return CommandResponse(
                result=CommandResult.SUCCESS,
                message=help_texts[command].strip(),
            )

        return CommandResponse(
            result=CommandResult.ERROR,
            message=f"No help available for: {command}",
        )

    async def _handle_bundle(self, cmd: Command) -> CommandResponse:
        """Handle /bundle command."""
        if not cmd.subcommand:
            return self._get_command_help("bundle")

        client = self.bridge._client

        match cmd.subcommand:
            case "list" | "ls":
                bundles = await client.bundle.list()
                if not bundles:
                    return CommandResponse(
                        result=CommandResult.SUCCESS,
                        message="No bundles available.",
                    )

                lines = ["╭─ Available Bundles ─────────────────────────────────────────╮"]
                for b in bundles:
                    name = b.get("name", "unknown")
                    desc = b.get("description", "")[:40]
                    lines.append(f"│  {name:<20} {desc:<37} │")
                lines.append("╰──────────────────────────────────────────────────────────────╯")

                return CommandResponse(
                    result=CommandResult.SUCCESS,
                    message="\n".join(lines),
                    data={"bundles": bundles},
                )

            case "info":
                if not cmd.args:
                    return CommandResponse(
                        result=CommandResult.ERROR,
                        message="Usage: /bundle info <name>",
                    )
                name = cmd.args[0]
                try:
                    info = await client.bundle.info(name)
                    lines = [
                        f"╭─ Bundle: {name} ─────────────────────────────────────────────╮",
                        f"│  Name:        {info.get('name', 'N/A'):<44} │",
                        f"│  Description: {info.get('description', 'N/A')[:44]:<44} │",
                        f"│  Source:      {info.get('source', 'N/A'):<44} │",
                        f"│  Path:        {str(info.get('path', 'N/A'))[:44]:<44} │",
                        "╰──────────────────────────────────────────────────────────────╯",
                    ]
                    return CommandResponse(
                        result=CommandResult.SUCCESS,
                        message="\n".join(lines),
                        data=info,
                    )
                except Exception as e:
                    return CommandResponse(
                        result=CommandResult.ERROR,
                        message=f"Bundle not found: {name}\n{e}",
                    )

            case "install":
                if not cmd.args:
                    return CommandResponse(
                        result=CommandResult.ERROR,
                        message="Usage: /bundle install <source> [--name <name>]",
                    )
                source = cmd.args[0]
                name = cmd.flags.get("name") if isinstance(cmd.flags.get("name"), str) else None

                self.app.add_system_message(f"Installing bundle from {source}...")

                try:
                    async for event in client.bundle.install(source, name):
                        if event.type == "bundle.install.progress":
                            stage = event.data.get("stage", "")
                            msg = event.data.get("message", "")
                            self.app.add_system_message(f"  [{stage}] {msg}")
                        elif event.type == "result":
                            installed_name = event.data.get("name", "unknown")
                            return CommandResponse(
                                result=CommandResult.SUCCESS,
                                message=f"✓ Bundle '{installed_name}' installed successfully!",
                                data=event.data,
                            )
                        elif event.type == "error":
                            return CommandResponse(
                                result=CommandResult.ERROR,
                                message=f"Installation failed: {event.data.get('error')}",
                            )

                    return CommandResponse(
                        result=CommandResult.ERROR,
                        message="Installation completed without result",
                    )
                except Exception as e:
                    return CommandResponse(
                        result=CommandResult.ERROR,
                        message=f"Installation failed: {e}",
                    )

            case "add":
                if len(cmd.args) < 2:
                    return CommandResponse(
                        result=CommandResult.ERROR,
                        message="Usage: /bundle add <path> <name>",
                    )
                path, name = cmd.args[0], cmd.args[1]
                try:
                    result = await client.bundle.add(path, name)
                    return CommandResponse(
                        result=CommandResult.SUCCESS,
                        message=f"✓ Bundle '{name}' added from {path}",
                        data=result,
                    )
                except Exception as e:
                    return CommandResponse(
                        result=CommandResult.ERROR,
                        message=f"Failed to add bundle: {e}",
                    )

            case "remove" | "rm":
                if not cmd.args:
                    return CommandResponse(
                        result=CommandResult.ERROR,
                        message="Usage: /bundle remove <name>",
                    )
                name = cmd.args[0]
                try:
                    removed = await client.bundle.remove(name)
                    if removed:
                        return CommandResponse(
                            result=CommandResult.SUCCESS,
                            message=f"✓ Bundle '{name}' removed",
                        )
                    else:
                        return CommandResponse(
                            result=CommandResult.ERROR,
                            message=f"Bundle '{name}' not found",
                        )
                except Exception as e:
                    return CommandResponse(
                        result=CommandResult.ERROR,
                        message=f"Failed to remove bundle: {e}",
                    )

            case "use":
                if not cmd.args:
                    return CommandResponse(
                        result=CommandResult.ERROR,
                        message="Usage: /bundle use <name>",
                    )
                bundle_name = cmd.args[0]
                # Delegate to reset with bundle
                reset_cmd = Command(name="reset", flags={"bundle": bundle_name})
                return await self._handle_reset(reset_cmd)

            case _:
                return CommandResponse(
                    result=CommandResult.ERROR,
                    message=f"Unknown bundle action: {cmd.subcommand}\nType /help bundle for usage.",
                )

    async def _handle_reset(self, cmd: Command) -> CommandResponse:
        """Handle /reset command."""
        bundle = cmd.flags.get("bundle") if isinstance(cmd.flags.get("bundle"), str) else None
        preserve = bool(cmd.flags.get("preserve", False))

        session_id = self.bridge.session_id
        if not session_id:
            return CommandResponse(
                result=CommandResult.ERROR,
                message="No active session to reset",
            )

        try:
            self.app.add_system_message(
                f"Resetting session{f' with bundle {bundle}' if bundle else ''}..."
            )
        except Exception:
            pass  # App may not be fully mounted in test mode

        try:
            client = self.bridge._client
            new_session_id = None

            async for event in client.session.reset(
                session_id=session_id,
                bundle=bundle,
                preserve_history=preserve,
            ):
                if event.type == "session.reset.started":
                    try:
                        self.app.add_system_message("  Session reset started...")
                    except Exception:
                        pass
                elif event.type == "session.reset.completed":
                    new_session_id = event.data.get("new_session_id")
                    new_bundle = event.data.get("bundle")
                    # Update the bridge with new session
                    self.bridge._session_id = new_session_id
                    # Refresh completion data (agents/tools may have changed with new bundle)
                    await self.bridge.refresh_completion_data()
                    return CommandResponse(
                        result=CommandResult.SUCCESS,
                        message=f"✓ Session reset!\n  New session: {new_session_id}\n  Bundle: {new_bundle}",
                        data=event.data,
                    )
                elif event.type == "error":
                    return CommandResponse(
                        result=CommandResult.ERROR,
                        message=f"Reset failed: {event.data.get('error')}",
                    )

            return CommandResponse(
                result=CommandResult.ERROR,
                message="Reset completed without confirmation",
            )

        except Exception as e:
            return CommandResponse(
                result=CommandResult.ERROR,
                message=f"Reset failed: {e}",
            )

    async def _handle_session(self, cmd: Command) -> CommandResponse:
        """Handle /session command."""
        client = self.bridge._client

        if cmd.subcommand == "list":
            sessions = await client.session.list()
            if not sessions:
                return CommandResponse(
                    result=CommandResult.SUCCESS,
                    message="No active sessions.",
                )

            lines = ["╭─ Active Sessions ────────────────────────────────────────────╮"]
            for s in sessions:
                sid = s.session_id[:20]
                state = s.state
                bundle = s.bundle or "N/A"
                current = " ←" if s.session_id == self.bridge.session_id else ""
                lines.append(f"│  {sid:<20} {state:<10} {bundle:<15}{current:<5} │")
            lines.append("╰──────────────────────────────────────────────────────────────╯")

            return CommandResponse(
                result=CommandResult.SUCCESS,
                message="\n".join(lines),
            )

        # Default: show current session info
        session_id = self.bridge.session_id
        if not session_id:
            return CommandResponse(
                result=CommandResult.ERROR,
                message="No active session",
            )

        try:
            info = await client.session.get(session_id)
            turn_count = getattr(info, "turn_count", 0)
            lines = [
                "╭─ Current Session ────────────────────────────────────────────╮",
                f"│  Session ID:  {info.session_id:<44} │",
                f"│  State:       {(info.state or 'N/A'):<44} │",
                f"│  Bundle:      {(info.bundle or 'N/A'):<44} │",
                f"│  Turn Count:  {str(turn_count):<44} │",
                "╰──────────────────────────────────────────────────────────────╯",
            ]
            return CommandResponse(
                result=CommandResult.SUCCESS,
                message="\n".join(lines),
            )
        except Exception as e:
            return CommandResponse(
                result=CommandResult.ERROR,
                message=f"Failed to get session info: {e}",
            )

    async def _handle_config(self, cmd: Command) -> CommandResponse:
        """Handle /config command."""
        client = self.bridge._client

        if cmd.subcommand == "providers":
            providers = await client.config.list_providers()
            if not providers:
                return CommandResponse(
                    result=CommandResult.SUCCESS,
                    message="No providers configured.",
                )

            lines = ["╭─ Providers ───────────────────────────────────────────────────╮"]
            for p in providers:
                name = p.get("name", "unknown")
                available = "✓" if p.get("available") else "✗"
                env_var = p.get("env_var", "")
                lines.append(f"│  {available} {name:<15} ({env_var:<30}) │")
            lines.append("╰──────────────────────────────────────────────────────────────╯")

            return CommandResponse(
                result=CommandResult.SUCCESS,
                message="\n".join(lines),
            )

        # Default: show current config
        try:
            config = await client.config.get()
            lines = [
                "╭─ Configuration ──────────────────────────────────────────────╮",
                f"│  Default Bundle:   {config.get('default_bundle', 'N/A'):<39} │",
                f"│  Default Provider: {config.get('default_provider', 'N/A'):<39} │",
                f"│  Data Directory:   {config.get('data_dir', 'N/A')[:39]:<39} │",
                "╰──────────────────────────────────────────────────────────────╯",
            ]
            return CommandResponse(
                result=CommandResult.SUCCESS,
                message="\n".join(lines),
            )
        except Exception as e:
            return CommandResponse(
                result=CommandResult.ERROR,
                message=f"Failed to get config: {e}",
            )

    async def _handle_agents(self, cmd: Command) -> CommandResponse:
        """Handle /agents command.

        Subcommands:
            list (default) - List available agents
            info <name>    - Show agent details
        """
        client = self.bridge._client
        session_id = self.bridge.session_id

        subcommand = cmd.subcommand or "list"

        if subcommand in ("list", "ls"):
            return await self._agents_list(client, session_id)
        elif subcommand == "info":
            if not cmd.args:
                return CommandResponse(
                    result=CommandResult.ERROR,
                    message="Usage: /agents info <agent-name>",
                )
            return await self._agents_info(client, session_id, cmd.args[0])
        else:
            return CommandResponse(
                result=CommandResult.ERROR,
                message=f"Unknown subcommand: {subcommand}\nUsage: /agents [list|info <name>]",
            )

    async def _agents_list(self, client: Any, session_id: str | None) -> CommandResponse:
        """List available agents."""
        try:
            agents = await client.agents.list(session_id)

            if not agents:
                return CommandResponse(
                    result=CommandResult.SUCCESS,
                    message="No agents available in current bundle.",
                )

            # Format output
            lines = [
                "╭─ Available Agents ────────────────────────────────────────────╮",
            ]

            for agent in agents:
                name = agent.get("name", "unknown")
                desc = agent.get("description", "")[:40]
                if len(agent.get("description", "")) > 40:
                    desc += "..."
                lines.append(f"│  @{name:<20} {desc:<36} │")

            lines.append("├────────────────────────────────────────────────────────────────┤")
            lines.append(
                f"│  Total: {len(agents)} agents                                          │"
            )
            lines.append("│                                                                │")
            lines.append("│  Tip: Use @agent-name in your prompt to invoke an agent       │")
            lines.append("│       Type /agents info <name> for details                    │")
            lines.append("╰────────────────────────────────────────────────────────────────╯")

            return CommandResponse(
                result=CommandResult.SUCCESS,
                message="\n".join(lines),
                data={"agents": agents},
            )

        except Exception as e:
            return CommandResponse(
                result=CommandResult.ERROR,
                message=f"Failed to list agents: {e}",
            )

    async def _agents_info(self, client: Any, session_id: str | None, name: str) -> CommandResponse:
        """Get detailed info about an agent."""
        try:
            # Remove @ prefix if present
            if name.startswith("@"):
                name = name[1:]

            info = await client.agents.info(name, session_id)

            # Format output
            lines = [
                f"╭─ Agent: @{name} ─────────────────────────────────────────────╮",
                f"│  Description: {info.get('description', 'N/A')[:46]:<46} │",
                f"│  Bundle:      {info.get('bundle', 'N/A'):<46} │",
            ]

            # Show truncated instructions if available
            instructions = info.get("instructions", "")
            if instructions:
                lines.append("├────────────────────────────────────────────────────────────────┤")
                lines.append("│  Instructions (preview):                                       │")
                # Show first 200 chars
                preview = instructions[:200].replace("\n", " ")
                if len(instructions) > 200:
                    preview += "..."
                # Wrap to fit
                while preview:
                    chunk = preview[:58]
                    preview = preview[58:]
                    lines.append(f"│    {chunk:<58} │")

            lines.append("╰────────────────────────────────────────────────────────────────╯")

            return CommandResponse(
                result=CommandResult.SUCCESS,
                message="\n".join(lines),
                data=info,
            )

        except Exception as e:
            return CommandResponse(
                result=CommandResult.ERROR,
                message=f"Failed to get agent info: {e}",
            )

    async def _handle_init(self, cmd: Command) -> CommandResponse:
        """Handle /init command - interactive configuration setup."""
        # For now, show a helpful message about configuration
        # In the future, this will launch an interactive config wizard
        lines = [
            "╭─ Configuration Setup ──────────────────────────────────────────╮",
            "│                                                                │",
            "│  The /init command helps you configure Amplifier.             │",
            "│                                                                │",
            "│  Configuration locations:                                      │",
            "│    • ~/.amplifier/settings.yaml  - Global settings            │",
            "│    • .amplifier/settings.yaml    - Project settings           │",
            "│                                                                │",
            "│  Quick setup:                                                  │",
            "│    1. Set your API key:                                        │",
            "│       export ANTHROPIC_API_KEY=your-key                       │",
            "│                                                                │",
            "│    2. Install a provider:                                      │",
            "│       /bundle install anthropic                                │",
            "│                                                                │",
            "│    3. Set active bundle:                                       │",
            "│       /bundle use foundation                                   │",
            "│                                                                │",
            "│  Use /config to view current configuration.                    │",
            "│                                                                │",
            "╰────────────────────────────────────────────────────────────────╯",
        ]
        return CommandResponse(
            result=CommandResult.SUCCESS,
            message="\n".join(lines),
        )

    async def _handle_tools(self, cmd: Command) -> CommandResponse:
        """Handle /tools command - list available tools."""
        try:
            # Get tools from session metadata or bundle
            session_id = self.bridge.session_id
            if not session_id:
                return CommandResponse(
                    result=CommandResult.ERROR,
                    message="No active session.",
                )

            # Try to get session info which may include tools
            info = await self.bridge._client.session.info(session_id)
            tools = info.get("tools", [])

            if not tools:
                return CommandResponse(
                    result=CommandResult.SUCCESS,
                    message="No tools available in current session.",
                )

            lines = [
                "╭─ Available Tools ─────────────────────────────────────────────╮",
            ]

            for tool in tools:
                if isinstance(tool, str):
                    lines.append(f"│  • {tool:<58} │")
                elif isinstance(tool, dict):
                    name = tool.get("name", tool.get("module", "unknown"))
                    lines.append(f"│  • {name:<58} │")

            lines.append("├────────────────────────────────────────────────────────────────┤")
            lines.append(
                f"│  Total: {len(tools)} tools                                            │"
            )
            lines.append("╰────────────────────────────────────────────────────────────────╯")

            return CommandResponse(
                result=CommandResult.SUCCESS,
                message="\n".join(lines),
                data={"tools": tools},
            )
        except Exception as e:
            return CommandResponse(
                result=CommandResult.ERROR,
                message=f"Failed to list tools: {e}",
            )

    async def _handle_status(self, cmd: Command) -> CommandResponse:
        """Handle /status command - show session status."""
        try:
            session_id = self.bridge.session_id
            if not session_id:
                return CommandResponse(
                    result=CommandResult.SUCCESS,
                    message="No active session.",
                )

            info = await self.bridge._client.session.info(session_id)

            lines = [
                "╭─ Session Status ──────────────────────────────────────────────╮",
                f"│  Session ID: {session_id:<48} │",
                f"│  State:      {info.get('state', 'unknown'):<48} │",
                f"│  Bundle:     {info.get('bundle', 'N/A'):<48} │",
                f"│  Messages:   {info.get('message_count', 0):<48} │",
            ]

            if info.get("created_at"):
                lines.append(f"│  Created:    {info.get('created_at', ''):<48} │")

            lines.append("╰────────────────────────────────────────────────────────────────╯")

            return CommandResponse(
                result=CommandResult.SUCCESS,
                message="\n".join(lines),
                data=info,
            )
        except Exception as e:
            return CommandResponse(
                result=CommandResult.ERROR,
                message=f"Failed to get status: {e}",
            )

    async def _handle_mode(self, cmd: Command) -> CommandResponse:
        """Handle /mode command - set or toggle a mode."""
        mode_name = cmd.subcommand or (cmd.args[0] if cmd.args else None)

        if not mode_name:
            return CommandResponse(
                result=CommandResult.SUCCESS,
                message="Usage: /mode <mode-name>\n\nAvailable modes: careful, explore, plan\n\nUse /modes for details.",
            )

        # Mode shortcuts
        mode_descriptions = {
            "careful": "Full capability with confirmation for destructive actions",
            "explore": "Zero-footprint exploration - understand before acting",
            "plan": "Analyze, strategize, and organize - but don't implement",
        }

        if mode_name in mode_descriptions:
            return CommandResponse(
                result=CommandResult.SUCCESS,
                message=f"Mode '{mode_name}' activated: {mode_descriptions[mode_name]}",
                data={"mode": mode_name},
            )
        else:
            return CommandResponse(
                result=CommandResult.ERROR,
                message=f"Unknown mode: {mode_name}\n\nAvailable modes: careful, explore, plan",
            )

    async def _handle_modes(self, cmd: Command) -> CommandResponse:
        """Handle /modes command - list available modes."""
        lines = [
            "╭─ Available Modes ─────────────────────────────────────────────╮",
            "│                                                                │",
            "│  /careful   Full capability with confirmation for             │",
            "│             destructive actions                               │",
            "│                                                                │",
            "│  /explore   Zero-footprint exploration - understand           │",
            "│             before acting                                      │",
            "│                                                                │",
            "│  /plan      Analyze, strategize, and organize -               │",
            "│             but don't implement                                │",
            "│                                                                │",
            "├────────────────────────────────────────────────────────────────┤",
            "│  Usage: /mode <name> or /<name> (e.g., /careful)              │",
            "╰────────────────────────────────────────────────────────────────╯",
        ]
        return CommandResponse(
            result=CommandResult.SUCCESS,
            message="\n".join(lines),
        )

    async def _handle_clear(self, cmd: Command) -> CommandResponse:
        """Handle /clear command."""
        # Clear the conversation display
        self.app.clear_conversation()
        return CommandResponse(
            result=CommandResult.SUCCESS,
            message="Conversation cleared.",
        )

    async def _handle_quit(self, cmd: Command) -> CommandResponse:
        """Handle /quit command."""
        return CommandResponse(
            result=CommandResult.QUIT,
            message="Goodbye!",
        )
