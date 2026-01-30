"""Content processor for streaming text and thinking blocks.

Handles:
- content_start, content_delta, content_end
- thinking_delta, thinking_final

Based on amplifier-web's content handling patterns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .base import EventProcessor, ProcessorAction, ProcessorResult


@dataclass
class ContentBlock:
    """A content block being streamed."""

    block_type: str  # text, thinking, tool_use
    content: str = ""
    is_streaming: bool = True
    order: int = 0


@dataclass
class ContentState:
    """State for content streaming."""

    blocks: list[ContentBlock] = field(default_factory=list)
    block_index_map: dict[int, int] = field(default_factory=dict)  # server index -> local index
    next_local_index: int = 0
    order_counter: int = 0
    is_streaming: bool = False


class ContentProcessor(EventProcessor):
    """Processes streaming content events.

    Handles the content_block:* events from amplifier-core,
    maintaining state for block index mapping and streaming status.
    """

    # Event types this processor handles
    HANDLED_EVENTS = frozenset(
        [
            # Content block events (amplifier-core format)
            "content_block:start",
            "content_block:delta",
            "content_block:end",
            # Thinking events
            "thinking:delta",
            "thinking:final",
            # Alternative formats (runtime may normalize)
            "content_start",
            "content_delta",
            "content_end",
            "thinking_delta",
            "thinking_final",
        ]
    )

    def __init__(self, app: Any = None) -> None:
        super().__init__(app)
        self._state = ContentState()

    def handles(self, event_type: str) -> bool:
        return event_type in self.HANDLED_EVENTS

    def process(self, event_type: str, data: dict[str, Any]) -> ProcessorResult:
        """Process a content event."""
        # Normalize event type (remove colons for matching)
        normalized = event_type.replace(":", "_").replace("block_", "")

        if normalized in ("content_start", "content_block_start"):
            return self._handle_content_start(data)
        elif normalized in ("content_delta", "content_block_delta"):
            return self._handle_content_delta(data)
        elif normalized in ("content_end", "content_block_end"):
            return self._handle_content_end(data)
        elif normalized in ("thinking_delta",):
            return self._handle_thinking_delta(data)
        elif normalized in ("thinking_final",):
            return self._handle_thinking_final(data)

        return ProcessorResult(handled=False)

    def _handle_content_start(self, data: dict[str, Any]) -> ProcessorResult:
        """Handle content block start."""
        block_type = data.get("block_type", "text")
        server_index = data.get("index", 0)

        # Map server index to local index
        local_index = self._state.next_local_index
        self._state.block_index_map[server_index] = local_index
        self._state.next_local_index += 1

        # Create new block
        block = ContentBlock(
            block_type=block_type,
            content="",
            is_streaming=True,
            order=self._state.order_counter,
        )
        self._state.order_counter += 1
        self._state.blocks.append(block)
        self._state.is_streaming = True

        # Update UI if app available
        if self._app:
            if block_type != "thinking":
                self._app.start_response()

        return ProcessorResult(
            handled=True,
            action=ProcessorAction.UPDATE_UI,
            data={
                "block_type": block_type,
                "local_index": local_index,
                "server_index": server_index,
            },
        )

    def _handle_content_delta(self, data: dict[str, Any]) -> ProcessorResult:
        """Handle content delta (streaming chunk)."""
        server_index = data.get("index", 0)
        delta = data.get("delta", "")

        local_index = self._state.block_index_map.get(server_index)
        if local_index is None or local_index >= len(self._state.blocks):
            return ProcessorResult(handled=False)

        # Append to block
        block = self._state.blocks[local_index]
        block.content += delta

        # Update UI if app available
        if self._app:
            output = self._app._get_output_zone()
            if output and block.block_type != "thinking":
                output.append_content(delta)

        return ProcessorResult(
            handled=True,
            action=ProcessorAction.UPDATE_UI,
            data={"delta": delta, "local_index": local_index},
        )

    def _handle_content_end(self, data: dict[str, Any]) -> ProcessorResult:
        """Handle content block end."""
        server_index = data.get("index", 0)
        final_content = data.get("content")

        local_index = self._state.block_index_map.get(server_index)
        if local_index is None or local_index >= len(self._state.blocks):
            return ProcessorResult(handled=False)

        block = self._state.blocks[local_index]
        if final_content is not None:
            block.content = final_content
        block.is_streaming = False

        # Update UI if app available
        if self._app:
            if block.block_type == "thinking":
                self._app.end_thinking()
            # Note: we don't call end_response here - that's done on prompt_complete

        return ProcessorResult(
            handled=True,
            action=ProcessorAction.UPDATE_UI,
            data={"local_index": local_index, "content": block.content},
        )

    def _handle_thinking_delta(self, data: dict[str, Any]) -> ProcessorResult:
        """Handle dedicated thinking delta event."""
        delta = data.get("delta", "")

        # Find or create streaming thinking block
        thinking_block = None
        for block in self._state.blocks:
            if block.block_type == "thinking" and block.is_streaming:
                thinking_block = block
                break

        if not thinking_block:
            # Create new thinking block
            thinking_block = ContentBlock(
                block_type="thinking",
                content="",
                is_streaming=True,
                order=self._state.order_counter,
            )
            self._state.order_counter += 1
            self._state.blocks.append(thinking_block)

        thinking_block.content += delta

        if self._app:
            self._app.stream_thinking(delta)

        return ProcessorResult(
            handled=True,
            action=ProcessorAction.UPDATE_UI,
            data={"delta": delta},
        )

    def _handle_thinking_final(self, data: dict[str, Any]) -> ProcessorResult:
        """Handle thinking finalized event."""
        content = data.get("content", "")

        # Find streaming thinking block
        for block in self._state.blocks:
            if block.block_type == "thinking" and block.is_streaming:
                block.content = content
                block.is_streaming = False
                break

        if self._app:
            self._app.end_thinking()

        return ProcessorResult(
            handled=True,
            action=ProcessorAction.UPDATE_UI,
            data={"content": content},
        )

    def reset(self) -> None:
        """Reset content state for new turn/session."""
        self._state = ContentState()
        return None

    def reset_block_mapping(self) -> None:
        """Reset block index mapping (called after tool results).

        This is needed because the server resets block indices to 0
        after each tool result, but we want to accumulate blocks.
        """
        self._state.block_index_map.clear()

    def get_state(self) -> dict[str, Any]:
        """Get current state for debugging."""
        return {
            "blocks": [
                {
                    "type": b.block_type,
                    "content_length": len(b.content),
                    "is_streaming": b.is_streaming,
                    "order": b.order,
                }
                for b in self._state.blocks
            ],
            "is_streaming": self._state.is_streaming,
            "block_count": len(self._state.blocks),
        }

    @property
    def is_streaming(self) -> bool:
        """Check if currently streaming content."""
        return self._state.is_streaming

    @property
    def blocks(self) -> list[ContentBlock]:
        """Get current content blocks."""
        return self._state.blocks
