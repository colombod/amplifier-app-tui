"""Unit tests for event processors.

Tests use realistic event data based on amplifier-core event structures
as documented in amplifier-web's type definitions.
"""

import pytest

from amplifier_app_tui.processors import (
    AgentProcessor,
    ApprovalProcessor,
    ContentProcessor,
    EventRouter,
    SessionProcessor,
    TodoProcessor,
    ToolProcessor,
)

# =============================================================================
# Realistic Event Data Fixtures (based on amplifier-web types)
# =============================================================================


@pytest.fixture
def content_start_event():
    """Content block start event."""
    return {
        "type": "content_start",
        "block_type": "text",
        "index": 0,
    }


@pytest.fixture
def content_delta_event():
    """Content delta (streaming chunk) event."""
    return {
        "type": "content_delta",
        "index": 0,
        "delta": "Hello, I can help you with that.",
    }


@pytest.fixture
def content_end_event():
    """Content block end event."""
    return {
        "type": "content_end",
        "index": 0,
        "content": "Hello, I can help you with that. Let me check.",
    }


@pytest.fixture
def thinking_delta_event():
    """Thinking delta event."""
    return {
        "type": "thinking_delta",
        "delta": "I should analyze this request...",
    }


@pytest.fixture
def thinking_final_event():
    """Thinking final event."""
    return {
        "type": "thinking_final",
        "content": "I should analyze this request and provide a helpful response.",
    }


@pytest.fixture
def tool_call_event():
    """Tool call event - realistic task tool invocation."""
    return {
        "type": "tool_call",
        "tool_name": "task",
        "tool_call_id": "toolu_01ABC123",
        "arguments": {
            "agent": "amplifier:amplifier-expert",
            "instruction": "Explain the role of the amplifier-core repository",
            "inherit_context": "none",
        },
        "status": "running",
    }


@pytest.fixture
def tool_call_bash_event():
    """Tool call event - bash command."""
    return {
        "type": "tool_call",
        "tool_name": "bash",
        "tool_call_id": "toolu_02DEF456",
        "arguments": {
            "command": "ls -la /home/user/project",
        },
        "status": "running",
    }


@pytest.fixture
def tool_result_event():
    """Tool result event - successful."""
    return {
        "type": "tool_result",
        "tool_call_id": "toolu_02DEF456",
        "tool_name": "bash",
        "output": "total 24\ndrwxr-xr-x 5 user user 4096 Jan 30 10:00 .\n",
        "success": True,
    }


@pytest.fixture
def tool_result_error_event():
    """Tool result event - with error."""
    return {
        "type": "tool_result",
        "tool_call_id": "toolu_03GHI789",
        "tool_name": "bash",
        "output": "",
        "success": False,
        "error": "Command failed with exit code 1",
    }


@pytest.fixture
def todo_update_event():
    """Todo list update event."""
    return {
        "type": "todo:update",
        "action": "update",
        "todos": [
            {
                "content": "Research amplifier-web event handling",
                "status": "completed",
                "activeForm": "Researched amplifier-web",
            },
            {
                "content": "Define processor interface",
                "status": "in_progress",
                "activeForm": "Defining processor interface",
            },
            {
                "content": "Create ContentProcessor",
                "status": "pending",
                "activeForm": "Creating ContentProcessor",
            },
        ],
    }


@pytest.fixture
def session_fork_event():
    """Session fork event - agent delegation."""
    return {
        "type": "session_fork",
        "parent_id": "session_main_123",
        "child_id": "session_child_456",
        "parent_tool_call_id": "toolu_01ABC123",
        "agent": "amplifier:amplifier-expert",
    }


@pytest.fixture
def approval_request_event():
    """Approval request event."""
    return {
        "type": "approval_request",
        "id": "approval_001",
        "prompt": "Allow bash command: rm -rf /tmp/test?",
        "options": ["approve", "deny"],
        "timeout": 60,
        "default": "deny",
        "tool_name": "bash",
        "params": {"command": "rm -rf /tmp/test"},
    }


@pytest.fixture
def prompt_complete_event():
    """Prompt complete event."""
    return {
        "type": "prompt_complete",
        "turn": 5,
    }


@pytest.fixture
def error_event():
    """Error event."""
    return {
        "type": "error",
        "error": "API rate limit exceeded. Please try again in 60 seconds.",
    }


@pytest.fixture
def display_message_event():
    """Display message event."""
    return {
        "type": "display_message",
        "level": "warning",
        "message": "Context window approaching limit (85% used)",
        "source": "context-manager",
    }


