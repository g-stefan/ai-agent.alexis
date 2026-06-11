# AI-Agent.Alexis
# SPDX-FileCopyrightText: 2026 Grigore Stefan <g_stefan@yahoo.com>
# SPDX-License-Identifier: Apache-2.0

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional


class LLMDriver(ABC):
    """Abstract base class for LLM drivers."""

    def __init__(self, url: str, api_key: Optional[str] = None):
        self.url = url
        self.api_key = api_key

    @abstractmethod
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
        """Prepare the request data for this LLM provider."""
        pass

    @abstractmethod
    def prepare_headers(self) -> Dict[str, str]:
        """Prepare the HTTP headers for this LLM provider."""
        pass

    @abstractmethod
    def get_endpoint_url(self) -> str:
        """Get the actual endpoint URL for this LLM provider."""
        pass

    def validate_url(self) -> bool:
        """Validate that the URL is appropriate for this driver."""
        return True
