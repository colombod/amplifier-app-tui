"""Custom widgets for the Amplifier TUI."""

from .header import AgentHeader
from .input import InputZone, PromptInput
from .output import OutputZone
from .status import StatusBar

__all__ = [
    "AgentHeader",
    "InputZone",
    "OutputZone",
    "PromptInput",
    "StatusBar",
]
