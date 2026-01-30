"""Status bar widget showing connection info and keybindings."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Static


class ConnectionIndicatorSmall(Static):
    """Compact connection indicator for status bar."""

    connected: reactive[bool] = reactive(False)

    def render(self) -> str:
        if self.connected:
            return "[green]●[/green] Connected"
        else:
            return "[red]○[/red] Disconnected"


class SessionInfo(Static):
    """Session info display with bundle and turn count."""

    session_id: reactive[str | None] = reactive(None)
    bundle_name: reactive[str | None] = reactive(None)
    turn_count: reactive[int] = reactive(0)

    def render(self) -> str:
        parts = []

        # Bundle name (most useful info)
        if self.bundle_name:
            parts.append(f"[cyan]{self.bundle_name}[/cyan]")

        # Turn count
        if self.turn_count > 0:
            parts.append(f"turn:{self.turn_count}")

        # Session ID (truncated)
        if self.session_id:
            display_id = self.session_id[-8:] if len(self.session_id) > 8 else self.session_id
            parts.append(f"[dim]{display_id}[/dim]")

        return " │ ".join(parts) if parts else "session:new"


class RuntimeMode(Static):
    """Runtime mode display (stdio/ws/http)."""

    mode: reactive[str] = reactive("stdio")

    def render(self) -> str:
        return f"[dim]{self.mode}[/dim]"


class BusyIndicator(Static):
    """Busy/processing indicator."""

    busy: reactive[bool] = reactive(False)
    approval_pending: reactive[bool] = reactive(False)

    def render(self) -> str:
        if self.approval_pending:
            return "[yellow]⚠ Awaiting Approval[/yellow]"
        elif self.busy:
            return "[yellow]◐ Processing...[/yellow]"
        else:
            return "[green]Ready[/green]"


class KeybindingHints(Static):
    """Keybinding hints on the right side."""

    approval_mode: reactive[bool] = reactive(False)

    def render(self) -> str:
        if self.approval_mode:
            return "[dim][Y]Approve [N]Deny [?]Help[/dim]"
        else:
            return "[dim]^P:Prompt ^T:Todos ^?:Help[/dim]"


class StatusBar(Static):
    """Bottom status bar with connection info and keybindings.

    ● Connected  session:abc123  ws  ◐ Processing...          ^P:Prompt ^T:Todos ^?:Help
    """

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: $surface-darken-2;
        padding: 0 1;
    }

    StatusBar #status-content {
        width: 100%;
    }

    StatusBar #status-left {
        width: 1fr;
    }

    StatusBar #status-right {
        width: auto;
    }

    StatusBar ConnectionIndicatorSmall {
        width: auto;
        margin-right: 2;
    }

    StatusBar SessionInfo {
        width: auto;
        margin-right: 2;
    }

    StatusBar RuntimeMode {
        width: auto;
        margin-right: 2;
    }

    StatusBar BusyIndicator {
        width: auto;
    }

    StatusBar KeybindingHints {
        width: auto;
        text-align: right;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="status-content"):
            with Horizontal(id="status-left"):
                yield ConnectionIndicatorSmall(id="conn-indicator")
                yield SessionInfo(id="session-info")
                yield RuntimeMode(id="runtime-mode")
                yield BusyIndicator(id="busy-indicator")
            yield KeybindingHints(id="keybinding-hints")

    def update_state(
        self,
        connected: bool,
        session_id: str | None,
        mode: str,
        busy: bool,
        approval_pending: bool = False,
        bundle_name: str | None = None,
        turn_count: int = 0,
    ) -> None:
        """Update status bar with current state."""
        self.query_one("#conn-indicator", ConnectionIndicatorSmall).connected = connected

        session_info = self.query_one("#session-info", SessionInfo)
        session_info.session_id = session_id
        session_info.bundle_name = bundle_name
        session_info.turn_count = turn_count

        self.query_one("#runtime-mode", RuntimeMode).mode = mode

        busy_indicator = self.query_one("#busy-indicator", BusyIndicator)
        busy_indicator.busy = busy
        busy_indicator.approval_pending = approval_pending

        self.query_one("#keybinding-hints", KeybindingHints).approval_mode = approval_pending
