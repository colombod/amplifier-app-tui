"""Command suggester for slash command autocomplete.

Provides intelligent completions for:
- Top-level commands (/help, /bundle, /reset, etc.)
- Subcommands (/bundle list, /bundle install, etc.)
- Dynamic values (bundle names, session IDs)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from textual.suggester import Suggester

if TYPE_CHECKING:
    from .bridge import RuntimeBridge


@dataclass
class CommandSpec:
    """Specification for a command's completions."""

    name: str
    aliases: list[str] = field(default_factory=list)
    subcommands: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    # For dynamic completions (e.g., bundle names)
    dynamic_arg: str | None = None  # "bundles", "sessions", etc.


# Command specifications
COMMANDS: dict[str, CommandSpec] = {
    "help": CommandSpec(
        name="help",
        aliases=["h", "?"],
        subcommands=["bundle", "reset", "session", "config", "clear", "quit"],
    ),
    "bundle": CommandSpec(
        name="bundle",
        aliases=["b"],
        subcommands=["list", "ls", "info", "install", "add", "remove", "rm", "use"],
        flags=["--name"],
        dynamic_arg="bundles",  # For info, use, remove
    ),
    "reset": CommandSpec(
        name="reset",
        flags=["--bundle", "--preserve"],
        dynamic_arg="bundles",  # For --bundle value
    ),
    "session": CommandSpec(
        name="session",
        subcommands=["list"],
        dynamic_arg="sessions",
    ),
    "config": CommandSpec(
        name="config",
        subcommands=["providers"],
    ),
    "clear": CommandSpec(name="clear"),
    "quit": CommandSpec(name="quit", aliases=["exit", "q"]),
}

# Build alias -> canonical name mapping
ALIAS_MAP: dict[str, str] = {}
for cmd_name, spec in COMMANDS.items():
    ALIAS_MAP[cmd_name] = cmd_name
    for alias in spec.aliases:
        ALIAS_MAP[alias] = cmd_name


