"""Completion providers for the autocomplete dropdown menu.

Provides rich completion items for:
- /commands (with descriptions)
- @agents (with bundle info)
- tool-* references

Uses textual-autocomplete for the dropdown UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from textual.content import Content
from textual_autocomplete import DropdownItem, TargetState

if TYPE_CHECKING:
    from .bridge import RuntimeBridge


@dataclass
class CommandInfo:
    """Information about a command for completion."""

    name: str
    description: str
    category: str = "command"  # command, subcommand, flag
    aliases: list[str] = field(default_factory=list)


# Built-in commands with descriptions
COMMANDS: dict[str, CommandInfo] = {
    "/help": CommandInfo(
        name="/help",
        description="Show help information",
        aliases=["/h", "/?"],
    ),
    "/bundle": CommandInfo(
        name="/bundle",
        description="Manage bundles",
        aliases=["/b"],
    ),
    "/bundle list": CommandInfo(
        name="/bundle list",
        description="List installed bundles",
        category="subcommand",
    ),
    "/bundle install": CommandInfo(
        name="/bundle install",
        description="Install a bundle from URL",
        category="subcommand",
    ),
    "/bundle use": CommandInfo(
        name="/bundle use",
        description="Set the active bundle",
        category="subcommand",
    ),
    "/bundle info": CommandInfo(
        name="/bundle info",
        description="Show bundle details",
        category="subcommand",
    ),
    "/reset": CommandInfo(
        name="/reset",
        description="Reset the session",
    ),
    "/clear": CommandInfo(
        name="/clear",
        description="Clear the output",
    ),
    "/session": CommandInfo(
        name="/session",
        description="Session management",
    ),
    "/session list": CommandInfo(
        name="/session list",
        description="List recent sessions",
        category="subcommand",
    ),
    "/config": CommandInfo(
        name="/config",
        description="Configuration settings",
    ),
    "/config providers": CommandInfo(
        name="/config providers",
        description="Show configured providers",
        category="subcommand",
    ),
    "/quit": CommandInfo(
        name="/quit",
        description="Exit the application",
        aliases=["/exit", "/q"],
    ),
    "/mode": CommandInfo(
        name="/mode",
        description="Toggle operational mode",
    ),
    "/modes": CommandInfo(
        name="/modes",
        description="List available modes",
    ),
}

# Category icons for visual distinction
CATEGORY_ICONS = {
    "command": "⌘",
    "subcommand": "  →",
    "flag": "  --",
    "agent": "@",
    "tool": "🔧",
    "bundle": "📦",
}


class CompletionProvider:
    """Provides completion items for the autocomplete dropdown.

    Handles three types of completions:
    - Commands: /help, /bundle, etc.
    - Agents: @foundation:explorer, etc.
    - Tools: tool-web, tool-bash, etc.
    """

    def __init__(self, bridge: RuntimeBridge | None = None) -> None:
        self._bridge = bridge
        self._cached_agents: list[str] | None = None
        self._cached_tools: list[str] | None = None
        self._cached_bundles: list[str] | None = None

    def set_bridge(self, bridge: RuntimeBridge) -> None:
        """Set the runtime bridge for dynamic completions."""
        self._bridge = bridge
        # Clear caches when bridge changes
        self._cached_agents = None
        self._cached_tools = None
        self._cached_bundles = None

    def get_candidates(self, state: TargetState) -> list[DropdownItem]:
        """Get completion candidates based on current input.

        This is called by textual-autocomplete on each keystroke.

        Args:
            state: Current state of the input (text, cursor position)

        Returns:
            List of DropdownItem for the dropdown menu
        """
        text = state.text.strip()

        # Determine completion context
        if text.startswith("/"):
            return self._get_command_completions(text)
        elif text.startswith("@"):
            return self._get_agent_completions(text)
        elif "tool-" in text.lower():
            return self._get_tool_completions(text)
        elif not text:
            # Empty input - show common commands
            return self._get_discovery_items()

        return []

    def _get_command_completions(self, text: str) -> list[DropdownItem]:
        """Get command completions for /commands."""
        items: list[tuple[str, DropdownItem]] = []  # (sort_key, item)
        text_lower = text.lower()

        for cmd_name, cmd_info in COMMANDS.items():
            # Check if input matches command or aliases
            if cmd_name.lower().startswith(text_lower):
                items.append((cmd_name, self._make_command_item(cmd_info)))
            elif any(alias.lower().startswith(text_lower) for alias in cmd_info.aliases):
                items.append((cmd_name, self._make_command_item(cmd_info)))

        # Sort: exact prefix matches first, then by name
        items.sort(key=lambda x: (not x[0].lower().startswith(text_lower), x[0]))

        return [item for _, item in items[:10]]  # Limit to 10 items

    def _get_agent_completions(self, text: str) -> list[DropdownItem]:
        """Get agent completions for @mentions.

        IMPORTANT: main text is what gets inserted, so it should be just @agent_name
        """
        agents = self._get_agents()
        items = []
        search = text[1:].lower() if text.startswith("@") else text.lower()

        for agent in agents:
            agent_lower = agent.lower()
            if search in agent_lower or not search:
                # Parse agent name for display
                if ":" in agent:
                    bundle, _name = agent.split(":", 1)
                    description = f"from {bundle}"
                else:
                    description = ""

                # Main is ONLY @agent (what gets inserted on Tab)
                # Description goes in prefix so it displays but doesn't get inserted
                prefix_text = f"[bold cyan]{CATEGORY_ICONS['agent']}[/] "
                if description:
                    prefix_text = (
                        f"[bold cyan]{CATEGORY_ICONS['agent']}[/] [dim]{description:<20}[/dim] "
                    )

                items.append(
                    DropdownItem(
                        main=f"@{agent}",  # Just the @agent - this gets inserted
                        prefix=Content.from_markup(prefix_text),
                    )
                )

        # Sort by match quality
        def get_sort_key(item: DropdownItem) -> tuple:
            main_str = str(item.main)
            return (search not in main_str.lower()[: len(search) + 1], main_str)

        items.sort(key=get_sort_key)

        return items[:10]

    def _get_tool_completions(self, text: str) -> list[DropdownItem]:
        """Get tool completions for tool-* references."""
        tools = self._get_tools()
        items = []
        text_lower = text.lower()

        for tool in tools:
            if text_lower in tool.lower():
                items.append(
                    DropdownItem(
                        main=tool,
                        prefix=Content.from_markup(f"[bold yellow]{CATEGORY_ICONS['tool']}[/] "),
                    )
                )

        return items[:10]

    def _get_discovery_items(self) -> list[DropdownItem]:
        """Get items shown when input is empty (discovery mode)."""
        # Show most common commands
        common = ["/help", "/bundle", "/reset", "/clear", "/quit"]
        items = []

        for cmd_name in common:
            if cmd_name in COMMANDS:
                items.append(self._make_command_item(COMMANDS[cmd_name]))

        return items

    def _make_command_item(self, cmd_info: CommandInfo) -> DropdownItem:
        """Create a DropdownItem for a command.

        IMPORTANT: main text is what gets inserted on Tab, so it must be
        just the command name, not the description.
        """
        icon = CATEGORY_ICONS.get(cmd_info.category, "⌘")

        # Style based on category
        if cmd_info.category == "subcommand":
            prefix = Content.from_markup(f"[dim]{icon}[/] ")
        else:
            prefix = Content.from_markup(f"[bold green]{icon}[/] ")

        # Main is ONLY the command (this is what gets inserted on Tab)
        # Description is included in prefix so it shows but doesn't get inserted
        prefix_with_desc = Content.from_markup(
            f"{prefix.plain} [dim]{cmd_info.description:<30}[/dim] "
        )

        return DropdownItem(
            main=cmd_info.name,
            prefix=prefix_with_desc,
        )

    def _get_agents(self) -> list[str]:
        """Get available agents from runtime."""
        if self._cached_agents is not None:
            return self._cached_agents

        if self._bridge and hasattr(self._bridge, "get_available_agents"):
            try:
                self._cached_agents = self._bridge.get_available_agents() or []
            except Exception:
                self._cached_agents = []
        else:
            # Default agents when no bridge available
            self._cached_agents = [
                "foundation:explorer",
                "foundation:zen-architect",
                "foundation:modular-builder",
                "foundation:bug-hunter",
                "foundation:git-ops",
                "amplifier:amplifier-expert",
            ]

        return self._cached_agents

    def _get_tools(self) -> list[str]:
        """Get available tools from runtime."""
        if self._cached_tools is not None:
            return self._cached_tools

        if self._bridge and hasattr(self._bridge, "get_available_tools"):
            try:
                self._cached_tools = self._bridge.get_available_tools() or []
            except Exception:
                self._cached_tools = []
        else:
            # Default tools when no bridge available
            self._cached_tools = [
                "bash",
                "read_file",
                "write_file",
                "edit_file",
                "glob",
                "grep",
                "web_search",
                "web_fetch",
                "task",
                "todo",
                "recipes",
            ]

        return self._cached_tools

    def invalidate_cache(self) -> None:
        """Clear cached data (call when runtime state changes)."""
        self._cached_agents = None
        self._cached_tools = None
        self._cached_bundles = None
