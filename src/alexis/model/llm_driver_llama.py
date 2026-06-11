# AI-Agent.Alexis
# SPDX-FileCopyrightText: 2026 Grigore Stefan <g_stefan@yahoo.com>
# SPDX-License-Identifier: Apache-2.0

from typing import Dict, Any, List, Optional
from .llm_driver import LLMDriver


class LlamaDriver(LLMDriver):
    """Driver for llama.cpp compatible servers."""

    def __init__(self, url: str, api_key: Optional[str] = None):
        super().__init__(url, api_key)

    def get_endpoint_url(self) -> str:
        """Get the endpoint URL, auto-correcting if needed."""
        if self.url.endswith("/completion"):
            return self.url.replace("/completion", "/v1/chat/completions")
        if not self.url.endswith("/v1/chat/completions"):
            if self.url.endswith("/"):
                return self.url + "v1/chat/completions"
            return self.url + "/v1/chat/completions"
        return self.url

    def prepare_request_data(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        model: str,
        temperature: float,
        n_predict: int,
        reasoning_effort: Optional[str] = None,
        include_thoughts: bool = False
    ) -> Dict[str, Any]:
        """Prepare request data for llama.cpp server."""
        data = {
            "model": model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "temperature": temperature
        }

        if n_predict > 0:
            data["max_tokens"] = n_predict

        if tools:
            data["tools"] = tools

        # Llama uses standard reasoning_effort parameter
        if reasoning_effort:
            data["reasoning_effort"] = reasoning_effort

        return data

    def prepare_headers(self) -> Dict[str, str]:
        """Prepare HTTP headers for llama.cpp server."""
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'text/event-stream',
            'Connection': 'keep-alive',
            'User-Agent': 'alexis/1.0'
        }

        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'

        return headers

    def validate_url(self) -> bool:
        """Validate the URL for llama.cpp."""
        return True
