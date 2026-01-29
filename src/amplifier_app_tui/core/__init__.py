"""Core components for the Amplifier TUI.

This module provides transport-agnostic abstractions for connecting
to the Amplifier runtime.
"""

from .event_bridge import EventBridge, EventCallback
from .runtime_manager import ConnectionMode, RuntimeConfig, RuntimeManager

__all__ = [
    "RuntimeManager",
    "RuntimeConfig",
    "ConnectionMode",
    "EventBridge",
    "EventCallback",
]
