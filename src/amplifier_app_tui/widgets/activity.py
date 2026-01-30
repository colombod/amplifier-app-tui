"""Activity panel for showing in-flight tools and sub-sessions.

Design goal: Keep main chat clean by moving intermediate activity here.
Users can see what's running without polluting the conversation.

Layout:
┌─ Activity (3) ─────────┐
│ ◐ bash       running   │
│   pytest -v    3.2s    │
│ ◐ read_file  running   │
│   src/auth.py          │
│ ○ grep       queued    │
└────────────────────────┘
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import ScrollableContainer, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static

if TYPE_CHECKING:
    pass


@dataclass
class ActivityItem:
    """An in-flight activity (tool call or sub-session)."""

    id: str
    name: str
    status: str = "pending"  # pending, running, success, error
    detail: str = ""  # Brief description (e.g., file path, command)
    started_at: datetime = field(default_factory=datetime.now)
    result_summary: str | None = None
    # For sub-sessions
    is_sub_session: bool = False
    agent_name: str | None = None


class ActivityItemWidget(Static):
    """Single activity item display.

    ◐ bash       running
      pytest -v    3.2s
    """

    DEFAULT_CSS = """
    ActivityItemWidget {
        height: auto;
        padding: 0 1;
        margin-bottom: 1;
    }

    ActivityItemWidget .activity-header {
        text-style: bold;
    }

    ActivityItemWidget .activity-detail {
        color: $text-muted;
        padding-left: 2;
    }

    ActivityItemWidget .activity-time {
        color: $text-muted;
        text-align: right;
    }

    ActivityItemWidget.pending .activity-header {
        color: $warning;
    }

    ActivityItemWidget.running .activity-header {
        color: $primary;
    }

    ActivityItemWidget.success .activity-header {
        color: $success;
    }

    ActivityItemWidget.error .activity-header {
        color: $error;
    }
    """

    ICONS = {
        "pending": "○",  # Hollow = waiting
        "running": "◐",  # Half = in progress
        "success": "●",  # Solid = complete
        "error": "✗",  # X = failed
    }

    def __init__(self, item: ActivityItem, **kwargs) -> None:
        super().__init__(**kwargs)
        self.item = item

    def compose(self) -> ComposeResult:
        icon = self.ICONS.get(self.item.status, "○")
        elapsed = self._get_elapsed()

        # Header: icon + name + status + time
        status_text = self.item.status if self.item.status != "running" else ""
        if self.item.is_sub_session and self.item.agent_name:
            name = f"@{self.item.agent_name}"
        else:
            name = self.item.name

        yield Static(f"{icon} {name} {status_text} {elapsed}", classes="activity-header")

        # Detail line (truncated)
        if self.item.detail:
            detail = (
                self.item.detail[:40] + "..." if len(self.item.detail) > 40 else self.item.detail
            )
            yield Static(f"  {detail}", classes="activity-detail")

    def on_mount(self) -> None:
        """Set status class."""
        self.add_class(self.item.status)

    def _get_elapsed(self) -> str:
        """Get elapsed time string."""
        elapsed = datetime.now() - self.item.started_at
        seconds = int(elapsed.total_seconds())
        if seconds < 60:
            return f"{seconds}s"
        minutes = seconds // 60
        return f"{minutes}m{seconds % 60}s"

    def update_item(self, item: ActivityItem) -> None:
        """Update the displayed item."""
        self.item = item
        # Update classes
        self.remove_class("pending", "running", "success", "error")
        self.add_class(item.status)
        # Re-render
        self.refresh(recompose=True)


class ActivityPanel(Vertical):
    """Panel showing in-flight activity.

    Collapsible sidebar showing:
    - Running tool calls
    - Pending tool calls
    - Sub-sessions in progress
    """

    DEFAULT_CSS = """
    ActivityPanel {
        width: 30;
        min-width: 20;
        max-width: 40;
        height: 100%;
        border-left: solid $border;
        background: $surface;
    }

    ActivityPanel.collapsed {
        width: 0;
        min-width: 0;
        display: none;
    }

    ActivityPanel .panel-header {
        height: 1;
        background: $primary-darken-2;
        padding: 0 1;
        text-style: bold;
    }

    ActivityPanel .panel-content {
        height: 1fr;
        padding: 1;
    }

    ActivityPanel .empty-message {
        color: $text-muted;
        text-style: italic;
        padding: 1;
    }
    """

    collapsed: reactive[bool] = reactive(False)

    class ActivityCompleted(Message):
        """Fired when an activity completes (for showing summary in main chat)."""

        def __init__(self, item: ActivityItem) -> None:
            super().__init__()
            self.item = item

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._activities: dict[str, ActivityItem] = {}

    def compose(self) -> ComposeResult:
        count = len(self._activities)
        yield Static(f"▼ Activity ({count})", classes="panel-header", id="activity-header")
        with ScrollableContainer(classes="panel-content", id="activity-content"):
            if not self._activities:
                yield Static("No activity", classes="empty-message")

    def add_activity(self, item: ActivityItem) -> None:
        """Add a new activity to track."""
        self._activities[item.id] = item
        self._update_display()

    def update_activity(self, activity_id: str, **updates) -> None:
        """Update an existing activity."""
        if activity_id in self._activities:
            item = self._activities[activity_id]
            for key, value in updates.items():
                if hasattr(item, key):
                    setattr(item, key, value)

            # If completed, notify for summary in main chat
            if updates.get("status") in ("success", "error"):
                self.post_message(self.ActivityCompleted(item))

            self._update_display()

    def remove_activity(self, activity_id: str) -> None:
        """Remove an activity (after completion)."""
        if activity_id in self._activities:
            del self._activities[activity_id]
            self._update_display()

    def clear_completed(self) -> None:
        """Remove all completed activities."""
        self._activities = {
            k: v for k, v in self._activities.items() if v.status not in ("success", "error")
        }
        self._update_display()

    def get_activity_count(self) -> int:
        """Get count of active (non-completed) activities."""
        return sum(1 for a in self._activities.values() if a.status in ("pending", "running"))

    def _update_display(self) -> None:
        """Update the panel display."""
        # Update header count
        try:
            header = self.query_one("#activity-header", Static)
            count = len(self._activities)
            icon = "▶" if self.collapsed else "▼"
            header.update(f"{icon} Activity ({count})")
        except Exception:
            pass

        # Update content
        try:
            content = self.query_one("#activity-content", ScrollableContainer)
            content.remove_children()

            if not self._activities:
                content.mount(Static("No activity", classes="empty-message"))
            else:
                # Sort: running first, then pending, then by start time
                sorted_items = sorted(
                    self._activities.values(),
                    key=lambda x: (
                        0 if x.status == "running" else 1 if x.status == "pending" else 2,
                        x.started_at,
                    ),
                )
                for item in sorted_items:
                    content.mount(ActivityItemWidget(item, id=f"activity-{item.id}"))
        except Exception:
            pass

    def toggle_collapse(self) -> None:
        """Toggle panel visibility."""
        self.collapsed = not self.collapsed
        self.toggle_class("collapsed")
        self._update_display()

    def on_click(self, event) -> None:
        """Handle click on header to toggle."""
        try:
            header = self.query_one("#activity-header", Static)
            if event.widget == header:
                self.toggle_collapse()
        except Exception:
            pass