# =============================================================================
# ContentProcessor Tests
# =============================================================================


class TestContentProcessor:
    """Tests for ContentProcessor."""

    def test_handles_content_events(self):
        """Should handle content_* and thinking_* events."""
        processor = ContentProcessor()

        assert processor.handles("content_start")
        assert processor.handles("content_delta")
        assert processor.handles("content_end")
        assert processor.handles("content_block:start")
        assert processor.handles("content_block:delta")
        assert processor.handles("content_block:end")
        assert processor.handles("thinking_delta")
        assert processor.handles("thinking_final")

        # Should not handle other events
        assert not processor.handles("tool_call")
        assert not processor.handles("todo:update")

    def test_content_streaming_flow(
        self, content_start_event, content_delta_event, content_end_event
    ):
        """Should track content blocks through streaming lifecycle."""
        processor = ContentProcessor()

        # Start block
        result = processor.process("content_start", content_start_event)
        assert result.handled
        assert processor.is_streaming
        assert len(processor.blocks) == 1
        assert processor.blocks[0].block_type == "text"
        assert processor.blocks[0].is_streaming

        # Receive delta
        result = processor.process("content_delta", content_delta_event)
        assert result.handled
        assert processor.blocks[0].content == "Hello, I can help you with that."

        # End block
        result = processor.process("content_end", content_end_event)
        assert result.handled
        assert not processor.blocks[0].is_streaming
        assert "Let me check" in processor.blocks[0].content

    def test_thinking_flow(self, thinking_delta_event, thinking_final_event):
        """Should track thinking blocks."""
        processor = ContentProcessor()

        # Receive thinking delta (auto-creates block)
        result = processor.process("thinking_delta", thinking_delta_event)
        assert result.handled
        assert len(processor.blocks) == 1
        assert processor.blocks[0].block_type == "thinking"

        # Finalize thinking
        result = processor.process("thinking_final", thinking_final_event)
        assert result.handled
        assert not processor.blocks[0].is_streaming

    def test_reset_clears_state(self, content_start_event):
        """Should clear all state on reset."""
        processor = ContentProcessor()
        processor.process("content_start", content_start_event)

        assert len(processor.blocks) > 0

        processor.reset()

        assert len(processor.blocks) == 0
        assert not processor.is_streaming

    def test_block_index_mapping(self):
        """Should map server indices to local indices correctly."""
        processor = ContentProcessor()

        # Start multiple blocks with non-sequential server indices
        processor.process("content_start", {"block_type": "text", "index": 0})
        processor.process("content_start", {"block_type": "thinking", "index": 2})
        processor.process("content_start", {"block_type": "text", "index": 5})

        assert len(processor.blocks) == 3

        # Delta to index 2 should go to second block (local index 1)
        processor.process("content_delta", {"index": 2, "delta": "thinking..."})
        assert processor.blocks[1].content == "thinking..."


# =============================================================================
# ToolProcessor Tests
# =============================================================================


class TestToolProcessor:
    """Tests for ToolProcessor."""

    def test_handles_tool_events(self):
        """Should handle tool_* events."""
        processor = ToolProcessor()

        assert processor.handles("tool_call")
        assert processor.handles("tool_result")
        assert processor.handles("tool_error")
        assert processor.handles("tool:pre")
        assert processor.handles("tool:post")

        # Should not handle other events
        assert not processor.handles("content_start")
        assert not processor.handles("session_fork")

    def test_tool_call_tracking(self, tool_call_bash_event):
        """Should track active tool calls."""
        processor = ToolProcessor()

        result = processor.process("tool_call", tool_call_bash_event)

        assert result.handled
        assert processor.has_pending_tools()
        assert len(processor.get_active_calls()) == 1

        call = processor.get_active_call("toolu_02DEF456")
        assert call is not None
        assert call.tool_name == "bash"
        assert call.status == "running"

    def test_tool_result_completes_call(self, tool_call_bash_event, tool_result_event):
        """Should complete tool call on result."""
        processor = ToolProcessor()

        # Start call
        processor.process("tool_call", tool_call_bash_event)
        assert processor.has_pending_tools()

        # Receive result
        result = processor.process("tool_result", tool_result_event)

        assert result.handled
        assert not processor.has_pending_tools()
        assert processor.get_active_call("toolu_02DEF456") is None

    def test_tool_error_handling(self, tool_call_bash_event):
        """Should handle tool errors."""
        processor = ToolProcessor()

        processor.process("tool_call", {**tool_call_bash_event, "tool_call_id": "toolu_03GHI789"})

        result = processor.process(
            "tool_error",
            {
                "tool_call_id": "toolu_03GHI789",
                "error": "Permission denied",
            },
        )

        assert result.handled
        assert result.error == "Permission denied"
        assert not processor.has_pending_tools()

    def test_multiple_concurrent_tools(self):
        """Should track multiple concurrent tool calls."""
        processor = ToolProcessor()

        processor.process(
            "tool_call",
            {
                "tool_name": "bash",
                "tool_call_id": "call_1",
                "arguments": {},
                "status": "running",
            },
        )
        processor.process(
            "tool_call",
            {
                "tool_name": "read_file",
                "tool_call_id": "call_2",
                "arguments": {},
                "status": "running",
            },
        )
        processor.process(
            "tool_call",
            {
                "tool_name": "grep",
                "tool_call_id": "call_3",
                "arguments": {},
                "status": "running",
            },
        )

        assert len(processor.get_active_calls()) == 3

        # Complete one
        processor.process(
            "tool_result",
            {
                "tool_call_id": "call_2",
                "output": "file contents",
                "success": True,
            },
        )

        assert len(processor.get_active_calls()) == 2


