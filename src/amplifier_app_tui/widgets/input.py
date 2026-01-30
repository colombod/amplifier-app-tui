"""Input zone widget with autocomplete dropdown menu.

Supports:
- Multi-line input with Ctrl+J for new lines
- Enter to submit
- Command history navigation
- Dropdown autocomplete for /commands, @agents, tools
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Input, Static
from textual_autocomplete import AutoComplete, DropdownItem, TargetState


class SmartAutoComplete(AutoComplete):
    """AutoComplete that uses item.id for completion value instead of item.main.

    This allows displaying rich text (command + description) while only
    inserting the command/agent name on Tab.
    """

    def apply_completion(self, value: str, state: TargetState) -> None:
        """Override to use id field if available.

        Args:
            value: The default value (from main text)
            state: Current input state
        """
        # Get the highlighted option to check for id
        option_list = self.query_one("AutoCompleteList")
        highlighted = option_list.highlighted
        if highlighted is not None:
            options = list(option_list._options)
            if 0 <= highlighted < len(options):
                option = options[highlighted]
                # Use id if set, otherwise fall back to extracting command from value
                if option.id:
                    value = option.id
                else:
                    # Extract just the command/agent (before whitespace)
                    value = value.split()[0] if value else value

        super().apply_completion(value, state)


if TYPE_CHECKING:
    from ..completions import CompletionProvider


class PromptInput(Input):
    """Single-line input with Enter to submit, history navigation.

    Keyboard:
        Enter       - Submit the prompt
        Up/Down     - History navigation
    """

    BINDINGS = [
        Binding("up", "history_prev", "Previous", show=False),
        Binding("down", "history_next", "Next", show=False),
    ]

    class Submitted(Message):
        """Fired when user presses Enter to submit."""

        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._history: list[str] = []
        self._history_index = -1
        self._temp_value = ""

    def _on_key(self, event) -> None:
        """Handle key events - intercept Enter."""
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            value = self.value.strip()
            if value:
                self.post_message(self.Submitted(value))
            return

    def action_history_prev(self) -> None:
        """Navigate to previous history item."""
        self._navigate_history(-1)

    def action_history_next(self) -> None:
        """Navigate to next history item."""
        self._navigate_history(1)

    def _navigate_history(self, direction: int) -> None:
        """Navigate through command history."""
        if not self._history:
            return

        # Save current input if starting navigation
        if self._history_index == -1:
            self._temp_value = self.value

        new_index = self._history_index + direction

        if new_index < -1:
            new_index = -1
        elif new_index >= len(self._history):
            new_index = len(self._history) - 1

        self._history_index = new_index

        if new_index == -1:
            self.value = self._temp_value
        else:
            # History is newest-first, so reverse index
            self.value = self._history[-(new_index + 1)]

    def add_to_history(self, value: str) -> None:
        """Add a command to history."""
        if value and (not self._history or self._history[-1] != value):
            self._history.append(value)
        self._history_index = -1
        self._temp_value = ""

    def clear(self) -> None:
        """Clear the input."""
        self.value = ""


class InputZone(Static):
    """Input area with dropdown autocomplete menu.

    ┃ Enter your prompt here...
    ┌─────────────────────────────────┐
    │ ⌘ /help      Show help          │
    │ ⌘ /bundle    Manage bundles     │
    │ → /bundle list  List bundles    │
    └─────────────────────────────────┘

    Features:
    - Dropdown menu appears as you type / or @
    - Arrow keys navigate menu
    - Enter/Tab selects completion
    - Escape closes menu
    """

    DEFAULT_CSS = """
    InputZone {
        height: auto;
        min-height: 3;
        max-height: 15;
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
        height: 1;
        color: $primary;
    }

    InputZone PromptInput {
        width: 1fr;
        border: none;
        background: transparent;
        padding: 0;
    }

    InputZone PromptInput:focus {
        border: none;
    }

    InputZone .input-hint {
        dock: bottom;
        height: 1;
        color: $text-muted;
        text-style: dim;
    }

    /* Autocomplete dropdown styling */
    InputZone AutoComplete {
        /* Position below the input */
        margin-top: 1;
    }

    InputZone AutoComplete AutoCompleteList {
        max-height: 8;
        background: $surface;
        border: solid $primary;
        scrollbar-size: 1 1;
    }

    InputZone AutoComplete .autocomplete--highlight-match {
        color: $success;
        text-style: bold;
    }

    InputZone AutoComplete .option-list--option-highlighted {
        background: $accent;
    }
    """

    class PromptSubmitted(Message):
        """Message sent when user submits a prompt."""

        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    disabled: reactive[bool] = reactive(False)

    def __init__(self, completion_provider: CompletionProvider | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._completion_provider = completion_provider

    def compose(self) -> ComposeResult:
        with Horizontal(id="input-container"):
            yield Static("┃ ", classes="prompt-indicator")
            prompt_input = PromptInput(
                placeholder="Enter prompt, /command, or @agent...",
                id="prompt-input",
            )
            yield prompt_input

            # Add autocomplete dropdown attached to the input
            # Use SmartAutoComplete which extracts command from id field
            if self._completion_provider:
                yield SmartAutoComplete(
                    prompt_input,
                    candidates=self._completion_provider.get_candidates,
                    id="autocomplete",
                )
            else:
                # Static completions fallback
                yield SmartAutoComplete(
                    prompt_input,
                    candidates=self._get_static_candidates,
                    id="autocomplete",
                )

        yield Static(
            "Enter: send │ ↑↓: history/menu │ Tab: complete",
            classes="input-hint",
        )

    def _get_static_candidates(self, state) -> list[DropdownItem]:
        """Fallback static candidates when no provider.

        Display: icon + command + description
        Insert on Tab: just command (via SmartAutoComplete using id field)
        """
        try:
            from textual.content import Content

            text = state.text.strip() if state.text else ""

            if not text.startswith("/"):
                return []

            # Basic command completions
            commands = [
                ("/help", "Show help information"),
                ("/bundle", "Manage bundles"),
                ("/bundle list", "List installed bundles"),
                ("/reset", "Reset the session"),
                ("/clear", "Clear the output"),
                ("/quit", "Exit the application"),
            ]

            items = []
            for cmd, desc in commands:
                if cmd.startswith(text.lower()):
                    prefix = Content.from_markup("[bold green]⌘[/] ")
                    # Display: command (padded) + description
                    display = f"{cmd:<18} [dim]{desc}[/dim]"
                    items.append(
                        DropdownItem(
                            main=Content.from_markup(display),
                            prefix=prefix,
                            id=cmd,  # SmartAutoComplete uses this for insertion
                        )
                    )

            return items
        except Exception:
            # Fallback on any error
            return []

    def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        """Handle input submission."""
        value = event.value.strip()
        if value:
            # Add to history
            prompt_input = self.query_one("#prompt-input", PromptInput)
            prompt_input.add_to_history(value)
            # Clear input
            prompt_input.clear()
            # Post message to app
            self.post_message(self.PromptSubmitted(value))

    def set_completion_provider(self, provider: CompletionProvider) -> None:
        """Set the completion provider for autocomplete."""
        self._completion_provider = provider
        # Update the autocomplete if it exists
        try:
            autocomplete = self.query_one("#autocomplete", AutoComplete)
            autocomplete._get_candidates = provider.get_candidates
        except Exception:
            pass

    def set_disabled(self, disabled: bool) -> None:
        """Enable or disable the input zone."""
        self.disabled = disabled
        if disabled:
            self.add_class("disabled")
        else:
            self.remove_class("disabled")

        prompt_input = self.query_one("#prompt-input", PromptInput)
        prompt_input.disabled = disabled

    def get_value(self) -> str:
        """Get current input value."""
        return self.query_one("#prompt-input", PromptInput).value

    def set_value(self, value: str) -> None:
        """Set input value."""
        self.query_one("#prompt-input", PromptInput).value = value

    def clear(self) -> None:
        """Clear the input."""
        self.query_one("#prompt-input", PromptInput).clear()

    def focus_input(self) -> None:
        """Focus the input field."""
        self.query_one("#prompt-input", PromptInput).focus()
