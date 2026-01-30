"""Runtime Bridge - Connects TUI to Amplifier Runtime.

Maps runtime events to TUI methods using the transport-aware SDK client.
Supports both subprocess (stdio) and attach (HTTP/WebSocket) modes.

Architecture:
    TUI <-> RuntimeBridge <-> EventRouter <-> Processors
                 |
    TransportAmplifierClient <-> Runtime
             |
    StdioTransport | HTTPTransport | WebSocketTransport

The EventRouter dispatches events to specialized processors:
- ContentProcessor: streaming text and thinking blocks
- ToolProcessor: tool calls and results
- TodoProcessor: todo list updates
- AgentProcessor: sub-session/agent delegation
- ApprovalProcessor: approval requests
- SessionProcessor: session lifecycle
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

from .processors import EventRouter

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

        # Event router for clean event processing
        self._router = EventRouter(app)

        # Tool call tracking (maps runtime tool_call_id -> UI block_id)
        self._current_tool_id: str | None = None
        self._tool_call_mapping: dict[str, str] = {}

        # Cached completion data (pre-fetched on connect)
        self._available_agents: list[str] = []
        self._available_tools: list[str] = []
        self._available_commands: dict[str, Any] = {}

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

    async def _find_or_create_session(self) -> Any:
        """Find an existing session to reuse, or create a new one.

        Looks for sessions that match:
        - Same bundle (if specified)
        - Same working directory (if specified)
        - Active state (not completed/aborted)

        Returns:
            SessionInfo for the session to use
        """
        try:
            # List existing sessions
            sessions = await self._client.session.list()

            # Filter for compatible sessions
            for session in sessions:
                # Skip if session is not active
                state = getattr(session, "state", "").lower()
                if state in ("completed", "aborted", "error"):
                    continue

                # Check bundle match (if we care about bundle)
                if self.config.bundle:
                    session_bundle = getattr(session, "bundle", None)
                    if session_bundle != self.config.bundle:
                        continue

                # Check working directory match (if we care about it)
                if self.config.working_directory:
                    session_cwd = getattr(session, "cwd", None)
                    if session_cwd != self.config.working_directory:
                        continue

                # Found a compatible session - reuse it
                logger.info(f"Reusing existing session: {session.session_id}")
                self._safe_app_call(
                    "add_system_message",
                    f"Reusing existing session: {session.session_id[:8]}...",
                )
                return session

        except Exception as e:
            logger.debug(f"Could not list sessions for reuse: {e}")

        # No compatible session found - create a new one
        logger.info("Creating new session")
        return await self._client.session.create(
            bundle=self.config.bundle,
            working_directory=self.config.working_directory,
        )

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

            # Try to find and reuse an existing session
            session_info = await self._find_or_create_session()
            self._session_id = session_info.session_id
            self._safe_app_call("set_session", self._session_id)
            # Set bundle name for status bar display (use actual bundle from session)
            bundle_name = session_info.bundle or self.config.bundle
            self._safe_app_call("set_bundle_name", bundle_name)

            # Start event listener for uncorrelated events (approvals, etc.)
            self._event_task = asyncio.create_task(self._event_loop())

            # Pre-fetch completion data (agents, tools, commands)
            await self._prefetch_completion_data()

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

        Routes events through the EventRouter to specialized processors.
        Some events require bridge-level handling (tool ID mapping, agent state).
        """
        event_type = event.type
        data = event.data or {}

        logger.debug(f"Event: {event_type} - {data}")

        # Special handling for tool events - we need to track UI block IDs
        if event_type in ("tool_call", "tool_call_start", "tool.start", "tool:pre"):
            self._handle_tool_call_start(data)
            return

        if event_type in ("tool_result", "tool_call_complete", "tool.complete", "tool:post"):
            self._handle_tool_call_complete(data)
            return

        if event_type in ("tool_error", "tool_call_error", "tool.error", "tool:error"):
            self._handle_tool_call_error(data)
            return

        # Route through the EventRouter for standard event processing
        result = self._router.route(event_type, data)

        if result.handled:
            # Handle any state changes signaled by processors
            if result.new_state:
                self._safe_app_call("set_agent_state", result.new_state)
            return

        # Fallback handling for events not covered by processors
        self._handle_fallback_event(event_type, data)

    def _handle_tool_call_start(self, data: dict[str, Any]) -> None:
        """Handle tool call start with UI block ID tracking."""
        tool_name = data.get("tool_name") or data.get("tool") or data.get("name") or "unknown"
        params = (
            data.get("arguments")
            or data.get("tool_input")
            or data.get("params")
            or data.get("input")
            or {}
        )
        tool_call_id = data.get("tool_call_id", data.get("id", ""))

        # Add to UI and get block ID
        tool_id = self.app.add_tool_call(tool_name, params, status="pending")
        self.app.set_agent_state("executing")

        # Store mapping for result matching
        self._current_tool_id = tool_id
        if tool_call_id:
            self._tool_call_mapping[tool_call_id] = tool_id

        # Also route to tool processor for state tracking
        self._router.route("tool_call", {**data, "ui_block_id": tool_id})

    def _handle_tool_call_complete(self, data: dict[str, Any]) -> None:
        """Handle tool call completion with UI block update."""
        tool_call_id = data.get("tool_call_id", data.get("id", ""))
        tool_id = self._tool_call_mapping.get(tool_call_id, self._current_tool_id)
        result = data.get("output", data.get("result", ""))

        if isinstance(result, dict):
            result = result.get("output", str(result))

        if tool_id:
            self.app.update_tool_call(tool_id, str(result)[:500], "success")

        self.app.set_agent_state("generating")

        # Route to processor for state tracking
        self._router.route("tool_result", {**data, "ui_block_id": tool_id})

    def _handle_tool_call_error(self, data: dict[str, Any]) -> None:
        """Handle tool call error with UI block update."""
        tool_call_id = data.get("tool_call_id", data.get("id", ""))
        tool_id = self._tool_call_mapping.get(tool_call_id, self._current_tool_id)
        error = data.get("error", data.get("message", "Unknown error"))

        if tool_id:
            self.app.update_tool_call(tool_id, str(error), "error")

        self.app.set_agent_state("generating")

        # Route to processor for state tracking
        self._router.route("tool_error", {**data, "ui_block_id": tool_id})

    def _handle_fallback_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Handle events not covered by processors."""
        # Content streaming (direct to app for now)
        if event_type in ("content_delta", "content.delta"):
            content = data.get("content", data.get("delta", ""))
            if content:
                self.app.append_content(content)

        elif event_type == "content.start":
            agent_name = data.get("agent_name")
            self._safe_app_call("start_response", agent_name)

        elif event_type == "content.end":
            content = data.get("content", "")
            if content:
                self.app.append_content(content)

        # Thinking events
        elif event_type in ("thinking_start", "thinking.start", "thinking:start"):
            self.app.set_agent_state("thinking")

        elif event_type in ("thinking_delta", "thinking.delta", "thinking:delta"):
            content = data.get("content", data.get("delta", ""))
            if content:
                self.app.add_thinking(content)

        elif event_type in ("thinking_end", "thinking.end", "thinking:end", "thinking:final"):
            content = data.get("content", "")
            if content:
                self.app.add_thinking(content)
            self.app.end_thinking()

        # Approval events
        elif event_type == "approval_requested":
            tool_name = data.get("tool", "unknown")
            params = data.get("params", {})
            approval_id = data.get("approval_id", "")
            risk_level = data.get("risk_level", "high")

            if risk_level == "low":
                self.app.add_inline_approval(tool_name, params, approval_id)
            else:
                self.app.show_approval(tool_name, params, approval_id)

        # Todo events - route to processor
        elif event_type in ("todo_update", "todo:update"):
            self._router.route(event_type, data)

        # Execution lifecycle events
        elif event_type == "execution.start":
            self.app.set_agent_state("thinking")

        elif event_type in ("provider.request", "llm.request"):
            self.app.set_agent_state("thinking")

        elif event_type in ("llm.response", "provider.response"):
            self.app.set_agent_state("generating")

        elif event_type in ("execution.end", "orchestrator.complete"):
            self.app.set_agent_state("idle")

        # Sub-session lifecycle - route to agent processor
        elif event_type in ("session:fork", "session.fork", "session_fork"):
            self._router.route("session_fork", data)

        elif event_type in ("session:join", "session.join"):
            parent_tool_call_id = data.get("parent_tool_call_id", "")
            status = data.get("status", "success")
            self.app.end_sub_session(parent_tool_call_id, status)

        elif event_type == "agent_push":
            agents = data.get("agents", data.get("stack", []))
            self.app.set_agent_stack(agents)

        elif event_type == "agent_pop":
            agents = data.get("agents", data.get("stack", []))
            self.app.set_agent_stack(agents)

        # Error and lifecycle events
        elif event_type == "error":
            error = data.get("error", data.get("message", "Unknown error"))
            self.app.add_error(str(error))
            self.app.set_agent_state("error")

        elif event_type == "done":
            self.app.set_agent_state("idle")

        elif event_type == "cancelled":
            self.app.add_system_message("Request cancelled")
            self.app.set_agent_state("idle")

        elif event_type == "result":
            turn = data.get("turn")
            if turn is not None:
                self._safe_app_call("set_turn_count", turn)

        else:
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

    # -------------------------------------------------------------------------
    # Completion Data APIs - Used by CompletionProvider for autocomplete
    # -------------------------------------------------------------------------

    async def refresh_completion_data(self) -> None:
        """Refresh completion data (agents, tools, commands) from runtime.

        Call this when:
        - Bundle changes (reset with new bundle)
        - Agents are enabled/disabled
        - Tools are added/removed
        - User explicitly requests refresh

        This is the public async method - use from async context.
        """
        await self._prefetch_completion_data()
        logger.info("Completion data refreshed")

    async def _prefetch_completion_data(self) -> None:
        """Pre-fetch completion data (agents, tools, commands) after connecting.

        Called during connect() to populate caches while we're in async context.
        This avoids async/sync issues when CompletionProvider calls get_* methods.
        """
        if not self._client or not self._session_id:
            return

        # Fetch agents
        try:
            agents_data = await self._client.agents.list(self._session_id)
            self._available_agents = [
                agent.get("name", "") for agent in agents_data if agent.get("name")
            ]
            logger.debug(f"Pre-fetched {len(self._available_agents)} agents")
        except Exception as e:
            logger.debug(f"Failed to fetch agents: {e}")
            self._available_agents = []

        # Fetch tools
        try:
            tools_data = await self._client.tools.list(self._session_id)
            self._available_tools = [
                tool.get("name", "") for tool in tools_data if tool.get("name")
            ]
            logger.debug(f"Pre-fetched {len(self._available_tools)} tools")
        except Exception as e:
            logger.debug(f"Failed to fetch tools: {e}")
            self._available_tools = []

        # Fetch commands
        try:
            self._available_commands = await self._client.slash_commands.list()
            logger.debug(f"Pre-fetched commands: {list(self._available_commands.keys())}")
        except Exception as e:
            logger.debug(f"Failed to fetch commands: {e}")
            self._available_commands = {}

    def get_available_agents(self) -> list[str]:
        """Get list of available agent names for @completions.

        Returns cached data that was pre-fetched during connect().

        Returns:
            List of agent names (e.g., ["foundation:explorer", "amplifier:amplifier-expert"])
        """
        return self._available_agents

    def get_available_tools(self) -> list[str]:
        """Get list of available tool names for completions.

        Returns cached data that was pre-fetched during connect().

        Returns:
            List of tool names (e.g., ["bash", "read_file", "web_search"])
        """
        return self._available_tools

    def get_available_commands(self) -> dict[str, Any]:
        """Get available slash commands from runtime.

        Returns cached data that was pre-fetched during connect().

        Returns:
            Dict of command info from runtime
        """
        return self._available_commands

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