# =============================================================================
# TodoProcessor Tests
# =============================================================================


class TestTodoProcessor:
    """Tests for TodoProcessor."""

    def test_handles_todo_events(self):
        """Should handle todo events."""
        processor = TodoProcessor()

        assert processor.handles("todo:update")
        assert processor.handles("todo_update")

        # Should not handle other events
        assert not processor.handles("tool_call")

    def test_todo_update(self, todo_update_event):
        """Should update todo list from event."""
        processor = TodoProcessor()

        result = processor.process("todo:update", todo_update_event)

        assert result.handled
        assert len(processor.items) == 3

        # Check item statuses
        state = processor.get_state()
        assert state["completed"] == 1
        assert state["in_progress"] == 1
        assert state["pending"] == 1

    def test_in_progress_item(self, todo_update_event):
        """Should return the in-progress item."""
        processor = TodoProcessor()
        processor.process("todo:update", todo_update_event)

        in_progress = processor.in_progress_item
        assert in_progress is not None
        assert in_progress.content == "Define processor interface"
        assert in_progress.active_form == "Defining processor interface"

    def test_reset_clears_todos(self, todo_update_event):
        """Should clear todos on reset."""
        processor = TodoProcessor()
        processor.process("todo:update", todo_update_event)

        processor.reset()

        assert len(processor.items) == 0


# =============================================================================
# AgentProcessor Tests
# =============================================================================


class TestAgentProcessor:
    """Tests for AgentProcessor."""

    def test_handles_session_events(self):
        """Should handle session fork/start/end events."""
        processor = AgentProcessor()

        assert processor.handles("session_fork")
        assert processor.handles("session_start")
        assert processor.handles("session_end")

        # Should not handle other events
        assert not processor.handles("tool_call")

    def test_session_fork_creates_sub_session(self, session_fork_event):
        """Should create sub-session record on fork."""
        processor = AgentProcessor()

        result = processor.process("session_fork", session_fork_event)

        assert result.handled
        assert processor.has_active_sub_sessions

        sub = processor.get_sub_session("toolu_01ABC123")
        assert sub is not None
        assert sub.session_id == "session_child_456"
        assert sub.agent_name == "amplifier:amplifier-expert"

    def test_child_to_parent_mapping(self, session_fork_event):
        """Should map child session ID to parent tool call ID."""
        processor = AgentProcessor()
        processor.process("session_fork", session_fork_event)

        parent_id = processor.get_parent_tool_call_id("session_child_456")
        assert parent_id == "toolu_01ABC123"

    def test_is_sub_session_event(self, session_fork_event):
        """Should detect sub-session events."""
        processor = AgentProcessor()
        processor.process("session_fork", session_fork_event)

        # Event with child_session_id
        assert processor.is_sub_session_event({"child_session_id": "session_child_456"})

        # Event with parent_tool_call_id
        assert processor.is_sub_session_event({"parent_tool_call_id": "toolu_01ABC123"})

        # Event with nesting_depth
        assert processor.is_sub_session_event({"nesting_depth": 1})

        # Regular event
        assert not processor.is_sub_session_event({})


# =============================================================================
# ApprovalProcessor Tests
# =============================================================================


