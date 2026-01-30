"""Tool processor for tool calls and results.

Handles:
- tool_call (tool:pre mapped by runtime)
- tool_result (tool:post mapped by runtime)
- tool_error

Maintains state for active tool calls and their results.
Based on amplifier-web's tool handling patterns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .base import EventProcessor, ProcessorAction, ProcessorResult


@dataclass
class ToolCall:
    """A tool call in progress or completed."""

    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]
    status: str = "pending"  # pending, running, complete, error
    result: str | None = None
    error: str | None = None
    order: int = 0
    # UI block ID returned from app.add_tool_call
    ui_block_id: str | None = None
    # Sub-session context
    child_session_id: str | None = None
    parent_tool_call_id: str | None = None
    nesting_depth: int = 0


@dataclass
class ToolState:
    """State for tool processing."""

    active_calls: dict[str, ToolCall] = field(default_factory=dict)  # tool_call_id -> ToolCall
    completed_calls: list[ToolCall] = field(default_factory=list)
    order_counter: int = 0


class ToolProcessor(EventProcessor):
    """Processes tool call and result events.

    Maintains state for tracking active tool calls, their results,
    and supports sub-session context for nested agent delegation.
    """

    # Event types this processor handles
    HANDLED_EVENTS = frozenset(
        [
            # Tool events (runtime normalized format)
            "tool_call",
            "tool_result",
            "tool_error",
            # Alternative formats (amplifier-core format)
            "tool:pre",
            "tool:post",
            "tool:error",
        ]
    )

    def __init__(self, app: Any = None) -> None:
        super().__init__(app)
        self._state = ToolState()

    def handles(self, event_type: str) -> bool:
        return event_type in self.HANDLED_EVENTS

    def process(self, event_type: str, data: dict[str, Any]) -> ProcessorResult:
        """Process a tool event."""
        # Normalize event type
        normalized = event_type.replace(":", "_")

        if normalized in ("tool_call", "tool_pre"):
            return self._handle_tool_call(data)
        elif normalized in ("tool_result", "tool_post"):
            return self._handle_tool_result(data)
        elif normalized in ("tool_error",):
            return self._handle_tool_error(data)

        return ProcessorResult(handled=False)

    def _handle_tool_call(self, data: dict[str, Any]) -> ProcessorResult:
        """Handle tool call start."""
        tool_call_id = data.get("tool_call_id", "")
        tool_name = data.get("tool_name", data.get("name", "unknown"))
        arguments = data.get("arguments", data.get("input", {}))
        status = data.get("status", "running")

        # Sub-session context
        child_session_id = data.get("child_session_id")
        parent_tool_call_id = data.get("parent_tool_call_id")
        nesting_depth = data.get("nesting_depth", 0)

        # Create tool call record
        tool_call = ToolCall(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=arguments if isinstance(arguments, dict) else {},
            status=status,
            order=self._state.order_counter,
            child_session_id=child_session_id,
            parent_tool_call_id=parent_tool_call_id,
            nesting_depth=nesting_depth,
        )
        self._state.order_counter += 1
        self._state.active_calls[tool_call_id] = tool_call

        # Update UI if app available
        if self._app:
            ui_block_id = self._app.add_tool_call(
                tool_name=tool_name,
                params=arguments if isinstance(arguments, dict) else {},
                result=None,
                status=status,
            )
            tool_call.ui_block_id = ui_block_id

        return ProcessorResult(
            handled=True,
            action=ProcessorAction.UPDATE_UI,
            data={
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "status": status,
            },
        )

    def _handle_tool_result(self, data: dict[str, Any]) -> ProcessorResult:
        """Handle tool result."""
        tool_call_id = data.get("tool_call_id", "")
        output = data.get("output", data.get("result", ""))
        success = data.get("success", True)
        error = data.get("error")

        # Update tool call record
        tool_call = self._state.active_calls.get(tool_call_id)
        if tool_call:
            tool_call.status = "complete" if success else "error"
            tool_call.result = output if isinstance(output, str) else str(output)
            tool_call.error = error
            # Move to completed
            self._state.completed_calls.append(tool_call)
            del self._state.active_calls[tool_call_id]

        # Update UI if app available
        if self._app and tool_call and tool_call.ui_block_id:
            status_str = "success" if success else "error"
            self._app.update_tool_call(
                block_id=tool_call.ui_block_id,
                result=output if isinstance(output, str) else str(output),
                status=status_str,
            )

        return ProcessorResult(
            handled=True,
            action=ProcessorAction.UPDATE_UI,
            data={
                "tool_call_id": tool_call_id,
                "success": success,
                "output": output,
            },
        )

    def _handle_tool_error(self, data: dict[str, Any]) -> ProcessorResult:
        """Handle tool error."""
        tool_call_id = data.get("tool_call_id", "")
        error = data.get("error", "Unknown error")

        # Update tool call record
        tool_call = self._state.active_calls.get(tool_call_id)
        if tool_call:
            tool_call.status = "error"
            tool_call.error = error
            self._state.completed_calls.append(tool_call)
            del self._state.active_calls[tool_call_id]

        # Update UI if app available
        if self._app and tool_call and tool_call.ui_block_id:
            self._app.update_tool_call(
                block_id=tool_call.ui_block_id,
                result=str(error),
                status="error",
            )

        return ProcessorResult(
            handled=True,
            action=ProcessorAction.UPDATE_UI,
            error=error,
            data={"tool_call_id": tool_call_id, "error": error},
        )

    def reset(self) -> None:
        """Reset tool state for new session."""
        self._state = ToolState()
        return None

    def get_state(self) -> dict[str, Any]:
        """Get current state for debugging."""
        return {
            "active_calls": {
                k: {
                    "tool_name": v.tool_name,
                    "status": v.status,
                    "order": v.order,
                }
                for k, v in self._state.active_calls.items()
            },
            "completed_count": len(self._state.completed_calls),
            "active_count": len(self._state.active_calls),
        }

    def get_active_call(self, tool_call_id: str) -> ToolCall | None:
        """Get an active tool call by ID."""
        return self._state.active_calls.get(tool_call_id)

    def get_active_calls(self) -> list[ToolCall]:
        """Get all active tool calls."""
        return list(self._state.active_calls.values())

    def has_pending_tools(self) -> bool:
        """Check if there are any pending/running tool calls."""
        return len(self._state.active_calls) > 0
