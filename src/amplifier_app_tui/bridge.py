"""Runtime Bridge - Connects TUI to Amplifier Runtime.

Maps runtime events to TUI methods using the transport-aware SDK client.
Supports both subprocess (stdio) and attach (HTTP/WebSocket) modes.

Architecture:
    TUI <-> RuntimeBridge <-> TransportAmplifierClient <-> Runtime
                                      |
                           StdioTransport | HTTPTransport | WebSocketTransport
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

# Import types from runtime - single source of truth
from amplifier_app_runtime.sdk import (
    create_attach_client,
    create_subprocess_client,
)
from amplifier_app_runtime.sdk.types import MessagePart

if TYPE_CHECKING:
    from .app import AmplifierTUI

logger = logging.getLogger(__name__)


class ConnectionMode(str, Enum):
    """How we connect to the runtime."""

    SUBPROCESS = "subprocess"  # Launch runtime as subprocess (stdio)
    HTTP = "http"  # Attach to HTTP server
    WEBSOCKET = "websocket"  # Attach to WebSocket server


@dataclass
class BridgeConfig:
    """Configuration for the runtime bridge."""

    mode: ConnectionMode = ConnectionMode.SUBPROCESS

    # Subprocess mode options
    runtime_command: list[str] = field(default_factory=lambda: ["amplifier-runtime"])
    working_directory: str | None = None
    env: dict[str, str] | None = None

    # Attach mode options
    server_url: str = "http://localhost:4096"
    timeout: float = 30.0

    # Session options
    bundle: str = "foundation"  # Default bundle to use


class RuntimeBridge:
    """Bridges TUI to Amplifier Runtime via SDK client.

    Responsibilities:
    - Manage connection lifecycle (connect/disconnect)
    - Route runtime events to appropriate TUI methods
    - Handle session management
    - Process approval requests

    Usage:
        bridge = RuntimeBridge(app, BridgeConfig(mode=ConnectionMode.SUBPROCESS))
        await bridge.connect()

        # Send prompt
        await bridge.send_prompt("Hello, world!")

        # Events are automatically routed to app methods
    """

    def __init__(self, app: AmplifierTUI, config: BridgeConfig | None = None):
        self.app = app
        self.config = config or BridgeConfig()
        self._client: Any = None  # TransportAmplifierClient
        self._session_id: str | None = None
        self._event_task: asyncio.Task[None] | None = None
        self._prompt_task: asyncio.Task[None] | None = None
        self._connected = False
        # Tool call tracking
        self._current_tool_id: str | None = None
        self._tool_call_mapping: dict[str, str] = {}

    @property
    def is_connected(self) -> bool:
        """Check if connected to runtime."""
        return self._connected and self._client is not None

    def _safe_app_call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """Safely call an app method, handling cases where app isn't fully initialized."""
        try:
            if hasattr(self.app, method):
                return getattr(self.app, method)(*args, **kwargs)
        except Exception as e:
            logger.debug(f"Could not call app.{method}: {e}")

    @property
    def session_id(self) -> str | None:
        """Current session ID."""
        return self._session_id

    async def connect(self) -> None:
        """Connect to the runtime and create a session."""
        if self._connected:
            return

        try:
            # Create client based on mode
            if self.config.mode == ConnectionMode.SUBPROCESS:
                self._client = create_subprocess_client(
                    command=self.config.runtime_command,
                    working_directory=self.config.working_directory,
                    env=self.config.env,
                )
            elif self.config.mode == ConnectionMode.HTTP:
                self._client = create_attach_client(
                    base_url=self.config.server_url,
                    timeout=self.config.timeout,
                )
            elif self.config.mode == ConnectionMode.WEBSOCKET:
                # For WebSocket, we use HTTP client for session management
                # and WebSocket for streaming (handled separately)
                self._client = create_attach_client(
                    base_url=self.config.server_url,
                    timeout=self.config.timeout,
                )

            # Connect transport
            await self._client.connect()
            self._connected = True

            # Update TUI state
            self._safe_app_call("set_connected", True, self.config.mode.value)

            # Create a session with the configured bundle
            session_info = await self._client.session.create(bundle=self.config.bundle)
            self._session_id = session_info.session_id
            self._safe_app_call("set_session", self._session_id)
            # Set bundle name for status bar display
            self._safe_app_call("set_bundle_name", self.config.bundle)

            # Start event listener for uncorrelated events (approvals, etc.)
            self._event_task = asyncio.create_task(self._event_loop())

            logger.info(
                f"Connected to runtime (mode={self.config.mode.value}, session={self._session_id})"
            )
            if self._session_id:
                self._safe_app_call(
                    "add_system_message",
                    f"Connected to runtime (session: {self._session_id[:8]}...)",
                )

        except ImportError as e:
            error_msg = "amplifier-app-runtime SDK not installed. Install with: pip install amplifier-app-runtime"
            logger.error(error_msg)
            self._safe_app_call("add_error", error_msg)
            raise RuntimeError(error_msg) from e
        except Exception as e:
            error_msg = f"Failed to connect: {e}"
            logger.error(error_msg)
            self._safe_app_call("add_error", error_msg)
            self._safe_app_call("set_connected", False)
            raise

    async def disconnect(self) -> None:
        """Disconnect from the runtime."""
        if not self._connected:
            return

        # Cancel event loop
        if self._event_task:
            self._event_task.cancel()
            try:
                await self._event_task
            except asyncio.CancelledError:
                pass
            self._event_task = None

        # Cancel prompt task if running
        if self._prompt_task:
            self._prompt_task.cancel()
            try:
                await self._prompt_task
            except asyncio.CancelledError:
                pass
            self._prompt_task = None

        # Disconnect client
        if self._client:
            await self._client.disconnect()
            self._client = None

        self._connected = False
        self._session_id = None
        self._safe_app_call("set_connected", False)
        self._safe_app_call("set_session", None)
        self._safe_app_call("add_system_message", "Disconnected from runtime")
        logger.info("Disconnected from runtime")

    async def send_prompt(self, prompt: str) -> None:
        """Send a prompt to the runtime and stream response.

        This method:
        1. Shows the user's message in the TUI
        2. Starts streaming response from runtime
        3. Routes events to appropriate TUI methods
        """
        if not self.is_connected or not self._session_id:
            self.app.add_error("Not connected to runtime")
            return

        # Show user message
        self.app.add_user_message(prompt)

        # Set busy state
        self.app.set_busy(True)

        # Start response in background task
        self._prompt_task = asyncio.create_task(self._process_prompt(prompt))

    async def _process_prompt(self, prompt: str) -> None:
        """Process prompt and route events to TUI."""
        try:
            # Create message parts
            parts = [MessagePart(type="text", text=prompt)]

            # Start response in TUI
            self.app.start_response()

            current_tool_id: str | None = None

            # Stream events from runtime
            async for event in self._client.session.prompt(self._session_id, parts):
                await self._handle_event(event, current_tool_id)

                # Track current tool for updates
                if event.type == "tool_call_start":
                    current_tool_id = event.data.get("tool_call_id")
                elif event.type in ("tool_call_complete", "tool_call_error"):
                    current_tool_id = None

        except asyncio.CancelledError:
            self.app.add_system_message("Request cancelled")
            raise
        except Exception as e:
            logger.error(f"Error processing prompt: {e}")
            self.app.add_error(f"Error: {e}")
        finally:
            self.app.end_response()
            self.app.set_busy(False)

    async def _handle_event(self, event: Any, current_tool_id: str | None = None) -> None:
        """Handle a single event from the runtime.

        Event type mapping:
            content_delta     -> app.append_content()
            thinking_start    -> app.add_thinking()
            thinking_delta    -> app.add_thinking() (append)
            thinking_end      -> app.end_thinking()
            tool_call_start   -> app.add_tool_call()
            tool_call_complete -> app.update_tool_call()
            tool_call_error   -> app.update_tool_call()
            approval_requested -> app.show_approval() or app.add_inline_approval()
            todo_update       -> app.update_todos()
            error             -> app.add_error()
            done              -> (handled by caller)
        """
        event_type = event.type
        data = event.data or {}

        logger.debug(f"Event: {event_type} - {data}")

        # Content events (runtime uses dot notation: content.start, content.delta, content.end)
        if event_type in ("content_delta", "content.delta"):
            # Streaming text content
            content = data.get("content", data.get("delta", ""))
            if content:
                self.app.append_content(content)

        elif event_type == "content.start":
            # Content block starting - start a response block
            # Check if this is for a specific agent
            agent_name = data.get("agent_name")
            self._safe_app_call("start_response", agent_name)

        elif event_type == "content.end":
            # Content block complete - may contain full content if not streaming
            content = data.get("content", "")
            if content:
                self.app.append_content(content)

        elif event_type in ("thinking_start", "thinking.start", "thinking:start"):
            # Agent started thinking
            self.app.set_agent_state("thinking")

        elif event_type in ("thinking_delta", "thinking.delta", "thinking:delta"):
            # Thinking content (usually collapsed)
            content = data.get("content", data.get("delta", ""))
            if content:
                self.app.add_thinking(content)

        elif event_type in ("thinking_end", "thinking.end", "thinking:end", "thinking:final"):
            # Thinking complete
            content = data.get("content", "")
            if content:
                self.app.add_thinking(content)
            self.app.end_thinking()

        elif event_type in ("tool_call_start", "tool.start", "tool_use.start", "tool.call"):
            # Tool call started
            tool_name = data.get("tool", data.get("name", "unknown"))
            params = data.get("params", data.get("arguments", data.get("input", {})))
            tool_id = self.app.add_tool_call(tool_name, params, status="pending")
            self.app.set_agent_state("executing")
            # Store tool_id for later updates
            data["_tui_tool_id"] = tool_id

        elif event_type in (
            "tool_call_complete",
            "tool.complete",
            "tool_use.complete",
            "tool_result",
            "tool.result",
            "tool.completed",
        ):
            # Tool call completed successfully
            tool_id = data.get("_tui_tool_id") or current_tool_id
            result = data.get("result", data.get("output", data.get("content", "")))
            if tool_id:
                self.app.update_tool_call(tool_id, str(result), "success")

        elif event_type in ("tool_call_error", "tool.error", "tool_use.error"):
            # Tool call failed
            tool_id = data.get("_tui_tool_id") or current_tool_id
            error = data.get("error", "Unknown error")
            if tool_id:
                self.app.update_tool_call(tool_id, str(error), "error")

        elif event_type == "approval_requested":
            # Approval needed for tool execution
            tool_name = data.get("tool", "unknown")
            params = data.get("params", {})
            approval_id = data.get("approval_id", "")
            risk_level = data.get("risk_level", "high")

            if risk_level == "low":
                # Inline approval for low-risk tools
                self.app.add_inline_approval(tool_name, params, approval_id)
            else:
                # Modal approval for high-risk tools
                self.app.show_approval(tool_name, params, approval_id)

        elif event_type == "todo_update":
            # Todo list updated
            todos = data.get("todos", [])
            self.app.update_todos(todos)

        # Execution lifecycle events - provide visual feedback
        elif event_type == "execution.start":
            self.app.set_agent_state("thinking")

        elif event_type in ("provider.request", "llm.request"):
            # Model is processing - show thinking state
            self.app.set_agent_state("thinking")

        elif event_type in ("llm.response", "provider.response"):
            # Response received - switch to generating state
            self.app.set_agent_state("generating")

        elif event_type in ("execution.end", "orchestrator.complete"):
            # Execution complete
            self.app.set_agent_state("idle")

        elif event_type == "session.start":
            # Session started/resumed - could show session info
            pass

        # Tool events from runtime (tool:pre, tool:post format)
        elif event_type == "tool.pre":
            tool_name = data.get("tool_name", "unknown")
            tool_input = data.get("tool_input", {})
            tool_call_id = data.get("tool_call_id", "")
            tool_id = self.app.add_tool_call(tool_name, tool_input, status="pending")
            self.app.set_agent_state("executing")
            # Store for result matching
            self._current_tool_id = tool_id
            self._tool_call_mapping[tool_call_id] = tool_id

        elif event_type == "tool.post":
            tool_call_id = data.get("tool_call_id", "")
            result = data.get("result", {})
            output = result.get("output", "") if isinstance(result, dict) else str(result)
            tool_id = self._tool_call_mapping.get(tool_call_id, self._current_tool_id)
            if tool_id:
                self.app.update_tool_call(tool_id, output, "success")
            self.app.set_agent_state("generating")

        elif event_type == "agent_push":
            # Agent stack changed (sub-agent spawned)
            agents = data.get("agents", data.get("stack", []))
            self.app.set_agent_stack(agents)

        elif event_type == "agent_pop":
            # Agent returned
            agents = data.get("agents", data.get("stack", []))
            self.app.set_agent_stack(agents)

        elif event_type == "error":
            # Error occurred
            error = data.get("error", data.get("message", "Unknown error"))
            self.app.add_error(str(error))
            self.app.set_agent_state("error")

        elif event_type == "done":
            # Request complete
            self.app.set_agent_state("idle")

        elif event_type == "cancelled":
            # Request was cancelled
            self.app.add_system_message("Request cancelled")
            self.app.set_agent_state("idle")

        elif event_type == "result":
            # Final result - extract turn count if available
            turn = data.get("turn")
            if turn is not None:
                self._safe_app_call("set_turn_count", turn)

        else:
            # Unknown event type - log but don't crash
            logger.debug(f"Unhandled event type: {event_type}")

    async def _event_loop(self) -> None:
        """Background loop for uncorrelated events (approvals, etc.)."""
        try:
            async for event in self._client.event.subscribe():
                await self._handle_event(event)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Event loop error: {e}")

    async def send_abort(self) -> None:
        """Cancel the current request."""
        if not self.is_connected or not self._session_id:
            return

        try:
            await self._client.session.abort(self._session_id)
            self.app.add_system_message("Abort requested")
        except Exception as e:
            logger.error(f"Failed to abort: {e}")
            self.app.add_error(f"Failed to abort: {e}")

    async def send_approval(self, approval_id: str, choice: str) -> None:
        """Send approval response.

        Args:
            approval_id: The approval request ID
            choice: "approve", "deny", or "approve_similar"
        """
        if not self.is_connected or not self._session_id:
            return

        try:
            # Map choice to approved boolean
            approved = choice in ("approve", "approve_similar")
            feedback = "allow_similar" if choice == "approve_similar" else None

            await self._client.approval.respond(
                session_id=self._session_id,
                approval_id=approval_id,
                approved=approved,
                feedback=feedback,
            )
            logger.info(f"Approval sent: {approval_id} -> {choice}")
        except Exception as e:
            logger.error(f"Failed to send approval: {e}")
            self.app.add_error(f"Failed to send approval: {e}")

    async def __aenter__(self) -> RuntimeBridge:
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.disconnect()


