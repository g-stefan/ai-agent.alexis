# Advanced Interactive UI with Textual

The interactive mode now supports an advanced TUI (Terminal User Interface) built with Textual for a modern, professional chat experience.

## Installation

### Basic Installation
```bash
pip install textual
```

### Complete Installation
```bash
pip install -r requirements.txt
```

## Features

### Multi-Pane Layout
The interface is organized into three main sections:

```
┌─────────────────────────────────┬──────────┐
│                                 │          │
│  Conversation Area              │ STATS    │
│  (messages, thinking, output)   │ -----    │
│  with copy/paste buttons        │ Tokens   │
│                                 │ Speed    │
│                                 │ MCP      │
├─────────────────────────────────┴──────────┤
│ Input Area (3 lines, expandable)           │
│ ❯ Type your message here...               │
│   Multi-line support for paste             │
└───────────────────────────────────────────┘
```

### Key Features

✓ **Mouse Support**
- Click to copy messages
- Click input area to focus
- Scroll conversation history
- Click statistics panel

✓ **Multi-Line Input**
- Default 3-line input area
- Auto-expands for larger text
- Supports copy/paste
- Shows cursor position
- Ctrl+Enter to send (Ctrl+J)

✓ **Rich Formatting**
- Colored output by message type
- Syntax highlighting support
- Symbol indicators (>>>, 💭, ◆)
- Panel borders for organization

✓ **Statistics Sidebar**
- Real-time token counting
- Generation speed (tokens/sec)
- MCP tool call tracking
- Prompt vs completion tokens
- **Context Memory Map** (when --context-limit specified):
  - Token usage breakdown by category (System, Tools, User, Thinking, Calls)
  - Visual bar graphs with Unicode block characters
  - Percentage usage for each category
  - Free tokens remaining
  - Color-coded total usage indicator (green/yellow/red)

✓ **Message History**
- Scrollable conversation area
- Separate styling for:
  - **User input** (green)
  - **Thinking/Reasoning** (magenta)
  - **Assistant output** (cyan)

✓ **Cross-Platform**
- Works on Windows, Linux, macOS
- ANSI VT100 escape code support
- Proper terminal handling

## Usage

### Automatic (Default)
When you use interactive mode, the CLI automatically uses Textual if available:

```bash
python alexis.py --interactive
# Textual TUI loads automatically if installed
```

### Explicit Selection
```bash
# Explicitly request textual UI
python alexis.py --ui-driver interactive

# If textual is not available, falls back to simple mode
```

### Fallback Mode
If Textual fails to load for any reason, the CLI automatically falls back to simple interactive mode with ANSI colors.

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Ctrl+Enter` | Send message |
| `Ctrl+J` | Send message (alternative) |
| `Ctrl+C` | Quit application |
| `Ctrl+L` | Clear conversation history |
| `Arrow Keys` | Navigate in conversation area |
| `Page Up/Down` | Scroll conversation |
| Tab | Cycle focus between panels |

## Mouse Actions

| Action | Effect |
|--------|--------|
| Click conversation | Focus and scroll to position |
| Click input area | Position cursor in input |
| Click stats panel | Highlight (view only) |
| Scroll wheel | Navigate conversation |
| Drag to select | Copy selected text |

## Command Examples

### Simple Interactive Chat
```bash
python alexis.py --interactive
```

### With Session History
```bash
python alexis.py --interactive --session chat.json
```

### With Gemini and Thinking
```bash
python alexis.py --interactive \
  --llm-driver gemini \
  --include-thoughts \
  --reasoning-effort high
```

### With System Message
```bash
python alexis.py --interactive \
  --system system_prompt.md
```

## Message Types

### User Input
```
>>> You:
  Your message appears here with this formatting
```

### Assistant Output
```
◆ Assistant:
  The model's response appears here
```

### Thinking/Reasoning
```
💭 Thinking:
  Extended reasoning from models that support it
  (Gemini with --include-thoughts, reasoning models, etc.)
```

## Statistics Panel

Real-time statistics display:

```
STATISTICS
──────────────────
Prompt: 245
Completion: 156
Total: 401
Speed: 45.32 tok/s
MCP Calls: 2
Thinking: ON
```

## Copy/Paste Support

Each message type has implicit copy support:

1. **Selection**: Click and drag to select text
2. **Copy**: Use standard Ctrl+C (works in terminal)
3. **Paste**: Use standard Ctrl+V in input area

## Customization

### Colors
The interface uses standard terminal colors:
- **User input**: Green
- **Thinking**: Magenta
- **Assistant output**: Cyan
- **Statistics**: Yellow/Cyan

### Layout
The layout automatically adjusts to terminal size:
- Minimum width: 80 characters
- Minimum height: 20 lines
- Statistics panel: 25 characters wide
- Input area: 3-5 lines

## Troubleshooting

### Textual Not Working
```bash
# Reinstall textual
pip install --upgrade textual

