# AI-Agent.Alexis
# SPDX-FileCopyrightText: 2026 Grigore Stefan <g_stefan@yahoo.com>
# SPDX-License-Identifier: Apache-2.0

import asyncio
import base64
import json
import os
import sys
import importlib.resources
from typing import Callable, Dict, Any, List

from .ui_driver import UIDriver

# Web client served at the root URL (like llama.cpp's server UI). Resolved via
# importlib.resources so it ships in the wheel and is found from any install.
try:
    WEB_CLIENT_PATH = os.fspath(
        importlib.resources.files(__package__).joinpath("ui_driver_api_web.html")
    )
except Exception:
    WEB_CLIENT_PATH = os.path.join(os.path.dirname(__file__), "ui_driver_api_web.html")
# Placeholder inside the HTML that is replaced with the live server URL so the
# client knows where to connect and can auto-connect on load.
SERVER_URL_PLACEHOLDER = "__SERVER_URL__"

try:
    import aiohttp
    import aiohttp_cors
    from aiohttp import web
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False


def _props_url_from_endpoint(endpoint_url: str) -> str:
    """Derive the llama.cpp /props URL from a chat-completions endpoint URL."""
    base = endpoint_url
    for suffix in ("/v1/chat/completions", "/chat/completions", "/completion"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    return base.rstrip("/") + "/props"


def _parse_data_url(data_url: str):
    """Split a data URL into (mime, base64_payload).

    Returns ("", "") if the string is not a recognizable data URL.
    """
    if not isinstance(data_url, str) or not data_url.startswith("data:"):
        return "", ""
    header, _, payload = data_url[len("data:"):].partition(",")
    # header looks like "text/plain;base64" or ";base64" or "image/png"
    mime = header.split(";", 1)[0].strip().lower()
    return mime, payload


def _decode_text(b64_payload: str):
    """Decode a base64 payload to text, or return None if it isn't UTF-8 text."""
    if not b64_payload:
        return None
    try:
        raw = base64.b64decode(b64_payload)
    except Exception:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


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
        api_port: int = 48010,
        user_content: List[Dict[str, Any]] = None,
        llm_driver=None,
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

        # A bind address of 0.0.0.0 (all interfaces) is not directly browsable;
        # advertise loopback in the URL we print and inject into the page.
        display_host = "127.0.0.1" if api_host in ("0.0.0.0", "::", "") else api_host
        web_ui_url = f"http://{display_host}:{api_port}"

        async def api_index(request):
            """GET / - Serve the web client with the live server URL injected."""
            try:
                with open(WEB_CLIENT_PATH, "r", encoding="utf-8") as f:
                    html = f.read()
            except OSError as e:
                return web.Response(status=500, text=f"Web client unavailable: {e}")

            # Inject the URL the browser used to reach us so the client connects
            # back to the right address/port and auto-connects on load.
            origin = f"{request.scheme}://{request.host}" if request.host else web_ui_url
            html = html.replace(SERVER_URL_PLACEHOLDER, origin)
            return web.Response(text=html, content_type="text/html")

        async def api_chat(request):
            """POST /chat - Submit a message and receive SSE stream."""
            data = await request.json()
            prompt = data.get("prompt", "")
            images = data.get("images", [])  # List of data URLs (base64) for images
            files = data.get("files", [])    # List of OpenAI file objects (see below)

            # Build content parts that a llama.cpp /v1/chat/completions endpoint
            # understands. llama.cpp only accepts these part types:
            #   text  -> {"type": "text",      "text": ...}
            #   image -> {"type": "image_url", "image_url": {"url": <data-url>}}
            # It does NOT support the OpenAI {"type": "file", ...} part, so file
            # attachments are converted here: text files are inlined as text
            # parts, and image files are routed to image_url parts.
            #
            # `attachments` is UI-only metadata recorded alongside the message so
            # the web client can render file chips on history reload without
            # parsing the inlined bodies. It maps each attachment to the index of
            # the content part it produced, and is stripped before the message is
            # sent to the model (see strip_ui_keys in alexis.py).
            turn_content = []
            attachments = []
            if prompt:
                turn_content.append({"type": "text", "text": prompt})

            for f in files:
                if not isinstance(f, dict):
                    continue
                filename = f.get("filename") or f.get("name") or "file"
                file_data = f.get("file_data")
                if not file_data:
                    # Legacy/plain shape: raw text content inlined directly.
                    content = f.get("content")
                    if content is not None:
                        turn_content.append({
                            "type": "text",
                            "text": f"[File: {filename}]\n{content}",
                        })
                        attachments.append({"name": filename, "kind": "text",
                                            "part": len(turn_content) - 1})
                    continue

                # file_data is a data URL: data:<mime>;base64,<payload>
                mime, b64 = _parse_data_url(file_data)
                if mime.startswith("image/"):
                    # An image attached through the file picker: send it as a
                    # proper image_url part so multimodal models can read it.
                    turn_content.append({
                        "type": "image_url",
                        "image_url": {"url": file_data},
                    })
                    attachments.append({"name": filename, "kind": "image",
                                        "part": len(turn_content) - 1})
                    continue

                text = _decode_text(b64)
                if text is not None:
                    turn_content.append({
                        "type": "text",
                        "text": f"[File: {filename}]\n{text}",
                    })
                    attachments.append({"name": filename, "kind": "text",
                                        "part": len(turn_content) - 1})
                else:
                    # Binary, non-image file: llama.cpp cannot ingest it.
                    turn_content.append({
                        "type": "text",
                        "text": f"[File: {filename}] (binary file omitted — "
                                f"unsupported by the model)",
                    })
                    attachments.append({"name": filename, "kind": "binary",
                                        "part": len(turn_content) - 1})

            for img in images:
                # Accept either a bare data-url string or an OpenAI image_url object.
                if isinstance(img, dict):
                    image_url = img.get("image_url", img)
                    if isinstance(image_url, str):
                        image_url = {"url": image_url}
                    turn_content.append({"type": "image_url", "image_url": image_url})
                else:
                    turn_content.append({"type": "image_url", "image_url": {"url": img}})

            if not turn_content:
                return web.Response(status=400, text="Empty prompt, files, or images list")

            user_msg = {"role": "user", "content": turn_content}
            if attachments:
                user_msg["attachments"] = attachments
            messages.append(user_msg)

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

        async def api_version(request):
            """GET /version - Report the app name and version for the web client."""
            try:
                from .. import version as alexis_version
                return web.json_response({
                    "name": alexis_version.APP_NAME,
                    "version": alexis_version.get_version(),
                    "build": alexis_version.get_build(),
                    "title": alexis_version.get_title(),
                })
            except Exception as e:
                return web.json_response({"name": "Alexis", "version": "0.0.0", "title": "Alexis", "error": str(e)})

        async def api_capabilities(request):
            """GET /capabilities - Report the LLM server's supported modalities.

            Queries the backing llama.cpp server's /props endpoint so the web
            client can, for example, disable the image button when the model
            has no vision support. Fields are null when unknown/unreachable.
            """
            caps = {"vision": None, "audio": None, "video": None, "model": None}
            if llm_driver is None:
                return web.json_response(caps)
            try:
                props_url = _props_url_from_endpoint(llm_driver.get_endpoint_url())
                headers = {}
                api_key = getattr(llm_driver, "api_key", None)
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"
                timeout = aiohttp.ClientTimeout(total=5)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(props_url, headers=headers) as resp:
                        if resp.status == 200:
                            props = await resp.json(content_type=None)
                            mods = props.get("modalities") or {}
                            caps["vision"] = bool(mods.get("vision", False))
                            caps["audio"] = bool(mods.get("audio", False))
                            caps["video"] = bool(mods.get("video", False))
                            caps["model"] = (
                                props.get("model_alias")
                                or props.get("model_path")
                            )
                        else:
                            caps["error"] = f"props HTTP {resp.status}"
            except Exception as e:
                caps["error"] = str(e)
            return web.json_response(caps)

        async def api_history(request):
            """GET /history - Get chat history."""
            return web.json_response({"messages": messages})

        async def api_clear(request):
            """POST /clear - Clear chat history (lightweight: messages only)."""
            sys_msg = [m for m in messages if m.get("role") == "system"]
            messages.clear()
            messages.extend(sys_msg)
            save_state()
            return web.json_response({"status": "cleared"})

        # Full per-directory session reset: wipe history AND the todo plan. The
        # backend hook (cli.session_reset) clears the in-memory messages, the
        # history sqlite, and the live todo over MCP. Runs on this aiohttp event
        # loop, which is the same loop the MCP session lives on.
        session_reset = kwargs.get("session_reset")

        async def api_session_reset(request):
            """POST /session/reset - wipe history + todo for a clean retry."""
            if session_reset is not None:
                try:
                    await session_reset()
                except Exception as e:
                    return web.json_response(
                        {"status": "error", "detail": str(e)}, status=500)
            else:
                # No session backend: fall back to a plain history clear.
                sys_msg = [m for m in messages if m.get("role") == "system"]
                messages.clear()
                messages.extend(sys_msg)
                save_state()
            return web.json_response({"status": "reset"})

        app.add_routes([
            web.get('/', api_index),
            web.get('/index.html', api_index),
            web.get('/version', api_version),
            web.get('/capabilities', api_capabilities),
            web.post('/chat', api_chat),
            web.get('/history', api_history),
            web.post('/clear', api_clear),
            web.post('/session/reset', api_session_reset)
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
        print(f"\033[96m    - Open the web client: {web_ui_url}\033[0m", file=sys.stderr)
        print(f"\033[90m    - Endpoints: GET /, GET /version, GET /capabilities, POST /chat, GET /history, POST /clear, POST /session/reset\033[0m", file=sys.stderr)

        try:
            # Keep server alive indefinitely
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass
        finally:
            await runner.cleanup()