class TestApprovalProcessor:
    """Tests for ApprovalProcessor."""

    def test_handles_approval_events(self):
        """Should handle approval events."""
        processor = ApprovalProcessor()

        assert processor.handles("approval_request")
        assert processor.handles("approval:required")

        # Should not handle other events
        assert not processor.handles("tool_call")

    def test_approval_request_tracking(self, approval_request_event):
        """Should track pending approvals."""
        processor = ApprovalProcessor()

        result = processor.process("approval_request", approval_request_event)

        assert result.handled
        assert processor.has_pending

        pending = processor.get_pending("approval_001")
        assert pending is not None
        assert pending.tool_name == "bash"
        assert pending.timeout == 60

    def test_resolve_approval(self, approval_request_event):
        """Should resolve and remove pending approval."""
        processor = ApprovalProcessor()
        processor.process("approval_request", approval_request_event)

        resolved = processor.resolve_approval("approval_001", "approve")

        assert resolved
        assert not processor.has_pending


# =============================================================================
# SessionProcessor Tests
# =============================================================================


class TestSessionProcessor:
    """Tests for SessionProcessor."""

    def test_handles_session_events(self):
        """Should handle session lifecycle events."""
        processor = SessionProcessor()

        assert processor.handles("prompt_complete")
        assert processor.handles("error")
        assert processor.handles("display_message")

        # Should not handle other events
        assert not processor.handles("tool_call")

    def test_prompt_complete_updates_turn(self, prompt_complete_event):
        """Should update turn count on prompt complete."""
        processor = SessionProcessor()

        result = processor.process("prompt_complete", prompt_complete_event)

        assert result.handled
        assert processor.turn_count == 5
        assert processor.status == "idle"

    def test_error_handling(self, error_event):
        """Should track errors."""
        processor = SessionProcessor()

        result = processor.process("error", error_event)

        assert result.handled
        assert result.error is not None
        assert "rate limit" in result.error
        assert processor.status == "error"


# =============================================================================
# EventRouter Tests
# =============================================================================


class TestEventRouter:
    """Tests for EventRouter."""

    def test_routes_to_correct_processor(self):
        """Should route events to appropriate processors."""
        router = EventRouter()

        # Content event
        result = router.route("content_start", {"block_type": "text", "index": 0})
        assert result.handled

        # Tool event
        result = router.route(
            "tool_call",
            {
                "tool_name": "bash",
                "tool_call_id": "test",
                "arguments": {},
                "status": "running",
            },
        )
        assert result.handled

        # Todo event
        result = router.route("todo:update", {"todos": [], "action": "update"})
        assert result.handled

    def test_unknown_event_not_handled(self):
        """Should return not-handled for unknown events."""
        router = EventRouter()

        result = router.route("unknown_event_type", {})
        assert not result.handled

    def test_reset_resets_all_processors(self):
        """Should reset all processor states."""
        router = EventRouter()

        # Add some state
        router.route("content_start", {"block_type": "text", "index": 0})
        router.route(
            "tool_call",
            {
                "tool_name": "bash",
                "tool_call_id": "test",
                "arguments": {},
                "status": "running",
            },
        )

        router.reset()

        assert len(router.content.blocks) == 0
        assert not router.tool.has_pending_tools()

    def test_convenience_state_queries(self):
        """Should provide convenience state query methods."""
        router = EventRouter()

        # Initially no activity
        assert not router.is_streaming()
        assert not router.has_pending_tools()
        assert not router.has_pending_approvals()
        assert not router.has_active_sub_sessions()

        # Start some activity
        router.route("content_start", {"block_type": "text", "index": 0})
        assert router.is_streaming()

        router.route(
            "tool_call",
            {
                "tool_name": "bash",
                "tool_call_id": "test",
                "arguments": {},
                "status": "running",
            },
        )
        assert router.has_pending_tools()

    def test_get_all_state(self):
        """Should aggregate state from all processors."""
        router = EventRouter()

        state = router.get_all_state()

        assert "content" in state
        assert "tool" in state
        assert "todo" in state
        assert "agent" in state
        assert "approval" in state
        assert "session" in state

    def test_sub_session_event_routing(self, session_fork_event):
        """Should enrich sub-session events with parent context."""
        router = EventRouter()

        # Fork a sub-session
        router.route("session_fork", session_fork_event)

        # Route an event with child_session_id (should get parent_tool_call_id added)
        event_data = {"child_session_id": "session_child_456", "delta": "test"}

        # The router should add parent_tool_call_id
        router.route("content_delta", event_data)

        # Check that the agent processor can map the child
        assert router.agent.get_parent_tool_call_id("session_child_456") == "toolu_01ABC123"
