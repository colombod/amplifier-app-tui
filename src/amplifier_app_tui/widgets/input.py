"""Input zone widget for multi-line prompts.

Supports:
- Multi-line input with Ctrl+J for new lines
- Enter to submit
- Command history navigation
- Ghost text autocomplete for @agents, /commands, tool-*
- Suggestions popup showing all matching options
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static, TextArea

if TYPE_CHECKING:
    from ..suggester import CommandSuggester


class PromptTextArea(TextArea):
    """Multi-line input with Ctrl+J for new lines, Enter to submit.

    Keyboard:
        Enter       - Submit the prompt
        Ctrl+J      - Insert new line
        Up/Down     - History navigation (when on first/last line)
        Tab         - Accept ghost text suggestion
    """

    BINDINGS = [
        Binding("enter", "submit", "Submit", show=False),
        Binding("ctrl+j", "newline", "New line", show=False),
        Binding("up", "history_prev", "Previous", show=False),
        Binding("down", "history_next", "Next", show=False),
        Binding("tab", "accept_suggestion", "Accept", show=False),
        Binding("ctrl+space", "trigger_completion", "Complete", show=False),
    ]

    class Submitted(Message):
        """Fired when user presses Enter to submit."""

        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    class SuggestionChanged(Message):
        """Fired when autocomplete suggestion changes."""

        def __init__(self, suggestion: str, current_text: str) -> None:
            super().__init__()
            self.suggestion = suggestion
            self.current_text = current_text

    def __init__(self, suggester: CommandSuggester | None = None, **kwargs) -> None:
        super().__init__(
            language=None,  # Plain text, no syntax highlighting
            soft_wrap=True,
            tab_behavior="focus",  # Tab doesn't insert, we handle it
            **kwargs,
        )
        self._history: list[str] = []
        self._history_index = -1
        self._temp_value = ""
        self._suggester = suggester
        self._ghost_text = ""

    def on_mount(self) -> None:
        """Set up placeholder text styling."""
        # TextArea doesn't have placeholder, we handle empty state in CSS
        pass

    def action_submit(self) -> None:
        """Handle Enter key - submit the prompt."""
        value = self.text.strip()
        if value:
            self.post_message(self.Submitted(value))

    def action_newline(self) -> None:
        """Handle Ctrl+J - insert a new line."""
        self.insert("\n")

    def action_history_prev(self) -> None:
        """Navigate to previous history item."""
        # Only navigate history if cursor is on the first line
        if self.cursor_location[0] == 0:
            self._navigate_history(-1)
        else:
            # Default behavior - move cursor up
            self.action_cursor_up()

    def action_history_next(self) -> None:
        """Navigate to next history item."""
        # Only navigate history if cursor is on the last line
        lines = self.text.split("\n")
        if self.cursor_location[0] >= len(lines) - 1:
            self._navigate_history(1)
        else:
            # Default behavior - move cursor down
            self.action_cursor_down()

    async def action_accept_suggestion(self) -> None:
        """Accept the ghost text suggestion, or insert tab if no suggestion."""
        if self._ghost_text and self._suggester:
            # Get suggestion for current text
            suggestion = await self._suggester.get_suggestion(self.text)
            if suggestion:
                self.text = suggestion
                # Move cursor to end
                self.cursor_location = (
                    len(self.text.split("\n")) - 1,
                    len(self.text.split("\n")[-1]),
                )
                self._ghost_text = ""
                # Clear the suggestion hint
                self.post_message(self.SuggestionChanged("", self.text))
                self.refresh()
                return

        # No suggestion - insert tab as whitespace (4 spaces)
        self.insert("    ")

    async def action_trigger_completion(self) -> None:
        """Manually trigger completion suggestions (Ctrl+Space)."""
        if not self._suggester:
            return

        # Force fetch suggestion for current text
        suggestion = await self._suggester.get_suggestion(self.text)
        if suggestion and suggestion != self.text:
            self._ghost_text = suggestion[len(self.text) :]
            self.post_message(self.SuggestionChanged(self._ghost_text, self.text))
            self.refresh()

    def _navigate_history(self, direction: int) -> None:
        """Navigate through command history."""
        if not self._history:
            return

        # Save current input if starting navigation
        if self._history_index == -1:
            self._temp_value = self.text

        new_index = self._history_index + direction

        if new_index < -1:
            new_index = -1
        elif new_index >= len(self._history):
            new_index = len(self._history) - 1

        self._history_index = new_index

        if new_index == -1:
            self.text = self._temp_value
        else:
            # History is newest-first, so reverse index
            self.text = self._history[-(new_index + 1)]

    def add_to_history(self, value: str) -> None:
        """Add a command to history."""
        if value and (not self._history or self._history[-1] != value):
            self._history.append(value)
        self._history_index = -1
        self._temp_value = ""

    def clear(self) -> None:
        """Clear the input."""
        self.text = ""
        self._ghost_text = ""

    async def _on_key(self, event) -> None:
        """Handle key events - intercept Enter before TextArea's default handler."""
        # Intercept Enter key BEFORE parent processes it (which would insert newline)
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            self.action_submit()
            return

        # Let the key event process first for all other keys
        await super()._on_key(event)

        # Then update ghost text suggestion
        if self._suggester and event.key not in ("tab", "escape"):
            suggestion = await self._suggester.get_suggestion(self.text)
            if suggestion and suggestion != self.text:
                self._ghost_text = suggestion[len(self.text) :]
                # Notify parent of suggestion change
                self.post_message(self.SuggestionChanged(suggestion, self.text))
            else:
                if self._ghost_text:  # Only notify if suggestion cleared
                    self._ghost_text = ""
                    self.post_message(self.SuggestionChanged("", self.text))


