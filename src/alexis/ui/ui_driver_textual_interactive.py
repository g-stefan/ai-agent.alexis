# AI-Agent.Alexis
# SPDX-FileCopyrightText: 2026 Grigore Stefan <g_stefan@yahoo.com>
# SPDX-License-Identifier: Apache-2.0

import asyncio
import sys
import threading
from typing import Callable, Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass

from .ui_driver import UIDriver
from .. import version as alexis_version

try:
    from textual.app import ComposeResult, App
    from textual import events
    from textual.message import Message
    from textual.containers import Container, Horizontal, Vertical, VerticalScroll
    from textual.widgets import Static, Button, TextArea, RichLog, Header, Footer, Label, Input
    from textual.screen import ModalScreen
    from textual.binding import Binding
    from textual.command import CommandPalette, SearchIcon
    from textual.worker import WorkerState
    from rich.text import Text
    from rich.panel import Panel
    from rich.table import Table
    from rich.console import Group as RichGroup
    TEXTUAL_AVAILABLE = True
except ImportError as e:
    TEXTUAL_AVAILABLE = False
    TEXTUAL_IMPORT_ERROR = str(e)


@dataclass
class ConversationMessage:
    """Represents a message in the conversation."""
    type: str  # "thinking", "input", "output"
    content: str
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


