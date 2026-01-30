"""Event processors for Amplifier TUI.

Processor-based architecture for handling runtime events.
Each processor owns its domain and state, making the system
more testable and maintainable.

Processors:
- ContentProcessor: Handles streaming content (text, thinking)
- ToolProcessor: Handles tool calls and results (stateful)
- TodoProcessor: Handles todo list updates (stateful)
- AgentProcessor: Handles sub-sessions and agent delegation (stateful)
- ApprovalProcessor: Handles approval requests (stateful)
- SessionProcessor: Handles session lifecycle events
"""

from .base import EventProcessor, ProcessorResult
from .content import ContentProcessor
from .tool import ToolProcessor
from .todo import TodoProcessor
from .agent import AgentProcessor
from .approval import ApprovalProcessor
from .session import SessionProcessor
from .router import EventRouter

__all__ = [
    "EventProcessor",
    "ProcessorResult",
    "ContentProcessor",
    "ToolProcessor",
    "TodoProcessor",
    "AgentProcessor",
    "ApprovalProcessor",
    "SessionProcessor",
    "EventRouter",
]
