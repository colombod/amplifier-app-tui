"""Tests for Amplifier TUI application."""

import pytest

from amplifier_app_tui.app import AmplifierTUI


@pytest.mark.asyncio
async def test_app_launches():
    """Test that the app can be created and composed."""
    app = AmplifierTUI()
    async with app.run_test():
        # Verify main components exist
        assert app.query_one("#header") is not None
        assert app.query_one("#output-zone") is not None
        assert app.query_one("#input-zone") is not None
        assert app.query_one("#status-bar") is not None
        assert app.query_one("#todo-panel") is not None
        assert app.query_one("#approval-panel") is not None


@pytest.mark.asyncio
async def test_initial_state():
    """Test initial application state."""
    app = AmplifierTUI()
    async with app.run_test():
        assert app._connected is False
        assert app._busy is False
        assert app._session_id is None
        assert app._transport_mode == "stdio"
        assert app._agent_stack == ["amplifier"]


@pytest.mark.asyncio
async def test_set_connected():
    """Test connection state updates."""
    app = AmplifierTUI()
    async with app.run_test():
        app.set_connected(True, "ws")
        assert app._connected is True
        assert app._transport_mode == "ws"


@pytest.mark.asyncio
async def test_set_busy():
    """Test busy state updates."""
    app = AmplifierTUI()
    async with app.run_test():
        app.set_busy(True)
        assert app._busy is True

        # Input should be disabled
        from amplifier_app_tui.widgets import InputZone

        input_zone = app.query_one("#input-zone", InputZone)
        assert input_zone.disabled is True


@pytest.mark.asyncio
async def test_todo_update():
    """Test todo panel updates."""
    app = AmplifierTUI()
    async with app.run_test():
        todos = [
            {"content": "First task", "status": "completed", "activeForm": "Completing first task"},
            {
                "content": "Second task",
                "status": "in_progress",
                "activeForm": "Working on second task",
            },
            {"content": "Third task", "status": "pending", "activeForm": "Pending third task"},
        ]
        app.update_todos(todos)

        from amplifier_app_tui.widgets import TodoPanel

        todo_panel = app.query_one("#todo-panel", TodoPanel)
        # Should not be empty anymore
        assert not todo_panel.has_class("empty")


@pytest.mark.asyncio
async def test_output_content():
    """Test output zone content methods."""
    app = AmplifierTUI()
    async with app.run_test():
        # Test append content
        app.append_content("Hello, world!")

        # Test thinking block
        app.add_thinking("Analyzing the situation...")

        # Test tool call
        block_id = app.add_tool_call("read_file", {"path": "test.py"})
        assert block_id.startswith("tool-")

        # Test update tool call
        app.update_tool_call(block_id, "Success", "success")

        # Test error
        app.add_error("Something went wrong")

        # Test system message
        app.add_system_message("System initialized")


@pytest.mark.asyncio
async def test_approval_panel():
    """Test approval panel show/hide."""
    app = AmplifierTUI()
    async with app.run_test():
        from amplifier_app_tui.widgets import ApprovalPanel

        approval_panel = app.query_one("#approval-panel", ApprovalPanel)

        # Initially hidden
        assert not approval_panel.has_class("visible")

        # Show approval
        app.show_approval("bash", {"command": "rm -rf /tmp/test"}, "approval-123")
        assert approval_panel.has_class("visible")
        assert app._pending_approval is not None

        # Hide approval
        app.hide_approval()
        assert not approval_panel.has_class("visible")
        assert app._pending_approval is None


@pytest.mark.asyncio
async def test_keybindings():
    """Test keybinding actions."""
    app = AmplifierTUI()
    async with app.run_test() as pilot:
        # Test focus input via keybinding
        await pilot.press("ctrl+p")
        assert app.query_one("#prompt-input").has_focus


@pytest.mark.asyncio
async def test_toggle_todos_action():
    """Test toggle todos action directly."""
    app = AmplifierTUI()
    async with app.run_test():
        from amplifier_app_tui.widgets import TodoPanel

        # Add todos so panel is visible
        todos = [{"content": "Test task", "status": "pending", "activeForm": "Testing"}]
        app.update_todos(todos)

        todo_panel = app.query_one("#todo-panel", TodoPanel)
        assert not todo_panel.has_class("hidden")  # Should be visible with todos

        # Call action directly
        app.action_toggle_todos()
        assert todo_panel.has_class("hidden")  # Now hidden after toggle

        app.action_toggle_todos()
        assert not todo_panel.has_class("hidden")  # Visible again after second toggle
