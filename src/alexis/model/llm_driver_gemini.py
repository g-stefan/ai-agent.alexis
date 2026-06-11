# AI-Agent.Alexis
# SPDX-FileCopyrightText: 2026 Grigore Stefan <g_stefan@yahoo.com>
# SPDX-License-Identifier: Apache-2.0

from typing import Dict, Any, List, Optional
from .llm_driver import LLMDriver


class GeminiDriver(LLMDriver):
    """Driver for Google Gemini API."""

    def __init__(self, url: str, api_key: Optional[str] = None):
        super().__init__(url, api_key)

    def get_endpoint_url(self) -> str:
        """Get the endpoint URL for Gemini."""
        # Gemini typically uses a proxy or gateway that provides OpenAI-compatible endpoint
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
        """Prepare request data for Gemini API."""
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

        # Gemini uses custom thinking_config for reasoning
        if include_thoughts:
            data.setdefault("extra_body", {}).setdefault("google", {})
            data["extra_body"]["google"].setdefault("thinking_config", {})
            data["extra_body"]["google"]["thinking_config"]["include_thoughts"] = True
            if reasoning_effort:
                data["extra_body"]["google"]["thinking_config"]["thinking_level"] = reasoning_effort
        elif reasoning_effort:
            # Fallback to standard parameter if thinking not explicitly requested
            data["reasoning_effort"] = reasoning_effort

        return data

    def prepare_headers(self) -> Dict[str, str]:
        """Prepare HTTP headers for Gemini API."""
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
        """Validate the URL for Gemini."""
        return True