def estimate_token_breakdown(messages: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Estimate token breakdown by category from messages.

    Returns a dictionary with token counts for:
    - system_tokens: System message tokens
    - tool_tokens: Tool definition tokens
    - user_tokens: User input tokens
    - thinking_tokens: Thinking/reasoning tokens
    - tool_call_tokens: Tool call tokens
    """
    breakdown = {
        "system_tokens": 0,
        "tool_tokens": 0,
        "user_tokens": 0,
        "thinking_tokens": 0,
        "tool_call_tokens": 0,
    }

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        # Rough token estimation: ~4 chars per token
        def count_tokens(text: str) -> int:
            if isinstance(text, str):
                return max(1, len(text) // 4)
            elif isinstance(text, list):
                return max(1, len(str(text)) // 4)
            return 1

        if role == "system":
            breakdown["system_tokens"] += count_tokens(content)
        elif role == "user":
            breakdown["user_tokens"] += count_tokens(content)
        elif role == "assistant":
            # Check for thinking content
            if "reasoning_content" in msg or "extra_content" in msg:
                reasoning = msg.get("reasoning_content", "")
                breakdown["thinking_tokens"] += count_tokens(reasoning)
            # Count tool calls
            if "tool_calls" in msg:
                breakdown["tool_call_tokens"] += count_tokens(str(msg["tool_calls"]))
            # Regular content
            breakdown["user_tokens"] += count_tokens(content)
        elif role == "tool":
            breakdown["tool_tokens"] += count_tokens(content)

    return breakdown


class SimpleFallbackUI:
    """Simple fallback UI when textual is not available."""

    async def run(
        self,
        run_single_turn: Callable,
        messages: List[Dict[str, Any]],
        save_state: Callable,
        user_content: List[Dict[str, Any]] = None,
        **kwargs
    ):
        """Run simple text-based interactive mode."""
        print("\n[*] Interactive Mode (Text-based)", file=sys.stderr)
        print("[*] Type 'exit', 'quit', /exit or /quit to stop\n", file=sys.stderr)

        # Process initial prompt if provided
        if user_content:
            try:
                await run_single_turn()
            except BaseException as e:
                if isinstance(e, SystemExit):
                    raise
                print(f"\n[!] Execution error: {e}", file=sys.stderr)

        # Interactive loop
        try:
            while True:
                try:
                    user_input = await asyncio.get_event_loop().run_in_executor(
                        None, input, "\n[input]You: "
                    )
                    stripped = user_input.strip()
                    if not stripped:
                        continue
                    # Accept both bare and slash forms (e.g. /quit, /exit).
                    if stripped.lower().lstrip('/') in ['exit', 'quit', 'q']:
                        break

                    messages.append({"role": "user", "content": [{"type": "text", "text": stripped}]})
                    await run_single_turn()
                    save_state()

                except (KeyboardInterrupt, EOFError):
                    print("\n[!] Session ended", file=sys.stderr)
                    break
        finally:
            save_state()


if TEXTUAL_AVAILABLE:

    # Context categories used by the defrag-style map and its legend:
    # (stats key, short label, hex colour). Order = fill order in the grid,
    # following the processing order: prompt is assembled, the model thinks,
    # then answers. thinking + answer == completion, so they don't double-count.
    CONTEXT_CATEGORIES = [
        ("history_tokens",  "Hist",  "#5f87ff"),  # blue    – prior conversation
        ("tools_tokens",    "Tool",  "#ffd75f"),  # yellow  – tool definitions
        ("new_tokens",      "New",   "#87d7ff"),  # cyan    – new prompt content
        ("thinking_tokens", "Think", "#b060d0"),  # magenta – this turn's reasoning
        ("answer_tokens",   "Out",   "#5fff5f"),  # green   – this turn's answer
    ]
    CONTEXT_FREE_COLOR = "#30304a"  # dark slate – unused window

    class StatisticsPanel(Static):
        """Right sidebar showing token statistics and config."""

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            # Instance-level so multiple panels / runs don't share state.
            self.stats: Dict[str, Any] = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "tokens_per_second": 0.0,
                "lifetime_tokens": 0,
                "mcp_calls": 0,
                "thinking_enabled": False,
                "context_limit": None,
                # Real prompt breakdown reported by the model.
                "history_tokens": 0,
                "tools_tokens": 0,
                "new_tokens": 0,
            }

        def render(self):
            """Render the statistics panel with memory map."""
            s = self.stats
            title = Text("STATISTICS", style="bold cyan")

            table = Table.grid(expand=False)
            table.add_column(width=8, no_wrap=True)           # label
            table.add_column(justify="right", min_width=9, no_wrap=True)   # value
            table.add_column(justify="left", no_wrap=True)    # unit

            thinking_status = "[green]✓ ON[/green]" if s["thinking_enabled"] else "[dim]✗ OFF[/dim]"
            table.add_row("[yellow]Think[/yellow]",   thinking_status, "")
            window = s.get("context_limit") or 0
            window_str = f"{window:,}" if window > 0 else "[dim]—[/dim]"
            table.add_row("[yellow]Context[/yellow]", window_str, "")

            table.add_row("[yellow]Prompt[/yellow]",  f"{s['prompt_tokens']:,}", "")
            table.add_row("[yellow]Output[/yellow]",  f"{s['completion_tokens']:,}", "")
            table.add_row("[yellow]Total[/yellow]",   f"{s['total_tokens']:,}", "")
            tps = s['tokens_per_second']
            table.add_row("[yellow]Speed[/yellow]",   f"{tps:.1f}", "[dim] t/s[/dim]")
            table.add_row("[yellow]MCP[/yellow]",     f"{s['mcp_calls']}", "")
            if s.get("lifetime_tokens"):
                table.add_row("[yellow]Life[/yellow]", f"{s['lifetime_tokens']:,}", "")

            return RichGroup(title, table)

        def update_stats(self, stats: Dict[str, Any]):
            """Update statistics."""
            self.stats.update(stats)
            self.refresh()

    class MCPServersPanel(Static):
        """Right-panel widget listing the configured MCP server names."""

        def __init__(self, servers: List[str], **kwargs):
            super().__init__(**kwargs)
            self._servers = servers

        def render(self):
            t = Text("MCP SERVERS\n", style="bold cyan")
            for name in self._servers:
                t.append(f"{name}\n", style="yellow")
            return t

    class SkillsPanel(Static):
        """Right-panel widget showing how many skills were discovered. Only
        mounted when skills are enabled via the --agent-use-skills flag."""

        def __init__(self, count: int, **kwargs):
            super().__init__(**kwargs)
            self._count = count

        def render(self):
            t = Text("SKILLS\n", style="bold cyan")
            t.append(f"{self._count}\n", style="yellow")
            return t


    class ContextMap(Static):
        """Defrag-style visualisation of context-window usage.

        The window is laid out as a grid of cells, each cell a slice of the
        context filled in order (history → tools → new → output → free) and
        colour-coded by category. Each *text* row encodes *two* data rows by
        drawing the upper-half-block ``▀``: the glyph's foreground colour is the
        top cell, its background colour the bottom cell — doubling the vertical
        resolution like the old Windows defragmenter."""

        HALF = "▀"  # upper half block

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.stats: Dict[str, Any] = {
                "context_limit": None,
                "total_tokens": 0,
                "history_tokens": 0,
                "tools_tokens": 0,
                "new_tokens": 0,
                "thinking_tokens": 0,
                "answer_tokens": 0,
                "completion_tokens": 0,
            }

        def update_stats(self, stats: Dict[str, Any]) -> None:
            self.stats.update(stats)
            self.refresh()

        def _grid_dims(self):
            """Columns × data-rows that fit the current widget size."""
            inner_w = max(8, (self.size.width or 24) - 1)
            cols = min(24, inner_w)
            # 2 data rows per text row; keep the map a few text rows tall.
            text_rows = 8
            return cols, text_rows * 2

        def _cell_colors(self, cols: int, data_rows: int):
            """Return a flat list (len cols*data_rows) of per-cell hex colours."""
            total_cells = cols * data_rows
            limit = self.stats.get("context_limit") or 0
            if limit <= 0:
                return [CONTEXT_FREE_COLOR] * total_cells

            colors = []
            for key, _label, hexcol in CONTEXT_CATEGORIES:
                tokens = max(0, int(self.stats.get(key, 0) or 0))
                n = int(round(tokens / limit * total_cells))
                colors.extend([hexcol] * n)
            # Trim overflow (rounding) and pad the remainder as free space.
            colors = colors[:total_cells]
            colors.extend([CONTEXT_FREE_COLOR] * (total_cells - len(colors)))
            return colors

        def render(self):
            limit = self.stats.get("context_limit") or 0
            t = Text()
            t.append("CONTEXT\n", style="bold cyan")
            if limit <= 0:
                t.append("no window configured", style="dim")
                return t

            cols, data_rows = self._grid_dims()
            colors = self._cell_colors(cols, data_rows)

            # Two data rows per printed line via fg(top)/bg(bottom) half blocks.
            for r in range(0, data_rows, 2):
                top = colors[r * cols:(r + 1) * cols]
                bottom = colors[(r + 1) * cols:(r + 2) * cols]
                for c in range(cols):
                    fg = top[c]
                    bg = bottom[c] if c < len(bottom) else CONTEXT_FREE_COLOR
                    t.append(self.HALF, style=f"{fg} on {bg}")
                t.append("\n")

            # Legend + usage summary.
            used = self.stats.get("total_tokens", 0)
            used_pct = (used / limit * 100) if limit else 0.0
            for key, label, hexcol in CONTEXT_CATEGORIES:
                tokens = int(self.stats.get(key, 0) or 0)
                t.append("■ ", style=hexcol)
                t.append(f"{label:5} {tokens:>9,}\n")
            free = max(0, limit - used)
            t.append("■ ", style=CONTEXT_FREE_COLOR)
            t.append(f"{'Free':5} {free:>9,}\n")
            gauge = "#5fff5f" if used_pct < 80 else "#ffd75f" if used_pct < 95 else "#ff5f5f"
            t.append("  ")                              # 2 spaces to match "■ " prefix
            t.append(f"{'Used':5} ", style="bold")
            t.append(f"{used_pct:>9.1f}", style=gauge)
            t.append(" %", style="dim")
            return t

    SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    # msg_type -> (title label, css class). The css class drives the left bar
    # colour and the title's "light" background (see ChatApp.CSS).
    BLOCK_META = {
        "input":       ("USER",        "block--input"),
        "thinking":    ("THINKING",    "block--thinking"),
        "output":      ("ASSISTANT",   "block--output"),
        "tool_call":   ("TOOL CALL",   "block--toolcall"),
        "tool_result": ("TOOL RESULT", "block--toolresult"),
        "tool":        ("TOOL",        "block--tool"),
        "error":       ("ERROR",       "block--error"),
    }

    def _message_text(content) -> str:
        """Flatten a message ``content`` (str or list of parts) to plain text."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for c in content:
                if isinstance(c, dict):
                    if c.get("type") == "text":
                        parts.append(c.get("text", ""))
                    elif c.get("type") == "image_url":
                        parts.append("[image]")
                else:
                    parts.append(str(c))
            return "\n".join(p for p in parts if p)
        return "" if content is None else str(content)

    _TOOL_TYPES = {"tool_call", "tool_result", "tool"}
    _TOOL_PREVIEW_LINES = 3

    def _truncate_tool_body(content: str) -> str:
        """Return the first _TOOL_PREVIEW_LINES lines of content, appending '...' if truncated."""
        lines = content.splitlines()
        if len(lines) <= _TOOL_PREVIEW_LINES:
            return content
        return "\n".join(lines[:_TOOL_PREVIEW_LINES]) + "\n..."

    class CopyButton(Static):
        """Small icon button — carries no content, just signals a copy request."""

        class Pressed(Message):
            pass  # No payload; the parent MessageBlock owns the content.

        def __init__(self, **kwargs) -> None:
            super().__init__(" ❐ ", **kwargs)

        def on_click(self, event: events.Click) -> None:
            event.stop()
            self.post_message(self.Pressed())

    class MessageBlock(Vertical):
        """A committed transcript entry: a coloured left bar, a title with a
        light background, and the body text on a black background."""

        def __init__(self, msg_type: str, content: str, tool_name: str = None,
                     send_bytes: int = None, recv_bytes: int = None, **kwargs):
            super().__init__(**kwargs)
            title, css_class = BLOCK_META.get(msg_type, ("ASSISTANT", "block--output"))
            self.add_class("message-block", css_class)
            # Full content lives only here — never passed into child widgets.
            self._original_content = content
            byte_count = len(content.encode("utf-8")) if content else 0
            if msg_type == "tool":
                # Joined tool call + result: everything lives in the title, e.g.
                # "TOOL - run_skill_script - 12/100 bytes" (sent/received). The
                # body stays empty; the copy button yields the full call+result.
                head = f"{title} - {tool_name}" if tool_name else title
                self._title = f"{head} - {send_bytes or 0}/{recv_bytes or 0} bytes"
                self._display_body = ""
            elif msg_type in _TOOL_TYPES:
                # Tool name (when known) lives in the header, e.g.
                # "TOOL RESULT - run_skill_script - 100 bytes".
                head = f"{title} - {tool_name}" if tool_name else title
                self._title = f"{head} - {byte_count} bytes"
                self._display_body = _truncate_tool_body(content)
            else:
                self._title = title
                # Drop the trailing newline(s) so the block ends on the last line
                # of text rather than a blank line — the gap between blocks
                # already separates them, keeping the transcript compact.
                self._display_body = content.rstrip("\n") if content else content

        def compose(self) -> ComposeResult:
            with Horizontal(classes="block-title-row"):
                yield Static(self._title, classes="block-title")
                yield CopyButton(classes="block-copy")
            # Title-only blocks (joined TOOL) render no body widget at all.
            if self._display_body:
                # Rich Text avoids any '[…]' being interpreted as markup.
                yield Static(Text(self._display_body), classes="block-body")

        def on_copy_button_pressed(self, message: "CopyButton.Pressed") -> None:
            try:
                self.app.copy_to_clipboard(self._original_content)
                self.app.notify("Copied to clipboard", timeout=1.5)
            except Exception:
                self.app.notify("Copy failed", severity="warning", timeout=1.5)

    class StreamingIndicator(Vertical):
        """Animated live block shown at the bottom while a turn streams.

        Same visual design as MessageBlock, but the title carries a spinner that
        keeps animating on its own timer regardless of token cadence."""

        # Streaming type -> (title label, css class).
        TYPE_META = {
            "thinking":  ("THINKING",  "block--thinking"),
            "output":    ("ASSISTANT", "block--output"),
            "tool_call": ("TOOL CALL", "block--toolcall"),
            # Live "tool is running" view: shown from the moment the call is
            # dispatched until its result arrives, so the tool never collapses to
            # nothing while it executes. Uses the tool-result colour to signal
            # "awaiting result".
            "tool_exec": ("TOOL",      "block--toolresult"),
        }
        _ALL_CLASSES = ("block--thinking", "block--output", "block--toolcall",
                        "block--toolresult")

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.add_class("message-block", "block--output")
            self.msg_type: Optional[str] = None
            self.body = ""
            self.frame = 0
            self.display = False
            self._title_widget: Optional["Static"] = None
            self._body_widget: Optional["Static"] = None

        def compose(self) -> ComposeResult:
            self._title_widget = Static("", classes="block-title")
            self._body_widget = Static("", classes="block-body")
            yield self._title_widget
            yield self._body_widget

        def on_mount(self) -> None:
            self.set_interval(0.1, self._tick)

        def _tick(self) -> None:
            if self.msg_type:
                self.frame = (self.frame + 1) % len(SPINNER_FRAMES)
                self._render_view()

        def set_stream(self, msg_type: str, content: str) -> None:
            if msg_type != self.msg_type:
                self.remove_class(*self._ALL_CLASSES)
                _label, css_class = self.TYPE_META.get(msg_type, self.TYPE_META["output"])
                self.add_class(css_class)
            self.msg_type = msg_type
            self.body = content
            self.display = True
            self._render_view()

        def clear(self) -> None:
            self.msg_type = None
            self.body = ""
            self.display = False
            self._render_view()

        def _render_view(self) -> None:
            if not self._title_widget:
                return
            if self.msg_type:
                spinner = SPINNER_FRAMES[self.frame]
                label = self.TYPE_META.get(self.msg_type, self.TYPE_META["output"])[0]
                if self.msg_type == "tool_call":
                    byte_count = len(self.body.encode("utf-8")) if self.body else 0
                    self._title_widget.update(f"{spinner} {label} - {byte_count} bytes")
                    self._body_widget.update(Text(_truncate_tool_body(self.body)))
                elif self.msg_type == "tool_exec":
                    # Call dispatched, result pending: keep the call text on screen
                    # with an animated spinner so progress is visible while it runs.
                    self._title_widget.update(f"{spinner} {label} - running…")
                    self._body_widget.update(Text(_truncate_tool_body(self.body)))
                else:
                    self._title_widget.update(f"{spinner} {label}")
                    self._body_widget.update(Text(self.body))
            else:
                self._title_widget.update("")
                self._body_widget.update("")

    class ConversationView(VerticalScroll):
        """Scrollable transcript built from committed child widgets."""

        def compose(self) -> ComposeResult:
            self.indicator = StreamingIndicator(id="stream-indicator")
            yield self.indicator

        async def add_block(self, msg_type: str, content: str,
                            tool_name: str = None, send_bytes: int = None,
                            recv_bytes: int = None) -> None:
            """Commit a permanent message block above the live indicator."""
            block = MessageBlock(msg_type, content, tool_name=tool_name,
                                 send_bytes=send_bytes, recv_bytes=recv_bytes,
                                 classes="message-block")
            await self.mount(block, before=self.indicator)
            self.scroll_end(animate=False)

        def update_streaming(self, msg_type: str, content: str) -> None:
            """Update the animated live block."""
            self.indicator.set_stream(msg_type, content)
            self.scroll_end(animate=False)

        def clear_streaming(self) -> None:
            self.indicator.clear()

        async def clear_messages(self) -> None:
            """Remove all committed blocks (keeps the live indicator)."""
            for block in self.query(MessageBlock):
                await block.remove()

    import os as _os
    import re as _re
    import base64 as _base64
    import mimetypes as _mimetypes

    _IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'}
    _TEXT_SIZE_LIMIT = 1 * 1024 * 1024  # 1 MB

    @dataclass
    class Attachment:
        path: str
        name: str
        kind: str        # "text" or "image"
        content: str     # raw text or base64 string
        mime_type: str = ""

    def _clean_path(raw: str) -> str:
        """Strip whitespace and surrounding quotes from a pasted Windows path."""
        p = raw.strip()
        # Windows drag-and-drop wraps paths in quotes, sometimes with inner spaces
        if len(p) >= 2 and p[0] in ('"', "'") and p[-1] == p[0]:
            p = p[1:-1]
        return p.strip()

    def _extract_file_paths(text: str):
        """Find file paths (quoted or unquoted) anywhere inside `text`.

        Windows drag-and-drop inserts the dropped file's path into the input.
        It wraps the path in double quotes when it contains spaces, frequently
        appends a trailing space, and on some terminals appends a newline or
        delivers it alongside text the user already typed. This scans for any
        token that resolves to a real file rather than requiring the whole
        field to be exactly the path.

        Returns ``(paths, leftover)`` where ``leftover`` is ``text`` with the
        detected paths removed, so an accompanying message survives.
        """
        paths: List[str] = []

        def _consume_quoted(s: str) -> str:
            def repl(m):
                cand = m.group(1).strip()
                if cand and _os.path.isfile(cand):
                    paths.append(cand)
                    return ""
                return m.group(0)
            s = _re.sub(r'"([^"]*)"', repl, s)
            s = _re.sub(r"'([^']*)'", repl, s)
            return s

        leftover = _consume_quoted(text)

        # An unquoted path that itself contains spaces: if the whole remaining
        # text is a file, take it wholesale before splitting on whitespace.
        whole = leftover.strip()
        if whole and _os.path.isfile(whole):
            paths.append(whole)
            return paths, ""

        # Otherwise scan whitespace-separated tokens (unquoted, space-free).
        kept = []
        for tok in _re.split(r"(\s+)", leftover):
            cand = tok.strip()
            if cand and _os.path.isfile(cand):
                paths.append(cand)
            else:
                kept.append(tok)
        return paths, "".join(kept).strip()

    def _extract_leading_file_paths(text: str):
        """Detect file path(s) only at the *start* of `text`.

        Used by the keystroke fallback: a file dropped onto an empty field
        lands at the very beginning, so only a path anchored at offset 0
        counts. A filename typed *after* other prose (``some text file.py``)
        leaves a non-path token at the front and is therefore ignored — it
        stays as plain text.

        Returns ``(paths, leftover)``. When the text does not begin with a
        file path, returns ``([], text)`` unchanged.
        """
        paths: List[str] = []
        rest = text
        while True:
            stripped = rest.lstrip()
            if not stripped:
                break
            # Quoted path at the start (Windows quotes paths containing spaces).
            m = _re.match(r'^"([^"]*)"|^\'([^\']*)\'', stripped)
            if m:
                cand = (m.group(1) or m.group(2) or "").strip()
                if cand and _os.path.isfile(cand):
                    paths.append(cand)
                    rest = stripped[m.end():]
                    continue
                break
            # Whole remaining text is one unquoted path (no trailing message).
            if _os.path.isfile(stripped):
                paths.append(stripped)
                rest = ""
                break
            # First whitespace-delimited token is an unquoted, space-free path.
            head, _sep, tail = stripped.partition(" ")
            if head and _os.path.isfile(head):
                paths.append(head)
                rest = tail
                continue
            break
        return paths, rest.strip()

    def _load_attachment(path: str) -> "Attachment":
        """Load a file as an Attachment, raising ValueError on failure."""
        path = _clean_path(path)
        if not _os.path.isfile(path):
            raise ValueError(f"Not a file: {path}")
        name = _os.path.basename(path)
        ext = _os.path.splitext(name)[1].lower()
        if ext in _IMAGE_EXTS:
            mime, _ = _mimetypes.guess_type(path)
            mime = mime or "image/png"
            with open(path, "rb") as f:
                b64 = _base64.b64encode(f.read()).decode("utf-8")
            return Attachment(path=path, name=name, kind="image",
                              content=b64, mime_type=mime)
        else:
            size = _os.path.getsize(path)
            if size > _TEXT_SIZE_LIMIT:
                raise ValueError(f"File too large ({size:,} bytes, limit 1 MB)")
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            return Attachment(path=path, name=name, kind="text", content=text)

    class InputSubmitted(Message):
        """Message sent when input is submitted."""
        def __init__(self, text: str, attachments: List["Attachment"] = None):
            super().__init__()
            self.text = text
            self.attachments: List[Attachment] = attachments or []

    class FilePasted(Message):
        """Posted by InputTextArea when a pasted string looks like a file path."""
        def __init__(self, path: str):
            super().__init__()
            self.path = path

    class AddFileRequested(Message):
        """Posted to ask the app to open the Add-file dialog."""
        pass

    class ChipRemoveButton(Static):
        """The X button inside an AttachmentChip."""

        class Pressed(Message):
            def __init__(self, attachment_id: int) -> None:
                super().__init__()
                self.attachment_id = attachment_id

        def __init__(self, attachment_id: int, **kwargs) -> None:
            super().__init__(" X ", **kwargs)
            self._aid = attachment_id

        def on_click(self, event: events.Click) -> None:
            event.stop()
            self.post_message(self.Pressed(self._aid))

    class AttachmentChip(Horizontal):
        """A labelled chip with an X button representing one attachment."""

        class Removed(Message):
            def __init__(self, attachment_id: int) -> None:
                super().__init__()
                self.attachment_id = attachment_id

        def __init__(self, attachment_id: int, name: str, kind: str, **kwargs):
            super().__init__(**kwargs)
            self._aid = attachment_id
            self._name = name
            self._kind = kind

        def compose(self) -> ComposeResult:
            icon = "🖼" if self._kind == "image" else "📄"
            yield Static(f" {icon} {self._name} ", classes="chip-label")
            yield ChipRemoveButton(self._aid, classes="chip-remove")

        def on_chip_remove_button_pressed(self,
                                          message: "ChipRemoveButton.Pressed") -> None:
            message.stop()
            self.post_message(self.Removed(message.attachment_id))

    class AttachmentsBar(VerticalScroll):
        """Vertically-stacked, scrollable list of AttachmentChip widgets sitting
        directly above the input line, so every attached file stays visible and
        removable however many are added."""

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self._attachments: Dict[int, Attachment] = {}
            self._next_id = 0
            self.display = False

        def add_attachment(self, att: Attachment) -> None:
            aid = self._next_id
            self._next_id += 1
            self._attachments[aid] = att
            chip = AttachmentChip(aid, att.name, att.kind,
                                  classes="attach-chip")
            self.mount(chip)
            self.display = True

        def on_attachment_chip_removed(self, message: "AttachmentChip.Removed") -> None:
            message.stop()
            self._attachments.pop(message.attachment_id, None)
            for chip in self.query(AttachmentChip):
                if chip._aid == message.attachment_id:
                    chip.remove()
                    break
            self.display = bool(self._attachments)
            # Clicking the chip's X moves focus off the input; give it back so
            # drag-and-drop keeps working after removing an attachment.
            try:
                self.app.query_one(MultiLineInput).input_area.focus()
            except Exception:
                pass

        def get_attachments(self) -> List[Attachment]:
            return list(self._attachments.values())

        def clear(self) -> None:
            self._attachments.clear()
            for chip in self.query(AttachmentChip):
                chip.remove()
            self.display = False

    class InputTextArea(TextArea):
        """Custom TextArea that handles Enter for submission and file drops.

        A filename is only turned into an attachment when it arrives at the
        *start* of the field — i.e. dropped onto an empty input. A filename
        typed (or dropped) *after* other text is kept as plain text, so a
        sentence like "modify the file report.py" leaves ``report.py`` as text
        for the model to read and edit. Drops are recognised both via bracketed
        paste (on_paste) and the keystroke fallback (on_text_area_changed)."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._drop_guard = False   # prevents re-entrant on_text_area_changed

        def _clear_field(self) -> None:
            """Clear the textarea without triggering file-drop detection."""
            self._drop_guard = True
            try:
                self.load_text("")
            finally:
                self._drop_guard = False

        def on_key(self, event: events.Key) -> None:
            if event.key == "enter":
                event.prevent_default()
                event.stop()
                text = self.text.strip()
                try:
                    bar = self.app.query_one(MultiLineInput, MultiLineInput).get_attachments()
                except Exception:
                    bar = []
                if text or bar:
                    self._clear_field()
                    self.post_message(InputSubmitted(text, bar))
            elif event.key in ("ctrl+j", "shift+enter", "ctrl+enter"):
                # Insert a newline. Ctrl+J (the LF character) is the reliable,
                # cross-terminal newline key — it survives the Windows console
                # driver, which collapses Shift+Enter to a plain Enter. Shift/
                # Ctrl+Enter are kept for terminals that support the enhanced
                # (kitty) keyboard protocol.
                event.prevent_default()
                event.stop()
                self.insert("\n")

        def on_paste(self, event: events.Paste) -> None:
            """Bracketed-paste / drag-drop hook.

            Only the *pasted* text is scanned for file paths — text the user
            has already typed is never inspected, so a filename written into a
            sentence is kept as-is rather than being pulled out and attached.
            A paste that carries no file path falls through to the default
            handler and is inserted as ordinary text."""
            if getattr(event, "_drop_handled", False):
                return
            paths, leftover = _extract_file_paths(event.text)
            if not paths:
                return  # plain text paste — let the default handler insert it
            event._drop_handled = True
            event.prevent_default()
            event.stop()
            # Insert any non-path text from the paste at the cursor, leaving
            # whatever the user had already typed untouched.
            if leftover:
                self.insert(leftover)
            for p in paths:
                self.post_message(FilePasted(p))

        def on_text_area_changed(self, event: "TextArea.Changed") -> None:
            """Fallback for terminals that deliver drag-and-drop as keystrokes
            (no bracketed paste). Only a path at the *start* of the field is
            treated as a drop — so this fires for a file dropped onto an empty
            input, but never pulls a filename out of text the user has typed."""
            if self._drop_guard:
                return
            paths, leftover = _extract_leading_file_paths(self.text)
            if not paths:
                return
            # Replace the field with just the leftover message text, without
            # re-triggering detection from the resulting Changed event.
            self._drop_guard = True
            try:
                self.load_text(leftover)
                try:
                    self.move_cursor(self.document.end)
                except Exception:
                    pass
            finally:
                self._drop_guard = False
            for p in paths:
                self.post_message(FilePasted(p))

    class StopButton(Static):
        """Bottom-left button that cancels the model while it is processing."""

        class Pressed(Message):
            pass

        def __init__(self, **kwargs) -> None:
            super().__init__("■ Stop", **kwargs)

        def on_click(self, event: events.Click) -> None:
            event.stop()
            self.post_message(self.Pressed())

    class MultiLineInput(Vertical):
        """Multi-line input widget with attachment bar and custom TextArea."""

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.input_area: Optional["InputTextArea"] = None
            self._attach_bar: Optional["AttachmentsBar"] = None

        def compose(self) -> ComposeResult:
            self._attach_bar = AttachmentsBar(id="attach-bar")
            yield self._attach_bar
            self.input_area = InputTextArea(id="input-area", language="text")
            yield self.input_area
            with Horizontal(id="input-bar"):
                yield StopButton(id="stop-btn")
                yield Static("Enter: send   Ctrl+J: new line   /help: commands",
                             id="input-hint")

        def on_mount(self) -> None:
            self.input_area.focus()

        def get_text(self) -> str:
            return self.input_area.text if self.input_area else ""

        def get_attachments(self) -> List[Attachment]:
            return self._attach_bar.get_attachments() if self._attach_bar else []

        def add_attachment(self, att: Attachment) -> None:
            if self._attach_bar:
                self._attach_bar.add_attachment(att)

        def clear(self) -> None:
            if self.input_area:
                self.input_area._clear_field()
            if self._attach_bar:
                self._attach_bar.clear()

        def on_file_pasted(self, message: FilePasted) -> None:
            message.stop()
            try:
                att = _load_attachment(message.path)
                self.add_attachment(att)
                self.app.notify(f"Attached: {att.name}", timeout=2)
            except Exception as e:
                self.app.notify(f"Cannot attach: {e}", severity="warning", timeout=3)
            finally:
                # Mounting the attachment chip can pull focus off the input.
                # Restore it so a subsequent drag-and-drop still lands here.
                if self.input_area:
                    self.input_area.focus()

    class MenuButton(Static):
        """A single-line clickable label used in the top bar."""

        class Pressed(Message):
            def __init__(self, action: str):
                super().__init__()
                self.action = action

        def __init__(self, label: str, action: str, **kwargs):
            super().__init__(label, **kwargs)
            self._action = action

        def on_click(self, event: events.Click) -> None:
            event.stop()
            self.post_message(self.Pressed(self._action))

    class TopBar(Horizontal):
        """Custom top bar: Menu | Commands | brand ... X."""

        def compose(self) -> ComposeResult:
            yield MenuButton("≡ Menu", "menu", id="menu-btn", classes="topbar-item")
            yield MenuButton("Commands", "command", id="cmd-btn", classes="topbar-item")
            yield Static(alexis_version.get_title(), id="brand")
            yield Static("", id="topbar-spacer")
            yield MenuButton("✕ ", "exit", id="exit-btn", classes="topbar-item")

    class DialogClose(Static):
        """The ✕ close control shown at the right of a dialog title bar."""

        class Pressed(Message):
            pass

        def __init__(self, **kwargs):
            super().__init__("✕ ", **kwargs)

        def on_click(self, event: events.Click) -> None:
            event.stop()
            self.post_message(self.Pressed())

    class DialogTitleBar(Horizontal):
        """A dialog header: title on the left, ✕ close button on the right."""

        def __init__(self, title: str, **kwargs):
            super().__init__(**kwargs)
            self._title = title

        def compose(self) -> ComposeResult:
            yield Static(self._title, classes="dialog-title-text")
            yield DialogClose(classes="dialog-close")

    class DialogScreen(ModalScreen):
        """Base modal: dims the background, closes on Esc or the ✕ button."""

        BINDINGS = [Binding("escape", "close_dialog", "Close")]

        def action_close_dialog(self) -> None:
            self.dismiss(None)

        def on_dialog_close_pressed(self, message: "DialogClose.Pressed") -> None:
            message.stop()
            self.dismiss(None)

    class CommandsPalette(CommandPalette):
        """The built-in command palette, dressed to match the menu dialog:
        a title bar (name left, ✕ right) and no search-magnifier icon."""

        def on_mount(self) -> None:
            # Drop the search magnifier.
            for icon in self.query(SearchIcon):
                icon.remove()
            # Add a menu-style title bar at the top of the palette box.
            try:
                container = self.query_one("#--container")
                input_row = self.query_one("#--input")
                container.mount(
                    DialogTitleBar("Commands", classes="dialog-title-bar"),
                    before=input_row,
                )
            except Exception:
                pass

        def on_dialog_close_pressed(self, message: "DialogClose.Pressed") -> None:
            message.stop()
            self.dismiss()

    class MenuScreen(DialogScreen):
        """Modal menu opened from the top bar."""

        def compose(self) -> ComposeResult:
            with Vertical(classes="themed-dialog"):
                yield DialogTitleBar("Menu", classes="dialog-title-bar")
                with Vertical(classes="dialog-body"):
                    yield Button("Add file / image", id="m-addfile", classes="menu-option")
                    yield Button("Load session", id="m-load", classes="menu-option")
                    yield Button("Save session", id="m-save", classes="menu-option")
                    yield Button("Help", id="m-help", classes="menu-option")
                    yield Button("Exit", id="m-exit", classes="menu-option")

        def on_button_pressed(self, event: "Button.Pressed") -> None:
            self.dismiss(event.button.id)

    class HelpScreen(DialogScreen):
        """Modal describing the available controls."""

        HELP_TEXT = (
            "[bold cyan]Controls[/bold cyan]\n\n"
            "[bold]Top bar[/bold]\n"
            "  ☰ Menu       Open this menu (Load / Save / Help / Exit)\n"
            "  ⌘ Command    Open the command palette\n"
            "  ✕            Exit the agent\n\n"
            "[bold]Menu[/bold]\n"
            "  Load session   Load a saved conversation from a JSON file\n"
            "  Save session   Write the current conversation to disk\n"
            "  Help           Show this screen\n"
            "  Exit           Quit the agent\n\n"
            "[bold]Keyboard[/bold]\n"
            "  Enter          Send your message\n"
            "  Ctrl+J         New line in the input box\n"
            "  Shift+Enter    New line (terminals with enhanced keys)\n"
            "  Ctrl+L         Clear the conversation\n"
            "  Ctrl+B         Show/hide the stats sidebar\n"
            "  Ctrl+P         Command palette\n"
            "  Ctrl+C         Quit\n\n"
            "[bold]Slash commands[/bold] (type in the input box)\n"
            "  /quit, /exit   Exit the agent\n"
            "  /stop          Stop the model while it is processing\n"
            "  /reset         Reset history and start a new session\n"
            "  /clear         Clear the conversation\n"
            "  /save          Save the current session\n"
            "  /load [path]   Load a session\n"
            "  /help          List all slash commands\n\n"
            "[dim]The ■ Stop button (bottom-left of the input) also stops "
            "processing.\nPress Esc or click Close to dismiss.[/dim]"
        )

        def compose(self) -> ComposeResult:
            with Vertical(classes="themed-dialog", id="help-dialog"):
                yield DialogTitleBar("Help", classes="dialog-title-bar")
                with Vertical(classes="dialog-body"):
                    yield Static(self.HELP_TEXT, id="help-text")
                    yield Button("Close", id="help-close", classes="menu-option")

        def on_button_pressed(self, event: "Button.Pressed") -> None:
            self.dismiss(None)

    class LoadScreen(DialogScreen):
        """Modal prompting for a session file path to load."""

        def __init__(self, default_path: str = "", **kwargs):
            super().__init__(**kwargs)
            self._default = default_path

        def compose(self) -> ComposeResult:
            with Vertical(classes="themed-dialog"):
                yield DialogTitleBar("Load Session", classes="dialog-title-bar")
                with Vertical(classes="dialog-body"):
                    yield Static("Path to session JSON:", classes="dialog-label")
                    yield Input(value=self._default, placeholder="session.json", id="load-path")
                    with Horizontal(classes="dialog-buttons"):
                        yield Button("Load", id="load-ok", classes="menu-option")
                        yield Button("Cancel", id="load-cancel", classes="menu-option")

        def on_mount(self) -> None:
            self.query_one("#load-path", Input).focus()

        def on_button_pressed(self, event: "Button.Pressed") -> None:
            if event.button.id == "load-ok":
                self.dismiss(self.query_one("#load-path", Input).value.strip())
            else:
                self.dismiss(None)

        def on_input_submitted(self, event: "Input.Submitted") -> None:
            self.dismiss(event.value.strip())

    class AddFileScreen(DialogScreen):
        """Modal prompting for a file or image path to attach."""

        def compose(self) -> ComposeResult:
            with Vertical(classes="themed-dialog"):
                yield DialogTitleBar("Add File / Image", classes="dialog-title-bar")
                with Vertical(classes="dialog-body"):
                    yield Static("Path to file (or drag it into the terminal):",
                                 classes="dialog-label")
                    yield Input(placeholder="path/to/file.txt or image.png",
                                id="addfile-path")
                    with Horizontal(classes="dialog-buttons"):
                        yield Button("Attach", id="addfile-ok", classes="menu-option")
                        yield Button("Cancel", id="addfile-cancel", classes="menu-option")

        def on_mount(self) -> None:
            self.query_one("#addfile-path", Input).focus()

        def on_button_pressed(self, event: "Button.Pressed") -> None:
            if event.button.id == "addfile-ok":
                self.dismiss(self.query_one("#addfile-path", Input).value.strip())
            else:
                self.dismiss(None)

        def on_input_submitted(self, event: "Input.Submitted") -> None:
            self.dismiss(event.value.strip())

    class ChatApp(App):
        """Main Textual application for chat."""

        # Below this terminal width the stats sidebar is hidden so the whole
        # row goes to the conversation — a narrow window is almost always the
        # user reading/typing chat, not watching token counters.
        STATS_MIN_WIDTH = 80

        # Panels are separated by background colour rather than borders.
        CSS = """
        Screen {
            layout: vertical;
            background: black;
        }

        /* ── Top bar ───────────────────────────────────────────── */
        #topbar {
            dock: top;
            height: 1;
            background: #14141e;
        }
        .topbar-item {
            width: auto;
            height: 1;
            padding: 0 2;
            color: #d0d0e0;
            background: #14141e;
        }
        .topbar-item:hover {
            background: #2a2a40;
            color: white;
            text-style: bold;
        }
        #brand {
            width: auto;
            height: 1;
            padding: 0 2;
            background: #14141e;
            color: #8080ff;
            text-style: bold;
        }
        #topbar-spacer {
            width: 1fr;
            height: 1;
            background: #14141e;
        }
        #exit-btn {
            width: 4;
            padding: 0;
            content-align: center middle;
            background: #14141e;
            color: #c03030;
            text-style: bold;
        }
        #exit-btn:hover {
            color: white;
            background: #802020;
        }

        /* ── Body layout ───────────────────────────────────────── */
        #main-container {
            height: 1fr;
        }

        #conversation {
            width: 1fr;
            height: 1fr;
            background: black;
            /* No padding at all — content runs to every edge. */
            padding: 0;
            overflow-y: auto;
            scrollbar-gutter: stable;
            scrollbar-size-vertical: 1;
        }

        #stats {
            width: 26;
            height: 1fr;
            background: #14141e;
            padding: 1 1;
            overflow-y: auto;
            scrollbar-gutter: stable;
            scrollbar-size-vertical: 1;
        }
        #stats-numbers {
            height: auto;
        }
        #context-map {
            height: auto;
            margin-top: 1;
        }
        #mcp-servers {
            height: auto;
        }
        #skills {
            height: auto;
        }

        #input {
            height: auto;
            background: #1a1a2e;
            padding: 0;
        }
        /* Editable area is its own box with a distinct background and a
           current-line highlight, so multi-line editing is easy to follow.
           Top edge only (inner border = lower-half-block ▄); no other borders. */
        #input TextArea {
            background: #1a1a2e;
            color: #e8e8f4;
            border: none;
            border-top: inner #1a1a2e;
            padding: 0 1;
            /* 1 row is consumed by the top border, so height 4 = 3 text lines. */
            height: 4;
        }
        #input TextArea:focus {
            border: none;
            border-top: inner #1a1a2e;
        }
        /* Subtle current-line tint, just enough to follow the cursor. */
        #input TextArea > .text-area--cursor-line {
            background: #242438;
        }
        #input TextArea > .text-area--gutter,
        #input TextArea > .text-area--cursor-gutter {
            background: #1a1a2e;
            color: #1a1a2e;
        }
        /* Bottom row of the input: Stop button (left) + hint (right). */
        #input-bar {
            height: 1;
            background: #1a1a2e;
        }
        #stop-btn {
            width: auto;
            height: 1;
            padding: 0 1;
            background: #2a1a1a;
            color: #ff6060;
            text-style: bold;
        }
        #stop-btn:hover {
            background: #802020;
            color: white;
        }
        #input-hint {
            width: 1fr;
            height: 1;
            background: #1a1a2e;
            color: #6a6a8a;
            text-align: right;
            padding: 0 1;
        }
        /* Attached files stack vertically just above the input line. The
           panel grows with the number of files up to a cap, then scrolls
           vertically — so the input never gets a horizontal scrollbar and
           every file stays visible and removable. */
        #attach-bar {
            height: auto;
            max-height: 6;
            background: #12122a;
            overflow-x: hidden;
            overflow-y: auto;
            scrollbar-size-vertical: 1;
            padding: 0 1;
        }
        .attach-chip {
            width: 100%;
            height: 1;
            margin-bottom: 0;
        }
        .chip-label {
            width: 1fr;
            height: 1;
            background: #2a2a50;
            color: #c0c0ff;
        }
        .chip-remove {
            width: auto;
            height: 1;
            background: #2a2a50;
            color: #ff6060;
        }
        .chip-remove:hover {
            background: #802020;
            color: white;
        }

        /* ── Message blocks: left bar + light title + black body ─ */
        .message-block {
            width: 1fr;
            height: auto;
            margin-bottom: 1;
            background: black;
        }
        .block-title-row {
            width: 1fr;
            height: 1;
        }
        .block-title {
            width: 1fr;
            height: 1;
            text-style: bold;
            padding: 0 1;
        }
        .block-copy {
            width: auto;
            height: 1;
        }
        .message-block .block-copy:hover {
            background: #3a3a3a;
            color: #ffd700;
            text-style: bold;
        }
        .block-body {
            width: 1fr;
            height: auto;
            background: black;
            color: #e0e0e0;
            padding: 0 1;
        }

        /* Left bar uses the `inner` border type, whose left edge is the
           right-half-block ▐ — a thin colour strip hugging the text. */
        .block--input        { border-left: inner #3fa33f; }
        .block--input .block-title-row { background: #3fa33f; }
        .block--input .block-title     { background: #3fa33f; color: black; }
        .block--input .block-copy      { background: #3fa33f; color: black; }
        .block--thinking     { border-left: inner #b060d0; }
        .block--thinking .block-title-row { background: #b060d0; }
        .block--thinking .block-title  { background: #b060d0; color: black; }
        .block--thinking .block-copy   { background: #b060d0; color: black; }
        .block--thinking .block-body   { color: #d8a8e8; }
        .block--output       { border-left: inner #30a0b0; }
        .block--output .block-title-row { background: #30a0b0; }
        .block--output .block-title    { background: #30a0b0; color: black; }
        .block--output .block-copy     { background: #30a0b0; color: black; }
        .block--toolcall     { border-left: inner #c0a030; }
        .block--toolcall .block-title-row { background: #c0a030; }
        .block--toolcall .block-title  { background: #c0a030; color: black; }
        .block--toolcall .block-copy   { background: #c0a030; color: black; }
        .block--toolcall .block-body   { height: 3; }
        .block--toolresult   { border-left: inner #3f7fc0; }
        .block--toolresult .block-title-row { background: #3f7fc0; }
        .block--toolresult .block-title{ background: #3f7fc0; color: black; }
        .block--toolresult .block-copy { background: #3f7fc0; color: black; }
        .block--toolresult .block-body { height: 3; }
        .block--tool         { border-left: inner #c0a030; }
        .block--tool .block-title-row { background: #c0a030; }
        .block--tool .block-title { background: #c0a030; color: black; }
        .block--tool .block-copy  { background: #c0a030; color: black; }
        .block--error        { border-left: inner #c03030; }
        .block--error .block-title-row { background: #c03030; }
        .block--error .block-title     { background: #c03030; color: white; }
        .block--error .block-copy      { background: #c03030; color: white; }
        .block--error .block-body      { color: #f0a0a0; }

        /* ── Modal dialogs — match the app's dark theme ────────────
           Every dialog is a compact, centered box: a title bar with the
           name on the left and a ✕ close button on the right, then a padded
           body. Colours come from the same palette as the rest of the UI
           (#1a1a2e panels, #2a2a50 highlights, #4040a0 / #8080ff accents). */
        MenuScreen, HelpScreen, LoadScreen, AddFileScreen {
            align: center middle;
            background: black 55%;
        }
        .themed-dialog {
            width: 56;
            max-width: 90%;
            height: auto;
            background: #1a1a2e;
            border: none;
            padding: 0;
        }
        #help-dialog { width: 72; }

        /* Title bar: name left, ✕ right. */
        .dialog-title-bar {
            width: 1fr;
            height: 1;
            background: #2a2a50;
        }
        .dialog-title-text {
            width: 1fr;
            height: 1;
            padding: 0 1;
            color: #c0c0ff;
            text-style: bold;
        }
        .dialog-close {
            width: 4;
            height: 1;
            content-align: center middle;
            background: #2a2a50;
            color: #ff8080;
        }
        .dialog-close:hover {
            background: #802020;
            color: white;
            text-style: bold;
        }

        .dialog-body { height: auto; padding: 1 2; }
        .dialog-buttons { height: auto; }
        .dialog-label { color: #d0d0e0; margin-bottom: 1; }
        #help-text { height: auto; margin-bottom: 1; color: #d0d0e0; }

        /* Buttons read like list rows / actions in the dark theme. */
        .menu-option {
            width: 1fr;
            height: 1;
            margin-top: 1;
            border: none;
            background: #1a1a2e;
            color: #d0d0e0;
        }
        .dialog-buttons .menu-option { margin-right: 1; }
        .menu-option:hover {
            background: #2a2a50;
            color: white;
        }
        .menu-option:focus {
            background: #4040a0;
            color: white;
            text-style: bold;
        }

        /* Input fields in dialogs, consistent with the main input box. */
        .themed-dialog Input {
            background: #0e0e1a;
            color: #e8e8f4;
            border: tall #2a2a50;
            padding: 0 1;
        }
        .themed-dialog Input:focus {
            border: tall #4040a0;
            background: #0e0e1a;
            color: #e8e8f4;
        }
        /* Blank line between the input and the buttons. */
        #addfile-path, #load-path { margin-bottom: 1; }

        /* ── Command palette — styled like the menu dialog ─────────── */
        CommandPalette > Vertical {
            background: #1a1a2e;
            border: none;
            width: 64;
            max-width: 90%;
            margin-top: 4;
        }
        /* The palette's container is visibility:hidden with only select
           children shown; opt the injected title bar back in. */
        CommandPalette .dialog-title-bar { visibility: visible; }
        /* Drop the search magnifier; keep the input flush like the menu. */
        CommandPalette SearchIcon { display: none; }
        CommandPalette #--input {
            height: auto;
            border: none;
            padding: 0;
        }
        CommandPalette #--input Input {
            background: #0e0e1a;
            color: #e8e8f4;
        }
        CommandPalette #--results { background: #1a1a2e; }
        CommandPalette OptionList {
            background: #1a1a2e;
            color: #d0d0e0;
        }
        CommandPalette OptionList > .option-list--option-highlighted {
            background: #4040a0;
            color: white;
            text-style: bold;
        }
        CommandPalette > .command-palette--highlight {
            text-style: bold;
            color: #8080ff;
        }
        """

        BINDINGS = [
            Binding("ctrl+c", "quit", "Quit", show=False),
            Binding("ctrl+l", "clear_history", "Clear", show=False),
            Binding("ctrl+b", "toggle_stats", "Toggle sidebar", show=False),
        ]

        def __init__(self, context_limit=None, run_callback=None, messages=None,
                     save_state=None, session_path=None, thinking_enabled=False,
                     mcp_servers=None, skills_count=None, reset_session=None,
                     join_tool_processing=True):
            super().__init__()
            self.context_limit = context_limit
            # When on, a tool call and its result are committed as one TOOL block
            # (title-only) instead of separate TOOL CALL / TOOL RESULT blocks.
            self.join_tool_processing = join_tool_processing
            self.run_callback = run_callback
            self.messages = messages if messages is not None else []
            self.save_state = save_state
            self.session_path = session_path
            self.thinking_enabled = thinking_enabled
            self.mcp_servers = mcp_servers or []
            # Number of discovered skills, or None when skills are disabled
            # (--no-agent-use-skills) — the SKILLS panel is hidden in that case.
            self.skills_count = skills_count
            # Backend hook to start a fresh session (clears history, rotates the
            # session file). Optional — falls back to a local clear if absent.
            self.reset_session = reset_session
            # Manual sidebar override: None = follow terminal width, True/False =
            # user forced it shown/hidden via Ctrl+B (sticks past resizes).
            self._stats_override: Optional[bool] = None
            # The worker running the current turn, so /stop can cancel it.
            self._active_worker = None
            # Set when the user presses Stop; plumbed to the backend so it can
            # close the server connection (llama.cpp aborts on disconnect).
            self._cancel_event = None

        def compose(self) -> ComposeResult:
            """Compose the UI."""
            yield TopBar(id="topbar")
            with Horizontal(id="main-container"):
                yield ConversationView(id="conversation")
                with VerticalScroll(id="stats"):
                    if self.mcp_servers:
                        yield MCPServersPanel(self.mcp_servers, id="mcp-servers")
                    if self.skills_count is not None:
                        yield SkillsPanel(self.skills_count, id="skills")
                    yield StatisticsPanel(id="stats-numbers")
                    yield ContextMap(id="context-map")
            yield MultiLineInput(id="input")

        def on_mount(self) -> None:
            """Initialize the app."""
            self.title = f"{alexis_version.get_title()} CLI - Interactive Chat"
            # Build the slash-command table before any input can be submitted.
            self._build_slash_commands()
            # Seed config (context window + thinking) so stats show from the start.
            self.update_stats({
                "context_limit": self.context_limit,
                "thinking_enabled": self.thinking_enabled,
            })
            # Match the sidebar to the current terminal width right away.
            self._update_stats_visibility(self.size.width)

        def on_resize(self, event: events.Resize) -> None:
            """Show/hide the stats sidebar as the terminal is resized."""
            self._update_stats_visibility(event.size.width)

        def _update_stats_visibility(self, width: int) -> None:
            """Hide the stats sidebar on a narrow terminal so the conversation
            gets the full width; show it again once there is room. A manual
            Ctrl+B override, if set, wins over the width-based default."""
            try:
                stats = self.query_one("#stats")
            except Exception:
                return
            if self._stats_override is not None:
                stats.display = self._stats_override
            else:
                stats.display = width >= self.STATS_MIN_WIDTH

        def action_toggle_stats(self) -> None:
            """Toggle the stats sidebar (Ctrl+B). Sets a manual override that
            persists across resizes until toggled back."""
            try:
                stats = self.query_one("#stats")
            except Exception:
                return
            self._stats_override = not stats.display
            stats.display = self._stats_override
            self.notify(
                "Sidebar shown" if self._stats_override else "Sidebar hidden",
                timeout=1.5,
            )

        # ── Slash commands ───────────────────────────────────────
        def _build_slash_commands(self) -> None:
            """Register the slash commands handled locally in the input box.

            Each command maps one or more names to a handler taking the
            argument string (the text after the command name). To add a custom
            command, append another `register(...)` call below — the name(s),
            handler, and a help line are all that's needed; it is then usable as
            `/name` from the input and listed by `/help`.
            """
            self._commands: Dict[str, Callable[[str], None]] = {}
            self._command_help: List[tuple] = []

            def register(names, handler, help_text):
                for n in names:
                    self._commands[n.lower()] = handler
                shown = ", ".join("/" + n for n in names)
                self._command_help.append((shown, help_text))

            register(["quit", "exit", "q"], lambda arg: self.exit(),
                     "Exit the agent")
            register(["clear", "cls"],
                     lambda arg: self.run_worker(self.action_clear_history(),
                                                 exclusive=False),
                     "Clear the conversation")
            register(["stop"], lambda arg: self._stop_processing(),
                     "Stop the model while it is processing")
            register(["reset"], lambda arg: self._reset_session(),
                     "Reset the conversation and start a new session")
            register(["save"], lambda arg: self._do_save(),
                     "Save the current session")
            register(["load"],
                     lambda arg: (self._on_load_result(arg) if arg else
                                  self.push_screen(LoadScreen(self.session_path or ""),
                                                   self._on_load_result)),
                     "Load a session (optionally pass a path)")
            register(["help", "?", "commands"], lambda arg: self._show_commands_help(),
                     "Show available slash commands")

        def _show_commands_help(self) -> None:
            """Notify with the list of registered slash commands."""
            lines = [f"{shown}  —  {desc}" for shown, desc in self._command_help]
            self.notify("Slash commands:\n" + "\n".join(lines),
                        title="Commands", timeout=8)

        def _handle_slash_command(self, text: str) -> bool:
            """If `text` is a slash command, run it and return True so the
            caller skips sending it to the model. A leading '/' with an unknown
            name is still consumed (with a warning) rather than sent to the LLM.
            """
            stripped = text.strip()
            if not stripped.startswith("/"):
                return False
            parts = stripped[1:].split(maxsplit=1)
            if not parts or not parts[0]:
                return False
            name = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""
            handler = self._commands.get(name)
            if handler is None:
                self.notify(f"Unknown command: /{name} (try /help)",
                            severity="warning", timeout=3)
                return True
            try:
                handler(arg)
            except Exception as e:
                self.notify(f"Command /{name} failed: {e}",
                            severity="error", timeout=4)
            return True

        # ── Top bar / menu handling ──────────────────────────────
        def action_command_palette(self) -> None:
            """Open our menu-styled command palette instead of the default."""
            if self.use_command_palette and not CommandsPalette.is_open(self):
                self.push_screen(CommandsPalette(id="--command-palette"))

        def on_menu_button_pressed(self, message: "MenuButton.Pressed") -> None:
            """Handle clicks on the top-bar items."""
            if message.action == "exit":
                self.exit()
            elif message.action == "command":
                self.action_command_palette()
            elif message.action == "menu":
                self.push_screen(MenuScreen(), self._on_menu_result)

        def _on_menu_result(self, result: Optional[str]) -> None:
            if result == "m-exit":
                self.exit()
            elif result == "m-save":
                self._do_save()
            elif result == "m-help":
                self.push_screen(HelpScreen())
            elif result == "m-load":
                self.push_screen(LoadScreen(self.session_path or ""), self._on_load_result)
            elif result == "m-addfile":
                self.push_screen(AddFileScreen(), self._on_addfile_result)

        def _on_addfile_result(self, path: Optional[str]) -> None:
            if path:
                self._attach_file(path)

        def _attach_file(self, path: str) -> None:
            try:
                att = _load_attachment(path)
                self.query_one(MultiLineInput, MultiLineInput).add_attachment(att)
                self.notify(f"Attached: {att.name}", timeout=2)
            except Exception as e:
                self.notify(f"Cannot attach: {e}", severity="warning", timeout=3)

        def on_paste(self, event: events.Paste) -> None:
            """App-level catch for file drag-and-drop.

            Terminals deliver a dropped file as a bracketed paste of its path.
            The paste is forwarded to whatever widget is focused — and while
            dragging, the pointer may have moved focus onto another widget —
            then bubbles up here. Handling it at the App level means the drop
            is recognised no matter what currently holds focus. If the input
            area already handled it (it stops the event when focused), this is
            never reached.
            """
            if getattr(event, "_drop_handled", False):
                return
            paths, leftover = _extract_file_paths(event.text)
            if not paths:
                return
            event._drop_handled = True
            event.stop()
            for p in paths:
                self._attach_file(p)
            # Keep any accompanying message text and return focus to the input.
            try:
                mli = self.query_one(MultiLineInput, MultiLineInput)
                if mli.input_area is not None:
                    if leftover:
                        mli.input_area.insert(leftover)
                    mli.input_area.focus()
            except Exception:
                pass

        def _do_save(self) -> None:
            if self.save_state:
                try:
                    self.save_state()
                    target = self.session_path or "session file"
                    self.notify(f"Session saved to {target}", severity="information")
                except Exception as e:
                    self.notify(f"Save failed: {e}", severity="error")
            else:
                self.notify("No session file configured (use --session).", severity="warning")

        def _on_load_result(self, path: Optional[str]) -> None:
            if path:
                self.run_worker(self._load_session(path), exclusive=False)

        async def _load_session(self, path: str) -> None:
            """Load a conversation JSON and rebuild the transcript."""
            import json
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, list):
                    raise ValueError("session file is not a message list")
            except Exception as e:
                self.notify(f"Load failed: {e}", severity="error")
                return

            # Replace shared message list in place so the backend sees it too.
            self.messages.clear()
            self.messages.extend(data)
            self.session_path = path
            await self._rebuild_transcript()
            self.notify(f"Loaded {len(data)} messages from {path}", severity="information")

        async def _rebuild_transcript(self) -> None:
            """Render committed blocks from the current self.messages."""
            conv = self.query_one(ConversationView, ConversationView)
            await conv.clear_messages()
            # Map tool_call_id -> tool name so tool results can show the name in
            # their header, matching the live streaming display.
            tool_names: Dict[str, str] = {}
            # When joining, pair each call with its result (by id) so the two are
            # rendered as one TOOL block; pre-scan results keyed by call id.
            results_by_id: Dict[str, str] = {}
            if self.join_tool_processing:
                for msg in self.messages:
                    if msg.get("role") == "tool" and msg.get("tool_call_id"):
                        results_by_id[msg["tool_call_id"]] = _message_text(
                            msg.get("content", ""))
            for msg in self.messages:
                role = msg.get("role", "")
                content = _message_text(msg.get("content", ""))
                if role == "user":
                    if content:
                        await conv.add_block("input", content)
                elif role == "assistant":
                    if msg.get("reasoning_content"):
                        await conv.add_block("thinking", str(msg["reasoning_content"]))
                    if content:
                        await conv.add_block("output", content)
                    for tc in msg.get("tool_calls", []) or []:
                        fn = tc.get("function", {})
                        name = fn.get("name", "tool")
                        if tc.get("id"):
                            tool_names[tc["id"]] = name
                        args = fn.get("arguments", "") or ""
                        label = f"{name}({args})" if args else name
                        if self.join_tool_processing:
                            result = results_by_id.get(tc.get("id"), "")
                            combined = f"{label}\n{result}" if result else label
                            await conv.add_block(
                                "tool", combined, tool_name=name,
                                send_bytes=len(label.encode("utf-8")),
                                recv_bytes=len(result.encode("utf-8")),
                            )
                        else:
                            await conv.add_block("tool_call", label)
                elif role == "tool":
                    # In join mode the result is folded into the TOOL block above.
                    if content and not self.join_tool_processing:
                        name = tool_names.get(msg.get("tool_call_id"))
                        await conv.add_block("tool_result", content, tool_name=name)

        async def action_quit(self) -> None:
            """Quit the application."""
            self.exit()

        async def action_clear_history(self) -> None:
            """Clear conversation history."""
            conv = self.query_one(ConversationView, ConversationView)
            await conv.clear_messages()

        # ── Stop / reset ─────────────────────────────────────────
        def _is_processing(self) -> bool:
            """True while a turn is actively running."""
            w = self._active_worker
            return w is not None and w.state in (WorkerState.PENDING, WorkerState.RUNNING)

        def _stop_processing(self) -> None:
            """Stop the in-flight turn, if any. Setting the cancel event closes
            the server connection so the model (e.g. llama.cpp) aborts
            generation just like its web UI; cancelling the worker then tears
            down the local async side."""
            if not self._is_processing():
                self.notify("Nothing is processing right now.", timeout=2)
                return
            if self._cancel_event is not None:
                self._cancel_event.set()
            self._active_worker.cancel()
            self._active_worker = None
            try:
                self.query_one(ConversationView, ConversationView).clear_streaming()
            except Exception:
                pass
            self.notify("Stopped processing.", severity="warning", timeout=2)

        def on_stop_button_pressed(self, message: "StopButton.Pressed") -> None:
            message.stop()
            self._stop_processing()

        def _reset_session(self) -> None:
            """Start a brand-new session: stop any running turn, clear history,
            and rotate the session file via the backend hook."""
            if self._is_processing():
                if self._cancel_event is not None:
                    self._cancel_event.set()
                self._active_worker.cancel()
            self._active_worker = None
            self.run_worker(self._do_reset(), exclusive=False)

        async def _do_reset(self) -> None:
            new_path = None
            if self.reset_session:
                try:
                    new_path = self.reset_session()
                except Exception as e:
                    self.notify(f"Reset failed: {e}", severity="error")
                    return
            else:
                # No backend hook: clear locally, preserving any system prompt.
                system_msgs = [m for m in self.messages if m.get("role") == "system"]
                self.messages.clear()
                self.messages.extend(system_msgs)
            if new_path:
                self.session_path = new_path
            # Rebuild the (now empty) transcript and reset the live counters.
            conv = self.query_one(ConversationView, ConversationView)
            conv.clear_streaming()
            await self._rebuild_transcript()
            self.update_stats({
                "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                "tokens_per_second": 0.0, "mcp_calls": 0,
                "history_tokens": 0, "tools_tokens": 0, "new_tokens": 0,
                "thinking_tokens": 0, "answer_tokens": 0,
            })
            target = self.session_path or "in-memory session"
            self.notify(f"New session started ({target}).",
                        severity="information", timeout=3)

        def update_stats(self, new_stats: Dict[str, Any]) -> None:
            """Update statistics panel and context map."""
            self.query_one(StatisticsPanel, StatisticsPanel).update_stats(new_stats)
            self.query_one(ContextMap, ContextMap).update_stats(new_stats)

        def on_input_submitted(self, message: "InputSubmitted") -> None:
            """Handle input submission — may carry text + attachments."""
            text = message.text
            attachments = message.attachments

            # Slash commands (e.g. /quit, /exit) are handled locally and never
            # sent to the model. They take precedence over any attachments.
            if self._handle_slash_command(text):
                try:
                    self.query_one(MultiLineInput, MultiLineInput).clear()
                except Exception:
                    pass
                return

            # `InputSubmitted` already carries the bar's attachments (see
            # InputTextArea.on_key). Re-read the bar only as a fallback and
            # de-duplicate by identity, otherwise every attachment would be
            # counted twice (and a deleted one could reappear).
            try:
                bar_atts = self.query_one(MultiLineInput, MultiLineInput).get_attachments()
                seen = {id(a) for a in attachments}
                attachments = list(attachments) + [a for a in bar_atts if id(a) not in seen]
            except Exception:
                pass

            if not text and not attachments:
                return

            # Build message content blocks.
            content_blocks: List[Dict[str, Any]] = []
            if text:
                content_blocks.append({"type": "text", "text": text})
            for att in attachments:
                if att.kind == "text":
                    content_blocks.append(
                        {"type": "text",
                         "text": f"[Attached file: {att.name}]\n{att.content}"}
                    )
                elif att.kind == "image":
                    content_blocks.append(
                        {"type": "image_url",
                         "image_url": {"url": f"data:{att.mime_type};base64,{att.content}"}}
                    )

            self.messages.append({"role": "user", "content": content_blocks})

            # Display label for the conversation block.
            display_parts = []
            if text:
                display_parts.append(text)
            for att in attachments:
                icon = "🖼" if att.kind == "image" else "📄"
                display_parts.append(f"{icon} {att.name}")
            display_text = "\n".join(display_parts)

            # Clear attachments bar now that they're committed.
            try:
                self.query_one(MultiLineInput, MultiLineInput)._attach_bar.clear()
            except Exception:
                pass

            # Fresh cancel signal for this turn; Stop sets it to abort the
            # server-side generation as well as the local worker.
            self._cancel_event = threading.Event()
            self._active_worker = self.run_worker(
                self._process_input_async(display_text, self._cancel_event),
                exclusive=False)

        async def _process_input_async(self, user_text: str, cancel_event=None) -> None:
            """Process input through the LLM, building the transcript from the
            streaming queue so thinking, tool calls and tool results are all
            kept (they are committed as permanent blocks as they arrive)."""
            conv = self.query_one(ConversationView, ConversationView)
            stats_panel = self.query_one(StatisticsPanel, StatisticsPanel)
            await conv.add_block("input", user_text)

            try:
                if not self.run_callback:
                    return

                queue: asyncio.Queue = asyncio.Queue()

                async def stream_from_queue():
                    """Consume the queue and commit blocks as sections complete."""
                    current_type: Optional[str] = None  # "thinking" or "output"
                    buffer = ""
                    # When join_tool_processing is on, a tool_call is held here
                    # until its tool_result arrives, then both are committed as a
                    # single TOOL block. dict: {name, label, send_bytes}.
                    pending_tool: Optional[dict] = None

                    async def commit_text():
                        """Commit any buffered thinking/output as a permanent block
                        WITHOUT touching the live indicator, so a 'tool running'
                        indicator can survive a text→tool handoff and stay visible."""
                        nonlocal current_type, buffer
                        if current_type and buffer.strip():
                            await conv.add_block(current_type, buffer)
                        current_type = None
                        buffer = ""

                    async def flush():
                        await commit_text()
                        conv.clear_streaming()

                    while True:
                        try:
                            item = await asyncio.wait_for(queue.get(), timeout=0.2)
                        except asyncio.TimeoutError:
                            continue
                        if item is None:
                            break

                        msg_type = item.get("type", "")
                        data = item.get("data", "") or item.get("content", "")

                        if msg_type == "thinking":
                            if current_type != "thinking":
                                await flush()
                                current_type = "thinking"
                            buffer += str(data)
                            conv.update_streaming("thinking", buffer)
                            if not stats_panel.stats.get("thinking_enabled"):
                                self.update_stats({"thinking_enabled": True})
                        elif msg_type == "content":
                            if current_type != "output":
                                await flush()
                                current_type = "output"
                            buffer += str(data)
                            conv.update_streaming("output", buffer)
                        elif msg_type == "tool_call_building":
                            # Model is still streaming the call's arguments — switch
                            # the live indicator to TOOL CALL so it doesn't look
                            # stuck on the assistant text. Commit any pending text
                            # first; the final "tool_call" event commits the block.
                            if current_type is not None:
                                await commit_text()
                            name = item.get("name", "") or ""
                            args = str(item.get("arguments", "") or "")
                            label = f"{name}({args})" if name else "(building…)"
                            conv.update_streaming("tool_call", label)
                        elif msg_type == "tool_call":
                            # Commit any preceding text, but KEEP a live indicator:
                            # the tool is now executing and must stay visible (with
                            # an animated spinner) until its result arrives — rather
                            # than collapsing to nothing while the tool runs.
                            await commit_text()
                            name = item.get("name", "Tool")
                            args = str(item.get("arguments", "") or "")
                            label = f"{name}({args})" if args else name
                            if self.join_tool_processing:
                                # Hold the call; the result event commits the
                                # joined TOOL block.
                                pending_tool = {
                                    "name": name,
                                    "label": label,
                                    "send_bytes": len(label.encode("utf-8")),
                                }
                            else:
                                await conv.add_block("tool_call", label)
                            # Live "running" view, kept on screen until tool_result
                            # commits the permanent block.
                            conv.update_streaming("tool_exec", label)
                            self.update_stats(
                                {"mcp_calls": stats_panel.stats.get("mcp_calls", 0) + 1}
                            )
                        elif msg_type == "tool_result":
                            await commit_text()
                            name = item.get("name", "Tool")
                            # Prefer the full result (for the copy button); the
                            # block truncates it for display on its own. The tool
                            # name goes in the header, not the body.
                            body = str(item.get("full", data)).strip()
                            if self.join_tool_processing and pending_tool:
                                # Joined TOOL block: title-only, copy yields the
                                # call text + a newline + the result data.
                                combined = f"{pending_tool['label']}\n{body}"
                                await conv.add_block(
                                    "tool", combined,
                                    tool_name=pending_tool["name"],
                                    send_bytes=pending_tool["send_bytes"],
                                    recv_bytes=len(body.encode("utf-8")),
                                )
                                pending_tool = None
                            else:
                                await conv.add_block("tool_result", body,
                                                     tool_name=name)
                            # Tool finished — remove the live "running" indicator.
                            conv.clear_streaming()
                        elif msg_type == "usage":
                            # Real token stats reported by the backend each turn.
                            self.update_stats({
                                k: item[k] for k in (
                                    "prompt_tokens", "completion_tokens", "total_tokens",
                                    "tokens_per_second", "context_limit", "lifetime_tokens",
                                    "history_tokens", "tools_tokens", "new_tokens",
                                    "thinking_tokens", "answer_tokens",
                                ) if k in item and item[k] is not None
                            })
                        elif msg_type == "error":
                            await flush()
                            await conv.add_block("error", str(item.get("error", data)))

                    await flush()
                    # A call with no result (e.g. aborted turn) still gets its own
                    # TOOL block so the call isn't lost.
                    if pending_tool:
                        await conv.add_block(
                            "tool", pending_tool["label"],
                            tool_name=pending_tool["name"],
                            send_bytes=pending_tool["send_bytes"],
                            recv_bytes=0,
                        )
                        pending_tool = None

                # Run the queue consumer and the LLM turn concurrently.
                stream_task = asyncio.create_task(stream_from_queue())
                try:
                    await self.run_callback(queue=queue, cancel_event=cancel_event)
                finally:
                    await queue.put(None)  # Signal end of streaming
                    await stream_task
            except asyncio.CancelledError:
                # /stop (or reset) cancelled the turn — leave the transcript as
                # it is and let the cancellation propagate so the worker ends.
                conv.clear_streaming()
                raise
            except Exception as e:
                import traceback
                conv.clear_streaming()
                await conv.add_block("error", f"{e}\n{traceback.format_exc()}")
            finally:
                self._active_worker = None


class TextualInteractiveUIDriver(UIDriver):
    """
    Advanced interactive UI driver using Textual for rich TUI experience.

    Features:
    - Multi-pane layout (conversation, statistics, input)
    - Mouse support
    - Copy/paste functionality
    - Multi-line input box
    - Token statistics tracking
    - Works on Windows and Linux
    """

    def get_name(self) -> str:
        return "textual"

    def get_description(self) -> str:
        if TEXTUAL_AVAILABLE:
            return "Advanced interactive TUI with mouse support, multi-pane layout (textual library)"
        return "Textual UI (textual library not installed - will use fallback)"

    def validate_args(self, args) -> bool:
        """Always available - falls back to simple mode if needed."""
        return True

    async def run(
        self,
        run_single_turn: Callable,
        messages: List[Dict[str, Any]],
        save_state: Callable,
        user_content: List[Dict[str, Any]] = None,
        **kwargs
    ) -> None:
        """
        Run the advanced textual interactive mode.
        Falls back to simple mode if textual is not available.
        """
        if not TEXTUAL_AVAILABLE:
            # Textual not available - inform user and fall back
            print("\n\033[91m[!] ERROR: Textual library is required for --ui-driver textual\033[0m", file=sys.stderr)
            print("\033[93m    Install it with: pip install textual\033[0m", file=sys.stderr)
            print("\033[93m    Or use: --ui-driver interactive (falls back gracefully)\033[0m", file=sys.stderr)
            print("\033[93m    Falling back to simple interactive mode for now.\033[0m", file=sys.stderr)
            # Use simple fallback
            ui = SimpleFallbackUI()
            await ui.run(
                run_single_turn=run_single_turn,
                messages=messages,
                save_state=save_state,
                user_content=user_content,
                **kwargs
            )
            return

        # Try to run the full textual app
        try:

            # Stats (tokens, speed, context map) are pushed live onto the stream
            # queue by the backend and applied in the UI, so run_single_turn is
            # passed through directly.
            context_limit = kwargs.get("context_limit")
            app = ChatApp(
                context_limit=context_limit,
                run_callback=run_single_turn,
                messages=messages,
                save_state=save_state,
                session_path=kwargs.get("session_path"),
                thinking_enabled=bool(kwargs.get("reasoning_effort")),
                mcp_servers=kwargs.get("mcp_servers", []),
                skills_count=kwargs.get("skills_count"),
                reset_session=kwargs.get("reset_session"),
                join_tool_processing=kwargs.get("join_tool_processing", True),
            )
            await app.run_async()
            save_state()

        except Exception as e:
            # Fallback to simple mode if textual app fails
            print(f"\n\033[93m[!] Textual UI error: {e}. Falling back to simple mode.\033[0m", file=sys.stderr)
            ui = SimpleFallbackUI()
            await ui.run(
                run_single_turn=run_single_turn,
                messages=messages,
                save_state=save_state,
                user_content=user_content,
                **kwargs
            )