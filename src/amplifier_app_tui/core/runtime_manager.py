"""RuntimeManager - Manages connection to Amplifier runtime.

Provides a transport-agnostic interface for:
- Launching runtime as subprocess (stdio transport)
- Attaching to existing HTTP server
- Managing lifecycle and reconnection
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from amplifier_app_runtime.sdk import (
    ClientTransport,
    MockClientTransport,
    TransportAmplifierClient,
    TransportState,
    create_attach_client,
    create_mock_transport,
    create_subprocess_client,
)

if TYPE_CHECKING:
    from .event_bridge import EventBridge

logger = logging.getLogger(__name__)


class ConnectionMode(str, Enum):
    """How to connect to the runtime."""

    SUBPROCESS = "subprocess"  # Launch runtime as child process
    ATTACH = "attach"  # Connect to existing HTTP server
    MOCK = "mock"  # Mock transport for testing


@dataclass
class RuntimeConfig:
    """Configuration for RuntimeManager.

    Attributes:
        mode: How to connect to runtime
        command: Custom command for subprocess mode
        working_directory: CWD for subprocess
        env: Additional environment variables
        server_url: URL for attach mode
        timeout: Connection/request timeout
        auto_reconnect: Whether to auto-reconnect on disconnect
    """

    mode: ConnectionMode = ConnectionMode.SUBPROCESS

    # Subprocess mode settings
    command: list[str] = field(default_factory=lambda: ["amplifier-runtime"])
    working_directory: str | None = None
    env: dict[str, str] | None = None

    # Attach mode settings
    server_url: str = "http://localhost:4096"

    # Common settings
    timeout: float = 30.0
    auto_reconnect: bool = True
    reconnect_delay: float = 1.0


class RuntimeManager:
    """Manages the connection to Amplifier runtime.

    This is the primary interface for the TUI to interact with the runtime.
    It handles:
    - Starting/stopping the runtime (subprocess mode)
    - Connecting to existing runtime (attach mode)
    - Reconnection on disconnect
    - Exposing the SDK client for operations

    Usage:
        # Subprocess mode (default)
        manager = RuntimeManager()
        await manager.start()
        sessions = await manager.client.session.list()
        await manager.stop()

        # Attach mode
        config = RuntimeConfig(mode=ConnectionMode.ATTACH, server_url="...")
        manager = RuntimeManager(config)
        await manager.start()

        # Context manager
        async with RuntimeManager() as manager:
            sessions = await manager.client.session.list()
    """

    def __init__(
        self,
        config: RuntimeConfig | None = None,
        event_bridge: EventBridge | None = None,
    ):
        self.config = config or RuntimeConfig()
        self._client: TransportAmplifierClient | None = None
        self._event_bridge = event_bridge
        self._reconnect_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    @property
    def client(self) -> TransportAmplifierClient:
        """Get the SDK client.

        Raises:
            RuntimeError: If not connected
        """
        if self._client is None:
            raise RuntimeError("RuntimeManager not started. Call start() first.")
        return self._client

    @property
    def transport(self) -> ClientTransport:
        """Get the underlying transport."""
        return self.client.transport

    @property
    def is_connected(self) -> bool:
        """Check if connected to runtime."""
        return self._client is not None and self._client.is_connected

    @property
    def state(self) -> TransportState:
        """Get current transport state."""
        if self._client is None:
            return TransportState.DISCONNECTED
        return self._client.transport.state

    async def start(self) -> None:
        """Start the runtime manager and connect.

        For subprocess mode, this launches the runtime process.
        For attach mode, this connects to the existing server.
        """
        if self._client is not None:
            logger.warning("RuntimeManager already started")
            return

        self._stop_event.clear()
        self._client = self._create_client()

        try:
            await self._client.connect()
            logger.info(f"Connected to runtime via {self.config.mode.value}")

            # Start event bridge if configured
            if self._event_bridge:
                self._event_bridge.start(self._client)

            # Start reconnection monitor if auto_reconnect enabled
            if self.config.auto_reconnect:
                self._reconnect_task = asyncio.create_task(self._reconnect_loop())

        except Exception as e:
            self._client = None
            raise ConnectionError(f"Failed to start runtime: {e}") from e

    async def stop(self) -> None:
        """Stop the runtime manager and disconnect.

        For subprocess mode, this terminates the runtime process.
        For attach mode, this closes the connection.
        """
        self._stop_event.set()

        # Cancel reconnect task
        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None

        # Stop event bridge
        if self._event_bridge:
            self._event_bridge.stop()

        # Disconnect client
        if self._client:
            await self._client.disconnect()
            self._client = None

        logger.info("RuntimeManager stopped")

    async def restart(self) -> None:
        """Restart the connection."""
        await self.stop()
        await self.start()

    def _create_client(self) -> TransportAmplifierClient:
        """Create SDK client based on config mode."""
        match self.config.mode:
            case ConnectionMode.SUBPROCESS:
                return create_subprocess_client(
                    command=self.config.command,
                    working_directory=self.config.working_directory,
                    env=self.config.env,
                )
            case ConnectionMode.ATTACH:
                return create_attach_client(
                    base_url=self.config.server_url,
                    timeout=self.config.timeout,
                )
            case ConnectionMode.MOCK:
                return TransportAmplifierClient(
                    _transport=create_mock_transport(),
                )

    async def _reconnect_loop(self) -> None:
        """Monitor connection and reconnect if needed."""
        while not self._stop_event.is_set():
            await asyncio.sleep(1.0)

            if self._client and not self._client.is_connected:
                logger.warning("Connection lost, attempting reconnect...")
                await self._attempt_reconnect()

    async def _attempt_reconnect(self) -> None:
        """Attempt to reconnect with backoff."""
        delay = self.config.reconnect_delay
        max_delay = 30.0

        while not self._stop_event.is_set():
            try:
                # Disconnect cleanly first
                if self._client:
                    await self._client.disconnect()

                # Create new client and connect
                self._client = self._create_client()
                await self._client.connect()

                # Restart event bridge
                if self._event_bridge:
                    self._event_bridge.start(self._client)

                logger.info("Reconnected successfully")
                return

            except Exception as e:
                logger.warning(f"Reconnect failed: {e}, retrying in {delay}s")
                await asyncio.sleep(delay)
                delay = min(delay * 2, max_delay)

    # Mock transport helpers for testing

    def get_mock_transport(self) -> MockClientTransport:
        """Get the mock transport (only valid in MOCK mode).

        Raises:
            RuntimeError: If not in mock mode
        """
        if self.config.mode != ConnectionMode.MOCK:
            raise RuntimeError("get_mock_transport() only valid in MOCK mode")
        if self._client is None:
            raise RuntimeError("RuntimeManager not started")
        transport = self._client.transport
        if not isinstance(transport, MockClientTransport):
            raise RuntimeError("Transport is not MockClientTransport")
        return transport

    def set_mock_response(self, command_type: str, events: list[Any]) -> None:
        """Set a mock response (only valid in MOCK mode)."""
        self.get_mock_transport().set_response(command_type, events)

    # Context manager support

    async def __aenter__(self) -> RuntimeManager:
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.stop()
