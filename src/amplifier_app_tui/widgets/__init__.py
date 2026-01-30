"""Custom widgets for the Amplifier TUI."""

from .header import AgentHeader
from .input import InputZone, PromptTextArea
from .output import OutputZone
from .status import StatusBar
from .suggestions import Suggestion, SuggestionItem, SuggestionsPopup

__all__ = [
    "AgentHeader",
    "InputZone",
    "OutputZone",
    "PromptTextArea",
    "StatusBar",
    "Suggestion",
    "SuggestionItem",
    "SuggestionsPopup",
]
