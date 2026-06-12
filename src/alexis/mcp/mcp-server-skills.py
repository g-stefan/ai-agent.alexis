# MCP Skills Server
# SPDX-FileCopyrightText: 2026 Grigore Stefan <g_stefan@yahoo.com>
# SPDX-License-Identifier: Apache-2.0

import os
import sys
import json
import re
import base64
import asyncio
import argparse
import subprocess
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from mcp.server.fastmcp import FastMCP
from mcp.types import ImageContent
from typing import List, Optional, Any


def get_env_var(name: str, default: Any = None) -> Any:
    """Get an environment variable, optionally applying the env-base prefix."""
    if ENV_PREFIX:
        # Ensure there is exactly one underscore between prefix and name
        prefix = ENV_PREFIX if ENV_PREFIX.endswith("_") else f"{ENV_PREFIX}_"
        env_key = f"{prefix}{name}"
    else:
        env_key = name
    return os.environ.get(env_key, default)

# Root(s) of the agent's skill folders. Skills and their bundled scripts live
# under <AGENT_DIR>/skills/<skill>/scripts/. AGENT_DIR may list several roots
# separated by ';' — they are searched left to right, so earlier roots take
# precedence. The CLI lists the project's .agents before the agent's own bundled
# "system" skills, so a project skill overrides a bundled one of the same name,
# while an agent launched in an empty directory still falls back to the skills
# shipped with it.
DEFAULT_AGENT_DIR = ".agents"

# Parse command line options to customize server details
pre_parser = argparse.ArgumentParser(add_help=False)
pre_parser.add_argument("--env-base", type=str, default="")
pre_parser.add_argument("--tool-prefix", type=str, default="skill_")
pre_parser.add_argument("--mcp-name", type=str, default="Skills")
pre_parser.add_argument("--agent-dir", type=str, default=DEFAULT_AGENT_DIR)
pre_args, _ = pre_parser.parse_known_args()

ENV_PREFIX = pre_args.env_base
TOOL_PREFIX = pre_args.tool_prefix
MCP_NAME = pre_args.mcp_name

# The agent folder(s) (env override: <PREFIX>AGENT_DIR). A skill's scripts are
# resolved per-call under <root>/skills/<skill>/scripts/ across every configured
# root — there is no default scripts directory, so the owning skill must always
# be specified.
AGENT_DIR = get_env_var("AGENT_DIR", pre_args.agent_dir)

# Get the port from the environment, defaulting to 48102
HTTP_PORT = int(get_env_var("PORT", "48102"))

# Max seconds a single skill script may run before it is killed.
EXEC_TIMEOUT = int(get_env_var("EXEC_TIMEOUT", "120"))

# Max characters returned from a single skill_read call.
MAX_READ_CHARS = int(get_env_var("MAX_READ_CHARS", str(256 * 1024)))


def _is_safe_component(value: str) -> bool:
    """True only if `value` is a single path component: no separators, no
    traversal (``.`` / ``..``). Used to keep script and skill names inside the
    intended directory."""
    return bool(value) and value not in (".", "..") and os.path.basename(value) == value


def _agent_dirs() -> List[str]:
    """Return the configured agent roots, in search order. AGENT_DIR is a
    ';'-separated list; blank entries are dropped."""
    return [p.strip() for p in AGENT_DIR.split(";") if p.strip()]


def _resolve_skill_root(skill: str) -> Optional[str]:
    """Return the first agent root that actually contains ``skills/<skill>/``,
    or None when the skill is present under none of them. Earlier roots win, so
    a project-local skill can shadow a bundled one of the same name."""
    for base in _agent_dirs():
        root = os.path.join(base, "skills", skill)
        if os.path.isdir(root):
            return root
    return None

# Initialize the FastMCP Server
mcp = FastMCP(MCP_NAME, stateless_http=True, json_response=False)

