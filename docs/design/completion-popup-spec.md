# Completion Popup Component Spec

## Overview

A floating popup widget that displays contextual autocomplete suggestions as the user types triggers (`@`, `/`, `tool-`). Replaces inline ghost-text suggestions with a visible, navigable list.

## Visual Design

### Appearance

```
┃ @found█                                    
┌─ Agents ────────────────────────────────┐
│ ▸ @foundation:explorer     Browse files │
│   @foundation:zen-architect     Design  │
│   @foundation:voice-strategist    Copy  │
│   @custom:my-agent              Custom  │
│   ↓ 3 more...                           │
└─────────────────────────────────────────┘
```

### Design Decisions

| Aspect | Decision | Rationale |
|--------|----------|-----------|
| **Position** | Above input by default | Preserves typed text visibility; flips below if insufficient space |
| **Max height** | 7 items + header | Balances discoverability with screen real estate |
| **Width** | 40-60 chars adaptive | Accommodates name + description without wrapping |
| **Border** | Solid, primary color | Clear boundary; matches existing component language |
| **Selection** | Background highlight | High contrast, no ambiguity |

### Color Scheme (matching existing theme)

```
┌─────────────────────────────────────────────┐
│ Header     │ $surface-darken-1, $text-muted │
│ Background │ $surface                       │
│ Border     │ $primary-darken-1              │
│ Selected   │ $primary-darken-2 bg           │
│ Icon       │ $primary                       │
│ Label      │ $text                          │
│ Description│ $text-muted                    │
│ No matches │ $text-muted, italic            │
└─────────────────────────────────────────────┘
```

## Triggers & Content

| Trigger | Kind | Header | Icon | Example Items |
|---------|------|--------|------|---------------|
| `@` | AGENT | "Agents" | `@` | `@foundation:explorer`, `@custom:my-agent` |
| `/` | COMMAND | "Commands" | `/` | `/help`, `/bundle`, `/reset` |
| `tool-` | TOOL | "Tools" | `⚙` | `tool-bash`, `tool-filesystem` |
| `/bundle ` | SUBCOMMAND | "Subcommands" | `›` | `list`, `install`, `use` |

## Keyboard Interaction

### Navigation Model

```
┌─────────────────────────────────────────────────────────────┐
│ Input has focus → captures all keys                         │
│                                                             │
│ Trigger detected (@, /, tool-):                             │
│   → Popup appears                                           │
│   → Navigation keys intercepted by popup                    │
│   → Character keys continue to input (filter updates)       │
│                                                             │
│ No trigger active:                                          │
│   → Popup hidden                                            │
│   → All keys go to input normally                           │
└─────────────────────────────────────────────────────────────┘
```

### Key Bindings

| Key | Action | Behavior |
|-----|--------|----------|
| `↑` / `Ctrl+P` | Select previous | Wraps to bottom |
| `↓` / `Ctrl+N` | Select next | Wraps to top |
| `Enter` | Accept | Inserts value, hides popup |
| `Tab` | Accept | Same as Enter |
| `Escape` | Dismiss | Hides popup, keeps typed text |
| `Space` | Dismiss & type | Closes popup (no longer in trigger context) |
| Any char | Filter | Updates filter, re-renders list |
| `Backspace` | Update filter | If filter empty, may hide popup |

### Focus Management

The input widget **retains focus** at all times. The popup intercepts specific navigation keys through a coordinated key handling approach:

```python
# In PromptInput.on_key():
def on_key(self, event: Key) -> None:
    if self._completion_popup.is_visible:
        if event.key in ("up", "down", "ctrl+p", "ctrl+n"):
            # Delegate to popup
            self._completion_popup.handle_navigation(event.key)
            event.prevent_default()
        elif event.key in ("enter", "tab"):
            # Accept completion
            self._completion_popup.action_accept()
            event.prevent_default()
        elif event.key == "escape":
            # Dismiss
            self._completion_popup.action_dismiss()
            event.prevent_default()
    # Otherwise, let normal input handling proceed
```

## State Machine

