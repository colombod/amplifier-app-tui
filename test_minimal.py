"""Minimal TUI test to isolate input issues."""
from textual.app import App, ComposeResult
from textual.widgets import Input, Static
from textual.containers import Vertical

class MinimalTUI(App):
    CSS = """
    Screen {
        layout: vertical;
    }
    #output {
        height: 1fr;
        border: solid green;
    }
    #input {
        height: 3;
        border: solid blue;
    }
    """
    
    def compose(self) -> ComposeResult:
        yield Static("Type below and press Enter:", id="output")
        yield Input(placeholder="Type here...", id="input")
    
    def on_input_submitted(self, event: Input.Submitted) -> None:
        output = self.query_one("#output", Static)
        output.update(f"You typed: {event.value}")
        event.input.clear()

if __name__ == "__main__":
    app = MinimalTUI()
    app.run()