@mcp.tool(name=f"{TOOL_PREFIX}run")
async def tool_run_skill_script(skill: str, name: str, arguments: Optional[List[str]] = None) -> Any:
    """
    Run a Python script bundled with a skill and return its output.

    The script is located at <root>/skills/<skill>/scripts/<name>.py, where
    <root> is the first configured agent directory that contains the skill.

    Args:
        skill (str): The skill that owns the script (required, non-empty), e.g. 'pdf-tools'.
        name (str): Script name, with or without the '.py' extension (e.g. 'convert').
        arguments (List[str], optional): The list of arguments to pass to the script.
    """
    # The owning skill is mandatory and must be a single, safe path component
    # so it cannot escape the agent folder.
    if not skill or not skill.strip():
        return "Error: A non-empty 'skill' is required."
    if not _is_safe_component(skill):
        return f"Error: Invalid skill name '{skill}'. Path traversal is not permitted."

    # Ensure name is normalized and has the .py extension
    script_file_name = name if name.lower().endswith(".py") else f"{name}.py"

    # Prevent path traversal by keeping the script to a simple base filename
    if not _is_safe_component(script_file_name):
        return f"Error: Invalid command name '{name}'. Path traversal is not permitted."

    # Locate the skill across every configured agent root (first match wins).
    skill_root = _resolve_skill_root(skill)
    if skill_root is None:
        return f"Error: Skill '{skill}' was not found in any agent directory."

    scripts_dir = os.path.join(skill_root, "scripts")
    script_path = os.path.join(scripts_dir, script_file_name)

    # Ensure the script actually exists
    if not os.path.isfile(script_path):
        return f"Error: Script '{name}' does not exist in skill '{skill}'."

    # Build the execution command running in the current directory
    cmd = [sys.executable, script_path]
    if arguments:
        cmd.extend(arguments)

    def _run():
        # stdin=DEVNULL is essential: when this server runs over stdio its own
        # stdin is the JSON-RPC pipe. A child that inherits/shares that handle
        # deadlocks the call on Windows, so the child must NOT touch it. The run
        # is also offloaded to a worker thread (so a slow script can't block the
        # server's event loop) and capped by EXEC_TIMEOUT.
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            stdin=subprocess.DEVNULL,
            timeout=EXEC_TIMEOUT,
        )

    try:
        # Run the Python interpreter as a subprocess, off the event loop.
        result = await asyncio.to_thread(_run)

        # Combine and return stdout and stderr
        output = result.stdout
        if result.stderr:
            if output:
                output += "\n" + result.stderr
            else:
                output = result.stderr

        # Check if output contains an image
        # Check result.stdout first to avoid potential pollution from stderr warnings
        for text_to_check in [result.stdout, output]:
            if not text_to_check:
                continue
            
            cleaned_text = text_to_check.strip()
            
            # 1. Check if it's a JSON object representing an image (as returned by read.py)
            if cleaned_text.startswith("{"):
                try:
                    parsed = json.loads(cleaned_text)
                    if isinstance(parsed, dict) and parsed.get("type") == "image" and "data" in parsed:
                        return ImageContent(
                            type="image",
                            data=parsed["data"],
                            mimeType=parsed.get("mimeType", "image/png"),
                        )
                except Exception:
                    pass

            # 2. Check if it's a Data URI
            if cleaned_text.startswith("data:image/"):
                base64_marker = ";base64,"
                marker_idx = cleaned_text.find(base64_marker)
                if marker_idx != -1:
                    mime_type = cleaned_text[5:marker_idx]
                    b64_part = cleaned_text[marker_idx + len(base64_marker):]
                    b64_match = re.match(r"^([a-zA-Z0-9+/=\s\r\n]+)", b64_part)
                    if b64_match:
                        raw_b64 = re.sub(r"\s+", "", b64_match.group(1))
                        return ImageContent(
                            type="image",
                            data=raw_b64,
                            mimeType=mime_type,
                        )

            # 3. Check if it is raw base64 data starting with image magic bytes
            b64_match = re.match(r"^([a-zA-Z0-9+/=\s\r\n]+)", cleaned_text)
            if b64_match:
                raw_b64 = re.sub(r"\s+", "", b64_match.group(1))
                if raw_b64:
                    # Match standard image headers
                    # Decode up to 32 chars (24 bytes) to safely identify magic bytes
                    test_b64 = raw_b64[:32]
                    padding_needed = (4 - len(test_b64) % 4) % 4
                    test_b64 += "=" * padding_needed
                    try:
                        decoded = base64.b64decode(test_b64)
                        mime_type = None
                        if decoded.startswith(b"\x89PNG\r\n\x1a\n"):
                            mime_type = "image/png"
                        elif decoded.startswith(b"\xff\xd8\xff"):
                            mime_type = "image/jpeg"
                        elif decoded.startswith(b"GIF89a") or decoded.startswith(b"GIF87a"):
                            mime_type = "image/gif"
                        elif decoded.startswith(b"RIFF") and len(decoded) >= 12 and decoded[8:12] == b"WEBP":
                            mime_type = "image/webp"
                        elif decoded.startswith(b"BM"):
                            mime_type = "image/bmp"
                        elif decoded.startswith(b"<?xml") or decoded.startswith(b"<svg"):
                            mime_type = "image/svg+xml"

                        if mime_type:
                            full_padding_needed = (4 - len(raw_b64) % 4) % 4
                            clean_b64 = raw_b64 + "=" * full_padding_needed
                            return ImageContent(
                                type="image",
                                data=clean_b64,
                                mimeType=mime_type,
                            )
                    except Exception:
                        pass
        
        return output
    except subprocess.TimeoutExpired:
        return f"Error: Script '{name}' in skill '{skill}' timed out after {EXEC_TIMEOUT}s."
    except Exception as e:
        return f"Error executing command '{script_file_name}': {str(e)}"


