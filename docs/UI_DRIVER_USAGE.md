# UI Driver System

The alexis now supports a pluggable UI driver system that separates the user interface logic from the core LLM chat functionality. This allows you to easily switch between different interaction modes without changing the underlying code.

## Available UI Drivers

### 1. Simple (Default)
**Name:** `simple`  
**Description:** Non-interactive batch processing for background tasks

Use this for:
- Batch processing
- Background jobs
- Non-interactive scripts
- Single-turn prompts

```bash
# Explicit selection (also the default)
python alexis.py "Your prompt" --ui-driver simple

# Implicit (no mode flags specified)
python alexis.py "Your prompt"
```

### 2. Interactive (Advanced TUI)
**Name:** `interactive`  
**Description:** Interactive terminal chat loop (uses Textual TUI if available)

Features:
- **Multi-pane layout** - Conversation, statistics, input
- **Mouse support** - Click, scroll, select
- **Multi-line input** - 3+ lines with copy/paste
- **Real-time stats** - Tokens, speed, MCP calls
- **Graceful fallback** - Simple mode if textual unavailable

Use this for:
- Real-time conversations with rich UI
- Multi-turn dialogs
- Interactive problem-solving
- Development and debugging

```bash
# Auto-selects textual if installed
python alexis.py --interactive

# Explicit selection
python alexis.py --ui-driver interactive

# Explicit textual selection
python alexis.py --ui-driver textual
```

**Requirements:** `pip install textual` (optional, falls back to simple if not installed)

### 3. Textual (Advanced)
**Name:** `textual`  
**Description:** Advanced Textual-based TUI with mouse support, multi-pane layout

This is the same as interactive mode when textual is available. Use this to:
- Explicitly request the advanced UI
- Get mouse support and multi-pane layout
- Copy/paste message content
- View real-time statistics

```bash
python alexis.py --ui-driver textual
```

For detailed usage, see [TEXTUAL_INTERACTIVE_UI.md](TEXTUAL_INTERACTIVE_UI.md)

### 4. API
**Name:** `api`  
**Description:** HTTP API server with SSE streaming for GUI clients

Use this for:
- Web-based interfaces
- GUI applications
- Remote access
- Integration with other services

```bash
# Explicit selection
python alexis.py --ui-driver api --api-port 8000

# Backward compatible (legacy flag)
python alexis.py --api-port 8000
```

## Usage Examples

### Simple Mode (Batch Processing)
```bash
# Process a single prompt and exit
python alexis.py "Translate to Spanish: Hello world" \
  --llm-driver llama \
  --url http://localhost:8000/v1/chat/completions \
  --ui-driver simple

# Process with output file
python alexis.py "Explain quantum computing" \
  -o output.txt \
  --ui-driver simple
```

### Interactive Mode (Advanced TUI with Mouse)
```bash
# Start interactive chat with advanced Textual UI (if installed)
python alexis.py --interactive --session chat_history.json

# Explicit textual selection
python alexis.py --ui-driver textual --session chat_history.json

# Fallback to simple mode if textual not available
python alexis.py --ui-driver interactive

# Legacy syntax (still works)
python alexis.py --interactive --session chat_history.json
```

The interactive mode allows you to:
- Chat with rich multi-pane interface (if textual installed)
- Use mouse to click, scroll, select, copy
- Multi-line input with copy/paste support
- View real-time token statistics
- Continue conversations with context
- Save/load chat history
- Exit with Ctrl+C or 'exit' command

### API Mode (Server)
```bash
# Start HTTP API server on port 8000
python alexis.py --ui-driver api --api-port 8000

# Specify custom host
python alexis.py --ui-driver api --api-host 0.0.0.0 --api-port 8080

# Legacy syntax (still works)
python alexis.py --api-port 8000
```

Available API endpoints:
- **POST /chat** - Submit a message and receive SSE stream
  ```bash
  curl -X POST http://localhost:8000/chat \
    -H "Content-Type: application/json" \
    -d '{"prompt": "Hello!", "images": []}'
  ```

- **GET /history** - Get chat history
  ```bash
  curl http://localhost:8000/history
  ```

- **POST /clear** - Clear chat history
  ```bash
  curl -X POST http://localhost:8000/clear
  ```

## Combining with LLM Drivers

You can use any UI driver with any LLM driver:

```bash
# Simple mode + Llama
python alexis.py "prompt" --llm-driver llama --ui-driver simple

# Simple mode + Gemini
python alexis.py "prompt" --llm-driver gemini --ui-driver simple --api-key YOUR_KEY

# Interactive mode + Gemini
python alexis.py --llm-driver gemini --ui-driver interactive

# API mode + Llama
python alexis.py --llm-driver llama --ui-driver api --api-port 8000
```

## Backward Compatibility

The CLI maintains backward compatibility with older argument syntax:

| Old Syntax | New Syntax |
|-----------|-----------|
| `--interactive` | `--ui-driver interactive` |
| `--api-port 8000` | `--ui-driver api --api-port 8000` |
| (no flags) | `--ui-driver simple` (default) |

**Note:** If you specify both a legacy flag and `--ui-driver`, the explicit `--ui-driver` takes precedence.

## Adding a Custom UI Driver

To create a new UI driver:

1. Create a new file (e.g., `custom_ui_driver.py`):

```python
from ui_driver import UIDriver
import sys
from typing import Callable, Dict, Any, List

class CustomUIDriver(UIDriver):
    def get_name(self) -> str:
        return "custom"
    
    def get_description(self) -> str:
        return "My custom UI driver"
    
    async def run(
        self,
        run_single_turn: Callable,
        messages: List[Dict[str, Any]],
        save_state: Callable,
        user_content: List[Dict[str, Any]] = None,
        **kwargs
    ) -> None:
        # Your custom UI logic here
        print("Custom UI Driver running!", file=sys.stderr)
        
        if user_content:
            await run_single_turn()
        
        save_state()
```

2. Update `ui_driver_factory.py` to include your driver:

```python
from custom_ui_driver import CustomUIDriver

def create_ui_driver(driver_name: str) -> UIDriver:
    driver_name_lower = driver_name.lower().strip()
    
    if driver_name_lower == "custom":
        return CustomUIDriver()
    # ... existing drivers ...

def get_available_driver_names() -> list:
    return ["simple", "interactive", "api", "custom"]
```

3. Use your custom driver:

```bash
python alexis.py --ui-driver custom
```

## Architecture

The UI driver system is built on:

- **UIDriver (Abstract Base Class):** Defines the interface all UI drivers must implement
  - `run()` - Execute the UI mode
  - `get_name()` - Get driver identifier
  - `get_description()` - Get human-readable description
  - `validate_args()` - Optional argument validation

- **UI Driver Factory:** Manages driver creation and discovery
  - `create_ui_driver()` - Instantiate a driver by name
  - `get_available_driver_names()` - List available drivers

This design provides:
- Clean separation of concerns
- Easy extensibility for new UI modes
- Testability of individual UI drivers
- Backward compatibility with legacy arguments