class CommandSuggester(Suggester):
    """Intelligent suggester for slash commands and @agent mentions.

    Provides context-aware completions:
    - `/` -> shows all commands
    - `/b` -> completes to `/bundle`
    - `/bundle ` -> shows subcommands (list, install, etc.)
    - `/bundle use ` -> shows available bundle names
    - `/reset --` -> shows flags (--bundle, --preserve)
    - `@` -> shows available agents
    - `@found` -> completes to `@foundation:explorer`
    """

    def __init__(self, bridge: RuntimeBridge | None = None) -> None:
        """Initialize the suggester.

        Args:
            bridge: Runtime bridge for dynamic completions (optional)
        """
        super().__init__(use_cache=False)  # Don't cache - we have dynamic values
        self._bridge = bridge
        self._cached_bundles: list[str] | None = None
        self._cached_sessions: list[str] | None = None
        self._cached_agents: list[str] | None = None
        self._cached_tools: list[str] | None = None
        # Dynamic commands from runtime
        self._cached_commands: dict[str, CommandSpec] | None = None
        self._cached_alias_map: dict[str, str] | None = None

    def set_bridge(self, bridge: RuntimeBridge) -> None:
        """Set the runtime bridge for dynamic completions."""
        self._bridge = bridge
        # Clear caches
        self._cached_bundles = None
        self._cached_sessions = None
        self._cached_agents = None
        self._cached_tools = None
        self._cached_commands = None
        self._cached_alias_map = None

    async def _get_bundles(self) -> list[str]:
        """Get available bundle names."""
        if self._cached_bundles is not None:
            return self._cached_bundles

        if not self._bridge or not self._bridge.is_connected:
            return []

        try:
            bundles = await self._bridge._client.bundle.list()
            self._cached_bundles = [b.get("name", "") for b in bundles if b.get("name")]
            return self._cached_bundles
        except Exception:
            return []

    async def _get_sessions(self) -> list[str]:
        """Get available session IDs."""
        if self._cached_sessions is not None:
            return self._cached_sessions

        if not self._bridge or not self._bridge.is_connected:
            return []

        try:
            sessions = await self._bridge._client.session.list()
            self._cached_sessions = [s.session_id for s in sessions]
            return self._cached_sessions
        except Exception:
            return []

    async def _get_agents(self) -> list[str]:
        """Get available agent names."""
        if self._cached_agents is not None:
            return self._cached_agents

        if not self._bridge or not self._bridge.is_connected:
            return []

        try:
            agents = await self._bridge._client.agents.list(self._bridge.session_id)
            self._cached_agents = [a.get("name", "") for a in agents if a.get("name")]
            return self._cached_agents
        except Exception:
            return []

    async def _get_tools(self) -> list[str]:
        """Get available tool names for completion."""
        if self._cached_tools is not None:
            return self._cached_tools

        if not self._bridge or not self._bridge.is_connected:
            return []

        try:
            tools = await self._bridge._client.tools.list(self._bridge.session_id)
            self._cached_tools = [t.get("name", "") for t in tools if t.get("name")]
            return self._cached_tools
        except Exception:
            return []

    def invalidate_cache(self) -> None:
        """Clear cached dynamic values."""
        self._cached_bundles = None
        self._cached_sessions = None
        self._cached_agents = None
        self._cached_tools = None
        self._cached_commands = None
        self._cached_alias_map = None

    async def _get_commands(self) -> tuple[dict[str, CommandSpec], dict[str, str]]:
        """Get commands and alias map, fetching from runtime if connected."""
        if self._cached_commands is not None and self._cached_alias_map is not None:
            return self._cached_commands, self._cached_alias_map

        # Start with static fallback
        commands = dict(COMMANDS)
        alias_map = dict(ALIAS_MAP)

        if self._bridge and self._bridge.is_connected:
            try:
                # Fetch from runtime
                data = await self._bridge._client.slash_commands.list()
                runtime_commands = data.get("commands", [])
                mode_shortcuts = data.get("mode_shortcuts", [])

                # Convert to CommandSpec objects
                for cmd in runtime_commands:
                    name = cmd.get("name", "")
                    if not name:
                        continue

                    # Extract subcommand names
                    subcommands = [
                        s.get("name", "") for s in cmd.get("subcommands", []) if s.get("name")
                    ]

                    spec = CommandSpec(
                        name=name,
                        aliases=cmd.get("aliases", []),
                        subcommands=subcommands,
                        flags=cmd.get("flags", []),
                        dynamic_arg=cmd.get("dynamic_arg"),
                    )
                    commands[name] = spec

                    # Update alias map
                    alias_map[name] = name
                    for alias in spec.aliases:
                        alias_map[alias] = name

                # Add mode shortcuts as commands
                for mode in mode_shortcuts:
                    name = mode.get("name", "")
                    if name:
                        commands[name] = CommandSpec(name=name, aliases=[])
                        alias_map[name] = name

            except Exception:
                pass  # Fall back to static commands

        self._cached_commands = commands
        self._cached_alias_map = alias_map
        return commands, alias_map

    async def get_suggestion(self, value: str) -> str | None:
        """Get a completion suggestion for the current input.

        Args:
            value: Current input value

        Returns:
            Suggested completion or None
        """
        # Check for @agent completion anywhere in the input
        agent_suggestion = await self._complete_agent_mention(value)
        if agent_suggestion:
            return agent_suggestion

        # Check for tool name completion (e.g., "tool-bas" -> "tool-bash")
        tool_suggestion = await self._complete_tool_mention(value)
        if tool_suggestion:
            return tool_suggestion

        # Check for slash command completion
        if not value.startswith("/"):
            return None

        # Parse current input
        parts = value[1:].split()  # Remove leading /

        if not parts:
            # Just "/" - suggest first command
            return "/help"

        # Get the command (first part)
        cmd_text = parts[0].lower()

        # Get dynamic commands
        commands, alias_map = await self._get_commands()

        # Case 1: Still typing the command name
        if len(parts) == 1 and not value.endswith(" "):
            return await self._complete_command(cmd_text, commands, alias_map)

        # Case 2: Command complete, looking for subcommand/flag/arg
        canonical = alias_map.get(cmd_text)
        if not canonical or canonical not in commands:
            return None

        spec = commands[canonical]

        # What comes after the command?
        remaining = parts[1:] if len(parts) > 1 else []
        last_part = remaining[-1] if remaining else ""
        ends_with_space = value.endswith(" ")

        # Case 2a: Looking for subcommand
        if not remaining or (len(remaining) == 1 and not ends_with_space):
            if spec.subcommands:
                return self._complete_subcommand(
                    value, canonical, last_part, ends_with_space, commands
                )

        # Case 2b: Looking for flag
        if last_part.startswith("-") and not ends_with_space:
            return self._complete_flag(value, spec, last_part)

        # Case 2c: After a flag that expects a value (e.g., --bundle)
        if len(remaining) >= 1:
            prev_part = remaining[-2] if len(remaining) >= 2 else remaining[-1] if remaining else ""
            if prev_part in ("--bundle", "-b") and spec.dynamic_arg == "bundles":
                if ends_with_space or not last_part.startswith("-"):
                    return await self._complete_dynamic(
                        value, "bundles", last_part if not ends_with_space else ""
                    )

        # Case 2d: Dynamic arg completion (e.g., bundle name for /bundle use)
        if spec.dynamic_arg and len(remaining) >= 1:
            subcommand = remaining[0] if remaining else ""
            # These subcommands expect a bundle/session name
            if subcommand in ("use", "info", "remove", "rm"):
                if ends_with_space or len(remaining) == 2:
                    arg_to_complete = (
                        "" if ends_with_space else (remaining[1] if len(remaining) > 1 else "")
                    )
                    return await self._complete_dynamic(value, spec.dynamic_arg, arg_to_complete)

        return None

    async def _complete_agent_mention(self, value: str) -> str | None:
        """Complete @agent mentions anywhere in the input.

        Handles:
        - `@` at start or after space -> suggest first agent
        - `@partial` -> complete agent name
        - `text @partial` -> complete agent name preserving prefix
        """
        # Find the last @ in the input
        at_pos = value.rfind("@")
        if at_pos == -1:
            return None

        # Check if @ is at start or after whitespace (not in middle of word)
        if at_pos > 0 and not value[at_pos - 1].isspace():
            return None

        # Get the partial agent name after @
        partial = value[at_pos + 1 :]

        # If there's a space after the partial, the mention is complete
        if " " in partial:
            return None

        # Get available agents
        agents = await self._get_agents()
        if not agents:
            return None

        # Find matching agent
        partial_lower = partial.lower()
        matches = [a for a in agents if a.lower().startswith(partial_lower)]

        if matches:
            # Return full input with completed agent name
            prefix = value[:at_pos]
            return f"{prefix}@{matches[0]}"

        return None

    async def _complete_tool_mention(self, value: str) -> str | None:
        """Complete tool names in the input.

        Triggers on patterns like:
        - `tool-` -> suggest tool names starting with "tool-"
        - `use tool-bas` -> complete to "use tool-bash"
        - Word boundaries only (not mid-word)
        """
        # Find potential tool name patterns
        # Tools typically start with "tool-" prefix
        words = value.split()
        if not words:
            return None

        last_word = words[-1]

        # Check if last word looks like a partial tool name
        # Tools usually have "tool-" prefix
        if not last_word.startswith("tool-") and not last_word.startswith("tool_"):
            return None

        # Don't complete if word is already complete (followed by space)
        if value.endswith(" "):
            return None

        # Get available tools
        tools = await self._get_tools()
        if not tools:
            return None

        # Find matching tool
        partial_lower = last_word.lower()
        matches = [t for t in tools if t.lower().startswith(partial_lower)]

        if matches:
            # Return full input with completed tool name
            prefix = value[: value.rfind(last_word)]
            return f"{prefix}{matches[0]}"

        return None

    async def _complete_command(
        self,
        partial: str,
        commands: dict[str, CommandSpec],
        alias_map: dict[str, str],
    ) -> str | None:
        """Complete a partial command name."""
        # First check for exact alias match -> return canonical form
        if partial in alias_map:
            canonical = alias_map[partial]
            return f"/{canonical}"

        # Check all commands (prefer canonical names over aliases)
        canonical_matches = [cmd for cmd in commands if cmd.startswith(partial)]
        if canonical_matches:
            return f"/{sorted(canonical_matches)[0]}"

        # Check aliases
        alias_matches = []
        for alias, canonical in alias_map.items():
            if alias.startswith(partial) and alias not in commands:
                alias_matches.append(canonical)

        if alias_matches:
            return f"/{sorted(set(alias_matches))[0]}"

        return None

    def _complete_subcommand(
        self,
        value: str,
        command: str,
        partial: str,
        ends_with_space: bool,
        commands: dict[str, CommandSpec],
    ) -> str | None:
        """Complete a subcommand."""
        spec = commands[command]

        if ends_with_space:
            # Suggest first subcommand
            if spec.subcommands:
                return f"{value}{spec.subcommands[0]}"
        else:
            # Complete partial subcommand
            matches = [sub for sub in spec.subcommands if sub.startswith(partial)]
            if matches:
                # Replace partial with complete subcommand
                base = value.rsplit(partial, 1)[0]
                return f"{base}{matches[0]}"

        return None

    def _complete_flag(self, value: str, spec: CommandSpec, partial: str) -> str | None:
        """Complete a flag."""
        matches = [f for f in spec.flags if f.startswith(partial)]
        if matches:
            base = value.rsplit(partial, 1)[0]
            return f"{base}{matches[0]}"
        return None

    async def _complete_dynamic(self, value: str, arg_type: str, partial: str) -> str | None:
        """Complete a dynamic argument (bundle name, session ID, etc.)."""
        if arg_type == "bundles":
            options = await self._get_bundles()
        elif arg_type == "sessions":
            options = await self._get_sessions()
        else:
            return None

        if not options:
            return None

        if partial:
            matches = [opt for opt in options if opt.startswith(partial)]
            if matches:
                base = value.rsplit(partial, 1)[0]
                return f"{base}{matches[0]}"
        else:
            # Suggest first option
            return f"{value}{options[0]}"

        return None


