# Quick Start Guide

## Installation

```bash
# Clone or navigate to the project
cd alexis

# Install basic dependencies
pip install mcp

# For advanced interactive UI with mouse support (recommended)
pip install textual

# For API server mode (optional)
pip install aiohttp aiohttp_cors

# Or install all at once
pip install -r requirements.txt
```

## Basic Usage

### Single Prompt (Default)
```bash
python alexis.py "What is the capital of France?"
```

### With Output File
```bash
python alexis.py "Explain quantum computing" -o output.txt
```

### Interactive Chat
```bash
# Advanced TUI with mouse support (if textual installed)
python alexis.py --interactive --session chat.json

# Explicit UI selection
python alexis.py --ui-driver interactive  # Auto-selects textual if available
python alexis.py --ui-driver textual      # Explicitly use textual TUI
python alexis.py --ui-driver simple       # Fallback to simple mode
```

### HTTP API Server
```bash
python alexis.py --api-port 8000
# Then access at http://localhost:8000
```

## Driver Selection

### LLM Drivers (Backend)

**Llama (Default)**
```bash
python alexis.py "prompt" --llm-driver llama
```

**Gemini**
```bash
python alexis.py "prompt" \
  --llm-driver gemini \
  --api-key YOUR_API_KEY \
  --model gemini-2.5-flash \
  --url https://your-gemini-gateway/v1/chat/completions
```

### UI Drivers (Interface Mode)

**Simple (Default) - Batch Processing**
```bash
python alexis.py "prompt" --ui-driver simple
```

**Interactive - Terminal Chat**
```bash
python alexis.py --ui-driver interactive
```

**API - HTTP Server**
```bash
python alexis.py --ui-driver api --api-port 8000
```

## Common Tasks

### Batch Process Multiple Prompts
```bash
# Create a file with your prompt
echo "Explain machine learning" > prompt.txt

# Process it
python alexis.py prompt.txt --ui-driver simple
```

### Save Conversation History
```bash
python alexis.py --ui-driver interactive \
  --session my_conversation.json
```

Load previous conversation:
```bash
python alexis.py --ui-driver interactive \
  --session my_conversation.json
```

### Run with Extended Thinking (Gemini)
```bash
python alexis.py "prompt" \
  --llm-driver gemini \
  --include-thoughts \
  --reasoning-effort high
```

### Use with MCP Tools
```bash
python alexis.py "prompt" \
  --mcp "npx -y @example/mcp-server" \
  --mcp-api-key your-key
```

## Command Examples

### Example 1: Quick Response
```bash
python alexis.py "What is AI?"
```

### Example 2: Write to File
```bash
python alexis.py "Write a short story about AI" \
  -o story.txt
```

### Example 3: Multi-turn Conversation
```bash
python alexis.py --interactive --session dev.json
# Type your prompts, continue the conversation
# Type 'exit' to quit
```

### Example 4: API Server for Frontend
```bash
python alexis.py --api-port 3000 --api-host 0.0.0.0
# Then connect your frontend to http://localhost:3000
```

### Example 5: Use Gemini with Reasoning
```bash
python alexis.py "Solve this logic puzzle: ..." \
  --llm-driver gemini \
  --reasoning-effort high \
  --include-thoughts \
  --api-key $GEMINI_KEY \
  --model gemini-2.5-flash
```

## API Endpoints (when using --api-port)

### Submit Message
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello!", "images": []}'
```

### Get Chat History
```bash
curl http://localhost:8000/history
```

### Clear Chat
```bash
curl -X POST http://localhost:8000/clear
```

## Configuration Files

### Session File (--session)
Stores chat history in JSON format. Automatically loads on startup.

### System Message (--system)
Load a markdown file as the system message:
```bash
python alexis.py "prompt" --system system.md
```

### Usage Tracking (--usage-file)
Track token usage across sessions:
```bash
python alexis.py "prompt" --usage-file usage.json
```

### Debug Log (--debug)
Log all requests and responses for debugging:
```bash
python alexis.py "prompt" --debug debug.jsonl
```

## Performance Tuning

### Temperature (Creativity)
```bash
python alexis.py "prompt" --temp 0.7  # Default
python alexis.py "prompt" --temp 0.1  # More focused
python alexis.py "prompt" --temp 1.5  # More creative
```

### Token Limit
```bash
python alexis.py "prompt" --max-tokens 500
```

### Context Limit (for usage display)
```bash
python alexis.py "prompt" --context-limit 8192
```

### Timeout
```bash
python alexis.py "prompt" --timeout 600  # 10 minutes
```

## Troubleshooting

### Connection Failed
```
Error: Connection refused
```
Make sure your LLM server is running on the specified URL.

### Certificate Error (SSL)
```bash
# Use insecure mode for self-signed certs
python alexis.py "prompt" --insecure
```

### Aiohttp not installed (API mode)
```bash
pip install aiohttp aiohttp_cors
```

### Large payloads failing
```bash
# The CLI auto-minifies JSON, usually fixes this
# If still failing, check your server's max request size
```

## Environment Variables

Set the API key via environment:
```bash
export API_KEY=your-api-key
python alexis.py "prompt"
```

## More Information

- **LLM Driver Details:** See [LLM_DRIVER_USAGE.md](LLM_DRIVER_USAGE.md)
- **UI Driver Details:** See [UI_DRIVER_USAGE.md](UI_DRIVER_USAGE.md)
- **Complete Overview:** See [DRIVER_SYSTEM_OVERVIEW.md](DRIVER_SYSTEM_OVERVIEW.md)
- **Help:** `python alexis.py --help`

## Next Steps

1. Start with the simple mode: `python alexis.py "test"`
2. Try interactive: `python alexis.py --interactive`
3. Explore API mode: `python alexis.py --api-port 8000`
4. Add features with MCP servers
5. Extend with custom drivers (see documentation)