@mcp.tool(name=f"{TOOL_PREFIX}read")
async def tool_read_skill_file(skill: str, file: str = "SKILL.md") -> str:
    """
    Read a text file bundled with a skill and return its contents.

    Handy when the workspace filesystem MCP is not active: it lets the model
    load a skill's instructions (SKILL.md) or a bundled resource it references,
    on demand. The file is read from <root>/skills/<skill>/<file> (the first
    configured agent directory that contains the skill) and cannot escape that
    folder.

    Args:
        skill (str): The skill to read from (required, non-empty), e.g. 'toolbox'.
        file (str): Path to the file within the skill folder. Defaults to 'SKILL.md'.
    """
    # The skill is mandatory and must be a single, safe path component.
    if not skill or not skill.strip():
        return "Error: A non-empty 'skill' is required."
    if not _is_safe_component(skill):
        return f"Error: Invalid skill name '{skill}'. Path traversal is not permitted."

    rel = (file or "").strip() or "SKILL.md"

    # Locate the skill across every configured agent root (first match wins).
    skill_root = _resolve_skill_root(skill)
    if skill_root is None:
        return f"Error: Skill '{skill}' was not found in any agent directory."

    # Resolve the target and keep it inside the skill folder (block traversal).
    root_abs = os.path.abspath(skill_root)
    target_abs = os.path.abspath(os.path.join(skill_root, rel))
    if target_abs != root_abs and not target_abs.startswith(root_abs + os.sep):
        return f"Error: Invalid file path '{file}'. Path traversal is not permitted."

    if not os.path.isfile(target_abs):
        return f"Error: File '{rel}' does not exist in skill '{skill}'."

    try:
        with open(target_abs, "r", encoding="utf-8", errors="replace") as fh:
            data = fh.read(MAX_READ_CHARS + 1)
        if len(data) > MAX_READ_CHARS:
            data = data[:MAX_READ_CHARS] + f"\n\n[... truncated at {MAX_READ_CHARS} characters ...]"
        return data
    except Exception as e:
        return f"Error reading '{rel}' from skill '{skill}': {str(e)}"

# --- Authentication Middleware ---
class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    """Middleware to enforce API key authentication for incoming HTTP requests."""

    def __init__(self, app, api_key: str):
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        x_api_key = request.headers.get("X-API-Key")

        provided_key = None
        if auth_header and auth_header.startswith("Bearer "):
            provided_key = auth_header.split(" ", 1)[1]
        elif x_api_key:
            provided_key = x_api_key

        if not provided_key or provided_key != self.api_key:
            return JSONResponse(
                {"detail": "Unauthorized: Invalid or missing API Key"}, status_code=401
            )

        return await call_next(request)

# --- Execution Entrypoint ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Skills MCP Server")
    parser.add_argument("--stdio", action="store_true", help="Run in standard stdio mode")
    parser.add_argument("--mcp", action="store_true", help="Run in HTTP mode")
    parser.add_argument("--mcp-name", type=str, default="Skills", help="MCP name")
    parser.add_argument("--agent-dir", type=str, default=DEFAULT_AGENT_DIR, help="Agent folder root(s), ';'-separated, searched left to right (skills live under <agent-dir>/skills/). List .agents before the agent's bundled-skills folder so project skills override bundled ones, while an agent in an empty directory still falls back to the bundled set.")
    parser.add_argument("--api-key", type=str, default=None, help="Require this API key for HTTP requests.")
    parser.add_argument(
        "--env-base",
        type=str,
        help="Prefix for environment variables to isolate different servers (e.g., PREFIX)",
    )
    parser.add_argument(
        "--tool-prefix",
        type=str,
        default="skill_",
        help="Prefix for MCP tool names (default: skill_, so tools are exposed as skill_run / skill_read)",
    )

    args = parser.parse_args()

    # Note: When using stdio mode, standard out must be clean for JSON-RPC messages.
    # Therefore, all initialization logs are routed to sys.stderr.
    if ENV_PREFIX:
        actual_prefix = ENV_PREFIX if ENV_PREFIX.endswith("_") else f"{ENV_PREFIX}_"
        print(
            f"Using environment variable prefix: '{actual_prefix}' (e.g., expecting {actual_prefix}PORT)",
            file=sys.stderr,
        )

    if args.stdio:
        mcp.run()
    else:
        starlette_app = mcp.streamable_http_app()

        if args.api_key:
            starlette_app.add_middleware(APIKeyAuthMiddleware, api_key=args.api_key)

        starlette_app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        uvicorn.run(starlette_app, host="127.0.0.1", port=HTTP_PORT)