# Convenience factory functions


def create_subprocess_bridge(
    app: AmplifierTUI,
    command: list[str] | None = None,
    working_directory: str | None = None,
) -> RuntimeBridge:
    """Create a bridge that launches runtime as subprocess.

    This is the default mode for standalone TUI usage.

    Args:
        app: The TUI application
        command: Custom runtime command (default: ["amplifier-runtime"])
        working_directory: Working directory for subprocess

    Returns:
        RuntimeBridge configured for subprocess mode
    """
    config = BridgeConfig(
        mode=ConnectionMode.SUBPROCESS,
        runtime_command=command or ["amplifier-runtime"],
        working_directory=working_directory,
    )
    return RuntimeBridge(app, config)


def create_attach_bridge(
    app: AmplifierTUI,
    server_url: str = "http://localhost:4096",
    use_websocket: bool = False,
) -> RuntimeBridge:
    """Create a bridge that attaches to existing runtime server.

    Args:
        app: The TUI application
        server_url: Server URL to attach to
        use_websocket: Use WebSocket for streaming (vs HTTP SSE)

    Returns:
        RuntimeBridge configured for attach mode
    """
    config = BridgeConfig(
        mode=ConnectionMode.WEBSOCKET if use_websocket else ConnectionMode.HTTP,
        server_url=server_url,
    )
    return RuntimeBridge(app, config)
