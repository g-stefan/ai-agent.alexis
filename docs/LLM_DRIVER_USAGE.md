# LLM Driver System

The alexis now supports a pluggable LLM driver system that allows you to easily switch between different LLM providers.

## Available Drivers

- **llama**: For llama.cpp compatible servers
- **gemini**: For Google Gemini API

## Usage

### Using Llama Driver (Default)

```bash
# Default behavior (llama driver is used by default)
python alexis.py "Your prompt here" --url http://localhost:8000/v1/chat/completions

# Explicitly specify llama driver
python alexis.py "Your prompt here" --llm-driver llama --url http://localhost:8000/v1/chat/completions
```

### Using Gemini Driver

```bash
python alexis.py "Your prompt here" --llm-driver gemini --url https://your-gemini-gateway/v1/chat/completions --api-key YOUR_API_KEY --model gemini-2.5-flash
```

## Driver-Specific Features

### Llama Driver
- Standard OpenAI-compatible API
- Supports `--reasoning-effort` for models that support extended thinking
- Auto-corrects URLs from `/completion` to `/v1/chat/completions`

### Gemini Driver
- Uses Gemini's custom `thinking_config` for reasoning features
- Supports `--include-thoughts` to capture model reasoning
- Can use `--reasoning-effort` (low/medium/high) with Gemini's thinking level
- Provides better handling of Gemini-specific extensions

## Adding a New Driver

To add support for a new LLM provider:

1. Create a new driver class in a file (e.g., `openai_driver.py`):

```python
from llm_driver import LLMDriver

class OpenAIDriver(LLMDriver):
    def get_endpoint_url(self) -> str:
        return self.url
    
    def prepare_request_data(self, messages, tools, model, temperature, n_predict, reasoning_effort=None, include_thoughts=False):
        data = {
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": temperature
        }
        # Add provider-specific logic here
        return data
    
    def prepare_headers(self) -> Dict[str, str]:
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'text/event-stream'
        }
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        return headers
```

2. Update `llm_driver_factory.py` to include your driver:

```python
from openai_driver import OpenAIDriver

def create_llm_driver(driver_name: str, url: str, api_key: Optional[str] = None) -> LLMDriver:
    if driver_name.lower() == "openai":
        return OpenAIDriver(url, api_key)
    # ... existing code ...

def get_available_drivers() -> list[str]:
    return ["llama", "gemini", "openai"]
```

3. Run the CLI with your new driver:

```bash
python alexis.py "Your prompt" --llm-driver openai --url https://api.openai.com/v1/chat/completions --api-key YOUR_API_KEY
```

## Architecture

The LLM driver system uses an abstract base class (`LLMDriver`) that defines the interface all drivers must implement:

- `prepare_request_data()`: Formats the request payload for the specific LLM API
- `prepare_headers()`: Prepares HTTP headers with proper authentication and content types
- `get_endpoint_url()`: Returns the actual endpoint URL (with any necessary corrections)
- `validate_url()`: Optional URL validation logic

This design allows for:
- Easy addition of new LLM providers
- Provider-specific request/response handling
- Centralized driver management through the factory pattern
- Clean separation of concerns in the main CLI code