```
                    ┌──────────────┐
                    │    Hidden    │
                    └──────┬───────┘
                           │ Trigger detected
                           ▼
                    ┌──────────────┐
         ┌─────────│   Visible    │─────────┐
         │         └──────┬───────┘         │
         │                │                 │
    Escape/Space     Character         Enter/Tab
         │                │                 │
         ▼                ▼                 ▼
    ┌─────────┐    ┌───────────┐    ┌───────────┐
    │ Dismiss │    │  Filter   │    │  Accept   │
    └────┬────┘    └─────┬─────┘    └─────┬─────┘
         │               │                │
         │               │ Re-render      │ Insert value
         │               ▼                │
         │         ┌───────────┐          │
         │         │  Visible  │          │
         │         │ (updated) │          │
         │         └───────────┘          │
         │                                │
         └────────────────┬───────────────┘
                          ▼
                    ┌──────────────┐
                    │    Hidden    │
                    └──────────────┘
```

## Filtering Behavior

### Algorithm

1. **Prefix match** (highest priority): Label starts with filter
2. **Contains match** (medium priority): Filter appears anywhere in label  
3. **Fuzzy match** (lowest priority): All filter chars appear in order

### Examples

Filter: `exp`
```
Prefix:   @foundation:explorer     ← Ranked first
Contains: @custom:code-expander    ← Ranked second
Fuzzy:    @my:example-parser       ← Ranked third (e-x-p in order)
```

### Edge Cases

| Scenario | Behavior |
|----------|----------|
| No matches | Show "No matches" in muted italic |
| Single match | Show it (no auto-accept) |
| Filter cleared | Show all items, reset to first |
| Very long list | Show max 7, indicate "↓ N more..." |

## Widget Architecture

```
InputZone (existing)
├── PromptInput (modified - coordinates with popup)
│   └── Handles key events, detects triggers
└── CompletionPopup (new - child of InputZone)
    ├── CompletionHeader (Static - category label)
    └── CompletionList (Vertical container)
        └── CompletionItem* (Static widgets)

CompletionController (new - coordination logic)
├── Watches input changes
├── Detects triggers  
├── Requests completions from providers
└── Manages popup show/hide/filter
```

## Integration Pattern

### Modified InputZone

```python
class InputZone(Static):
    def compose(self) -> ComposeResult:
        with Horizontal(id="input-container"):
            yield Static("┃ ", classes="prompt-indicator")
            yield PromptInput(id="prompt-input")
        # Popup as sibling, uses layer system
        yield CompletionPopup(id="completion-popup")
    
    def on_mount(self) -> None:
        # Wire up controller
        self._controller = CompletionController(
            popup=self.query_one("#completion-popup", CompletionPopup)
        )
        self._controller.register_provider("@", AgentCompletionProvider(self._bridge))
        self._controller.register_provider("/", CommandCompletionProvider())
        self._controller.register_provider("tool-", ToolCompletionProvider(self._bridge))
```

### Modified PromptInput

```python
class PromptInput(Input):
    def __init__(self, **kwargs) -> None:
        super().__init__(placeholder="Enter your prompt... (/ for commands)", **kwargs)
        self._controller: CompletionController | None = None
    
    def set_completion_controller(self, controller: CompletionController) -> None:
        self._controller = controller
    
    def on_key(self, event: Key) -> None:
        # Intercept navigation when popup visible
        if self._controller and self._controller.popup.is_visible:
            if event.key in ("up", "down", "ctrl+p", "ctrl+n"):
                if event.key in ("up", "ctrl+p"):
                    self._controller.popup.action_select_prev()
                else:
                    self._controller.popup.action_select_next()
                event.prevent_default()
                return
            
            if event.key in ("enter", "tab"):
                self._controller.popup.action_accept()
                event.prevent_default()
                return
            
            if event.key == "escape":
                self._controller.popup.action_dismiss()
                event.prevent_default()
                return
        
        # Existing history navigation (only when popup hidden)
        if event.key == "up":
            self._navigate_history(-1)
            event.prevent_default()
        elif event.key == "down":
            self._navigate_history(1)
            event.prevent_default()
    
    async def watch_value(self, value: str) -> None:
        """React to value changes - update completions."""
        if self._controller:
            await self._controller.on_input_changed(value, self.cursor_position)
    
    def on_completion_popup_accepted(self, event: CompletionPopup.Accepted) -> None:
        """Handle accepted completion."""
        new_value = self._controller.handle_accepted(event.item, self.value)
        self.value = new_value
        self.cursor_position = len(new_value)
```

## Completion Providers

### AgentCompletionProvider

