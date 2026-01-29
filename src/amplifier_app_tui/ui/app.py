"""Main TUI Application.

The primary Textual application that hosts all UI components.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.widgets import Footer, Header, Static

from ..core import EventBridge, RuntimeConfig, RuntimeManager

if TYPE_CHECKING:
    from amplifier_app_runtime.protocol.events import Event


class StatusBar(Static):
    """Status bar showing connection state."""

    def __init__(self) -> None:
        super().__init__("Disconnected")
        self.add_class("status-bar")

    def set_status(self, status: str, style: str = "") -> None:
        """Update status text and style."""
        self.update(status)
        self.remove_class("connected", "disconnected", "error")
        if style:
            self.add_class(style)


class MessageArea(Static):
    """Area for displaying messages and output."""

    DEFAULT_CSS = """
    MessageArea {
        height: 100%;
        overflow-y: auto;
        padding: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__("")
        self._content: list[str] = []

    def append_message(self, message: str) -> None:
        """Append a message to the display."""
        self._content.append(message)
        self.update("\n".join(self._content))

    def clear_messages(self) -> None:
        """Clear all messages."""
        self._content.clear()
        self.update("")


class InputArea(Static):
    """Placeholder for input area (to be expanded with actual input widget)."""

    DEFAULT_CSS = """
    InputArea {
        height: 3;
        border: solid green;
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__("Type your message here... (Input coming soon)")


class AmplifierTUI(App[None]):
    """Main Amplifier TUI Application.

    A terminal interface for interacting with the Amplifier runtime.
    Supports both subprocess (launch runtime) and attach (connect to server) modes.

    Usage:
        # Default: launch runtime as subprocess
        app = AmplifierTUI()
        app.run()

        # Attach to existing server
        config = RuntimeConfig(mode=ConnectionMode.ATTACH, server_url="...")
        app = AmplifierTUI(config)
        app.run()
    """

    TITLE = "Amplifier TUI"
    SUB_TITLE = "AI Agent Interface"

    CSS = """
    Screen {
        layout: grid;
        grid-size: 1;
        grid-rows: auto 1fr auto auto;
    }

    #main-container {
        height: 100%;
    }

    .status-bar {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }

    .status-bar.connected {
        background: $success;
        color: $text;
    }

    .status-bar.disconnected {
        background: $warning;
        color: $text;
    }

    .status-bar.error {
        background: $error;
        color: $text;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("r", "reconnect", "Reconnect"),
        Binding("c", "clear", "Clear"),
    ]

    def __init__(
        self,
        config: RuntimeConfig | None = None,
    ) -> None:
        super().__init__()
        self._config = config or RuntimeConfig()
        self._event_bridge = EventBridge()
        self._runtime = RuntimeManager(self._config, self._event_bridge)

        # UI components (created in compose)
        self._status_bar: StatusBar | None = None
        self._message_area: MessageArea | None = None

    def compose(self) -> ComposeResult:
        """Compose the UI layout."""
        yield Header()

        with Container(id="main-container"):
            with Vertical():
                yield MessageArea()
                yield InputArea()

        yield StatusBar()
        yield Footer()

    def on_mount(self) -> None:
        """Handle app mount - get references and start runtime."""
        # Get component references
        self._status_bar = self.query_one(StatusBar)
        self._message_area = self.query_one(MessageArea)

        # Subscribe to events
        self._event_bridge.subscribe(self._handle_event)

        # Start runtime connection
        self.run_worker(self._start_runtime())

    async def _start_runtime(self) -> None:
        """Start the runtime connection."""
        if self._status_bar:
            self._status_bar.set_status("Connecting...", "disconnected")

        try:
            await self._runtime.start()
            if self._status_bar:
                mode = self._config.mode.value
                self._status_bar.set_status(f"Connected ({mode})", "connected")
            if self._message_area:
                self._message_area.append_message("Connected to Amplifier runtime")
        except Exception as e:
            if self._status_bar:
                self._status_bar.set_status(f"Error: {e}", "error")
            if self._message_area:
                self._message_area.append_message(f"Connection failed: {e}")

    async def _handle_event(self, event: Event) -> None:
        """Handle events from the runtime."""
        if self._message_area:
            # Format event for display
            event_str = f"[{event.type}] {event.data}"
            self._message_area.append_message(event_str)

    async def action_quit(self) -> None:
        """Quit the application."""
        await self._runtime.stop()
        self.exit()

    async def action_reconnect(self) -> None:
        """Reconnect to runtime."""
        if self._status_bar:
            self._status_bar.set_status("Reconnecting...", "disconnected")
        await self._runtime.restart()
        if self._status_bar:
            self._status_bar.set_status("Connected", "connected")

    def action_clear(self) -> None:
        """Clear the message area."""
        if self._message_area:
            self._message_area.clear_messages()
