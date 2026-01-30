"""Event router that dispatches events to appropriate processors.

The router is the central hub that:
1. Receives events from the runtime bridge
2. Determines which processor(s) should handle each event
3. Dispatches to processors and aggregates results
4. Provides access to processor state
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .agent import AgentProcessor
from .approval import ApprovalProcessor
from .base import EventProcessor, ProcessorResult
from .content import ContentProcessor
from .session import SessionProcessor
from .todo import TodoProcessor
from .tool import ToolProcessor

if TYPE_CHECKING:
    from ..app import AmplifierTUI


class EventRouter:
    """Routes events to appropriate processors.

    The router manages all processors and handles event dispatch.
    It also provides a unified interface for querying processor state.
    """

    def __init__(self, app: AmplifierTUI | None = None) -> None:
        """Initialize the router with all processors.

        Args:
            app: The TUI application instance. Can be None for testing.
        """
        self._app = app

        # Initialize all processors
        self._content = ContentProcessor(app)
        self._tool = ToolProcessor(app)
        self._todo = TodoProcessor(app)
        self._agent = AgentProcessor(app)
        self._approval = ApprovalProcessor(app)
        self._session = SessionProcessor(app)

        # List of all processors for iteration
        self._processors: list[EventProcessor] = [
            self._content,
            self._tool,
            self._todo,
            self._agent,
            self._approval,
            self._session,
        ]

    def set_app(self, app: AmplifierTUI) -> None:
        """Set the app instance on all processors."""
        self._app = app
        for processor in self._processors:
            processor.set_app(app)

    def route(self, event_type: str, data: dict[str, Any]) -> ProcessorResult:
        """Route an event to the appropriate processor(s).

        Args:
            event_type: The event type string
            data: The event data dictionary

        Returns:
            ProcessorResult from the handling processor, or a not-handled result
        """
        # Check for sub-session events first
        # If it's a sub-session event, we might need special routing
        if self._agent.is_sub_session_event(data):
            # Get the parent tool call ID for routing context
            child_session_id = data.get("child_session_id")
            if child_session_id:
                parent_tool_call_id = self._agent.get_parent_tool_call_id(child_session_id)
                if parent_tool_call_id:
                    data["parent_tool_call_id"] = parent_tool_call_id

        # Find processor that handles this event type
        for processor in self._processors:
            if processor.handles(event_type):
                result = processor.process(event_type, data)
                if result.handled:
                    return result

        # No processor handled the event
        return ProcessorResult(handled=False)

    def reset(self) -> None:
        """Reset all processor states."""
        for processor in self._processors:
            processor.reset()

    def reset_content_block_mapping(self) -> None:
        """Reset content block index mapping.

        Called after tool results to prepare for next model response.
        """
        self._content.reset_block_mapping()

    # -------------------------------------------------------------------------
    # Processor accessors for direct state access
    # -------------------------------------------------------------------------

    @property
    def content(self) -> ContentProcessor:
        """Get the content processor."""
        return self._content

    @property
    def tool(self) -> ToolProcessor:
        """Get the tool processor."""
        return self._tool

    @property
    def todo(self) -> TodoProcessor:
        """Get the todo processor."""
        return self._todo

    @property
    def agent(self) -> AgentProcessor:
        """Get the agent processor."""
        return self._agent

    @property
    def approval(self) -> ApprovalProcessor:
        """Get the approval processor."""
        return self._approval

    @property
    def session(self) -> SessionProcessor:
        """Get the session processor."""
        return self._session

    # -------------------------------------------------------------------------
    # Convenience state queries
    # -------------------------------------------------------------------------

    def is_streaming(self) -> bool:
        """Check if currently streaming content."""
        return self._content.is_streaming

    def has_pending_tools(self) -> bool:
        """Check if there are pending tool calls."""
        return self._tool.has_pending_tools()

    def has_pending_approvals(self) -> bool:
        """Check if there are pending approvals."""
        return self._approval.has_pending

    def has_active_sub_sessions(self) -> bool:
        """Check if there are active sub-sessions."""
        return self._agent.has_active_sub_sessions

    def get_in_progress_todo(self) -> str | None:
        """Get the currently in-progress todo item text."""
        item = self._todo.in_progress_item
        return item.active_form if item else None

    def get_all_state(self) -> dict[str, Any]:
        """Get state from all processors for debugging."""
        return {
            "content": self._content.get_state(),
            "tool": self._tool.get_state(),
            "todo": self._todo.get_state(),
            "agent": self._agent.get_state(),
            "approval": self._approval.get_state(),
            "session": self._session.get_state(),
        }
