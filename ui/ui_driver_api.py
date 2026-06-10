# AI-Agent.Alexis
# SPDX-FileCopyrightText: 2026 Grigore Stefan <g_stefan@yahoo.com>
# SPDX-License-Identifier: Apache-2.0

import asyncio
import json
import sys
from typing import Callable, Dict, Any, List

from .ui_driver import UIDriver

try:
    import aiohttp_cors
    from aiohttp import web
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False


class APIUIDriver(UIDriver):
    """
    HTTP API server UI driver for GUI clients.
    Provides REST endpoints with Server-Sent Events (SSE) streaming.
    """

    def get_name(self) -> str:
        return "api"

    def get_description(self) -> str:
        return "HTTP API server with SSE streaming for GUI clients"

    def validate_args(self, args) -> bool:
        """Validate that aiohttp is available."""
        if not AIOHTTP_AVAILABLE:
            print("\n\033[91m[!] Error: 'aiohttp' is required for the API server mode.\033[0m", file=sys.stderr)
            print("\033[93m    Please install it using: pip install aiohttp aiohttp_cors\033[0m", file=sys.stderr)
            return False
        return True

    async def run(
        self,
        run_single_turn: Callable,
        messages: List[Dict[str, Any]],
        save_state: Callable,
        api_host: str = "127.0.0.1",
        api_port: int = 8000,
        user_content: List[Dict[str, Any]] = None,
        **kwargs
    ) -> None:
        """
        Run the HTTP API server mode.

        Provides REST endpoints:
        - POST /chat - Submit a message and get SSE stream
        - GET /history - Get chat history
        - POST /clear - Clear chat history
        """
        if not AIOHTTP_AVAILABLE:
            raise RuntimeError("aiohttp is not available")

        # Set client_max_size to 32 MB (32 * 1024 * 1024 bytes)
        app = web.Application(client_max_size=(32 * 1024 * 1024))

        async def api_chat(request):
            """POST /chat - Submit a message and receive SSE stream."""
            data = await request.json()
            prompt = data.get("prompt", "")
            images = data.get("images", [])  # List of dicts: {"b64": "...", "mime": "image/jpeg"}

            turn_content = []
            if prompt:
                turn_content.append({"type": "text", "text": prompt})
            for img in images:
                turn_content.append({"type": "image_url", "image_url": {"url": img}})

            if not turn_content:
                return web.Response(status=400, text="Empty prompt or images list")

            messages.append({"role": "user", "content": turn_content})

            response = web.StreamResponse(
                status=200,
                reason='OK',
                headers={
                    'Content-Type': 'text/event-stream',
                    'Cache-Control': 'no-cache',
                    'Connection': 'keep-alive',
                }
            )
            await response.prepare(request)

            stream_queue = asyncio.Queue()

            async def bg_chat():
                try:
                    # Call run_single_turn with the stream_queue
                    await run_single_turn(stream_queue)
                except Exception as e:
                    await stream_queue.put({"type": "error", "error": str(e)})
                finally:
                    await stream_queue.put({"type": "done"})

            chat_task = asyncio.create_task(bg_chat())

            try:
                while True:
                    msg = await stream_queue.get()
                    if msg["type"] == "done":
                        break
                    # `full` carries the untruncated tool result for in-process
                    # UIs only; drop it here to keep SSE frames small (`data`
                    # already holds the summary).
                    if isinstance(msg, dict):
                        msg.pop("full", None)
                    await response.write(f"data: {json.dumps(msg)}\n\n".encode('utf-8'))
            except ConnectionResetError:
                pass  # Client disconnected during stream
            finally:
                save_state()

            await response.write(b"data: [DONE]\n\n")
            return response

        async def api_history(request):
            """GET /history - Get chat history."""
            return web.json_response({"messages": messages})

        async def api_clear(request):
            """POST /clear - Clear chat history."""
            sys_msg = [m for m in messages if m.get("role") == "system"]
            messages.clear()
            messages.extend(sys_msg)
            save_state()
            return web.json_response({"status": "cleared"})

        app.add_routes([
            web.post('/chat', api_chat),
            web.get('/history', api_history),
            web.post('/clear', api_clear)
        ])

        runner = web.AppRunner(app)

        # Setup CORS on all routes
        cors = aiohttp_cors.setup(app, defaults={
            "*": aiohttp_cors.ResourceOptions(
                allow_credentials=True,
                expose_headers="*",
                allow_headers="*"
            )
        })

        for route in list(app.router.routes()):
            cors.add(route)

        await runner.setup()
        site = web.TCPSite(runner, api_host, api_port)
        await site.start()

        print(f"\n\033[92m[*] GUI API Server listening on http://{api_host}:{api_port}\033[0m", file=sys.stderr)
        print(f"\033[90m    - Endpoints: POST /chat, GET /history, POST /clear\033[0m", file=sys.stderr)

        try:
            # Keep server alive indefinitely
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass
        finally:
            await runner.cleanup()