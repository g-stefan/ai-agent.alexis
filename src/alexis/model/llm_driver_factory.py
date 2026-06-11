# AI-Agent.Alexis
# SPDX-FileCopyrightText: 2026 Grigore Stefan <g_stefan@yahoo.com>
# SPDX-License-Identifier: Apache-2.0

from typing import Optional
from .llm_driver import LLMDriver
from .llm_driver_llama import LlamaDriver
from .llm_driver_gemini import GeminiDriver


def create_llm_driver(
    driver_name: str,
    url: str,
    api_key: Optional[str] = None
) -> LLMDriver:
    """
    Factory function to create the appropriate LLM driver.

    Args:
        driver_name: The name of the driver ('llama' or 'gemini')
        url: The API endpoint URL
        api_key: Optional API key for authentication

    Returns:
        An instance of the appropriate LLMDriver subclass

    Raises:
        ValueError: If the driver_name is not recognized
    """
    driver_name_lower = driver_name.lower().strip()

    if driver_name_lower == "llama":
        return LlamaDriver(url, api_key)
    elif driver_name_lower == "gemini":
        return GeminiDriver(url, api_key)
    else:
        raise ValueError(
            f"Unknown LLM driver: '{driver_name}'. "
            f"Supported drivers: 'llama', 'gemini'"
        )


def get_available_drivers() -> list[str]:
    """Get a list of available driver names."""
    return ["llama", "gemini"]
