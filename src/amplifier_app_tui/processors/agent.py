"""Agent processor for sub-sessions and agent delegation.

Handles:
- session_fork (sub-session spawned)
- session_start, session_end
- Content/tool events with nesting_depth > 0

Maintains state for tracking nested agent sessions.
Based on amplifier-web's sub-session handling patterns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .base import EventProcessor, ProcessorAction, ProcessorResult


@dataclass
class SubSession:
    """A sub-session (nested agent) state."""

    session_id: str
    parent_tool_call_id: str
    agent_name: str | None = None
    status: str = "running"  # running, complete, error
    nesting_depth: int = 1


@dataclass
class AgentState:
    """State for agent/sub-session processing."""

    # Map parent_tool_call_id -> SubSession
    sub_sessions: dict[str, SubSession] = field(default_factory=dict)
    # Map child_session_id -> parent_tool_call_id (for routing events)
    child_to_parent: dict[str, str] = field(default_factory=dict)
    # Current main session info
    main_session_id: str | None = None
    main_session_status: str = "disconnected"


class AgentProcessor(EventProcessor):
    """Processes agent delegation and sub-session events.

    Tracks nested sessions created via the 'task' tool, maintaining
    the mapping between child session IDs and their parent tool calls.
    """

    # Event types this processor handles
    HANDLED_EVENTS = frozenset(
        [
            "session_fork",
            "session_start",
            "session_end",
            "session:start",
            "session:end",
            "session_created",
        ]
    )

    def __init__(self, app: Any = None) -> None:
        super().__init__(app)
        self._state = AgentState()

    def handles(self, event_type: str) -> bool:
        return event_type in self.HANDLED_EVENTS

    def process(self, event_type: str, data: dict[str, Any]) -> ProcessorResult:
        """Process an agent/session event."""
        normalized = event_type.replace(":", "_")

        if normalized == "session_fork":
            return self._handle_session_fork(data)
        elif normalized in ("session_start", "session_created"):
            return self._handle_session_start(data)
        elif normalized == "session_end":
            return self._handle_session_end(data)

        return ProcessorResult(handled=False)

    def _handle_session_fork(self, data: dict[str, Any]) -> ProcessorResult:
        """Handle sub-session fork (agent delegation).

        This is called when the 'task' tool spawns a new agent session.
        """
        child_id = data.get("child_id")
        parent_tool_call_id = data.get("parent_tool_call_id")
        agent_name = data.get("agent")

        if not child_id:
            return ProcessorResult(handled=False)

        # If no parent_tool_call_id provided, we need to find it
        # This happens when the event doesn't include it directly
        if not parent_tool_call_id:
            # Try to infer from pending task tool calls
            # For now, just use the child_id as a fallback key
            parent_tool_call_id = f"task_{child_id}"

        # Create sub-session record
        sub_session = SubSession(
            session_id=child_id,
            parent_tool_call_id=parent_tool_call_id,
            agent_name=agent_name,
            status="running",
        )
        self._state.sub_sessions[parent_tool_call_id] = sub_session
        self._state.child_to_parent[child_id] = parent_tool_call_id

        # Update UI if app available
        if self._app:
            self._app.start_sub_session(
                parent_tool_call_id=parent_tool_call_id,
                session_id=child_id,
                agent_name=agent_name or "agent",
            )

        return ProcessorResult(
            handled=True,
            action=ProcessorAction.UPDATE_UI,
            data={
                "child_id": child_id,
                "parent_tool_call_id": parent_tool_call_id,
                "agent": agent_name,
            },
        )

    def _handle_session_start(self, data: dict[str, Any]) -> ProcessorResult:
        """Handle session start event."""
        session_id = data.get("session_id")
        parent_id = data.get("parent_id")

        if parent_id:
            # This is a sub-session start
            parent_tool_call_id = self._state.child_to_parent.get(session_id or "")
            if parent_tool_call_id and parent_tool_call_id in self._state.sub_sessions:
                self._state.sub_sessions[parent_tool_call_id].status = "running"
        else:
            # Main session start
            self._state.main_session_id = session_id
            self._state.main_session_status = "connected"

        return ProcessorResult(
            handled=True,
            action=ProcessorAction.UPDATE_UI,
            data={"session_id": session_id, "is_sub_session": bool(parent_id)},
        )

    def _handle_session_end(self, data: dict[str, Any]) -> ProcessorResult:
        """Handle session end event."""
        session_id = data.get("session_id")
        status = data.get("status", "complete")

        # Check if this is a sub-session
        parent_tool_call_id = self._state.child_to_parent.get(session_id or "")
        if parent_tool_call_id:
            # Sub-session ended
            if parent_tool_call_id in self._state.sub_sessions:
                self._state.sub_sessions[parent_tool_call_id].status = status

            # Update UI if app available
            if self._app:
                self._app.end_sub_session(
                    parent_tool_call_id=parent_tool_call_id,
                    status=status,
                )

            return ProcessorResult(
                handled=True,
                action=ProcessorAction.UPDATE_UI,
                data={
                    "session_id": session_id,
                    "parent_tool_call_id": parent_tool_call_id,
                    "status": status,
                },
            )
        else:
            # Main session ended
            self._state.main_session_status = "disconnected"
            return ProcessorResult(
                handled=True,
                action=ProcessorAction.UPDATE_UI,
                data={"session_id": session_id, "status": status},
            )

    def get_parent_tool_call_id(self, child_session_id: str) -> str | None:
        """Get the parent tool call ID for a child session.

        Used for routing events from sub-sessions to the correct context.
        """
        return self._state.child_to_parent.get(child_session_id)

    def get_sub_session(self, parent_tool_call_id: str) -> SubSession | None:
        """Get a sub-session by its parent tool call ID."""
        return self._state.sub_sessions.get(parent_tool_call_id)

    def is_sub_session_event(self, data: dict[str, Any]) -> bool:
        """Check if an event belongs to a sub-session.

        Events from sub-sessions have either:
        - parent_tool_call_id set
        - child_session_id set (can be mapped to parent)
        - nesting_depth > 0
        """
        if data.get("parent_tool_call_id"):
            return True
        if data.get("child_session_id"):
            return data["child_session_id"] in self._state.child_to_parent
        if data.get("nesting_depth", 0) > 0:
            return True
        return False

    def reset(self) -> None:
        """Reset agent state for new session."""
        self._state = AgentState()
        return None

    def get_state(self) -> dict[str, Any]:
        """Get current state for debugging."""
        return {
            "sub_sessions": {
                k: {
                    "session_id": v.session_id,
                    "agent": v.agent_name,
                    "status": v.status,
                }
                for k, v in self._state.sub_sessions.items()
            },
            "active_count": sum(
                1 for s in self._state.sub_sessions.values() if s.status == "running"
            ),
            "main_session_id": self._state.main_session_id,
            "main_session_status": self._state.main_session_status,
        }

    @property
    def has_active_sub_sessions(self) -> bool:
        """Check if there are any active sub-sessions."""
        return any(s.status == "running" for s in self._state.sub_sessions.values())
