"""Output zone widget for displaying AI responses, tool calls, and thinking.

Design principles (from TUI research):
- Block-based output with clear user/agent/tool boundaries
- Scroll behavior that respects user position + signals live activity
- Redundant encoding (color + symbol + position) for status
- Thinking collapsed by default, expandable on demand
"""

from __future__ import annotations

import uuid
from datetime import datetime

from textual.app import ComposeResult
from textual.containers import ScrollableContainer, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import RichLog, Static


class UserMessageBlock(Static):
    """User input message block - visually distinct from agent responses.

    ┌─ You ──────────────────────────────────────────── 14:32 ─┐
    │ Can you run the tests and fix any failures?              │
    └──────────────────────────────────────────────────────────┘
    """

    DEFAULT_CSS = """
    UserMessageBlock {
        margin: 1 0;
        padding: 0 1;
        border: round $primary;
        background: $primary 10%;
    }

    UserMessageBlock .user-header {
        text-style: bold;
        color: $primary;
    }

    UserMessageBlock .user-content {
        padding: 0 1;
    }

    UserMessageBlock .user-timestamp {
        color: $text-muted;
        text-align: right;
    }
    """

    def __init__(self, content: str, timestamp: datetime | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._content = content
        self._timestamp = timestamp or datetime.now()

    def compose(self) -> ComposeResult:
        time_str = self._timestamp.strftime("%H:%M")
        yield Static(f"─ You {' ' * 40} {time_str} ─", classes="user-header")
        yield Static(self._content, classes="user-content")


class AgentResponseBlock(Vertical):
    """Container for agent response with clear boundaries.

    ┌─ Agent ─────────────────────────────────────────── 14:32 ─┐
    │ I'll run the test suite first...                         │
    │                                                          │
    │ ┌─ Tool: bash ────────────────────────────────────────┐  │
    │ │ pytest tests/ -v                                    │  │
    │ └─────────────────────────────────────────────────────┘  │
    └──────────────────────────────────────────────────────────┘
    """

    DEFAULT_CSS = """
    AgentResponseBlock {
        margin: 1 0;
        padding: 0 1;
        border: round $secondary;
    }

    AgentResponseBlock .agent-header {
        text-style: bold;
        color: $secondary;
    }

    AgentResponseBlock .agent-content {
        padding: 0 1;
    }

    AgentResponseBlock.streaming {
        border: round $warning;
    }

    AgentResponseBlock.streaming .agent-header {
        color: $warning;
    }
    """

    streaming: reactive[bool] = reactive(False)

    def __init__(
        self,
        timestamp: datetime | None = None,
        agent_name: str | None = None,
        bundle_name: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._timestamp = timestamp or datetime.now()
        self._content_widget: RichLog | None = None
        self._agent_name = agent_name
        self._bundle_name = bundle_name

    def compose(self) -> ComposeResult:
        time_str = self._timestamp.strftime("%H:%M")
        # Build header with agent/bundle info
        if self._agent_name and self._bundle_name:
            agent_display = f"[cyan]{self._bundle_name}[/cyan]:[bold]{self._agent_name}[/bold]"
        elif self._bundle_name:
            agent_display = f"[cyan]{self._bundle_name}[/cyan]"
        elif self._agent_name:
            agent_display = f"[bold]{self._agent_name}[/bold]"
        else:
            agent_display = "Agent"
        yield Static(f"─ {agent_display} {' ' * 30} {time_str} ─", classes="agent-header")
        self._content_widget = RichLog(
            id="agent-content",
            highlight=True,
            markup=True,
            wrap=True,
            auto_scroll=True,
            classes="agent-content",
        )
        yield self._content_widget

    def append_content(self, content: str) -> None:
        """Append streaming content."""
        if self._content_widget:
            self._content_widget.write(content, expand=True)

    def set_streaming(self, streaming: bool) -> None:
        """Update streaming state."""
        self.streaming = streaming
        if streaming:
            self.add_class("streaming")
        else:
            self.remove_class("streaming")


class ThinkingBlock(Static):
    """Collapsible thinking/reasoning display.

    Research insight: Collapsed by default, expandable on demand.
    Shows indicator when collapsed so user knows thinking occurred.

    ▶ Thinking (click to expand)
    or expanded:
    ▼ Thinking ─────────────────────────────────────────────────
    │ Analyzing the authentication module for potential issues...
    """

    DEFAULT_CSS = """
    ThinkingBlock {
        margin: 1 0;
        padding: 0 1;
        background: $surface-darken-1;
        border: round $secondary;
        color: $text-muted;
    }

    ThinkingBlock .thinking-header {
        text-style: bold;
        color: $secondary;
    }

    ThinkingBlock .thinking-content {
        padding: 0 1;
        max-height: 10;
        overflow-y: auto;
    }

    ThinkingBlock.collapsed .thinking-content {
        display: none;
    }

    ThinkingBlock.collapsed {
        height: 1;
        min-height: 1;
    }
    """

    collapsed: reactive[bool] = reactive(True)  # Collapsed by default per research

    def __init__(self, content: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._content = content

    def compose(self) -> ComposeResult:
        icon = "▶" if self.collapsed else "▼"
        yield Static(f"{icon} Thinking ", classes="thinking-header")
        yield Static(self._content, classes="thinking-content")

    def on_mount(self) -> None:
        """Start collapsed."""
        if self.collapsed:
            self.add_class("collapsed")

    def on_click(self) -> None:
        """Toggle on click."""
        self.toggle_collapse()

    def toggle_collapse(self) -> None:
        """Toggle collapsed state."""
        self.collapsed = not self.collapsed
        self.toggle_class("collapsed")
        # Update icon
        icon = "▶" if self.collapsed else "▼"
        try:
            header = self.query_one(".thinking-header", Static)
            header.update(f"{icon} Thinking ")
        except Exception:
            pass

    def update_content(self, content: str) -> None:
        """Update thinking content (for streaming)."""
        self._content = content
        try:
            content_widget = self.query_one(".thinking-content", Static)
            content_widget.update(content)
        except Exception:
            pass


class ToolCallBlock(Static):
    """Tool call display with status icons.

    Research insight: Use semantic colors AND symbols for redundant encoding.

    ┌─ Tool: read_file ✓ ───────────────────────────────────────┐
    │ path: "src/auth.py"                                       │
    │ ✓ 127 lines read (0.3s)                                   │
    └───────────────────────────────────────────────────────────┘
    """

    DEFAULT_CSS = """
    ToolCallBlock {
        margin: 1 0;
        padding: 0 1;
        border: round $primary-darken-2;
    }

    ToolCallBlock .tool-header {
        text-style: bold;
    }

    ToolCallBlock .tool-params {
        color: $text-muted;
        padding-left: 2;
    }

    ToolCallBlock .tool-result {
        padding-left: 2;
        margin-top: 1;
    }

    ToolCallBlock.pending {
        border: round $warning;
    }

    ToolCallBlock.pending .tool-header {
        color: $warning;
    }

    ToolCallBlock.running {
        border: round $primary;
    }

    ToolCallBlock.running .tool-header {
        color: $primary;
    }

    ToolCallBlock.success {
        border: round $success;
    }

    ToolCallBlock.success .tool-header {
        color: $success;
    }

    ToolCallBlock.error {
        border: round $error;
    }

    ToolCallBlock.error .tool-header {
        color: $error;
    }
    """

    # Research: redundant encoding with both icon and color
    ICONS = {
        "pending": "○",  # Hollow = waiting
        "running": "◐",  # Half = in progress
        "success": "●",  # Solid = complete
        "error": "✗",  # X = failed
    }

    def __init__(
        self,
        tool_name: str,
        params: dict,
        result: str | None = None,
        status: str = "pending",
        tool_call_id: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.tool_name = tool_name
        self.params = params
        self._result = result
        self._status = status
        self._tool_call_id = tool_call_id
        # Sub-session tracking for agent delegation
        self._sub_session_id: str | None = None
        self._sub_agent_name: str | None = None

    def compose(self) -> ComposeResult:
        icon = self.ICONS.get(self._status, "○")
        yield Static(f"─ Tool: {self.tool_name} {icon} ", classes="tool-header")
        yield Static(self._format_params(), classes="tool-params")
        if self._result:
            yield Static(f"{icon} {self._result}", classes="tool-result")

    def on_mount(self) -> None:
        """Set initial status class."""
        self.add_class(self._status)

    def _format_params(self) -> str:
        """Format parameters for display."""
        lines = []
        for key, value in self.params.items():
            value_str = str(value)
            if len(value_str) > 60:
                value_str = value_str[:57] + "..."
            # Handle newlines in values
            if "\n" in value_str:
                value_str = value_str.replace("\n", "\\n")[:60] + "..."
            lines.append(f"{key}: {value_str}")
        return "\n".join(lines) if lines else "(no parameters)"

    def update_result(self, result: str, status: str) -> None:
        """Update tool result and status."""
        self._result = result
        self._status = status

        # Update status class
        self.remove_class("pending", "running", "success", "error")
        self.add_class(status)

        # Only update children if we're mounted
        if not self.is_mounted:
            return

        # Update header icon
        icon = self.ICONS.get(status, "○")
        try:
            header = self.query_one(".tool-header", Static)
            header.update(f"─ Tool: {self.tool_name} {icon} ")
        except Exception:
            pass

        # Add or update result
        try:
            result_widget = self.query_one(".tool-result", Static)
            result_widget.update(f"{icon} {result}")
        except Exception:
            if self.is_mounted:
                self.mount(Static(f"{icon} {result}", classes="tool-result"))

    def set_sub_session(self, session_id: str, agent_name: str) -> None:
        """Mark this tool as running a sub-agent."""
        self._sub_session_id = session_id
        self._sub_agent_name = agent_name
        self._status = "running"
        self.remove_class("pending", "success", "error")
        self.add_class("running")

        # Update header to show sub-agent
        try:
            header = self.query_one(".tool-header", Static)
            header.update(f"─ Tool: {self.tool_name} → {agent_name} ◐ ")
        except Exception:
            pass

    def end_sub_session(self, status: str = "success") -> None:
        """Mark sub-agent as complete."""
        self._status = status
        self.remove_class("pending", "running")
        self.add_class(status)

        # Update header
        icon = self.ICONS.get(status, "●")
        try:
            header = self.query_one(".tool-header", Static)
            if self._sub_agent_name:
                header.update(f"─ Tool: {self.tool_name} → {self._sub_agent_name} {icon} ")
            else:
                header.update(f"─ Tool: {self.tool_name} {icon} ")
        except Exception:
            pass


class InlineApprovalBlock(Static):
    """Inline approval for low-risk tool calls.

    Research insight: Not all approvals need modal - inline for low risk.

    ┌─ ⚡ Tool: bash ──────────────────────────────────────────┐
    │ Command: pytest tests/ -v                                │
    │                                                          │
    │ [y] Allow  [a] Allow Similar  [n] Deny                   │
    └──────────────────────────────────────────────────────────┘
    """

    DEFAULT_CSS = """
    InlineApprovalBlock {
        margin: 1 0;
        padding: 0 1;
        border: double $warning;
        background: $warning 10%;
    }

    InlineApprovalBlock .approval-header {
        text-style: bold;
        color: $warning;
    }

    InlineApprovalBlock .approval-content {
        padding: 0 1;
    }

    InlineApprovalBlock .approval-actions {
        margin-top: 1;
        color: $text-muted;
    }
    """

    class ApprovalResponse(Message):
        """Message sent when user responds to approval."""

        def __init__(self, approval_id: str, response: str) -> None:
            super().__init__()
            self.approval_id = approval_id
            self.response = response  # "allow", "allow_similar", "deny"

    def __init__(
        self,
        tool_name: str,
        params: dict,
        approval_id: str,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.tool_name = tool_name
        self.params = params
        self.approval_id = approval_id

    def compose(self) -> ComposeResult:
        yield Static(f"─ ⚡ Approval: {self.tool_name} ", classes="approval-header")
        yield Static(self._format_params(), classes="approval-content")
        yield Static("[y] Allow  [a] Allow Similar  [n] Deny", classes="approval-actions")

    def _format_params(self) -> str:
        """Format parameters for display."""
        lines = []
        for key, value in self.params.items():
            value_str = str(value)
            if len(value_str) > 60:
                value_str = value_str[:57] + "..."
            lines.append(f"{key}: {value_str}")
        return "\n".join(lines) if lines else "(no parameters)"


class ErrorBlock(Static):
    """Error display block with clear visual treatment."""

    DEFAULT_CSS = """
    ErrorBlock {
        margin: 1 0;
        padding: 0 1;
        border: round $error;
        background: $error 10%;
    }

    ErrorBlock .error-header {
        text-style: bold;
        color: $error;
    }

    ErrorBlock .error-content {
        color: $error;
        padding-left: 2;
    }
    """

    def __init__(self, error: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._error = error

    def compose(self) -> ComposeResult:
        yield Static("─ ✗ Error ", classes="error-header")
        yield Static(self._error, classes="error-content")


class SystemMessage(Static):
    """System message display (centered, dimmed)."""

    DEFAULT_CSS = """
    SystemMessage {
        text-align: center;
        color: $text-muted;
        margin: 1 0;
        text-style: italic;
    }
    """


class CommandOutputBlock(Static):
    """Command output display - preserves formatting for /help, etc.

    Uses monospace rendering to preserve box drawings and alignment.
    """

    DEFAULT_CSS = """
    CommandOutputBlock {
        margin: 1 0;
        padding: 0;
        color: $text;
        background: $surface;
    }
    
    CommandOutputBlock .command-content {
        padding: 0 1;
    }
    """

    def __init__(self, content: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._content = content

    def compose(self) -> ComposeResult:
        yield Static(self._content, classes="command-content")


class StreamingIndicator(Static):
    """Shows when user is scrolled away from live streaming content.

    Research insight: "New content below" indicator preserves context
    while signaling new content.

    ↓ Streaming (42 tokens) - Press End to follow
    """

    DEFAULT_CSS = """
    StreamingIndicator {
        display: none;
        height: 1;
        background: $warning 20%;
        color: $warning;
        text-align: center;
        text-style: bold;
        dock: bottom;
    }

    StreamingIndicator.visible {
        display: block;
    }
    """

    token_count: reactive[int] = reactive(0)
    visible: reactive[bool] = reactive(False)

    def render(self) -> str:
        return f"↓ Streaming ({self.token_count} tokens) - Press End to follow"

    def show(self, token_count: int = 0) -> None:
        """Show the indicator."""
        self.token_count = token_count
        self.visible = True
        self.add_class("visible")

    def hide(self) -> None:
        """Hide the indicator."""
        self.visible = False
        self.remove_class("visible")

    def update_count(self, count: int) -> None:
        """Update token count."""
        self.token_count = count


class OutputZone(ScrollableContainer):
    """Main scrolling output area with block-based content.

    Research-driven design:
    - Block-based output with clear user/agent/tool boundaries
    - Scroll behavior respects user position
    - Streaming indicator when scrolled away from live content
    - vim-style navigation support
    """

    DEFAULT_CSS = """
    OutputZone {
        height: 100%;
        scrollbar-gutter: stable;
        padding: 1 2;
    }

    OutputZone RichLog {
        background: transparent;
        padding: 0;
    }
    """

    # Track if user has scrolled away from bottom
    _user_scrolled_away: bool = False
    _is_streaming: bool = False

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._tool_blocks: dict[str, ToolCallBlock] = {}
        self._inline_approvals: dict[str, InlineApprovalBlock] = {}
        self._current_thinking: ThinkingBlock | None = None
        self._current_response: AgentResponseBlock | None = None
        self._streaming_indicator: StreamingIndicator | None = None
        self._token_count = 0

    def compose(self) -> ComposeResult:
        # Streaming indicator (hidden by default)
        self._streaming_indicator = StreamingIndicator(id="streaming-indicator")
        yield self._streaming_indicator

    def on_scroll(self) -> None:
        """Track when user scrolls away from bottom."""
        # Check if we're at the bottom
        at_bottom = self.scroll_y >= (self.max_scroll_y - 2)
        self._user_scrolled_away = not at_bottom

        # Update streaming indicator visibility
        if self._is_streaming and self._user_scrolled_away:
            if self._streaming_indicator:
                self._streaming_indicator.show(self._token_count)
        else:
            if self._streaming_indicator:
                self._streaming_indicator.hide()

    # -------------------------------------------------------------------------
    # User Messages
    # -------------------------------------------------------------------------

    def add_user_message(self, content: str) -> None:
        """Add a user message block."""
        block = UserMessageBlock(content)
        self.mount(block)
        self._auto_scroll()

    # -------------------------------------------------------------------------
    # Agent Responses
    # -------------------------------------------------------------------------

    def start_response(self, bundle_name: str | None = None, agent_name: str | None = None) -> None:
        """Start a new agent response block."""
        self._current_response = AgentResponseBlock(bundle_name=bundle_name, agent_name=agent_name)
        self._current_response.set_streaming(True)
        self.mount(self._current_response)
        self._is_streaming = True
        self._token_count = 0
        self._auto_scroll()

    def append_content(self, content: str) -> None:
        """Append streaming content to current response."""
        if self._current_response:
            self._current_response.append_content(content)
            self._token_count += len(content.split())
            if self._streaming_indicator and self._user_scrolled_away:
                self._streaming_indicator.update_count(self._token_count)
        self._auto_scroll()

    def end_response(self) -> None:
        """End the current agent response."""
        if self._current_response:
            self._current_response.set_streaming(False)
        self._current_response = None
        self._is_streaming = False
        if self._streaming_indicator:
            self._streaming_indicator.hide()

    # -------------------------------------------------------------------------
    # Thinking Blocks
    # -------------------------------------------------------------------------

    def add_thinking(self, content: str) -> None:
        """Add or update thinking block."""
        if self._current_thinking:
            self._current_thinking.update_content(content)
        else:
            block = ThinkingBlock(content)
            self._current_thinking = block
            self.mount(block)
            self._auto_scroll()

    def end_thinking(self) -> None:
        """Mark thinking as complete."""
        self._current_thinking = None

    # -------------------------------------------------------------------------
    # Tool Calls
    # -------------------------------------------------------------------------

    def add_tool_call(
        self,
        tool_name: str,
        params: dict,
        result: str | None = None,
        status: str = "pending",
    ) -> str:
        """Add a tool call block and return its ID."""
        block_id = f"tool-{uuid.uuid4().hex[:8]}"
        block = ToolCallBlock(
            tool_name=tool_name,
            params=params,
            result=result,
            status=status,
            id=block_id,
        )
        self._tool_blocks[block_id] = block
        self.mount(block)
        self._auto_scroll()
        return block_id

    def update_tool_call(self, block_id: str, result: str, status: str) -> None:
        """Update an existing tool call block."""
        if block_id in self._tool_blocks:
            self._tool_blocks[block_id].update_result(result, status)

    # -------------------------------------------------------------------------
    # Sub-Sessions (agent delegation)
    # -------------------------------------------------------------------------

    def start_sub_session(self, parent_tool_call_id: str, session_id: str, agent_name: str) -> None:
        """Start tracking a sub-session (spawned agent).

        This updates the tool call block to show that a sub-agent is running.
        """
        # Find the tool call block by tool_call_id
        for block in self._tool_blocks.values():
            if hasattr(block, "_tool_call_id") and block._tool_call_id == parent_tool_call_id:
                block.set_sub_session(session_id, agent_name)
                return
        # If no matching tool call found, add a system message
        self.add_system_message(f"Sub-agent started: {agent_name}")

    def end_sub_session(self, parent_tool_call_id: str, status: str = "success") -> None:
        """End tracking a sub-session."""
        # Find the tool call block and update its status
        for block in self._tool_blocks.values():
            if hasattr(block, "_sub_session_id") and block._sub_session_id:
                block.end_sub_session(status)
                return

    # -------------------------------------------------------------------------
    # Inline Approvals (for low-risk tools)
    # -------------------------------------------------------------------------

    def add_inline_approval(
        self,
        tool_name: str,
        params: dict,
        approval_id: str,
    ) -> None:
        """Add an inline approval request (for low-risk tools)."""
        block = InlineApprovalBlock(
            tool_name=tool_name,
            params=params,
            approval_id=approval_id,
            id=f"approval-{approval_id}",
        )
        self._inline_approvals[approval_id] = block
        self.mount(block)
        self._auto_scroll()

    def remove_inline_approval(self, approval_id: str) -> None:
        """Remove an inline approval after response."""
        if approval_id in self._inline_approvals:
            self._inline_approvals[approval_id].remove()
            del self._inline_approvals[approval_id]

    # -------------------------------------------------------------------------
    # Errors and System Messages
    # -------------------------------------------------------------------------

    def add_error(self, error: str) -> None:
        """Add an error block."""
        block = ErrorBlock(error)
        self.mount(block)
        self._auto_scroll()

    def add_system_message(self, message: str) -> None:
        """Add a system message."""
        msg = SystemMessage(message)
        self.mount(msg)
        self._auto_scroll()

    def add_command_output(self, content: str) -> None:
        """Add command output with preserved formatting (for /help, etc.)."""
        block = CommandOutputBlock(content)
        self.mount(block)
        self._auto_scroll()

    # -------------------------------------------------------------------------
    # Navigation
    # -------------------------------------------------------------------------

    def scroll_to_bottom(self) -> None:
        """Scroll to bottom and resume following."""
        self._user_scrolled_away = False
        self.scroll_end()
        if self._streaming_indicator:
            self._streaming_indicator.hide()

    def _auto_scroll(self) -> None:
        """Auto-scroll if user hasn't scrolled away."""
        if not self._user_scrolled_away:
            self.scroll_end()

    # -------------------------------------------------------------------------
    # Clear
    # -------------------------------------------------------------------------

    def clear(self) -> None:
        """Clear all output."""
        self._tool_blocks.clear()
        self._inline_approvals.clear()
        self._current_thinking = None
        self._current_response = None
        self._is_streaming = False
        self._user_scrolled_away = False
        self._token_count = 0

        # Remove all blocks except the streaming indicator
        for child in list(self.children):
            if not isinstance(child, StreamingIndicator):
                child.remove()

        if self._streaming_indicator:
            self._streaming_indicator.hide()
