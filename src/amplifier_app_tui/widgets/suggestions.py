"""Suggestions popup widget for autocomplete.

Shows a list of matching suggestions that the user can navigate and select.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

if TYPE_CHECKING:
    pass


@dataclass
class Suggestion:
    """A single suggestion item."""

    value: str
    description: str = ""
    category: str = ""  # "command", "agent", "tool", "subcommand", "flag"


class SuggestionItem(Static):
    """A single suggestion in the list."""

    DEFAULT_CSS = """
    SuggestionItem {
        width: 100%;
        height: 1;
        padding: 0 1;
    }
    
    SuggestionItem.selected {
        background: $accent;
        color: $text;
    }
    
    SuggestionItem .suggestion-value {
        width: auto;
    }
    
    SuggestionItem .suggestion-desc {
        color: $text-muted;
        margin-left: 2;
    }
    """

    def __init__(self, suggestion: Suggestion, **kwargs) -> None:
        self.suggestion = suggestion
        display = suggestion.value
        if suggestion.description:
            display = f"{suggestion.value}  [dim]{suggestion.description}[/dim]"
        super().__init__(display, **kwargs)


class SuggestionsPopup(Widget):
    """Popup widget showing autocomplete suggestions.

    Features:
    - Arrow keys to navigate
    - Enter/Tab to select
    - Escape to close
    - Shows category and description for each suggestion
    """

    DEFAULT_CSS = """
    SuggestionsPopup {
        layer: overlay;
        width: auto;
        min-width: 30;
        max-width: 60;
        max-height: 10;
        background: $surface;
        border: solid $primary;
        padding: 0;
        display: none;
    }
    
    SuggestionsPopup.visible {
        display: block;
    }
    
    SuggestionsPopup .suggestions-header {
        width: 100%;
        height: 1;
        background: $primary;
        color: $text;
        padding: 0 1;
    }
    
    SuggestionsPopup .suggestions-list {
        width: 100%;
        height: auto;
        max-height: 8;
        overflow-y: auto;
    }
    
    SuggestionsPopup .suggestions-hint {
        width: 100%;
        height: 1;
        background: $surface-darken-1;
        color: $text-muted;
        padding: 0 1;
        text-style: italic;
    }
    """

    BINDINGS = [
        Binding("up", "prev", "Previous", show=False),
        Binding("down", "next", "Next", show=False),
        Binding("enter", "select", "Select", show=False),
        Binding("tab", "select", "Select", show=False),
        Binding("escape", "close", "Close", show=False),
    ]

    selected_index: reactive[int] = reactive(0)
    suggestions: reactive[list[Suggestion]] = reactive(list, always_update=True)

    class Selected(Message):
        """Fired when a suggestion is selected."""

        def __init__(self, suggestion: Suggestion) -> None:
            super().__init__()
            self.suggestion = suggestion

    class Closed(Message):
        """Fired when popup is closed without selection."""

        pass

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._items: list[SuggestionItem] = []

    def compose(self) -> ComposeResult:
        yield Static("Suggestions", classes="suggestions-header")
        yield Vertical(id="suggestions-list", classes="suggestions-list")
        yield Static("↑↓ navigate • Enter select • Esc close", classes="suggestions-hint")

    def show_suggestions(self, suggestions: list[Suggestion]) -> None:
        """Show suggestions in the popup."""
        self.suggestions = suggestions
        self.selected_index = 0
        self._update_list()
        self.add_class("visible")

    def hide(self) -> None:
        """Hide the popup."""
        self.remove_class("visible")
        self.suggestions = []

    def _update_list(self) -> None:
        """Update the suggestions list."""
        container = self.query_one("#suggestions-list", Vertical)
        container.remove_children()
        self._items = []

        for i, suggestion in enumerate(self.suggestions):
            item = SuggestionItem(suggestion)
            if i == self.selected_index:
                item.add_class("selected")
            self._items.append(item)
            container.mount(item)

    def watch_selected_index(self, old_index: int, new_index: int) -> None:
        """Update selection highlighting."""
        if self._items:
            if 0 <= old_index < len(self._items):
                self._items[old_index].remove_class("selected")
            if 0 <= new_index < len(self._items):
                self._items[new_index].add_class("selected")
                # Scroll into view
                self._items[new_index].scroll_visible()

    def action_prev(self) -> None:
        """Select previous suggestion."""
        if self.suggestions:
            self.selected_index = (self.selected_index - 1) % len(self.suggestions)

    def action_next(self) -> None:
        """Select next suggestion."""
        if self.suggestions:
            self.selected_index = (self.selected_index + 1) % len(self.suggestions)

    def action_select(self) -> None:
        """Select current suggestion."""
        if self.suggestions and 0 <= self.selected_index < len(self.suggestions):
            self.post_message(self.Selected(self.suggestions[self.selected_index]))
            self.hide()

    def action_close(self) -> None:
        """Close without selecting."""
        self.hide()
        self.post_message(self.Closed())

    @property
    def is_visible(self) -> bool:
        """Check if popup is visible."""
        return self.has_class("visible")

    @property
    def current_suggestion(self) -> Suggestion | None:
        """Get currently selected suggestion."""
        if self.suggestions and 0 <= self.selected_index < len(self.suggestions):
            return self.suggestions[self.selected_index]
        return None
