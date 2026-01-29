"""Header widget showing agent context and connection status.

Design principles (from TUI research):
- Gestalt assessment in <200ms through visual weight
- Binary states need binary indicators (connected/disconnected)
- Semantic color consistency across the interface
- Status icons: ● solid=active, ◐ half=thinking, ○ hollow=idle, ⊗ error
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Static


class AgentBreadcrumb(Static):
    """Shows agent hierarchy: Agent: parent › child › current."""

    agents: reactive[list[str]] = reactive(["amplifier"], init=False)

    def render(self) -> str:
        breadcrumb = " › ".join(self.agents)
        return f"Agent: {breadcrumb}"

    def update_agents(self, agents: list[str]) -> None:
        """Update the agent stack."""
        self.agents = agents if agents else ["amplifier"]


class AgentStateIndicator(Static):
    """Shows agent state with semantic icons.

    Research insight: Gestalt assessment in <200ms through visual weight.
    Icons communicate state before reading text.

    States:
    - ● bright solid = Actively generating/executing
    - ◐ half = Thinking/processing
    - ○ hollow = Idle, waiting for input
    - ⊗ error = Connection lost / Fatal error
    """

    # Agent states
    IDLE = "idle"
    THINKING = "thinking"
    GENERATING = "generating"
    EXECUTING = "executing"
    ERROR = "error"

    ICONS = {
        "idle": "○",  # Hollow = waiting for input
        "thinking": "◐",  # Half = processing
        "generating": "●",  # Solid = active generation
        "executing": "◑",  # Different half = executing tool
        "error": "⊗",  # Error state
    }

    COLORS = {
        "idle": "green",
        "thinking": "yellow",
        "generating": "cyan",
        "executing": "blue",
        "error": "red",
    }

    LABELS = {
        "idle": "Ready",
        "thinking": "Thinking...",
        "generating": "Generating...",
        "executing": "Executing...",
        "error": "Error",
    }

    state: reactive[str] = reactive("idle", init=False)

    def render(self) -> str:
        icon = self.ICONS.get(self.state, "○")
        color = self.COLORS.get(self.state, "white")
        label = self.LABELS.get(self.state, "Unknown")
        return f"[{color}]{icon} {label}[/{color}]"

    def set_state(self, state: str) -> None:
        """Update agent state."""
        self.state = state


class ConnectionIndicator(Static):
    """Shows connection status and transport mode.

    Research insight: Binary states need binary indicators.
    Connection is either working or not - make it unmistakable.
    """

    connected: reactive[bool] = reactive(False, init=False)
    mode: reactive[str] = reactive("stdio", init=False)

    def render(self) -> str:
        if self.connected:
            return f"[green]● Connected[/green] │ [dim]{self.mode}[/dim]"
        else:
            return f"[red]○ Disconnected[/red] │ [dim]{self.mode}[/dim]"

    def update_state(self, connected: bool, mode: str) -> None:
        """Update connection state."""
        self.connected = connected
        self.mode = mode


class AgentHeader(Static):
    """Header bar showing agent context, state, and connection status.

    ┌─────────────────────────────────────────────────────────────────────┐
    │ Agent: claude › code-review       ● Generating...  │ ● Connected ws │
    └─────────────────────────────────────────────────────────────────────┘

    Research-driven design:
    - Left: Agent breadcrumb (context)
    - Center: Agent state indicator (what's happening)
    - Right: Connection status (system health)
    """

    DEFAULT_CSS = """
    AgentHeader {
        height: 1;
        background: $surface-darken-1;
        padding: 0 1;
    }

    AgentHeader #header-content {
        width: 100%;
    }

    AgentHeader AgentBreadcrumb {
        width: 1fr;
    }

    AgentHeader AgentStateIndicator {
        width: auto;
        margin-right: 2;
    }

    AgentHeader ConnectionIndicator {
        width: auto;
        text-align: right;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="header-content"):
            yield AgentBreadcrumb(id="agent-breadcrumb")
            yield AgentStateIndicator(id="agent-state")
            yield ConnectionIndicator(id="connection-indicator")

    def update_agents(self, agents: list[str]) -> None:
        """Update agent breadcrumb."""
        self.query_one("#agent-breadcrumb", AgentBreadcrumb).update_agents(agents)

    def update_agent_state(self, state: str) -> None:
        """Update agent state indicator."""
        self.query_one("#agent-state", AgentStateIndicator).set_state(state)

    def update_connection(self, connected: bool, mode: str) -> None:
        """Update connection indicator."""
        self.query_one("#connection-indicator", ConnectionIndicator).update_state(connected, mode)

    def update_state(
        self,
        agents: list[str],
        connected: bool,
        mode: str,
        busy: bool,
    ) -> None:
        """Update header with current state (legacy interface)."""
        self.update_agents(agents)
        self.update_connection(connected, mode)
        # Map busy to agent state
        if busy:
            self.update_agent_state("generating")
        else:
            self.update_agent_state("idle")
