"""Integration tests for processors with mocked app.

Tests verify that processors correctly call app methods with expected arguments.
"""

from unittest.mock import MagicMock

import pytest

from amplifier_app_tui.processors import (
    AgentProcessor,
    ContentProcessor,
    EventRouter,
    TodoProcessor,
    ToolProcessor,
)

# =============================================================================
# Mock App Fixture
# =============================================================================


@pytest.fixture
def mock_app():
    """Create a mock app with all required methods."""
    app = MagicMock()
    # Content methods
    app.append_content = MagicMock()
    app.start_response = MagicMock()
    app.end_response = MagicMock()
    # Thinking methods
    app.add_thinking = MagicMock()
    app.end_thinking = MagicMock()
    # Tool methods
    app.add_tool_call = MagicMock(return_value="block_123")
    app.update_tool_call = MagicMock()
    # State methods
    app.set_agent_state = MagicMock()
    # Todo panel query
    app.query_one = MagicMock(return_value=None)
    # Sub-session methods
    app.start_sub_session = MagicMock()
    app.end_sub_session = MagicMock()
    # Approval methods
    app.add_inline_approval = MagicMock()
    # Error/message methods
    app.add_error = MagicMock()
    app.add_system_message = MagicMock()
    return app


# =============================================================================
# ContentProcessor with App Integration
# =============================================================================


class TestContentProcessorAppIntegration:
    """Test ContentProcessor calls correct app methods."""

    def test_content_delta_calls_append(self, mock_app):
        """Content delta should call app.append_content."""
        processor = ContentProcessor(mock_app)

        # Start a block first
        processor.process("content_start", {"block_type": "text", "index": 0})

        # Send delta
        processor.process("content_delta", {"index": 0, "delta": "Hello world"})

        mock_app.append_content.assert_called_with("Hello world")

    def test_thinking_calls_add_thinking(self, mock_app):
        """Thinking delta should call app.add_thinking."""
        processor = ContentProcessor(mock_app)

        processor.process("thinking_delta", {"delta": "Let me think..."})

        mock_app.add_thinking.assert_called_with("Let me think...")

    def test_thinking_final_calls_end_thinking(self, mock_app):
        """Thinking final should call app.end_thinking."""
        processor = ContentProcessor(mock_app)

        # First send a thinking delta to create the block
        processor.process("thinking_delta", {"delta": "Thinking..."})

        # Then finalize
        processor.process("thinking_final", {"content": "Done thinking"})

        # end_thinking is called on final
        mock_app.end_thinking.assert_called_once()


# =============================================================================
# ToolProcessor with App Integration
# =============================================================================


class TestToolProcessorAppIntegration:
    """Test ToolProcessor calls correct app methods."""

    def test_tool_call_adds_block(self, mock_app):
        """Tool call should add a tool block via app."""
        processor = ToolProcessor(mock_app)

        processor.process(
            "tool_call",
            {
                "tool_name": "bash",
                "tool_call_id": "call_1",
                "arguments": {"command": "ls"},
                "status": "running",
            },
        )

        mock_app.add_tool_call.assert_called_once()
        call_args = mock_app.add_tool_call.call_args
        assert call_args[1]["tool_name"] == "bash"
        assert call_args[1]["status"] == "running"

    def test_tool_result_updates_block(self, mock_app):
        """Tool result should update the tool block."""
        processor = ToolProcessor(mock_app)

        # Start tool call
        processor.process(
            "tool_call",
            {
                "tool_name": "bash",
                "tool_call_id": "call_1",
                "arguments": {},
                "status": "running",
            },
        )

        # Complete it
        processor.process(
            "tool_result",
            {
                "tool_call_id": "call_1",
                "output": "file1.txt\nfile2.txt",
                "success": True,
            },
        )

        mock_app.update_tool_call.assert_called_once()
        call_args = mock_app.update_tool_call.call_args
        assert "file1.txt" in call_args[1]["result"]
        assert call_args[1]["status"] == "success"


# =============================================================================
# TodoProcessor with App Integration
# =============================================================================


class TestTodoProcessorAppIntegration:
    """Test TodoProcessor updates todo panel."""

    def test_todo_update_queries_panel(self, mock_app):
        """Todo update should try to update the panel."""
        processor = TodoProcessor(mock_app)

        processor.process(
            "todo:update",
            {
                "action": "update",
                "todos": [
                    {"content": "Task 1", "status": "pending", "activeForm": "Doing task 1"},
                    {"content": "Task 2", "status": "in_progress", "activeForm": "Doing task 2"},
                ],
            },
        )

        # Should query for the todo panel
        mock_app.query_one.assert_called()


# =============================================================================
# AgentProcessor with App Integration
# =============================================================================


class TestAgentProcessorAppIntegration:
    """Test AgentProcessor handles sub-sessions correctly."""

    def test_session_fork_starts_sub_session(self, mock_app):
        """Session fork should call app.start_sub_session."""
        processor = AgentProcessor(mock_app)

        processor.process(
            "session_fork",
            {
                "child_id": "child_123",
                "parent_tool_call_id": "tool_456",
                "agent": "amplifier:amplifier-expert",
            },
        )

        mock_app.start_sub_session.assert_called_once_with(
            parent_tool_call_id="tool_456",
            session_id="child_123",
            agent_name="amplifier:amplifier-expert",
        )


# =============================================================================
# EventRouter Integration
# =============================================================================


