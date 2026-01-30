"""Base processor interface and types.

Defines the contract for all event processors and common types
used across the processor system.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..app import AmplifierTUI


class ProcessorAction(Enum):
    """Actions a processor can request."""

    NONE = "none"  # No action needed
    UPDATE_UI = "update_ui"  # Request UI refresh
    SET_STATE = "set_state"  # Change agent state
    ADD_MESSAGE = "add_message"  # Add a message to output
    ADD_ERROR = "add_error"  # Add an error message


@dataclass
class ProcessorResult:
    """Result from processing an event.

    Processors return this to indicate what happened and any
    actions the bridge should take.
    """

    handled: bool = False
    action: ProcessorAction = ProcessorAction.NONE
    data: dict[str, Any] = field(default_factory=dict)
    message: str | None = None
    error: str | None = None
    new_state: str | None = None  # For SET_STATE action


class EventProcessor(ABC):
    """Base class for event processors.

    Each processor handles a specific domain of events and
    maintains its own state. Processors are designed to be
    testable in isolation.
    """

    def __init__(self, app: AmplifierTUI | None = None) -> None:
        """Initialize processor.

        Args:
            app: The TUI application instance. Can be None for testing.
        """
        self._app = app

    @property
    def app(self) -> AmplifierTUI | None:
        """Get the app instance."""
        return self._app

    def set_app(self, app: AmplifierTUI) -> None:
        """Set the app instance (for deferred initialization)."""
        self._app = app

    @abstractmethod
    def handles(self, event_type: str) -> bool:
        """Check if this processor handles the given event type.

        Args:
            event_type: The event type string

        Returns:
            True if this processor should handle the event
        """
        ...

    @abstractmethod
    def process(self, event_type: str, data: dict[str, Any]) -> ProcessorResult:
        """Process an event.

        Args:
            event_type: The event type string
            data: The event data dictionary

        Returns:
            ProcessorResult indicating what happened
        """
        ...

    def reset(self) -> None:
        """Reset processor state.

        Called when starting a new session or clearing state.
        Override in subclasses that maintain state.
        Default implementation does nothing (stateless processors).
        """
        # Default no-op for stateless processors
        return None

    def get_state(self) -> dict[str, Any]:
        """Get processor state for debugging/testing.

        Returns:
            Dictionary of current processor state
        """
        return {}
