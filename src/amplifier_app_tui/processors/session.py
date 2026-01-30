"""Session processor for session lifecycle events.

Handles:
- prompt_complete
- error
- display_message

Tracks overall session state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import EventProcessor, ProcessorAction, ProcessorResult


@dataclass
class SessionState:
    """State for session processing."""

    turn_count: int = 0
    status: str = "idle"  # idle, executing, error
    last_error: str | None = None


class SessionProcessor(EventProcessor):
    """Processes session lifecycle events.

    Handles prompt completion, errors, and display messages.
    """

    # Event types this processor handles
    HANDLED_EVENTS = frozenset(
        [
            "prompt_complete",
            "error",
            "display_message",
            "prompt:complete",
        ]
    )

    def __init__(self, app: Any = None) -> None:
        super().__init__(app)
        self._state = SessionState()

    def handles(self, event_type: str) -> bool:
        return event_type in self.HANDLED_EVENTS

    def process(self, event_type: str, data: dict[str, Any]) -> ProcessorResult:
        """Process a session event."""
        normalized = event_type.replace(":", "_")

        if normalized == "prompt_complete":
            return self._handle_prompt_complete(data)
        elif normalized == "error":
            return self._handle_error(data)
        elif normalized == "display_message":
            return self._handle_display_message(data)

        return ProcessorResult(handled=False)

    def _handle_prompt_complete(self, data: dict[str, Any]) -> ProcessorResult:
        """Handle prompt complete event."""
        turn = data.get("turn", self._state.turn_count + 1)
        self._state.turn_count = turn
        self._state.status = "idle"

        # Update UI if app available
        if self._app:
            self._app.end_response()
            self._app.set_agent_state("idle")

        return ProcessorResult(
            handled=True,
            action=ProcessorAction.UPDATE_UI,
            data={"turn": turn},
            new_state="idle",
        )

    def _handle_error(self, data: dict[str, Any]) -> ProcessorResult:
        """Handle error event."""
        error = data.get("error", "Unknown error")
        self._state.last_error = error
        self._state.status = "error"

        # Update UI if app available
        if self._app:
            self._app.add_error(error)
            self._app.set_agent_state("idle")

        return ProcessorResult(
            handled=True,
            action=ProcessorAction.ADD_ERROR,
            error=error,
            data={"error": error},
        )

    def _handle_display_message(self, data: dict[str, Any]) -> ProcessorResult:
        """Handle display message event."""
        level = data.get("level", "info")
        message = data.get("message", "")
        source = data.get("source")

        # Update UI if app available
        if self._app:
            if level == "error":
                self._app.add_error(message)
            else:
                self._app.add_system_message(message)

        return ProcessorResult(
            handled=True,
            action=ProcessorAction.ADD_MESSAGE,
            message=message,
            data={"level": level, "source": source},
        )

    def reset(self) -> None:
        """Reset session state."""
        self._state = SessionState()
        return None

    def get_state(self) -> dict[str, Any]:
        """Get current state for debugging."""
        return {
            "turn_count": self._state.turn_count,
            "status": self._state.status,
            "last_error": self._state.last_error,
        }

    @property
    def turn_count(self) -> int:
        """Get current turn count."""
        return self._state.turn_count

    @property
    def status(self) -> str:
        """Get current status."""
        return self._state.status
