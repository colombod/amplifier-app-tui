"""Approval panel for tool permission requests."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Static


class ApprovalPanel(Container):
    """Modal overlay for approval requests.

    ╔════════════════════════════════════════════════════════════════╗
    ║  ⚠ Approval Required                                          ║
    ╠════════════════════════════════════════════════════════════════╣
    ║                                                                ║
    ║  Tool: bash                                                    ║
    ║                                                                ║
    ║  Command:                                                      ║
    ║    rm -rf /tmp/test                                            ║
    ║                                                                ║
    ║                                                                ║
    ║         [Y] Approve                    [N] Deny                ║
    ║                                                                ║
    ╚════════════════════════════════════════════════════════════════╝
    """

    DEFAULT_CSS = """
    ApprovalPanel {
        display: none;
        layer: overlay;
        align: center middle;
        width: 100%;
        height: 100%;
        background: $background 80%;
    }

    ApprovalPanel.visible {
        display: block;
    }

    ApprovalPanel #approval-dialog {
        width: 60;
        max-width: 90%;
        height: auto;
        max-height: 80%;
        border: thick $warning;
        background: $surface;
        padding: 1 2;
    }

    ApprovalPanel #approval-header {
        text-style: bold;
        color: $warning;
        text-align: center;
        margin-bottom: 1;
    }

    ApprovalPanel #approval-tool {
        margin-bottom: 1;
    }

    ApprovalPanel #approval-tool-name {
        text-style: bold;
    }

    ApprovalPanel #approval-params-header {
        color: $text-muted;
        margin-top: 1;
    }

    ApprovalPanel #approval-params {
        margin-left: 2;
        padding: 1;
        background: $surface-darken-1;
        max-height: 10;
        overflow-y: auto;
    }

    ApprovalPanel #approval-actions {
        margin-top: 2;
        text-align: center;
    }

    ApprovalPanel .action-hint {
        color: $text-muted;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._tool_name = ""
        self._params: dict = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="approval-dialog"):
            yield Static("⚠ Approval Required", id="approval-header")
            yield Static("Tool: ", id="approval-tool")
            yield Static("Parameters:", id="approval-params-header")
            yield Static("", id="approval-params")
            yield Static(
                "[Y] Approve          [N] Deny",
                id="approval-actions",
                classes="action-hint",
            )

    def show_approval(self, tool: str, params: dict) -> None:
        """Show the approval panel with tool details."""
        self._tool_name = tool
        self._params = params

        # Update tool name
        self.query_one("#approval-tool", Static).update(f"Tool: [bold]{tool}[/bold]")

        # Format parameters
        params_text = self._format_params(params)
        self.query_one("#approval-params", Static).update(params_text)

        # Show panel
        self.add_class("visible")

    def hide(self) -> None:
        """Hide the approval panel."""
        self.remove_class("visible")
        self._tool_name = ""
        self._params = {}

    def _format_params(self, params: dict) -> str:
        """Format parameters for display."""
        if not params:
            return "(no parameters)"

        lines = []
        for key, value in params.items():
            value_str = str(value)
            # Truncate long values
            if len(value_str) > 100:
                value_str = value_str[:97] + "..."
            # Handle multi-line values
            if "\n" in value_str:
                value_str = value_str.replace("\n", "\\n")[:100] + "..."
            lines.append(f"{key}: {value_str}")

        return "\n".join(lines)

    @property
    def is_visible(self) -> bool:
        """Check if approval panel is visible."""
        return self.has_class("visible")

    @property
    def tool_name(self) -> str:
        """Get the tool name requiring approval."""
        return self._tool_name

    @property
    def params(self) -> dict:
        """Get the parameters requiring approval."""
        return self._params