```python
class AgentCompletionProvider(CompletionProvider):
    def __init__(self, bridge: RuntimeBridge) -> None:
        self._bridge = bridge
        self._cache: list[CompletionItem] | None = None
    
    async def get_completions(
        self, trigger: str, filter_text: str
    ) -> tuple[list[CompletionItem], CompletionKind]:
        if self._cache is None:
            agents = await self._bridge._client.agents.list(self._bridge.session_id)
            self._cache = [
                CompletionItem(
                    value=f"@{a['name']}",
                    label=a["name"],
                    description=a.get("description", "")[:20],
                    kind=CompletionKind.AGENT,
                )
                for a in agents
            ]
        return self._cache, CompletionKind.AGENT
```

### CommandCompletionProvider

```python
class CommandCompletionProvider(CompletionProvider):
    COMMANDS = [
        CompletionItem("/help", "help", "Show help", CompletionKind.COMMAND),
        CompletionItem("/bundle", "bundle", "Manage bundles", CompletionKind.COMMAND),
        CompletionItem("/reset", "reset", "Reset session", CompletionKind.COMMAND),
        CompletionItem("/session", "session", "Session info", CompletionKind.COMMAND),
        CompletionItem("/config", "config", "Configuration", CompletionKind.COMMAND),
        CompletionItem("/clear", "clear", "Clear output", CompletionKind.COMMAND),
        CompletionItem("/quit", "quit", "Exit TUI", CompletionKind.COMMAND),
        # ... more commands
    ]
    
    async def get_completions(
        self, trigger: str, filter_text: str
    ) -> tuple[list[CompletionItem], CompletionKind]:
        return self.COMMANDS, CompletionKind.COMMAND
```

## CSS Additions

Add to `amplifier.tcss`:

```css
/* ============================================================================
 * COMPLETION POPUP
 * ============================================================================ */

CompletionPopup {
    layer: completion;
    display: none;
    width: auto;
    min-width: 40;
    max-width: 60;
    height: auto;
    max-height: 9;
    
    background: $surface;
    border: solid $primary-darken-1;
    padding: 0;
}

CompletionPopup.visible {
    display: block;
}

CompletionPopup #completion-header {
    height: 1;
    padding: 0 1;
    background: $surface-darken-1;
    color: $text-muted;
    text-style: bold;
}

CompletionPopup #completion-list {
    height: auto;
    max-height: 7;
    overflow-y: auto;
    scrollbar-size: 1 1;
}

CompletionPopup .completion-item {
    height: 1;
    padding: 0 1;
}

CompletionPopup .completion-item.selected {
    background: $primary-darken-2;
    color: $text;
}

CompletionPopup .completion-item .item-icon {
    width: 2;
    color: $primary;
}

CompletionPopup .completion-item .item-description {
    color: $text-muted;
}

CompletionPopup .completion-item.selected .item-description {
    color: $text;
}

CompletionPopup .no-matches {
    padding: 0 1;
    color: $text-muted;
    text-style: italic;
}

/* Responsive adjustments */
.layout-narrow CompletionPopup {
    min-width: 30;
    max-width: 45;
}

.layout-mobile CompletionPopup {
    min-width: 100%;
    max-width: 100%;
}
```

## Accessibility Considerations

| Aspect | Implementation |
|--------|----------------|
| Screen readers | Item count announced on open |
| High contrast | Selection uses strong bg contrast |
| Keyboard-only | Full functionality without mouse |
| Focus visible | Selection state always visible |

## Testing Checklist

- [ ] Popup appears on `@` trigger
- [ ] Popup appears on `/` trigger  
- [ ] Popup appears on `tool-` trigger
- [ ] Arrow keys navigate selection
- [ ] Enter/Tab accepts selection
- [ ] Escape dismisses without insertion
- [ ] Typing filters the list
- [ ] Backspace updates filter
- [ ] Space after trigger dismisses popup
- [ ] Empty filter shows all items
- [ ] No matches shows message
- [ ] Long lists show scroll indicator
- [ ] Selection wraps at boundaries
- [ ] Popup positions correctly (above/below)
- [ ] Works with narrow terminals
- [ ] Works with short terminals

## Migration Notes

### Removing Inline Suggester

The existing `CommandSuggester` class can be deprecated once the popup is implemented. However, consider keeping it for a transition period:

```python
# In PromptInput.__init__
# Remove: suggester=suggester
# The popup now handles all completion UI
```

### Backward Compatibility

The `CommandSuggester` can remain as the data source (renamed to something like `CompletionDataSource`) while the UI moves to the popup.
