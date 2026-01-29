"""EventBridge - Bridges runtime events to TUI components.

Provides a pub/sub mechanism for routing events from the runtime
to interested UI components without tight coupling.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from amplifier_app_runtime.protocol.events import Event
    from amplifier_app_runtime.sdk import TransportAmplifierClient

logger = logging.getLogger(__name__)

# Type alias for event callbacks
EventCallback = Callable[["Event"], Awaitable[None] | None]


@dataclass
class EventSubscription:
    """A subscription to events."""

    callback: EventCallback
    event_types: set[str] | None = None  # None = all events
    session_id: str | None = None  # None = all sessions


class EventBridge:
    """Bridges events from runtime to TUI components.

    This component:
    - Subscribes to the runtime's event stream
    - Routes events to registered callbacks
    - Provides filtering by event type and session
    - Handles async callbacks properly

    Usage:
        bridge = EventBridge()

        # Subscribe to all events
        bridge.subscribe(handle_all_events)

        # Subscribe to specific event types
        bridge.subscribe(handle_content, event_types={"content.delta", "content.end"})

        # Subscribe to specific session
        bridge.subscribe(handle_session, session_id="sess_123")

        # Start listening (called by RuntimeManager)
        bridge.start(client)

        # Unsubscribe
        bridge.unsubscribe(handle_all_events)
    """

    def __init__(self) -> None:
        self._subscriptions: list[EventSubscription] = []
        self._client: TransportAmplifierClient | None = None
        self._listen_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    def subscribe(
        self,
        callback: EventCallback,
        event_types: set[str] | None = None,
        session_id: str | None = None,
    ) -> EventSubscription:
        """Subscribe to events.

        Args:
            callback: Function to call with events (sync or async)
            event_types: Filter by event types (None = all)
            session_id: Filter by session ID (None = all)

        Returns:
            Subscription object (can be used to unsubscribe)
        """
        sub = EventSubscription(
            callback=callback,
            event_types=event_types,
            session_id=session_id,
        )
        self._subscriptions.append(sub)
        return sub

    def unsubscribe(self, callback_or_sub: EventCallback | EventSubscription) -> bool:
        """Unsubscribe from events.

        Args:
            callback_or_sub: The callback or subscription to remove

        Returns:
            True if subscription was found and removed
        """
        if isinstance(callback_or_sub, EventSubscription):
            try:
                self._subscriptions.remove(callback_or_sub)
                return True
            except ValueError:
                return False
        else:
            # Find by callback
            for sub in self._subscriptions:
                if sub.callback == callback_or_sub:
                    self._subscriptions.remove(sub)
                    return True
            return False

    def start(self, client: TransportAmplifierClient) -> None:
        """Start listening to events from the client.

        Called by RuntimeManager when connection is established.
        """
        self._client = client
        if self._listen_task is None or self._listen_task.done():
            self._listen_task = asyncio.create_task(self._listen_loop())

    def stop(self) -> None:
        """Stop listening to events.

        Called by RuntimeManager when disconnecting.
        """
        if self._listen_task:
            self._listen_task.cancel()
            self._listen_task = None
        self._client = None

    async def _listen_loop(self) -> None:
        """Background task that listens for events."""
        if self._client is None:
            return

        try:
            async for event in self._client.event.subscribe():
                await self._dispatch(event)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Event listener error: {e}")

    async def _dispatch(self, event: Event) -> None:
        """Dispatch event to matching subscribers."""
        for sub in self._subscriptions:
            if self._matches(sub, event):
                try:
                    result = sub.callback(event)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    logger.error(f"Event callback error: {e}")

    def _matches(self, sub: EventSubscription, event: Event) -> bool:
        """Check if event matches subscription filters."""
        # Check event type filter
        if sub.event_types is not None and event.type not in sub.event_types:
            return False

        # Check session filter
        if sub.session_id is not None:
            # Extract session_id from event data if present
            event_session = event.data.get("session_id") if event.data else None
            if event_session != sub.session_id:
                return False

        return True


# Convenience decorators for common event patterns


@dataclass
class EventHandler:
    """Decorator for event handler methods.

    Usage:
        class MyWidget(Widget):
            @EventHandler.on("content.delta", "content.end")
            async def handle_content(self, event: Event):
                ...

            @EventHandler.on_session("sess_123")
            async def handle_session(self, event: Event):
                ...
    """

    event_types: set[str] | None = None
    session_id: str | None = None

    @classmethod
    def on(cls, *event_types: str) -> EventHandler:
        """Subscribe to specific event types."""
        return cls(event_types=set(event_types))

    @classmethod
    def on_session(cls, session_id: str) -> EventHandler:
        """Subscribe to events for a specific session."""
        return cls(session_id=session_id)

    @classmethod
    def on_all(cls) -> EventHandler:
        """Subscribe to all events."""
        return cls()