class InputZone(Static):
    """Multi-line input area for user prompts.

    ┃ Enter your prompt here...
    ┃ Use Ctrl+J for new lines
    ┃ Press Enter to send

    Supports:
    - Multi-line editing with Ctrl+J
    - Ghost text autocomplete
    - Command history
    """

    DEFAULT_CSS = """
    InputZone {
        height: auto;
        min-height: 4;
        max-height: 12;
        border-top: solid $border;
        padding: 0 1;
    }

    InputZone.disabled {
        opacity: 0.5;
    }

    InputZone #input-container {
        width: 100%;
        height: auto;
    }

    InputZone .prompt-indicator {
        width: 2;
        height: 100%;
        color: $primary;
    }

    InputZone PromptTextArea {
        width: 1fr;
        min-height: 1;
        max-height: 8;
        border: none;
        background: transparent;
        padding: 0;
    }

    InputZone PromptTextArea:focus {
        border: none;
    }
    
    InputZone .suggestion-hint {
        dock: bottom;
        height: 1;
        color: $text-muted;
        text-style: italic;
        padding-left: 2;
    }
    
    InputZone .suggestion-hint.hidden {
        display: none;
    }
    
    InputZone .input-hint {
        dock: bottom;
        height: 1;
        color: $text-muted;
        text-style: dim;
    }
    """

    class PromptSubmitted(Message):
        """Message sent when user submits a prompt."""

        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    disabled: reactive[bool] = reactive(False)

    def __init__(self, suggester: CommandSuggester | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._suggester = suggester

    def compose(self) -> ComposeResult:
        with Horizontal(id="input-container"):
            yield Static("┃ ", classes="prompt-indicator")
            yield PromptTextArea(suggester=self._suggester, id="prompt-input")
        yield Static("", id="suggestion-hint", classes="suggestion-hint hidden")
        yield Static("Enter: send │ Ctrl+J: new line │ Tab: complete", classes="input-hint")

    def on_prompt_text_area_submitted(self, event: PromptTextArea.Submitted) -> None:
        """Handle input submission."""
        value = event.value.strip()
        if value:
            # Add to history
            prompt_input = self.query_one("#prompt-input", PromptTextArea)
            prompt_input.add_to_history(value)
            # Clear input
            prompt_input.clear()
            # Clear suggestion hint
            self._update_suggestion_hint("", "")
            # Post message to app
            self.post_message(self.PromptSubmitted(value))

    def on_prompt_text_area_suggestion_changed(
        self, event: PromptTextArea.SuggestionChanged
    ) -> None:
        """Handle suggestion changes - update the hint display."""
        self._update_suggestion_hint(event.suggestion, event.current_text)

    def _update_suggestion_hint(self, suggestion: str, current_text: str) -> None:
        """Update the suggestion hint label with multiple suggestions if available."""
        hint = self.query_one("#suggestion-hint", Static)
        if suggestion and suggestion != current_text:
            # Try to get all matching suggestions for richer hint
            hint_text = f"Tab → {suggestion}"
            if self._suggester and hasattr(self._suggester, "get_all_suggestions"):
                all_suggestions = self._suggester.get_all_suggestions(current_text)
                if len(all_suggestions) > 1:
                    # Show first 3 suggestions with descriptions
                    parts = []
                    for s in all_suggestions[:3]:
                        if s.description:
                            parts.append(f"{s.value} ({s.description})")
                        else:
                            parts.append(s.value)
                    if len(all_suggestions) > 3:
                        parts.append(f"+{len(all_suggestions) - 3} more")
                    hint_text = "Tab → " + " │ ".join(parts)
            hint.update(hint_text)
            hint.remove_class("hidden")
        else:
            hint.update("")
            hint.add_class("hidden")

    def set_suggester(self, suggester: CommandSuggester) -> None:
        """Set the command suggester for autocomplete."""
        self._suggester = suggester
        prompt_input = self.query_one("#prompt-input", PromptTextArea)
        prompt_input._suggester = suggester

    def set_disabled(self, disabled: bool) -> None:
        """Enable or disable the input zone."""
        self.disabled = disabled
        if disabled:
            self.add_class("disabled")
        else:
            self.remove_class("disabled")

        prompt_input = self.query_one("#prompt-input", PromptTextArea)
        prompt_input.disabled = disabled

    def get_value(self) -> str:
        """Get current input value."""
        return self.query_one("#prompt-input", PromptTextArea).text

    def set_value(self, value: str) -> None:
        """Set input value."""
        self.query_one("#prompt-input", PromptTextArea).text = value

    def clear(self) -> None:
        """Clear the input."""
        self.query_one("#prompt-input", PromptTextArea).clear()
