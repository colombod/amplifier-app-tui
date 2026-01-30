"""Approval processor for approval requests.

Handles:
- approval_request
- approval:required

Maintains state for pending approvals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .base import EventProcessor, ProcessorAction, ProcessorResult


@dataclass
class ApprovalRequest:
    """An approval request."""

    approval_id: str
    prompt: str
    options: list[str]
    timeout: int
    default: str
    tool_name: str | None = None
    remaining_time: int = 0


@dataclass
class ApprovalState:
    """State for approval processing."""

    pending: dict[str, ApprovalRequest] = field(default_factory=dict)


class ApprovalProcessor(EventProcessor):
    """Processes approval request events.

    Maintains state for pending approvals that need user response.
    """

    # Event types this processor handles
    HANDLED_EVENTS = frozenset(
        [
            "approval_request",
            "approval:required",
            "approval_required",
        ]
    )

    def __init__(self, app: Any = None) -> None:
        super().__init__(app)
        self._state = ApprovalState()

    def handles(self, event_type: str) -> bool:
        return event_type in self.HANDLED_EVENTS

    def process(self, event_type: str, data: dict[str, Any]) -> ProcessorResult:
        """Process an approval event."""
        return self._handle_approval_request(data)

    def _handle_approval_request(self, data: dict[str, Any]) -> ProcessorResult:
        """Handle approval request."""
        approval_id = data.get("id", data.get("approval_id", ""))
        prompt = data.get("prompt", "")
        options = data.get("options", ["approve", "deny"])
        timeout = data.get("timeout", 60)
        default = data.get("default", "deny")
        tool_name = data.get("tool_name", data.get("tool"))

        # Create approval request record
        request = ApprovalRequest(
            approval_id=approval_id,
            prompt=prompt,
            options=options,
            timeout=timeout,
            default=default,
            tool_name=tool_name,
            remaining_time=timeout,
        )
        self._state.pending[approval_id] = request

        # Update UI if app available
        if self._app:
            # Extract params for display
            params = data.get("params", data.get("arguments", {}))
            self._app.add_inline_approval(
                tool_name=tool_name or "unknown",
                params=params if isinstance(params, dict) else {},
                approval_id=approval_id,
            )

        return ProcessorResult(
            handled=True,
            action=ProcessorAction.UPDATE_UI,
            data={
                "approval_id": approval_id,
                "tool_name": tool_name,
                "timeout": timeout,
            },
        )

    def resolve_approval(self, approval_id: str, choice: str) -> bool:
        """Mark an approval as resolved.

        Returns True if the approval was found and resolved.
        """
        if approval_id in self._state.pending:
            del self._state.pending[approval_id]
            return True
        return False

    def reset(self) -> None:
        """Reset approval state for new session."""
        self._state = ApprovalState()
        return None

    def get_state(self) -> dict[str, Any]:
        """Get current state for debugging."""
        return {
            "pending": {
                k: {
                    "tool_name": v.tool_name,
                    "timeout": v.timeout,
                    "remaining": v.remaining_time,
                }
                for k, v in self._state.pending.items()
            },
            "pending_count": len(self._state.pending),
        }

    @property
    def has_pending(self) -> bool:
        """Check if there are pending approvals."""
        return len(self._state.pending) > 0

    def get_pending(self, approval_id: str) -> ApprovalRequest | None:
        """Get a pending approval by ID."""
        return self._state.pending.get(approval_id)