class TestEventRouterIntegration:
    """Test EventRouter dispatches to correct processors."""

    def test_router_dispatches_content_to_content_processor(self, mock_app):
        """Router should dispatch content events to ContentProcessor."""
        router = EventRouter(mock_app)

        # Start and delta
        router.route("content_start", {"block_type": "text", "index": 0})
        router.route("content_delta", {"index": 0, "delta": "Test content"})

        mock_app.append_content.assert_called_with("Test content")

    def test_router_dispatches_todo_to_todo_processor(self, mock_app):
        """Router should dispatch todo events to TodoProcessor."""
        router = EventRouter(mock_app)

        router.route(
            "todo:update",
            {
                "todos": [{"content": "Test", "status": "pending", "activeForm": "Testing"}],
            },
        )

        # Verify state was updated
        assert len(router.todo.items) == 1
        assert router.todo.items[0].content == "Test"

    def test_router_tracks_sub_sessions(self, mock_app):
        """Router should track sub-session relationships."""
        router = EventRouter(mock_app)

        router.route(
            "session_fork",
            {
                "child_id": "child_abc",
                "parent_tool_call_id": "parent_xyz",
                "agent": "test-agent",
            },
        )

        # Verify mapping
        assert router.agent.get_parent_tool_call_id("child_abc") == "parent_xyz"
        assert router.has_active_sub_sessions()


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================


class TestEdgeCases:
    """Test edge cases and malformed data handling."""

    def test_content_delta_without_start(self, mock_app):
        """Delta without start should return not-handled (invalid state)."""
        processor = ContentProcessor(mock_app)

        # Send delta without starting a block (server index mismatch)
        result = processor.process("content_delta", {"index": 5, "delta": "Orphan"})

        # Should NOT handle - no block exists for this index
        # This is correct behavior: processor rejects invalid state
        assert not result.handled

    def test_tool_result_without_call(self, mock_app):
        """Tool result without matching call should handle gracefully."""
        processor = ToolProcessor(mock_app)

        result = processor.process(
            "tool_result",
            {
                "tool_call_id": "nonexistent",
                "output": "result",
                "success": True,
            },
        )

        # Should handle but not crash
        assert result.handled

    def test_empty_todo_list(self, mock_app):
        """Empty todo list should be handled."""
        processor = TodoProcessor(mock_app)

        result = processor.process("todo:update", {"todos": []})

        assert result.handled
        assert len(processor.items) == 0

    def test_missing_event_fields(self, mock_app):
        """Events with missing fields should use defaults."""
        processor = ToolProcessor(mock_app)

        # Minimal tool call
        result = processor.process(
            "tool_call",
            {
                "tool_call_id": "minimal",
            },
        )

        assert result.handled
        call = processor.get_active_call("minimal")
        assert call.tool_name == "unknown"

    def test_router_unknown_event(self, mock_app):
        """Unknown events should return not handled."""
        router = EventRouter(mock_app)

        result = router.route("completely_unknown_event", {"data": "test"})

        assert not result.handled


# =============================================================================
# State Consistency Tests
# =============================================================================


class TestStateConsistency:
    """Test state remains consistent across operations."""

    def test_tool_state_after_multiple_operations(self, mock_app):
        """Tool state should be consistent after many operations."""
        processor = ToolProcessor(mock_app)

        # Start 3 tools
        for i in range(3):
            processor.process(
                "tool_call",
                {
                    "tool_name": f"tool_{i}",
                    "tool_call_id": f"call_{i}",
                    "arguments": {},
                    "status": "running",
                },
            )

        assert len(processor.get_active_calls()) == 3

        # Complete 2
        processor.process(
            "tool_result", {"tool_call_id": "call_0", "output": "done", "success": True}
        )
        processor.process(
            "tool_result", {"tool_call_id": "call_2", "output": "done", "success": True}
        )

        assert len(processor.get_active_calls()) == 1
        assert processor.get_active_call("call_1") is not None

    def test_todo_state_replacement(self, mock_app):
        """Todo updates should replace state, not append."""
        processor = TodoProcessor(mock_app)

        # First update
        processor.process(
            "todo:update",
            {
                "todos": [{"content": "A", "status": "pending", "activeForm": ""}],
            },
        )
        assert len(processor.items) == 1

        # Second update replaces
        processor.process(
            "todo:update",
            {
                "todos": [
                    {"content": "B", "status": "pending", "activeForm": ""},
                    {"content": "C", "status": "pending", "activeForm": ""},
                ],
            },
        )
        assert len(processor.items) == 2
        assert processor.items[0].content == "B"

    def test_router_reset_clears_all_state(self, mock_app):
        """Router reset should clear all processor states."""
        router = EventRouter(mock_app)

        # Add state to multiple processors
        router.route("content_start", {"block_type": "text", "index": 0})
        router.route(
            "tool_call",
            {"tool_name": "test", "tool_call_id": "t1", "arguments": {}, "status": "running"},
        )
        router.route(
            "todo:update", {"todos": [{"content": "X", "status": "pending", "activeForm": ""}]}
        )

        # Verify state exists
        assert len(router.content.blocks) > 0
        assert router.tool.has_pending_tools()
        assert len(router.todo.items) > 0

        # Reset
        router.reset()

        # Verify all cleared
        assert len(router.content.blocks) == 0
        assert not router.tool.has_pending_tools()
        assert len(router.todo.items) == 0
