# AI-Agent.Alexis
# SPDX-FileCopyrightText: 2026 Grigore Stefan <g_stefan@yahoo.com>
# SPDX-License-Identifier: Apache-2.0

import sys
from typing import Callable, Dict, Any, List
from .ui_driver import UIDriver


class SimpleUIDriver(UIDriver):
    """
    Non-interactive UI driver for batch processing and background tasks.
    Shows all info but requires no user interaction.
    """

    def get_name(self) -> str:
        return "simple"

    def get_description(self) -> str:
        return "Non-interactive batch processing (default, no user interaction)"

    async def run(
        self,
        run_single_turn: Callable,
        messages: List[Dict[str, Any]],
        save_state: Callable,
        user_content: List[Dict[str, Any]] = None,
        **kwargs
    ) -> None:
        """
        Run the simple non-interactive mode.

        Processes a single prompt if user_content is provided,
        otherwise just saves state.
        """
        # Only process initial prompt if supplied
        if user_content:
            try:
                await run_single_turn()
            except BaseException as e:
                if isinstance(e, SystemExit):
                    raise
                print(f"\n\033[91m[!] Execution error: {e}\033[0m", file=sys.stderr)
                sys.exit(1)

        # Save state after processing
        save_state()
