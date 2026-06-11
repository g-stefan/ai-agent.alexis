# AI-Agent.Alexis
# SPDX-FileCopyrightText: 2026 Grigore Stefan <g_stefan@yahoo.com>
# SPDX-License-Identifier: Apache-2.0

import asyncio
import sys
from typing import Callable, Dict, Any, List
from .ui_driver import UIDriver


class InteractiveUIDriver(UIDriver):
    """
    Interactive terminal UI driver for continuous conversation.
    Provides a simple chat loop with user prompts and model responses.
    """

    def get_name(self) -> str:
        return "interactive"

    def get_description(self) -> str:
        return "Interactive terminal chat loop with user input"

    def validate_args(self, args) -> bool:
        return True

    async def run(
        self,
        run_single_turn: Callable,
        messages: List[Dict[str, Any]],
        save_state: Callable,
        user_content: List[Dict[str, Any]] = None,
        **kwargs
    ) -> None:
        """Run the simple interactive terminal mode."""
        # Process initial prompt if supplied
        if user_content:
            try:
                await run_single_turn()
            except BaseException as e:
                if isinstance(e, SystemExit):
                    raise
                print(f"\n\033[91m[!] Execution error: {e}\033[0m", file=sys.stderr)

        print("\n\033[92m[*] Entering Interactive Mode. Type 'exit' or 'quit' to stop.\033[0m", file=sys.stderr)
        while True:
            try:
                user_input = await asyncio.get_event_loop().run_in_executor(
                    None, input, "\n\033[92mYou:\033[0m "
                )
                if not user_input.strip():
                    continue
                if user_input.strip().lower() in ['exit', 'quit']:
                    break

                messages.append({"role": "user", "content": [{"type": "text", "text": user_input.strip()}]})
                await run_single_turn()
                save_state()

            except (KeyboardInterrupt, EOFError):
                print("\n\033[93m[!] Interactive session ended.\033[0m", file=sys.stderr)
                break
            except Exception as e:
                print(f"\n\033[91m[!] Error: {e}\033[0m", file=sys.stderr)

        save_state()
