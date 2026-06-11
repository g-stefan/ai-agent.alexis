# AI-Agent.Alexis
# SPDX-FileCopyrightText: 2026 Grigore Stefan <g_stefan@yahoo.com>
# SPDX-License-Identifier: Apache-2.0

from abc import ABC, abstractmethod
from typing import Callable, Dict, Any, Optional, List


class UIDriver(ABC):
    """Abstract base class for UI drivers."""

    @abstractmethod
    async def run(
        self,
        run_single_turn: Callable,
        messages: List[Dict[str, Any]],
        save_state: Callable,
        **kwargs
    ) -> None:
        """
        Run the UI mode.

        Args:
            run_single_turn: Async function to execute a single chat turn
            messages: The chat message history
            save_state: Callback function to save the current state
            **kwargs: Additional driver-specific arguments
        """
        pass

    @abstractmethod
    def get_name(self) -> str:
        """Get the name of this UI driver."""
        pass

    @abstractmethod
    def get_description(self) -> str:
        """Get a description of this UI driver."""
        pass

    def validate_args(self, args) -> bool:
        """Validate arguments for this driver. Return True if valid."""
        return True
