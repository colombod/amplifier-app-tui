"""Amplifier TUI - Main Application.

Terminal User Interface for interacting with Amplifier Runtime.
Built with Textual + Rich for a modern terminal experience.

Design principles (from TUI research):
- Block-based output with clear user/agent/tool boundaries
- Scroll behavior respects user position + signals live activity
- Gestalt assessment in <200ms through visual weight
- Keyboard-first navigation with vim-style optional bindings
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.css.query import NoMatches

from .widgets.approval import ApprovalPanel
from .widgets.header import AgentHeader
from .widgets.input import InputZone
from .widgets.output import OutputZone
from .widgets.status import StatusBar
from .widgets.todos import TodoPanel

if TYPE_CHECKING:
    from .bridge import RuntimeBridge
    from .commands import CommandHandler
    from .completions import CompletionProvider


class AmplifierTUI(App):
    """Main Amplifier TUI Application.

    Layout (research-driven):
    ┌─ Header ────────────────────────────────────────────────────┐
    │ Agent: claude › agent       ○ Ready      │ ● Connected ws  │
    ├─────────────────────────────────────────────┬───────────────┤
    │                                             │ ▼ Tasks (3/7) │
    │  ┌─ You ────────────────────── 14:32 ─┐    │ ✓ Done        │
    │  │ Run the tests and fix failures     │    │ ▶ Running     │
    │  └────────────────────────────────────┘    │ · Pending     │
    │                                             │               │
    │  ┌─ Agent ──────────────────── 14:32 ─┐    │               │
    │  │ I'll run the test suite first...   │    │               │
    │  │ ┌─ Tool: bash ● ─────────────────┐ │    │               │
    │  │ │ pytest tests/ -v               │ │    │               │
    │  │ └────────────────────────────────┘ │    │               │
    │  └────────────────────────────────────┘    │               │
    ├─────────────────────────────────────────────┴───────────────┤
    │ ┃ Enter your prompt...                                      │
    ├─────────────────────────────────────────────────────────────┤
    │ ● Connected  session:abc  ws  Ready          ^P ^T ^? Help  │
    └─────────────────────────────────────────────────────────────┘
    """

    CSS_PATH = "styles/amplifier.tcss"
    TITLE = "Amplifier TUI"

    BINDINGS = [
        # Core navigation
        Binding("ctrl+p", "focus_input", "Prompt", show=True),
        Binding("ctrl+t", "toggle_todos", "Todos", show=True),
        Binding("ctrl+c", "cancel_request", "Cancel", show=False),
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("f1", "show_help", "Help", show=True),
        # Vim-style navigation (when not in input)
        Binding("j", "scroll_down", "Down", show=False),
        Binding("k", "scroll_up", "Up", show=False),
        Binding("g", "scroll_top", "Top", show=False),
        Binding("G", "scroll_bottom", "Bottom", show=False),
        Binding("end", "scroll_bottom", "Bottom", show=False),
        Binding("home", "scroll_top", "Top", show=False),
        # Approval bindings (active only when approval panel visible)
        Binding("y", "approve", "Approve", show=False, priority=True),
        Binding("n", "deny", "Deny", show=False, priority=True),
        Binding("a", "approve_similar", "Allow Similar", show=False, priority=True),
    ]

    def __init__(self, bridge: RuntimeBridge | None = None, **kwargs):
        super().__init__(**kwargs)
        # Bridge connection to runtime
        self._bridge = bridge
        # Command handler (initialized when bridge is set)
        self._command_handler: CommandHandler | None = None
        # Completion provider for autocomplete dropdown
        self._completion_provider: CompletionProvider | None = None
        # State
        self._connected = False
        self._busy = False
        self._session_id: str | None = None
        self._transport_mode = "stdio"
        self._agent_stack: list[str] = ["amplifier"]
        self._pending_approval: dict | None = None
        self._agent_state = "idle"  # idle, thinking, generating, executing, error
        # Session info
        self._bundle_name: str | None = None
        self._turn_count: int = 0

    def compose(self) -> ComposeResult:
        """Compose the application layout."""
        yield AgentHeader(id="header")
        yield Horizontal(
            OutputZone(id="output-zone"),
            TodoPanel(id="todo-panel"),
            id="main-workspace",
        )
        yield InputZone(id="input-zone")
        yield StatusBar(id="status-bar")
        # Modal overlay (hidden by default)
        yield ApprovalPanel(id="approval-panel")

    def on_mount(self) -> None:
        """Called when app is mounted."""
        # Focus input by default
        self.query_one("#prompt-input").focus()
        # Update initial state
        self._update_header()
        self._update_status()
        # Apply initial responsive layout
        self._apply_responsive_layout()
        # Set completion provider if bridge was set before mount (timing fix)
        if self._completion_provider:
            try:
                input_zone = self.query_one("#input-zone", InputZone)
                input_zone.set_completion_provider(self._completion_provider)
            except Exception:
                pass

    def on_resize(self) -> None:
        """Handle terminal resize - apply responsive layout classes."""
        self._apply_responsive_layout()

    def _apply_responsive_layout(self) -> None:
        """Apply responsive layout classes based on terminal size.

        Breakpoints (from TUI research):
        - Wide (>120 cols): Spacious layout with expanded panels
        - Normal (80-120): Standard layout
        - Narrow (60-80): Compact mode, reduced padding
        - Mobile (<60): Hide non-essential elements
        - Tall (>40 rows): More input space
        - Short (<20 rows): Minimal chrome
        """
        width = self.size.width
        height = self.size.height

        # Remove all layout classes first
        self.remove_class("layout-wide", "layout-narrow", "layout-mobile")
        self.remove_class("layout-tall", "layout-short")

        # Apply width-based classes
        if width > 120:
            self.add_class("layout-wide")
        elif width < 60:
            self.add_class("layout-mobile")
        elif width < 80:
            self.add_class("layout-narrow")

        # Apply height-based classes
        if height > 40:
            self.add_class("layout-tall")
        elif height < 20:
            self.add_class("layout-short")

    # -------------------------------------------------------------------------
    # Actions - Core Navigation
    # -------------------------------------------------------------------------

    def action_focus_input(self) -> None:
        """Focus the input zone."""
        self.query_one("#prompt-input").focus()

    def action_toggle_todos(self) -> None:
        """Toggle todo panel visibility."""
        todo_panel = self.query_one("#todo-panel", TodoPanel)
        todo_panel.toggle_class("hidden")

    def action_cancel_request(self) -> None:
        """Cancel the current request."""
        if self._busy and self._bridge:
            self.notify("Cancelling request...", severity="warning")
            self.run_worker(self._bridge.send_abort())

    def action_show_help(self) -> None:
        """Show help screen."""
        self.notify(
            "Keybindings:\n"
            "  Ctrl+P  Focus prompt input\n"
            "  Ctrl+T  Toggle todo panel\n"
            "  Ctrl+C  Cancel current request\n"
            "  Ctrl+Q  Quit\n"
            "  j/k     Scroll down/up (vim-style)\n"
            "  g/G     Jump to top/bottom\n"
            "  End     Follow live output\n"
            "  Y/N/A   Approve/Deny/Allow Similar",
            title="Help",
            timeout=10,
        )

    # -------------------------------------------------------------------------
    # Actions - Vim-style Navigation
    # -------------------------------------------------------------------------

    def action_scroll_down(self) -> None:
        """Scroll output down (vim j)."""
        output = self.query_one("#output-zone", OutputZone)
        output.scroll_down()

    def action_scroll_up(self) -> None:
        """Scroll output up (vim k)."""
        output = self.query_one("#output-zone", OutputZone)
        output.scroll_up()

    def action_scroll_top(self) -> None:
        """Scroll to top (vim g)."""
        output = self.query_one("#output-zone", OutputZone)
        output.scroll_home()

    def action_scroll_bottom(self) -> None:
        """Scroll to bottom and follow (vim G / End)."""
        output = self.query_one("#output-zone", OutputZone)
        output.scroll_to_bottom()

    # -------------------------------------------------------------------------
    # Actions - Approvals
    # -------------------------------------------------------------------------

    def action_approve(self) -> None:
        """Approve pending request."""
        if self._pending_approval:
            self._handle_approval_response("approve")

    def action_deny(self) -> None:
        """Deny pending request."""
        if self._pending_approval:
            self._handle_approval_response("deny")

    def action_approve_similar(self) -> None:
        """Approve and allow similar future requests."""
        if self._pending_approval:
            self._handle_approval_response("approve_similar")

    # -------------------------------------------------------------------------
    # Bridge Integration
    # -------------------------------------------------------------------------

    def set_bridge(self, bridge: RuntimeBridge) -> None:
        """Set the runtime bridge and initialize command support."""
        from .commands import CommandHandler
        from .completions import CompletionProvider

        self._bridge = bridge
        self._command_handler = CommandHandler(self, bridge)

        # Create and set up the completion provider for autocomplete dropdown
        self._completion_provider = CompletionProvider(bridge)

        # Update the input zone with the completion provider (if mounted)
        try:
            input_zone = self.query_one("#input-zone", InputZone)
            input_zone.set_completion_provider(self._completion_provider)
        except Exception:
            pass  # App may not be fully mounted yet

    async def submit_prompt(self, prompt: str) -> None:
        """Submit a prompt to the runtime via bridge.

        If prompt starts with /, it's treated as a slash command.
        """
        from .commands import CommandResult

        if not prompt.strip():
            return

        # Check for slash commands
        if self._command_handler and self._command_handler.is_command(prompt):
            response = await self._command_handler.execute(prompt)

            if response.result == CommandResult.QUIT:
                self.add_system_message(response.message)
                self.exit()
                return

            if response.result == CommandResult.SUCCESS:
                if response.message:
                    # Use command output block for formatted help (preserves box drawing)
                    if any(c in response.message for c in "╭╮╰╯│─"):
                        self.add_command_output(response.message)
                    else:
                        self.add_system_message(response.message)
            else:
                self.add_error(response.message)
            return

        # Regular prompt - send to runtime
        if not self._bridge:
            self.add_error("No runtime connection. Use --attach or launch subprocess.")
            return

        if not self._bridge.is_connected:
            self.add_error("Not connected to runtime.")
            return

        await self._bridge.send_prompt(prompt)

    def on_input_zone_prompt_submitted(self, event: InputZone.PromptSubmitted) -> None:
        """Handle input submission from InputZone widget."""
        self.run_worker(self.submit_prompt(event.value))
        # Keep focus on input after submission
        self.query_one("#prompt-input").focus()

    # -------------------------------------------------------------------------
    # State Updates
    # -------------------------------------------------------------------------

    def set_connected(self, connected: bool, mode: str = "stdio") -> None:
        """Update connection state."""
        self._connected = connected
        self._transport_mode = mode
        self._update_header()
        self._update_status()

    def set_busy(self, busy: bool) -> None:
        """Update busy state."""
        self._busy = busy
        self._update_header()
        self._update_status()
        # Disable/enable input
        input_zone = self.query_one("#input-zone", InputZone)
        input_zone.set_disabled(busy)

    def set_agent_state(self, state: str) -> None:
        """Update agent state (idle, thinking, generating, executing, error)."""
        self._agent_state = state
        header = self.query_one("#header", AgentHeader)
        header.update_agent_state(state)
        # Also update busy based on state
        self._busy = state not in ("idle", "error")
        self._update_status()

    def set_session(self, session_id: str | None) -> None:
        """Update session ID."""
        self._session_id = session_id
        self._update_status()

    def set_agent_stack(self, agents: list[str]) -> None:
        """Update agent breadcrumb."""
        self._agent_stack = agents if agents else ["amplifier"]
        self._update_header()

    def set_turn_count(self, turn: int) -> None:
        """Update the turn count."""
        self._turn_count = turn
        self._update_status()

    def set_bundle_name(self, name: str) -> None:
        """Update the bundle name."""
        self._bundle_name = name
        self._update_status()

    def show_approval(self, tool: str, params: dict, approval_id: str) -> None:
        """Show approval panel for a tool request."""
        self._pending_approval = {
            "tool": tool,
            "params": params,
            "approval_id": approval_id,
        }
        approval_panel = self.query_one("#approval-panel", ApprovalPanel)
        approval_panel.show_approval(tool, params)
        self._update_status()

    def hide_approval(self) -> None:
        """Hide approval panel."""
        self._pending_approval = None
        approval_panel = self.query_one("#approval-panel", ApprovalPanel)
        approval_panel.hide()
        self._update_status()

    # -------------------------------------------------------------------------
    # Output Methods - User Messages
    # -------------------------------------------------------------------------

    def add_user_message(self, content: str) -> None:
        """Add a user message block to output."""
        output = self.query_one("#output-zone", OutputZone)
        output.add_user_message(content)

    # -------------------------------------------------------------------------
    # Output Methods - Agent Responses
    # -------------------------------------------------------------------------

    def _get_output_zone(self) -> OutputZone | None:
        """Safely get output zone (returns None during shutdown)."""
        try:
            return self.query_one("#output-zone", OutputZone)
        except NoMatches:
            return None

    def start_response(self, agent_name: str | None = None) -> None:
        """Start a new agent response (call before streaming)."""
        if output := self._get_output_zone():
            output.start_response(bundle_name=self._bundle_name, agent_name=agent_name)
            self.set_agent_state("generating")

    def append_content(self, content: str) -> None:
        """Append content to current response (for streaming)."""
        if output := self._get_output_zone():
            output.append_content(content)

    def end_response(self) -> None:
        """End the current agent response."""
        if output := self._get_output_zone():
            output.end_response()
            self.set_agent_state("idle")

    # -------------------------------------------------------------------------
    # Output Methods - Thinking
    # -------------------------------------------------------------------------

    def add_thinking(self, content: str) -> None:
        """Add a thinking block to output."""
        if output := self._get_output_zone():
            output.add_thinking(content)
            self.set_agent_state("thinking")

    def end_thinking(self) -> None:
        """End thinking block."""
        if output := self._get_output_zone():
            output.end_thinking()

    # -------------------------------------------------------------------------
    # Output Methods - Tool Calls
    # -------------------------------------------------------------------------

    def add_tool_call(
        self,
        tool_name: str,
        params: dict,
        result: str | None = None,
        status: str = "pending",
    ) -> str:
        """Add a tool call block and return its ID for updates."""
        if output := self._get_output_zone():
            self.set_agent_state("executing")
            return output.add_tool_call(tool_name, params, result, status)
        return ""

    def update_tool_call(self, block_id: str, result: str, status: str) -> None:
        """Update an existing tool call block."""
        if output := self._get_output_zone():
            output.update_tool_call(block_id, result, status)
            if status in ("success", "error"):
                self.set_agent_state("idle")

    # -------------------------------------------------------------------------
    # Output Methods - Sub-Sessions (agent delegation)
    # -------------------------------------------------------------------------

    def start_sub_session(self, parent_tool_call_id: str, session_id: str, agent_name: str) -> None:
        """Start tracking a sub-session (spawned agent)."""
        if output := self._get_output_zone():
            output.start_sub_session(parent_tool_call_id, session_id, agent_name)
            self.set_agent_state("executing")

    def end_sub_session(self, parent_tool_call_id: str, status: str = "success") -> None:
        """End tracking a sub-session."""
        if output := self._get_output_zone():
            output.end_sub_session(parent_tool_call_id, status)

    # -------------------------------------------------------------------------
    # Output Methods - Inline Approvals (low-risk tools)
    # -------------------------------------------------------------------------

    def add_inline_approval(self, tool_name: str, params: dict, approval_id: str) -> None:
        """Add inline approval request for low-risk tools."""
        output = self.query_one("#output-zone", OutputZone)
        output.add_inline_approval(tool_name, params, approval_id)
        self._pending_approval = {
            "tool": tool_name,
            "params": params,
            "approval_id": approval_id,
            "inline": True,
        }
        self._update_status()

    def remove_inline_approval(self, approval_id: str) -> None:
        """Remove inline approval after response."""
        output = self.query_one("#output-zone", OutputZone)
        output.remove_inline_approval(approval_id)
        if self._pending_approval and self._pending_approval.get("approval_id") == approval_id:
            self._pending_approval = None
        self._update_status()

    # -------------------------------------------------------------------------
    # Output Methods - Errors and System Messages
    # -------------------------------------------------------------------------

    def add_error(self, error: str) -> None:
        """Add an error block to output."""
        if output := self._get_output_zone():
            output.add_error(error)
            self.set_agent_state("error")

    def add_system_message(self, message: str) -> None:
        """Add a system message to output."""
        if output := self._get_output_zone():
            output.add_system_message(message)

    def add_command_output(self, content: str) -> None:
        """Add command output with preserved formatting (for /help, etc.)."""
        if output := self._get_output_zone():
            output.add_command_output(content)

    def clear_output(self) -> None:
        """Clear the output zone."""
        if output := self._get_output_zone():
            output.clear()

    def clear_conversation(self) -> None:
        """Clear the conversation (alias for clear_output)."""
        self.clear_output()

    # -------------------------------------------------------------------------
    # Todo Methods
    # -------------------------------------------------------------------------

    def update_todos(self, todos: list[dict]) -> None:
        """Update the todo panel with new todos."""
        todo_panel = self.query_one("#todo-panel", TodoPanel)
        todo_panel.update_todos(todos)

    # -------------------------------------------------------------------------
    # Internal Helpers
    # -------------------------------------------------------------------------

    def _update_header(self) -> None:
        """Update header with current state."""
        header = self.query_one("#header", AgentHeader)
        header.update_state(
            agents=self._agent_stack,
            connected=self._connected,
            mode=self._transport_mode,
            busy=self._busy,
        )

    def _update_status(self) -> None:
        """Update status bar with current state."""
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.update_state(
            connected=self._connected,
            session_id=self._session_id,
            mode=self._transport_mode,
            busy=self._busy,
            approval_pending=self._pending_approval is not None,
            bundle_name=self._bundle_name,
            turn_count=self._turn_count,
        )

    def _handle_approval_response(self, choice: str) -> None:
        """Handle approval response."""
        if not self._pending_approval:
            return

        approval_id = self._pending_approval["approval_id"]
        tool = self._pending_approval["tool"]
        is_inline = self._pending_approval.get("inline", False)

        if is_inline:
            self.remove_inline_approval(approval_id)
        else:
            self.hide_approval()

        # Map choice to display text
        choice_text = {
            "approve": "Approved",
            "deny": "Denied",
            "approve_similar": "Approved (+ similar)",
        }.get(choice, choice)

        self.notify(
            f"{choice_text}: {tool}",
            severity="information" if "approve" in choice else "warning",
        )

        # Send approval via bridge
        if self._bridge:
            self.run_worker(self._bridge.send_approval(approval_id, choice))
        else:
            self.add_system_message(f"{choice_text} for {tool} (id: {approval_id})")


def run(
    attach_url: str | None = None,
    runtime_command: list[str] | None = None,
    working_directory: str | None = None,
    bundle: str | None = None,
) -> None:
    """Run the Amplifier TUI application.

    Args:
        attach_url: URL to attach to existing server (e.g., "http://localhost:4096")
        runtime_command: Custom command to launch runtime (default: ["amplifier-runtime"])
        working_directory: Working directory for subprocess mode
        bundle: Bundle to use for session (default: "foundation")
    """
    from .bridge import BridgeConfig, ConnectionMode, RuntimeBridge

    # Create bridge configuration
    if attach_url:
        # Attach mode
        use_ws = attach_url.startswith("ws://") or attach_url.startswith("wss://")
        config = BridgeConfig(
            mode=ConnectionMode.WEBSOCKET if use_ws else ConnectionMode.HTTP,
            server_url=attach_url.replace("ws://", "http://").replace("wss://", "https://"),
            bundle=bundle or "foundation",
        )
    else:
        # Subprocess mode (default)
        config = BridgeConfig(
            mode=ConnectionMode.SUBPROCESS,
            runtime_command=runtime_command or ["amplifier-runtime"],
            working_directory=working_directory,
            bundle=bundle or "foundation",
        )

    # Create app with bridge
    app = AmplifierTUI()
    bridge = RuntimeBridge(app, config)
    app.set_bridge(bridge)

    # Run app with bridge lifecycle
    async def run_with_bridge():
        try:
            await bridge.connect()
            await app.run_async()
        finally:
            await bridge.disconnect()

    import asyncio

    asyncio.run(run_with_bridge())


if __name__ == "__main__":
    run()
