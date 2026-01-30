"""Todo processor for todo list updates.

Handles:
- todo:update
- todo_update

Maintains state for the current todo list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .base import EventProcessor, ProcessorAction, ProcessorResult


@dataclass
class TodoItem:
    """A todo item."""

    content: str
    status: str  # pending, in_progress, completed
    active_form: str = ""


@dataclass
class TodoState:
    """State for todo processing."""

    items: list[TodoItem] = field(default_factory=list)
    last_update_time: float = 0


class TodoProcessor(EventProcessor):
    """Processes todo list update events.

    Maintains state for the current todo list and notifies UI
    of changes.
    """

    # Event types this processor handles
    HANDLED_EVENTS = frozenset(
        [
            "todo:update",
            "todo_update",
        ]
    )

    def __init__(self, app: Any = None) -> None:
        super().__init__(app)
        self._state = TodoState()

    def handles(self, event_type: str) -> bool:
        return event_type in self.HANDLED_EVENTS

    def process(self, event_type: str, data: dict[str, Any]) -> ProcessorResult:
        """Process a todo event."""
        return self._handle_todo_update(data)

    def _handle_todo_update(self, data: dict[str, Any]) -> ProcessorResult:
        """Handle todo list update."""
        # Extract todos from event data
        # Format from amplifier-core: {"todos": [...], "action": "create|update"}
        todos_data = data.get("todos", [])
        action = data.get("action", "update")

        # Parse todo items
        new_items: list[TodoItem] = []
        for item in todos_data:
            if isinstance(item, dict):
                new_items.append(
                    TodoItem(
                        content=item.get("content", ""),
                        status=item.get("status", "pending"),
                        active_form=item.get("activeForm", item.get("active_form", "")),
                    )
                )

        # Update state
        if action == "create":
            self._state.items = new_items
        else:
            self._state.items = new_items

        import time

        self._state.last_update_time = time.time()

        # Update UI if app available
        if self._app:
            self._update_todo_panel()

        return ProcessorResult(
            handled=True,
            action=ProcessorAction.UPDATE_UI,
            data={
                "action": action,
                "todo_count": len(new_items),
                "pending": sum(1 for t in new_items if t.status == "pending"),
                "in_progress": sum(1 for t in new_items if t.status == "in_progress"),
                "completed": sum(1 for t in new_items if t.status == "completed"),
            },
        )

    def _update_todo_panel(self) -> None:
        """Update the todo panel in the UI."""
        if not self._app:
            return

        # Try to get the todo panel
        try:
            from ..widgets.todos import TodoPanel

            todo_panel = self._app.query_one(TodoPanel)
            if todo_panel:
                # Convert items to the format the panel expects
                items = [
                    {
                        "content": item.content,
                        "status": item.status,
                        "activeForm": item.active_form,
                    }
                    for item in self._state.items
                ]
                todo_panel.update_todos(items)
        except Exception:
            # Panel not available or not mounted
            pass

    def reset(self) -> None:
        """Reset todo state for new session."""
        self._state = TodoState()
        return None

    def get_state(self) -> dict[str, Any]:
        """Get current state for debugging."""
        return {
            "items": [
                {
                    "content": item.content,
                    "status": item.status,
                }
                for item in self._state.items
            ],
            "count": len(self._state.items),
            "pending": sum(1 for t in self._state.items if t.status == "pending"),
            "in_progress": sum(1 for t in self._state.items if t.status == "in_progress"),
            "completed": sum(1 for t in self._state.items if t.status == "completed"),
        }

    @property
    def items(self) -> list[TodoItem]:
        """Get current todo items."""
        return self._state.items

    @property
    def in_progress_item(self) -> TodoItem | None:
        """Get the current in-progress item, if any."""
        for item in self._state.items:
            if item.status == "in_progress":
                return item
        return None