class CommandCompletions:
    """Provides completion lists for command UI (dropdown menus, etc.)."""

    def __init__(self, bridge: RuntimeBridge | None = None) -> None:
        self._bridge = bridge

    def get_commands(self) -> list[tuple[str, str]]:
        """Get all commands with descriptions.

        Returns:
            List of (command, description) tuples
        """
        return [
            ("/help", "Show help"),
            ("/bundle", "Manage bundles"),
            ("/reset", "Reset session"),
            ("/session", "Session info"),
            ("/config", "Configuration"),
            ("/clear", "Clear output"),
            ("/quit", "Exit TUI"),
        ]

    def get_subcommands(self, command: str) -> list[tuple[str, str]]:
        """Get subcommands for a command.

        Returns:
            List of (subcommand, description) tuples
        """
        descriptions = {
            "bundle": [
                ("list", "List available bundles"),
                ("info", "Show bundle details"),
                ("install", "Install from git/path"),
                ("add", "Register local bundle"),
                ("remove", "Remove bundle"),
                ("use", "Switch to bundle"),
            ],
            "session": [
                ("list", "List all sessions"),
            ],
            "config": [
                ("providers", "List providers"),
            ],
            "help": [
                ("bundle", "Bundle command help"),
                ("reset", "Reset command help"),
                ("session", "Session command help"),
            ],
        }
        return descriptions.get(command, [])

    async def get_bundle_names(self) -> list[str]:
        """Get available bundle names for completion."""
        if not self._bridge or not self._bridge.is_connected:
            return []

        try:
            bundles = await self._bridge._client.bundle.list()
            return [b.get("name", "") for b in bundles if b.get("name")]
        except Exception:
            return []