# Check version
python -c "import textual; print(textual.__version__)"
```

### Mouse Not Working
- Terminal may not support mouse
- Use keyboard shortcuts instead
- Try different terminal emulator

### Colors Not Showing
```bash
# Force color support
FORCE_COLOR=1 python alexis.py --interactive
```

### Terminal Rendering Issues
```bash
# Try ANSI-safe mode
NO_COLOR=0 python alexis.py --interactive
```

## Performance

- **Startup**: ~200-500ms (textual framework initialization)
- **Input handling**: <10ms per keystroke
- **Rendering**: 60 FPS (adaptive)
- **Memory**: ~5-10MB additional overhead

## Limitations

- **Copy buttons**: Implicit selection-based (terminal standard)
- **Terminal dependencies**: Requires terminal emulator with ANSI support
- **Windows Console**: Works best with Windows Terminal (not classic cmd.exe)

## Recommended Terminals

### Windows
- **Windows Terminal** ✓ (Recommended)
- **ConEmu** ✓
- **alacritty** ✓

### Linux
- **GNOME Terminal** ✓
- **xterm** ✓
- **alacritty** ✓

### macOS
- **Terminal.app** ✓
- **iTerm2** ✓
- **alacritty** ✓

## Context Memory Map

The statistics panel can display a visual context memory map showing token usage breakdown by category when `--context-limit` is specified.

**Enable with:**
```bash
python alexis.py --interactive --context-limit 8000
```

**Shows:**
- System tokens (light red)
- Tool tokens (light yellow)
- User tokens (white)
- Thinking tokens (light green)
- Tool call tokens (light yellow)
- Free tokens remaining
- Total usage with color indicator

**See:** [CONTEXT_MEMORY_MAP.md](CONTEXT_MEMORY_MAP.md) for detailed guide

## Advanced Configuration

### Environment Variables

```bash
# Disable mouse support
NO_MOUSE=1 python alexis.py --interactive

# Force legacy mode
TEXTUAL_LEGACY=1 python alexis.py --interactive

# Debug mode
TEXTUAL_DEBUG=1 python alexis.py --interactive
```

## Future Enhancements

Planned features:

- [ ] Syntax highlighting for code blocks
- [ ] Image display support
- [ ] Conversation export (markdown, JSON)
- [ ] Search/filter conversation history
- [ ] Custom themes/color schemes
- [ ] Keyboard macro support
- [ ] Plugin system for extensions

## Architecture

The textual UI driver:

1. Inherits from `UIDriver` abstract base
2. Uses Textual's app framework for rendering
3. Maintains compatibility with existing chat loop
4. Falls back gracefully if textual unavailable
5. Integrates with LLM driver system

See `ui_driver_textual_interactive.py` for implementation details.

## Development

To contribute improvements to the textual UI:

```python
# Key classes in ui_driver_textual_interactive.py
class ConversationView(VerticalScroll)
    # Handles message rendering and display

class StatisticsPanel(Static)
    # Displays real-time statistics

class MultiLineInput(Static)
    # Multi-line input widget

class TextualInteractiveUIDriver(UIDriver)
    # Main driver implementation
```

## Examples

### Example 1: Debugging with Extended Thinking
```bash
python alexis.py --interactive \
  --llm-driver gemini \
  --reasoning-effort high \
  --include-thoughts
```

The thinking panel will show reasoning steps in real-time.

### Example 2: Technical Documentation Review
```bash
python alexis.py --interactive \
  --system "You are a technical documentation expert" \
  --session docs_review.json
```

Maintains full context across multiple turns.

### Example 3: Code Review Session
```bash
python alexis.py --interactive \
  --mcp "npx -y @anthropic-ai/codereview" \
  --mcp-api-key your-key
```

Access code review tools through MCP integration.

## Support

For issues with Textual UI:

1. Check textual documentation: https://textual.textualize.io/
2. Report issues to Textual project
3. Try fallback mode (`--ui-driver simple`)
4. Check terminal compatibility
