# Driver System Overview

The alexis is now organized around two independent plugin systems: **LLM Drivers** for backend selection and **UI Drivers** for interface mode selection. This modular architecture makes the codebase more maintainable and extensible.

## Two Independent Driver Systems

### 1. LLM Drivers
**Purpose:** Select which LLM provider/backend to use  
**Selection:** `--llm-driver {llama|gemini}`  
**Default:** `llama`

Handles:
- Request payload formatting for each provider
- HTTP header preparation with authentication
- Provider-specific parameter handling (e.g., Gemini's thinking_config)
- Endpoint URL normalization

### 2. UI Drivers
**Purpose:** Select the interaction mode/interface  
**Selection:** `--ui-driver {simple|interactive|api}`  
**Default:** `simple`

Handles:
- User interface presentation
- Input/output handling
- Server lifecycle management
- State persistence

## Architecture Diagram

```
┌─────────────────────────────────────────────┐
│         alexis.py (Main)             │
├─────────────────────────────────────────────┤
│                                             │
│  ┌────────────────────┐                    │
│  │   UI Driver        │                    │
│  │  (simple/int./api) │ ◄─── run()         │
│  └────────────────────┘                    │
│           │                                │
│           └────► run_single_turn()         │
│                       │                    │
│  ┌────────────────────▼───────────────┐   │
│  │      chat_loop()                   │   │
│  │                                    │   │
│  │  ┌──────────────────────────────┐ │   │
│  │  │  LLM Driver                  │ │   │
│  │  │  (llama/gemini)              │ │   │
│  │  │                              │ │   │
│  │  │ • prepare_request_data()     │ │   │
│  │  │ • prepare_headers()          │ │   │
│  │  │ • get_endpoint_url()         │ │   │
│  │  └──────────────────────────────┘ │   │
│  │           │                        │   │
│  │           └────► HTTP Request      │   │
│  │                                    │   │
│  │           ◄────── HTTP Response    │   │
│  │                   (SSE stream)     │   │
│  └────────────────────────────────────┘   │
│                                             │
└─────────────────────────────────────────────┘
```

## Combined Driver Selection

Select both drivers explicitly:

```bash
python alexis.py --llm-driver PROVIDER --ui-driver MODE
```

### Common Combinations

| Use Case | LLM Driver | UI Driver | Command |
|----------|-----------|-----------|---------|
| Batch processing with Llama | llama | simple | `--llm-driver llama --ui-driver simple` |
| Interactive Llama chat | llama | interactive | `--llm-driver llama --ui-driver interactive` |
| Llama with GUI | llama | api | `--llm-driver llama --ui-driver api --api-port 8000` |
| Batch Gemini | gemini | simple | `--llm-driver gemini --ui-driver simple` |
| Interactive Gemini | gemini | interactive | `--llm-driver gemini --ui-driver interactive` |
| Gemini with GUI | gemini | api | `--llm-driver gemini --ui-driver api --api-port 8000` |

## Examples

### Example 1: Batch Processing
Process a single prompt and save output to file:

```bash
python alexis.py "Explain machine learning" \
  --llm-driver llama \
  --ui-driver simple \
  --url http://localhost:8000/v1/chat/completions \
  -o output.txt \
  --session session.json
```

This:
1. Creates a Llama LLM driver for the backend
2. Creates a Simple UI driver for batch processing
3. Processes the prompt once
4. Saves output to file
5. Saves session for reuse

### Example 2: Interactive Development
Real-time conversation with Gemini:

```bash
python alexis.py \
  --llm-driver gemini \
  --ui-driver interactive \
  --url https://api.example.com/v1/chat/completions \
  --api-key $GEMINI_API_KEY \
  --model gemini-2.5-flash \
  --session dev_chat.json \
  --include-thoughts \
  --reasoning-effort high
```

This:
1. Creates a Gemini LLM driver with extended thinking
2. Creates an Interactive UI driver
3. Provides a terminal chat loop
4. Persists conversation to file
5. Each turn can use model's reasoning features

### Example 3: API Server for GUI
Start an HTTP server for a web interface:

```bash
python alexis.py \
  --llm-driver llama \
  --ui-driver api \
  --api-port 8000 \
  --api-host 0.0.0.0 \
  --url http://localhost:8080/v1/chat/completions \
  --session api_session.json
```

This:
1. Creates a Llama LLM driver
2. Creates an API UI driver that serves HTTP
3. Listens on all interfaces on port 8000
4. Provides /chat, /history, /clear endpoints
5. Streams responses via Server-Sent Events

### Example 4: Llama with Reasoning
Interactive chat with reasoning model:

```bash
python alexis.py \
  --llm-driver llama \
  --ui-driver interactive \
  --model reasoning-model \
  --reasoning-effort high \
  --include-thoughts
```

### Example 5: Multi-turn Conversation
Continue a previous conversation:

```bash
python alexis.py \
  --llm-driver llama \
  --ui-driver interactive \
  --session previous_chat.json
```

The chat history is loaded and you can continue the conversation.

## File Organization

```
alexis/
├── alexis.py              # Main CLI entry point
│
├── llm_driver.py                 # LLM driver abstract base
├── llm_driver_llama.py               # Llama.cpp implementation
├── llm_driver_gemini.py              # Gemini API implementation
├── llm_driver_factory.py         # LLM driver factory
├── LLM_DRIVER_USAGE.md           # LLM driver documentation
│
├── ui_driver.py                  # UI driver abstract base
├── ui_driver_simple.py           # Non-interactive mode
├── ui_driver_interactive.py      # Terminal interactive mode
├── ui_driver_api.py              # HTTP API server mode
├── ui_driver_factory.py          # UI driver factory
├── UI_DRIVER_USAGE.md            # UI driver documentation
│
└── DRIVER_SYSTEM_OVERVIEW.md     # This file
```

## Extending the System

### Adding a New LLM Provider

See [LLM_DRIVER_USAGE.md](LLM_DRIVER_USAGE.md#adding-a-new-driver)

### Adding a New UI Mode

See [UI_DRIVER_USAGE.md](UI_DRIVER_USAGE.md#adding-a-custom-ui-driver)

## Default Behavior

If no driver flags are specified:
- **LLM Driver:** `llama` (to http://127.0.0.1:8080/v1/chat/completions)
- **UI Driver:** `simple` (batch/non-interactive mode)

```bash
# Equivalent:
python alexis.py "prompt"

# Is the same as:
python alexis.py "prompt" --llm-driver llama --ui-driver simple
```

## Backward Compatibility

The old argument styles still work and auto-select the appropriate UI driver:

```bash
# Old style: --interactive
python alexis.py --interactive

# Auto-selects: --ui-driver interactive
```

```bash
# Old style: --api-port 8000
python alexis.py --api-port 8000

# Auto-selects: --ui-driver api --api-port 8000
```

**Note:** Explicit `--ui-driver` takes precedence over auto-detection.

## Performance Considerations

Each driver adds minimal overhead:

- **LLM Drivers:** ~1-2ms per request (for request preparation)
- **UI Drivers:** Negligible for simple/interactive, ~10-50ms for API (framework overhead)

The modular design allows you to:
- Test drivers independently
- Mock drivers for testing
- Profile individual driver performance
- Replace drivers without rebuilding

## Testing Drivers

Test a specific driver combination:

```bash
# Test Gemini driver
python alexis.py "test" \
  --llm-driver gemini \
  --api-key test-key

# Test interactive UI
python alexis.py \
  --ui-driver interactive \
  --session test_session.json
```

## Future Enhancements

Potential drivers to add:

**LLM Drivers:**
- OpenAI (GPT-3.5, GPT-4)
- Claude API
- Hugging Face Inference API
- Local GGML models

**UI Drivers:**
- Discord bot interface
- Slack integration
- Web Socket server
- Webhook-based mode
- TUI (terminal UI) with better formatting
