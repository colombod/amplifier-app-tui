"""Todo panel widget showing task progress."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.reactive import reactive
from textual.widgets import Static


class TodoItem(Static):
    """Single todo item: ✓/●/○ Task description."""

    DEFAULT_CSS = """
    TodoItem {
        height: 1;
        padding: 0 1;
    }

    TodoItem.completed {
        color: $success;
    }

    TodoItem.in_progress {
        color: $warning;
    }

    TodoItem.pending {
        color: $text-muted;
    }
    """

    ICONS = {
        "completed": "✓",
        "in_progress": "●",
        "pending": "○",
    }

    def __init__(self, todo: dict, **kwargs) -> None:
        self._todo = todo
        status = todo.get("status", "pending")
        icon = self.ICONS.get(status, "○")

        # Use activeForm for in_progress, content otherwise
        if status == "in_progress":
            text = todo.get("activeForm", todo.get("content", ""))
        else:
            text = todo.get("content", "")

        # Truncate long text
        if len(text) > 22:
            text = text[:19] + "..."

        super().__init__(f"{icon} {text}", **kwargs)
        self.add_class(status)


class TodoHeader(Static):
    """Todo panel header: ▼ Tasks (2/5)."""

    DEFAULT_CSS = """
    TodoHeader {
        height: 1;
        padding: 0 1;
        text-style: bold;
        border-bottom: solid $border;
    }
    """

    completed: reactive[int] = reactive(0)
    total: reactive[int] = reactive(0)

    def render(self) -> str:
        return f"▼ Tasks ({self.completed}/{self.total})"

    def update_counts(self, completed: int, total: int) -> None:
        """Update task counts."""
        self.completed = completed
        self.total = total


class TodoList(VerticalScroll):
    """Scrollable list of todo items."""

    DEFAULT_CSS = """
    TodoList {
        height: 1fr;
        padding: 0;
    }
    """

    def update_todos(self, todos: list[dict]) -> None:
        """Update the todo list with new items."""
        # Remove existing items
        self.remove_children()

        # Add new items
        for todo in todos:
            self.mount(TodoItem(todo))


class TodoPanel(Container):
    """Side panel showing task progress.

    ▼ Tasks (2/5)
    ────────────────────────
    ✓ Read auth.py
    ● Analyzing security
    ○ Check permissions
    ○ Review error handling
    ○ Write summary
    """

    DEFAULT_CSS = """
    TodoPanel {
        width: 28;
        border-left: solid $border;
        padding: 0;
    }

    TodoPanel.hidden {
        display: none;
    }

    TodoPanel.empty {
        display: none;
    }
    """

    def compose(self) -> ComposeResult:
        yield TodoHeader(id="todo-header")
        yield TodoList(id="todo-list")

    def update_todos(self, todos: list[dict]) -> None:
        """Update the todo panel with new todos."""
        if not todos:
            self.add_class("empty")
            return

        self.remove_class("empty")

        # Count completed
        completed = sum(1 for t in todos if t.get("status") == "completed")
        total = len(todos)

        # Update header
        self.query_one("#todo-header", TodoHeader).update_counts(completed, total)

        # Update list
        self.query_one("#todo-list", TodoList).update_todos(todos)

    def clear(self) -> None:
        """Clear the todo panel."""
        self.add_class("empty")
        self.query_one("#todo-header", TodoHeader).update_counts(0, 0)
        self.query_one("#todo-list", TodoList).remove_children()
