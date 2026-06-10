# AI-Agent.Alexis
# SPDX-FileCopyrightText: 2026 Grigore Stefan <g_stefan@yahoo.com>
# SPDX-License-Identifier: Apache-2.0

import argparse
import asyncio
import base64
import contextlib
import json
import mimetypes
import os
import shlex
import sys
import threading
import time
import urllib.request
import ssl
import itertools
import socket
import re
from urllib.error import URLError, HTTPError
from typing import Optional, Dict, Any, List, Tuple
from contextlib import AsyncExitStack
from datetime import datetime, timezone

from model.llm_driver_factory import create_llm_driver, get_available_drivers as get_llm_drivers
from model.llm_driver import LLMDriver
from ui.ui_driver_factory import create_ui_driver, get_available_driver_names as get_ui_driver_names
from ui.ui_driver import UIDriver
import alexis_version
import alexis_config

def log_debug(filepath: Optional[str], log_type: str, data: Any) -> None:
    """Logs the API request or response chunk to a JSONL file."""
    if not filepath:
        return
    try:
        entry = {
            "datetime": datetime.now(timezone.utc).isoformat(),
            "type": log_type,
            "data": data
        }
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"\033[93m[!] Warning: Failed to write to debug file: {e}\033[0m", file=sys.stderr)

def encode_image(filepath: str) -> Tuple[str, str]:
    """Reads an image and returns its base64 string and mime type."""
    mime_type, _ = mimetypes.guess_type(filepath)
    if not mime_type:
        mime_type = "image/jpeg"
    with open(filepath, "rb") as f:
        # Strictly remove newlines/carriage returns to prevent data URI corruption
        b64_str = base64.b64encode(f.read()).decode('utf-8').replace('\n', '').replace('\r', '').strip()
    return b64_str, mime_type

def estimate_text_chars(messages: List[Dict[str, Any]]) -> int:
    """Helper to count characters in text parts of messages for rough token estimation."""
    chars = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            chars += len(content)
        elif isinstance(content, list):
            for item in content:
                if item.get("type") == "text":
                    chars += len(item.get("text", ""))
        if "tool_calls" in m:
            chars += len(json.dumps(m["tool_calls"]))
        if "extra_content" in m:
            chars += len(json.dumps(m["extra_content"]))
    return chars

def deep_merge(target: Dict[str, Any], source: Dict[str, Any]) -> None:
    """Deep merges source dictionary into target. Safely concatenates strings if streamed."""
    for key, value in source.items():
        if isinstance(value, dict):
            node = target.setdefault(key, {})
            deep_merge(node, value)
        elif isinstance(value, str) and key in target and isinstance(target[key], str):
            target[key] += value
        elif isinstance(value, list) and key in target and isinstance(target[key], list):
            target[key].extend(value)
        else:
            target[key] = value


def parse_skill_frontmatter(text: str) -> Dict[str, Any]:
    """Parse the leading YAML frontmatter of a SKILL.md (Agent Skills protocol).

    Returns a dict of the frontmatter keys (notably ``name`` and
    ``description``). Uses PyYAML when available for robust parsing (quoted /
    folded / multi-line values), falling back to a simple ``key: value`` reader.
    """
    if not text.startswith("---"):
        return {}
    lines = text.splitlines()
    if lines[0].strip() != "---":
        return {}
    body_lines = []
    closed = False
    for ln in lines[1:]:
        if ln.strip() == "---":
            closed = True
            break
        body_lines.append(ln)
    if not closed:
        return {}
    fm_text = "\n".join(body_lines)
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(fm_text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    # Fallback: top-level single-line "key: value" pairs only.
    out: Dict[str, Any] = {}
    for ln in body_lines:
        if not ln or ln[0] in (" ", "\t") or ":" not in ln:
            continue
        k, _, v = ln.partition(":")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def discover_skills(skills_dir: str) -> List[Tuple[str, str, str]]:
    """Find skills under `skills_dir` per the Agent Skills protocol: each skill
    is a subdirectory containing a ``SKILL.md``. Returns a sorted list of
    ``(name, description, skill_md_path)``."""
    found: List[Tuple[str, str, str]] = []
    if not os.path.isdir(skills_dir):
        return found
    for entry in sorted(os.listdir(skills_dir)):
        sub = os.path.join(skills_dir, entry)
        skill_md = os.path.join(sub, "SKILL.md")
        if not (os.path.isdir(sub) and os.path.isfile(skill_md)):
            continue
        try:
            with open(skill_md, "r", encoding="utf-8") as f:
                fm = parse_skill_frontmatter(f.read())
        except Exception:
            continue
        name = str(fm.get("name") or entry).strip()
        desc = str(fm.get("description") or "").strip()
        found.append((name, desc, skill_md))
    return found


def build_skills_prompt(skills: List[Tuple[str, str, str]]) -> str:
    """Render the discovered skills as a system-prompt section. Follows the
    progressive-disclosure model: only names + descriptions are shown; the
    model reads each SKILL.md in full on demand when a task matches."""
    out = [
        "# Available Skills",
        "",
        "You have access to the following skills. A skill is a folder of "
        "instructions and resources for a specific kind of task. When a "
        "request matches a skill's description, read that skill's SKILL.md "
        "file (and any files it references) in full before proceeding, then "
        "follow its instructions.",
        "",
    ]
    for name, desc, path in skills:
        out.append(f"- **{name}**: {desc}".rstrip())
        out.append(f"  SKILL.md: {path}")
    return "\n".join(out)


def alexis_home() -> str:
    """Return the AI-Agent.Alexis per-user home directory.

    Defaults to ``~/.alexis``; override with the ``AI_AGENT_ALEXIS_HOME``
    environment variable. This is the user-global config root that may hold:
      - ``mcp/``      – user-provided MCP servers (``mcp-server-<name>.py``)
      - ``skills/``   – user-provided skills (Agent Skills protocol)
      - ``SYSTEM.md`` – a user-global system prompt, always applied when present
    """
    env = os.environ.get("AI_AGENT_ALEXIS_HOME")
    if env and env.strip():
        return os.path.abspath(os.path.expanduser(env.strip()))
    return os.path.join(os.path.expanduser("~"), ".alexis")


def agent_skill_roots() -> List[str]:
    """Return the folder roots to search for skills, in precedence order:
    the current project's ``.agents`` first, then the user's home ``~/.alexis``
    (override via ``AI_AGENT_ALEXIS_HOME``). A project skill overrides a user
    skill of the same name.

    The agent's *own* bundled skills (shipped next to this script) are
    deliberately NOT searched: when ``alexis`` is installed and run from an
    unrelated project, it must not self-reference the package folder's skills.
    User-global skills live under ``~/.alexis/skills`` instead.

    Shared by the system-prompt skill discovery (--agent-use-skills) and the
    skills MCP server's search path (MCP_SKILLS_AGENT_DIR), so the model is told
    about exactly the skills the server can run."""
    roots = [".agents"]
    home = alexis_home()
    # Skills live under <root>/skills/. Add the user home unless it resolves to
    # the project root already (avoids a duplicate when run from ~/.alexis).
    if os.path.abspath(home) != os.path.abspath(".agents"):
        roots.append(home)
    return roots


def mcp_server_dirs() -> List[str]:
    """Directories scanned for ``mcp-server-<name>.py`` servers, in precedence
    order: the agent's own bundled ``mcp/`` (next to this script) first, then the
    user's ``~/.alexis/mcp`` (override the home via ``AI_AGENT_ALEXIS_HOME``) for
    user-provided servers."""
    dirs = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp")]
    home_mcp = os.path.join(alexis_home(), "mcp")
    if os.path.abspath(home_mcp) != os.path.abspath(dirs[0]):
        dirs.append(home_mcp)
    return dirs


def discover_bundled_mcp_servers() -> List[str]:
    """Return the names of available MCP servers: every ``mcp-server-<name>.py``
    found under the agent's bundled ``mcp/`` and the user's ``~/.alexis/mcp``
    becomes ``<name>``. Bundled servers take precedence on a name clash. Discovery
    is dynamic, so dropping a new ``mcp-server-<name>.py`` into either folder
    automatically exposes a ``--agent-use-mcp-<name>`` flag (and lets it be
    forwarded to subagents)."""
    names: List[str] = []
    for mcp_dir in mcp_server_dirs():
        if not os.path.isdir(mcp_dir):
            continue
        for fn in sorted(os.listdir(mcp_dir)):
            m = re.match(r"^mcp-server-(.+)\.py$", fn)
            if m and m.group(1) not in names:
                names.append(m.group(1))
    return names


def resolve_mcp_server_path(name: str) -> Optional[str]:
    """Return the path to ``mcp-server-<name>.py``, searching the bundled ``mcp/``
    first then the user's ``~/.alexis/mcp``; None if not found anywhere."""
    for mcp_dir in mcp_server_dirs():
        cand = os.path.join(mcp_dir, f"mcp-server-{name}.py")
        if os.path.isfile(cand):
            return cand
    return None


# Per-server wiring for bundled MCP servers attached via --agent-use-mcp-<name>.
#   env_base     – prefix the stdio client maps into the child env (a <BASE>_FOO
#                  var is also exposed to the server as FOO); copying the full
#                  parent env as a side effect.
#   env_defaults – os.environ defaults (set only when unset) so the server works
#                  out of the box; may be a dict or a zero-arg callable.
# Servers not listed get a generic env-base of <NAME> (sanitised, upper-cased)
# and no defaults — set <NAME>_FOO in the environment to pass FOO through.
SPECIAL_MCP_SERVERS: Dict[str, Dict[str, Any]] = {
    "workspace": {
        "env_base": "WORKSPACE",
        "env_defaults": {"WORKSPACE_DIR": ".", "WORKSPACE_HIDE_DOT_DIRS": "yes"},
    },
    "skills": {
        "env_base": "MCP_SKILLS",
        "env_defaults": lambda: {"MCP_SKILLS_AGENT_DIR": ";".join(agent_skill_roots())},
    },
}


def bundled_mcp_server_spec(name: str) -> Dict[str, Any]:
    """Return the env-base/env-defaults spec for a bundled MCP server name,
    falling back to a generic spec for servers without special wiring."""
    spec = SPECIAL_MCP_SERVERS.get(name)
    if spec is not None:
        return spec
    env_base = re.sub(r"[^A-Z0-9]", "_", name.upper())
    return {"env_base": env_base, "env_defaults": {}}


def bundled_mcp_help(name: str) -> str:
    """Help text for the --agent-use-mcp-<name> flag of a bundled server."""
    known = {
        "workspace": "Attach the bundled workspace filesystem MCP server (mcp/mcp-server-workspace.py) for file operations — equivalent to '--mcp \"python <AGENT_PATH>/mcp/mcp-server-workspace.py --stdio\" --mcp-env-base WORKSPACE'. Defaults WORKSPACE_DIR=. and WORKSPACE_HIDE_DOT_DIRS=yes when unset. Forwarded to subagents.",
        "skills": "Attach the bundled skills MCP server (mcp/mcp-server-skills.py) so the model can run scripts bundled with skills — equivalent to '--mcp \"python <AGENT_PATH>/mcp/mcp-server-skills.py --stdio\" --mcp-env-base MCP_SKILLS'. MCP_SKILLS_AGENT_DIR is a ';'-separated search path; defaults to the current .agents then the user-global ~/.alexis (override via AI_AGENT_ALEXIS_HOME). Forwarded to subagents.",
    }
    return known.get(
        name,
        f"Attach the bundled MCP server mcp/mcp-server-{name}.py (stdio), with env-base "
        f"'{bundled_mcp_server_spec(name)['env_base']}', and forward it to subagents.",
    )

def http_stream_reader(req: urllib.request.Request, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop, insecure: bool = False, timeout: Optional[int] = 360, cancel_event: Optional[threading.Event] = None):
    """Runs in a background thread to read the HTTP stream and push to an asyncio Queue.

    When `cancel_event` is set (the user pressed Stop), the open response is
    closed so the server detects the client disconnect and aborts generation —
    the same mechanism the llama.cpp web UI uses to stop. A ("aborted", None)
    item is then queued instead of ("done"/"error")."""
    response = None
    done = threading.Event()
    try:
        ctx = None
        if insecure:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        response = urllib.request.urlopen(req, context=ctx, timeout=timeout)

        # Watcher thread: as soon as Stop is requested, close the socket. This
        # interrupts a read that is blocked waiting on the server (e.g. during
        # prompt processing, before any token has streamed) so the stop is
        # immediate rather than waiting for the next token.
        if cancel_event is not None:
            resp_ref = response
            def _watch():
                while not done.is_set():
                    if cancel_event.wait(0.1):
                        try:
                            resp_ref.close()
                        except Exception:
                            pass
                        return
            threading.Thread(target=_watch, daemon=True).start()

        for line in response:
            if cancel_event is not None and cancel_event.is_set():
                break
            asyncio.run_coroutine_threadsafe(queue.put(("data", line)), loop)

        if cancel_event is not None and cancel_event.is_set():
            asyncio.run_coroutine_threadsafe(queue.put(("aborted", None)), loop)
        else:
            asyncio.run_coroutine_threadsafe(queue.put(("done", None)), loop)
    except Exception as e:
        if cancel_event is not None and cancel_event.is_set():
            # The exception is the side effect of us closing the socket.
            asyncio.run_coroutine_threadsafe(queue.put(("aborted", None)), loop)
        else:
            asyncio.run_coroutine_threadsafe(queue.put(("error", e)), loop)
    finally:
        done.set()
        try:
            if response is not None:
                response.close()
        except Exception:
            pass

async def chat_loop(
    driver: LLMDriver,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    tool_to_session: Dict[str, Any],
    temperature: float = 0.7,
    n_predict: int = -1,
    model: str = "default",
    context_limit: Optional[int] = None,
    session_msg_count: int = 0,
    usage_tracker: Optional[Dict[str, Any]] = None,
    insecure: bool = False,
    timeout: Optional[int] = 360,
    debug_file: Optional[str] = None,
    no_spinner: bool = False,
    output_file: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
    include_thoughts: bool = True,
    stream_queue: Optional[asyncio.Queue] = None,
    cancel_event: Optional[threading.Event] = None
) -> None:
    """
    Handles the chat loop, streaming text, detecting tool calls, executing them via MCP, and continuing.
    """
    
    print(f"\033[94m[*] Connecting to {driver.url}...\033[0m", file=sys.stderr)

    if usage_tracker is None:
        usage_tracker = {}

    while True:
        # Stop requested between turns (e.g. after a tool call) — don't start
        # another request.
        if cancel_event is not None and cancel_event.is_set():
            break

        data = driver.prepare_request_data(
            messages=messages,
            tools=tools,
            model=model,
            temperature=temperature,
            n_predict=n_predict,
            reasoning_effort=reasoning_effort,
            include_thoughts=include_thoughts
        )

        log_debug(debug_file, "request", data)

        # Use separators to minify JSON, significantly reducing payload size to prevent server-side truncation
        payload = json.dumps(data, separators=(',', ':')).encode('utf-8')

        # Prepare headers from driver
        headers = driver.prepare_headers()
        # Explicitly declare Content-Length to avoid HTTP chunking issues with large payloads
        headers['Content-Length'] = str(len(payload))

        endpoint_url = driver.get_endpoint_url()
        req = urllib.request.Request(
            endpoint_url,
            data=payload,
            headers=headers,
            method="POST"
        )

        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()
        thread = threading.Thread(target=http_stream_reader, args=(req, queue, loop, insecure, timeout, cancel_event), daemon=True)
        thread.start()

        start_time = time.time()
        first_token_time: Optional[float] = None
        first_print_time: Optional[float] = None
        last_print_time = time.time()
        last_spinner_update = 0.0
        
        # Accumulators for streaming text, tool calls, and custom attributes like thought signatures
        current_tool_calls = {}
        current_assistant_content = ""
        current_reasoning_content = ""
        current_assistant_extra = None
        finish_reason = None
        
        final_usage = None
        final_timings = None
        
        # Setup the UI thinking spinner
        spinner = itertools.cycle(['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'])
        spinner_active = False

        buffer = ""
        last_state = None  # Tracks the last data frame type ("content", "thinking", "tool_call")

        while True:
            try:
                # Wait for 0.1s slices to allow the UI spinner to update dynamically
                msg_type, content_bytes = await asyncio.wait_for(queue.get(), timeout=0.1)
                got_msg = True
            except asyncio.TimeoutError:
                got_msg = False

            current_time = time.time()
            
            # Spinner update logic
            if not no_spinner and current_time - last_spinner_update >= 0.1:
                if first_print_time is None:
                    elapsed = current_time - start_time
                    sys.stdout.write(f"\r\033[96m[{next(spinner)}] Thinking... ({elapsed:.1f}s)\033[0m\033[K")
                    sys.stdout.flush()
                    spinner_active = True
                    last_spinner_update = current_time
                elif current_time - last_print_time > 3.0:
                    if not spinner_active:
                        sys.stdout.write("\033[s")
                    elapsed = current_time - last_print_time
                    sys.stdout.write(f"\033[u\033[K \033[96m[{next(spinner)}] Working... ({elapsed:.1f}s)\033[0m")
                    sys.stdout.flush()
                    spinner_active = True
                    last_spinner_update = current_time

            if not got_msg:
                continue
            
            if msg_type == "error":
                if spinner_active:
                    if first_print_time is None:
                        sys.stdout.write("\r\033[K")
                    else:
                        sys.stdout.write("\033[u\033[K")
                    sys.stdout.flush()
                    spinner_active = False
                e = content_bytes
                
                err_msg = str(e)
                if isinstance(e, HTTPError):
                    error_body = e.read().decode('utf-8')
                    err_msg = f"Server Error {e.code}: {e.reason} - {error_body}"
                    print(f"\n\033[91m[!] Server Error: {e.code} - {e.reason}\033[0m", file=sys.stderr)
                    if error_body:
                        print(f"\033[91m    Details: {error_body}\033[0m", file=sys.stderr)
                        if "key 'prompt' not found" in error_body:
                            print("\033[93m    Hint: You are targeting the '/completion' endpoint, but this script requires the Chat API ('/v1/chat/completions').\033[0m", file=sys.stderr)
                elif isinstance(e, URLError):
                    err_msg = f"Connection Error: {e.reason}"
                    print(f"\n\033[91m[!] Connection Error: {e.reason}\033[0m", file=sys.stderr)
                    if "time" in str(e.reason).lower() or isinstance(e.reason, socket.timeout):
                        timeout_str = f"timeout={timeout}s" if timeout else "infinite timeout"
                        print(f"\033[93m    The server took too long to respond ({timeout_str}). You can adjust it with --timeout.\033[0m", file=sys.stderr)
                    else:
                        print("\033[93m    Make sure your llama-server is running and the URL is correct.\033[0m", file=sys.stderr)
                elif isinstance(e, TimeoutError):
                    timeout_str = f"{timeout}s" if timeout else "infinite"
                    err_msg = f"Connection Timeout ({timeout_str})"
                    print(f"\n\033[91m[!] Connection Timeout: The request exceeded the {timeout_str} timeout.\033[0m", file=sys.stderr)
                else:
                    print(f"\n\033[91m[!] Stream Error: {e}\033[0m", file=sys.stderr)

                if stream_queue:
                    stream_queue.put_nowait({"type": "error", "error": err_msg})
                raise RuntimeError(err_msg)

            if msg_type == "done":
                if spinner_active:
                    if first_print_time is None:
                        sys.stdout.write("\r\033[K")
                    else:
                        sys.stdout.write("\033[u\033[K")
                    sys.stdout.flush()
                    spinner_active = False
                break

            if msg_type == "aborted":
                # User pressed Stop: the server connection was closed. End the
                # whole turn cleanly without starting another request.
                if spinner_active:
                    sys.stdout.write("\r\033[K" if first_print_time is None else "\033[u\033[K")
                    sys.stdout.flush()
                    spinner_active = False
                print("\n\033[93m[!] Generation stopped by user.\033[0m", file=sys.stderr)
                if stream_queue:
                    stream_queue.put_nowait({"type": "aborted"})
                return

            line = content_bytes.decode('utf-8').strip()
            
            if line == "data: [DONE]":
                if spinner_active:
                    if first_print_time is None:
                        sys.stdout.write("\r\033[K")
                    else:
                        sys.stdout.write("\033[u\033[K")
                    sys.stdout.flush()
                    spinner_active = False
                break
                
            if line.startswith("data: "):
                data_str = line[6:]
                buffer += data_str
                try:
                    chunk = json.loads(buffer)
                    buffer = "" # clear buffer on success
                    log_debug(debug_file, "response", chunk)
                except json.JSONDecodeError:
                    continue

                if chunk.get("usage"):
                    final_usage = chunk["usage"]
                if chunk.get("timings"):
                    final_timings = chunk["timings"]

                choices = chunk.get("choices", [])
                if not choices:
                    continue

                delta = choices[0].get("delta", {})

                # Check if there is meaningful content to display (for TTFT stats)
                has_meaningful_content = bool(
                    delta.get("content") or 
                    delta.get("reasoning_content") or 
                    delta.get("tool_calls") or 
                    delta.get("extra_content")
                )

                if has_meaningful_content and first_token_time is None:
                    first_token_time = time.time()
                    
                # Handle extra content (captures thought signatures for non-tool calls)
                if "extra_content" in delta:
                    if current_assistant_extra is None:
                        current_assistant_extra = {}
                    deep_merge(current_assistant_extra, delta["extra_content"])

                # Handle text and reasoning content printing
                reasoning = delta.get("reasoning_content", "")
                content = delta.get("content", "")
                
                # Update the last recorded state based on current delta contents
                if reasoning:
                    last_state = "thinking"
                if content:
                    last_state = "content"
                if delta.get("tool_calls"):
                    last_state = "tool_call"
                
                just_printed = False
                
                if reasoning or content:
                    if spinner_active:
                        if first_print_time is None:
                            sys.stdout.write("\r\033[K")
                        else:
                            sys.stdout.write("\033[u\033[K")
                        sys.stdout.flush()
                        spinner_active = False
                        
                    if first_print_time is None:
                        first_print_time = time.time()
                                            
                    if reasoning:
                        sys.stdout.write(f"\033[95m{reasoning}\033[0m")
                        current_reasoning_content += reasoning
                        if stream_queue:
                            stream_queue.put_nowait({"type": "thinking", "data": reasoning})
                        just_printed = True

                    is_thinking = False
                    if reasoning:
                        is_thinking = True
                        
                    if content:
                        current_assistant_content += content
                        if is_thinking:
                            sys.stdout.write(f"{content}\033[0m")                            
                        else:
                            sys.stdout.write(content)
                        if stream_queue:
                            stream_queue.put_nowait({"type": "content", "data": content})
                            
                        just_printed = True
                        
                    if just_printed:
                        sys.stdout.flush()
                        last_print_time = time.time()

                # Handle tool calls
                for tc in delta.get("tool_calls", []):
                    idx = tc.get("index")
                    if idx not in current_tool_calls:
                        current_tool_calls[idx] = {"id": "", "name": "", "arguments": "", "extra_content": None}
                    if "id" in tc:
                        current_tool_calls[idx]["id"] += tc["id"]
                    if "function" in tc:
                        if "name" in tc["function"]:
                            current_tool_calls[idx]["name"] += tc["function"]["name"]
                        if "arguments" in tc["function"]:
                            current_tool_calls[idx]["arguments"] += tc["function"]["arguments"]

                    # Capture tool-call specific extra content (thought signatures)
                    if "extra_content" in tc:
                        if current_tool_calls[idx]["extra_content"] is None:
                            current_tool_calls[idx]["extra_content"] = {}
                        deep_merge(current_tool_calls[idx]["extra_content"], tc["extra_content"])

                    # Live "building" update so the UI switches to TOOL CALL while
                    # the arguments are still streaming (rather than appearing stuck
                    # on the assistant text).
                    if stream_queue:
                        stream_queue.put_nowait({
                            "type": "tool_call_building",
                            "name": current_tool_calls[idx]["name"],
                            "arguments": current_tool_calls[idx]["arguments"],
                        })

                if choices[0].get("finish_reason") is not None:
                    finish_reason = choices[0].get("finish_reason")

        # End of stream block. Print a newline to separate streamed text from stats or tool executions.
        print("\n", file=sys.stderr)
        
        # Save output data frame to file if requested
        if output_file and current_assistant_content:
            try:
                with open(output_file, "a", encoding="utf-8") as f:
                    f.write(current_assistant_content)
            except Exception as e:
                print(f"\033[93m[!] Warning: Failed to write to output file: {e}\033[0m", file=sys.stderr)
        
        # New Check: Exit with error if generation gracefully completed but was still in the "thinking" state.
        if finish_reason == "stop" and last_state == "thinking":
            err_msg = "Model stopped processing in thinking state"
            print(f"\033[91m[!] Error: {err_msg}\033[0m", file=sys.stderr)
            if stream_queue:
                stream_queue.put_nowait({"type": "error", "error": err_msg})
            raise RuntimeError(err_msg)
        
        if final_usage:
            predicted_n = final_usage.get("completion_tokens", 0)
            prompt_n = final_usage.get("prompt_tokens", 0)
            total_n = final_usage.get("total_tokens", predicted_n + prompt_n)
            
            ttft = first_token_time - start_time if first_token_time else 0.0
            
            if final_timings and "predicted_per_second" in final_timings:
                speed = final_timings.get("predicted_per_second", 0.0)
            else:
                gen_time = time.time() - first_token_time if first_token_time else 0.0
                speed = (predicted_n / gen_time) if gen_time > 0.001 else 0.0

            exact_history = False
            history_est = 0
            tools_est = 0
            new_est = prompt_n

            if total_n > 0:
                # Calculate character lengths for estimation
                tools_chars = len(json.dumps(tools)) if tools else 0
                history_msgs = messages[:session_msg_count]
                current_msgs = messages[session_msg_count:]
                
                history_chars = estimate_text_chars(history_msgs) if history_msgs else 0
                current_chars = estimate_text_chars(current_msgs) if current_msgs else 0
                total_chars = history_chars + current_chars + tools_chars
                
                if "last_context_size" in usage_tracker and session_msg_count > 0:
                    # Use exact history size from the provided usage file
                    history_est = usage_tracker["last_context_size"]
                    history_est = min(history_est, prompt_n) # Cap just in case tokenization drifted slightly
                    
                    remaining_prompt = prompt_n - history_est
                    if tools_chars + current_chars > 0:
                        tools_est = int(remaining_prompt * (tools_chars / (tools_chars + current_chars)))
                    else:
                        tools_est = 0
                        
                    new_est = remaining_prompt - tools_est
                    exact_history = True
                else:
                    # Fallback to current text-length estimation method
                    if total_chars > 0:
                        history_est = int(prompt_n * (history_chars / total_chars))
                        tools_est = int(prompt_n * (tools_chars / total_chars))
                        new_est = prompt_n - history_est - tools_est
                    else:
                        history_est = 0
                        tools_est = 0
                        new_est = prompt_n
                        
                # Update usage tracking info
                usage_tracker["last_context_size"] = total_n
                usage_tracker["cumulative_prompt_tokens"] = usage_tracker.get("cumulative_prompt_tokens", 0) + prompt_n
                usage_tracker["cumulative_completion_tokens"] = usage_tracker.get("cumulative_completion_tokens", 0) + predicted_n
                usage_tracker["total_tokens_used"] = usage_tracker.get("total_tokens_used", 0) + total_n
                usage_tracker["cumulative_tools_tokens"] = usage_tracker.get("cumulative_tools_tokens", 0) + tools_est
                
                if "history" not in usage_tracker:
                    usage_tracker["history"] = []
                usage_tracker["history"].append({
                    "timestamp": time.time(),
                    "prompt_tokens": prompt_n,
                    "completion_tokens": predicted_n,
                    "total_tokens": total_n,
                    "estimated_tools_tokens": tools_est
                })

            # Split the completion into thinking vs. answer tokens. The backend
            # rarely reports a reasoning-token count, so estimate it from the
            # streamed character ratio (thinking + answer == completion).
            think_chars = len(current_reasoning_content)
            answer_chars = len(current_assistant_content)
            if predicted_n > 0 and (think_chars + answer_chars) > 0:
                thinking_n = int(round(predicted_n * think_chars / (think_chars + answer_chars)))
            else:
                thinking_n = 0
            answer_n = max(0, predicted_n - thinking_n)

            # Push real usage stats onto the stream queue for live UIs (e.g. textual).
            # Fires every turn, including intermediate tool-call turns.
            if stream_queue:
                stream_queue.put_nowait({
                    "type": "usage",
                    "prompt_tokens": prompt_n,
                    "completion_tokens": predicted_n,
                    "total_tokens": total_n,
                    "tokens_per_second": speed,
                    "context_limit": context_limit,
                    "lifetime_tokens": usage_tracker.get("total_tokens_used", 0),
                    "history_tokens": history_est,
                    "tools_tokens": tools_est,
                    "new_tokens": new_est,
                    "thinking_tokens": thinking_n,
                    "answer_tokens": answer_n,
                })

            # Only print the summary if we are NOT making a tool call (i.e. this is the final turn)
            if not current_tool_calls:
                print(f"\033[92m[+] Generation Complete!\033[0m", file=sys.stderr)
                print(f"\033[90m    - Tokens generated : {predicted_n}\033[0m", file=sys.stderr)
                
                if total_n > 0:
                    # Format the breakdown cleanly
                    hist_label = "history:" if exact_history else "history ≈"
                    new_label = "new:" if exact_history else "new ≈"
                    
                    breakdown_parts = []
                    if history_est > 0 or exact_history:
                        breakdown_parts.append(f"{hist_label} {history_est}")
                    if tools_est > 0:
                        breakdown_parts.append(f"tools ≈ {tools_est}")
                    breakdown_parts.append(f"{new_label} {new_est}")
                    
                    breakdown_str = ", ".join(breakdown_parts)

                    if context_limit and context_limit > 0:
                        pct = (total_n / context_limit) * 100
                        print(f"\033[90m    - Context usage    : {total_n} / {context_limit} tokens ({pct:.1f}%)\033[0m", file=sys.stderr)
                        print(f"\033[90m                         ({breakdown_str})\033[0m", file=sys.stderr)
                    else:
                        print(f"\033[90m    - Context usage    : {total_n} tokens ({breakdown_str})\033[0m", file=sys.stderr)
                        
                    if "total_tokens_used" in usage_tracker:
                        print(f"\033[90m    - Lifetime usage   : {usage_tracker['total_tokens_used']} tokens\033[0m", file=sys.stderr)
                        
                print(f"\033[90m    - Speed            : {speed:.2f} tokens/sec\033[0m", file=sys.stderr)
                print(f"\033[90m    - Time to 1st token: {ttft:.2f}s\033[0m", file=sys.stderr)

        # Process Tool Calls if necessary
        if finish_reason == "tool_calls" or current_tool_calls:
            assistant_msg = {"role": "assistant", "content": current_assistant_content if current_assistant_content else None, "tool_calls": []}
            
            # Embed message-level thought signatures if present
            if current_assistant_extra:
                assistant_msg["extra_content"] = current_assistant_extra
                
            for idx, tc in sorted(current_tool_calls.items()):
                tc_obj = {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc["arguments"]
                    }
                }
                # Embed tool-call-level thought signatures to satisfy strict API validation
                if tc.get("extra_content"):
                    tc_obj["extra_content"] = tc["extra_content"]
                    
                assistant_msg["tool_calls"].append(tc_obj)
            messages.append(assistant_msg)

            # Execute Tools
            for tc in assistant_msg["tool_calls"]:
                name = tc["function"]["name"]
                args_str = tc["function"]["arguments"]
                tool_call_id = tc["id"]
                
                display_args = args_str if len(args_str) <= 60 else args_str[:57] + "..."
                print(f"\033[93m[*] Model executing tool: {name}({display_args})\033[0m", file=sys.stderr)
                if stream_queue:
                    stream_queue.put_nowait({"type": "tool_call", "name": name, "arguments": args_str})
                
                try:
                    args_dict = json.loads(args_str) if args_str else {}
                    
                    session = tool_to_session.get(name)
                    
                    if session:
                        result = await session.call_tool(name, arguments=args_dict)
                        
                        tool_content_list = []
                        text_snippets = []
                        
                        # Process returned tool components for Text and Images
                        for c in result.content:
                            if c.type == "text":
                                tool_content_list.append({"type": "text", "text": c.text})
                                text_snippets.append(c.text)
                            elif c.type == "image":
                                img_url = f"data:{c.mimeType};base64,{c.data}"
                                tool_content_list.append({"type": "image_url", "image_url": {"url": img_url}})
                                text_snippets.append(f"[Image: {c.mimeType}]")
                        
                        result_str = "\n".join(text_snippets)
                        print(f"\033[92m[+] Tool result snippet: {result_str[:150]}...\033[0m", file=sys.stderr)
                        
                        # If the tool result contains an image, we send an array of parts back.
                        # Otherwise, we join the text snippets as a string for broader API compatibility.
                        has_image = any(c.type == "image" for c in result.content)
                        if has_image:
                            final_content = tool_content_list
                        else:
                            final_content = "\n".join([c.text for c in result.content if c.type == "text"])
                            
                    else:
                        final_content = f"Error: Tool '{name}' not found on any connected MCP server."
                        print(f"\033[91m[!] {final_content}\033[0m", file=sys.stderr)
                        
                except Exception as e:
                    final_content = f"Error executing tool '{name}': {str(e)}"
                    print(f"\033[91m[!] {final_content}\033[0m", file=sys.stderr)
                    
                if stream_queue:
                    full = str(final_content)
                    # `data` is a short summary so the API UI's SSE frames stay
                    # small; `full` carries the complete result for in-process
                    # UIs (e.g. the Textual copy button). The API driver strips
                    # `full` before serializing — see ui_driver_api.
                    summary = full[:1500] + ("..." if len(full) > 1500 else "")
                    stream_queue.put_nowait({"type": "tool_result", "name": name,
                                             "data": summary, "full": full})

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": final_content
                })
                
            # Loop will continue to send the tool results back to the LLM
            print(f"\033[94m[*] Sending tool results back to model...\033[0m", file=sys.stderr)
            continue
            
        # If we got here and it's not a tool call, the generation is complete
        if current_assistant_content or current_assistant_extra:
            msg = {"role": "assistant"}
            if current_assistant_content:
                msg["content"] = current_assistant_content
            else:
                msg["content"] = "" # Models prefer an explicit empty string over missing content
                
            # Preserve message-level thought signatures to satisfy reasoning context
            if current_assistant_extra:
                msg["extra_content"] = current_assistant_extra
            messages.append(msg)
            
        break

class _LocalTextContent:
    """Minimal stand-in for an MCP text content block (has ``.type``/``.text``),
    so results from in-process tools flow through chat_loop's result handling
    exactly like results from a real MCP ClientSession."""
    type = "text"

    def __init__(self, text: str):
        self.text = text


class _LocalToolResult:
    """Minimal stand-in for an MCP CallToolResult: just a ``.content`` list."""

    def __init__(self, text: str):
        self.content = [_LocalTextContent(text)]


class _MainToolSession:
    """In-process stand-in for an MCP ClientSession exposing the "Main" server's
    ``processing_done(result)`` tool to the subagent.

    chat_loop treats every tool the same way — it looks the name up in
    ``tool_to_session`` and calls ``await session.call_tool(name, arguments=...)``
    expecting a result with a ``.content`` list. This class implements just that
    surface. When the subagent calls ``processing_done`` we capture the result in
    a shared holder and set the cancel event so the chat loop stops cleanly at the
    next turn boundary (the captured result is then returned to the main agent
    instead of the subagent's final assistant text)."""

    def __init__(self, holder: Dict[str, Any]):
        self._holder = holder
        # Reset per subagent call (calls are serialized by an asyncio.Lock).
        self.cancel_event: Optional[threading.Event] = None

    async def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None):
        arguments = arguments or {}
        if name == "processing_done":
            self._holder["result"] = arguments.get("result", "")
            self._holder["done"] = True
            if self.cancel_event is not None:
                self.cancel_event.set()
            return _LocalToolResult(
                "Result recorded and returned to the main agent. The conversation "
                "is complete; no further action is needed."
            )
        return _LocalToolResult(f"Error: unknown Main tool '{name}'.")


# Tool schema advertised to the subagent for the in-process "Main" server.
MAIN_PROCESSING_DONE_TOOL = {
    "type": "function",
    "function": {
        "name": "processing_done",
        "description": (
            "Signal that you have finished and return your final result to the "
            "main agent. Call this once, with your complete answer passed as "
            "'result'. After you call it the conversation ends and 'result' is "
            "delivered verbatim to the caller — so put your entire final answer "
            "in it, not a summary."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "result": {
                    "type": "string",
                    "description": "The complete final result to return to the main agent.",
                }
            },
            "required": ["result"],
        },
    },
}


def _extract_final_assistant_text(msgs: List[Dict[str, Any]]) -> str:
    """Return the text of the last assistant turn, ignoring thinking and tool
    calls. chat_loop stores only the streamed answer text (not reasoning) on the
    assistant message, so the most recent assistant message with text content is
    the clean conversation result."""
    for m in reversed(msgs):
        if m.get("role") != "assistant":
            continue
        content = m.get("content")
        if isinstance(content, str):
            if content.strip():
                return content
        elif isinstance(content, list):
            parts = [
                it.get("text", "")
                for it in content
                if isinstance(it, dict) and it.get("type") == "text"
            ]
            joined = "\n".join(p for p in parts if p)
            if joined.strip():
                return joined
    return "(subagent produced no final text output)"


class MCPAppendAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if getattr(namespace, 'mcp_configs', None) is None:
            setattr(namespace, 'mcp_configs', [])
        for v in values:
            namespace.mcp_configs.append({"endpoint": v, "api_key": None, "env_base": None})

class MCPAPIKeyAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        mcp_configs = getattr(namespace, 'mcp_configs', None)
        if not mcp_configs:
            parser.error(f"{option_string} must be provided after an --mcp argument")
        mcp_configs[-1]["api_key"] = values

class MCPEnvBaseAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        mcp_configs = getattr(namespace, 'mcp_configs', None)
        if not mcp_configs:
            parser.error(f"{option_string} must be provided after an --mcp argument")
        mcp_configs[-1]["env_base"] = values

async def async_main():
    parser = argparse.ArgumentParser(
        prog=alexis_version.APP_NAME,
        description="Stream multimodal input (text, images) to an LLM server with MCP support."
    )
    parser.add_argument("--version", action="version", version=alexis_version.get_title(),
                        help="Show the program version and exit.")

    parser.add_argument("input", type=str, nargs='?', default=None, help="Path to a text file containing the prompt, or the direct prompt string itself.")
    parser.add_argument("-p", "--prompt", type=str, default=None, help="Pass a direct string on the command line to use as the prompt.")
    parser.add_argument("--session", type=str, help="Path to a JSON file to save/load the chat history for continuous conversations.")
    parser.add_argument("--system", type=str, help="Path to a markdown text file containing the system message.")
    parser.add_argument("--agent-use-system-md", action="store_true", help="If present, prepend .agents/SYSTEM.md (from the current folder) to the system prompt when it exists. The user-global ~/.alexis/SYSTEM.md (override home via AI_AGENT_ALEXIS_HOME) is always included when present, regardless of this flag.")
    parser.add_argument("--agent-use-agents-md", action="store_true", help="If present, append AGENTS.md (from the current folder) to the system prompt when it exists.")
    parser.add_argument("--agent-use-skills", action="store_true", help="If present, discover skills (Agent Skills protocol) and add their names/descriptions to the system prompt. Searches the project's .agents/skills/ first, then the user-global ~/.alexis/skills/ (override home via AI_AGENT_ALEXIS_HOME).")
    parser.add_argument("--images", type=str, nargs='+', help="Path(s) to image files to include in the prompt.")
    parser.add_argument("--assets", type=str, nargs='+', help="Path(s) to folder(s) containing image (png, jpg, jpeg) files to automatically include in the prompt.")
    parser.add_argument("--mcp", type=str, action=MCPAppendAction, nargs='+', help="Commands to start MCP servers (e.g., 'npx -y ...') or HTTP URLs ('http://.../sse' for SSE, 'http://.../mcp' for Streamable HTTP). Can be specified multiple times.")
    parser.add_argument("--mcp-api-key", type=str, action=MCPAPIKeyAction, help="API key for the preceding MCP server.")
    parser.add_argument("--mcp-env-base", type=str, action=MCPEnvBaseAction, help="Prefix for environment variables to pass to the preceding MCP server in stdio mode.")
    # Generalised bundled MCP servers: one --agent-use-mcp-<name> flag per
    # mcp/mcp-server-<name>.py shipped next to this script. Enabling one attaches
    # that server (stdio) and forwards it to subagents. Drop a new
    # mcp-server-<name>.py into mcp/ and its flag appears here automatically.
    for _mcp_name in discover_bundled_mcp_servers():
        parser.add_argument(f"--agent-use-mcp-{_mcp_name}", action="store_true",
                            help=bundled_mcp_help(_mcp_name))
    parser.add_argument("--agent-internal-mcp-subagent", action="store_true", help="Attach this agent itself as a bundled stdio Subagent MCP server (like --agent-use-mcp-skills) — equivalent to '--mcp \"python <THIS_SCRIPT> --agent-as-mcp-server --agent-mcp-transport stdio <forwarded config>\"'. The spawned subagent inherits the main agent's LLM driver/url/model/generation settings, the --agent-use-* capability flags, and the full environment, and exposes a 'subagent(prompt)' tool that runs a full conversation and returns only the final answer.")
    parser.add_argument("--mcp-subagent-use-processing-done", action="store_true", help="With --agent-internal-mcp-subagent, forward --subagent-mcp-main to the spawned subagent so it registers the in-process 'Main' server's processing_done(result) tool and returns that result as its output (instead of its final assistant text).")
    parser.add_argument("--agent-subagent-tree", action="store_true", help="With --agent-internal-mcp-subagent, also forward --agent-internal-mcp-subagent (and --mcp-subagent-use-processing-done, if set) to each spawned subagent, so subagents can recursively spawn their own subagents. Depth is bounded by --agent-subagent-level.")
    parser.add_argument("--agent-subagent-level", type=int, default=3, help="Maximum subagent tree depth below this agent (default: 3, i.e. main -> subagent[1] -> subagent[2] -> subagent[3]). Decremented for each spawned subagent; at 0 no further subagent is registered. Only meaningful with --agent-internal-mcp-subagent (and recursion needs --agent-subagent-tree).")
    parser.add_argument("--provider", type=str, default=None, help="Name of a provider defined in ~/.alexis/config.jsonc to use for the LLM connection (driver/url/api-key/model). Defaults to that file's 'default-provider'. Individual --llm-driver/--url/--api-key/--model flags override the provider's values.")
    parser.add_argument("--llm-driver", type=str, default=None, choices=get_llm_drivers(), help=f"LLM driver to use (default: config provider, else 'llama'). Available: {', '.join(get_llm_drivers())}")
    parser.add_argument("--ui-driver", type=str, default="simple", choices=get_ui_driver_names(), help=f"UI driver/mode to use (default: simple). Available: {', '.join(get_ui_driver_names())}")
    parser.add_argument("--url", type=str, default=None, help="URL of the server (default: config provider, else http://127.0.0.1:8080/v1/chat/completions)")
    parser.add_argument("--temp", type=float, default=0.7, help="Generation temperature (default: 0.7)")
    parser.add_argument("--max-tokens", type=int, default=-1, help="Maximum tokens to predict. -1 means infinity (default: -1)")
    parser.add_argument("--api-key", type=str, default=None, help="API key for the server (default: config provider, else API_KEY env var)")
    parser.add_argument("--model", type=str, default=None, help="Model name (default: config provider, else 'default'; e.g. 'gemini-2.5-flash' for Gemini)")
    parser.add_argument("--context-limit", type=int, default=None, help="Maximum context size (e.g., 8192) to display usage percentage.")
    parser.add_argument("--usage-file", type=str, default=None, help="Path to a JSON file to save and load lifetime token usage tracking.")
    parser.add_argument("--tool-session", type=str, default=None, help="Path to a JSON file to log the tool descriptions loaded into the model.")
    parser.add_argument("--insecure", action="store_true", help="Allow insecure server connections when using SSL (disable certificate verification).")
    parser.add_argument("--timeout", type=int, default=None, help="Timeout in seconds for HTTP requests (default: infinite in interactive mode, 900s in batch mode)")
    parser.add_argument("--prompt-timeout", type=int, default=None, help="Maximum overall time in seconds allowed for the generation (default: infinite in interactive mode, 900s in batch mode).")
    parser.add_argument("--debug", type=str, default=None, help="Path to a JSONL file to log API requests and responses for debugging.")
    parser.add_argument("--no-spinner", action="store_true", help="Disable the thinking and working spinner animation on the console.")
    parser.add_argument("--join-tool-processing", action=argparse.BooleanOptionalAction, default=True, help="In the textual UI, render each tool call and its result as a single title-only TOOL block (TOOL - name - sent/received bytes). Use --no-join-tool-processing for separate TOOL CALL / TOOL RESULT blocks. (default: on)")
    parser.add_argument("-o", "--output", type=str, default=None, help="Path to a file to save only the final text output (no thinking/tool call).")
    parser.add_argument("--reasoning-effort", type=str, choices=["low", "medium", "high"], default=None, help="Thinking mode/reasoning effort for supported models.")
    parser.add_argument("--no-include-thoughts", action="store_false", dest="include_thoughts", default=True, help="Exclude the model's reasoning thoughts from the output.")

    # New interactive and API mode arguments
    parser.add_argument("-i", "--interactive", action="store_true", help="Start an interactive terminal chat loop.")
    parser.add_argument("--api-port", type=int, default=None, help="Start an HTTP API server on this port for GUI clients (SSE streaming).")
    parser.add_argument("--api-host", type=str, default="127.0.0.1", help="Host interface for the API server (default: 127.0.0.1).")

    # Agent-as-MCP-server (Subagent) mode
    parser.add_argument("--agent-as-mcp-server", action="store_true", help="Run this agent itself as an MCP server named 'Subagent' (instead of the chat UI). It exposes a single tool that accepts a text prompt, runs a full agentic conversation using this same agent's configuration (LLM driver/url/model, MCP servers, skills, system prompt + SUBAGENTS.md) and returns only the final answer text (no thinking / tool traces).")
    parser.add_argument("--agent-mcp-transport", choices=["stdio", "http"], default="stdio", help="Transport for --agent-as-mcp-server: 'stdio' (default) or 'http' (Streamable HTTP).")
    parser.add_argument("--agent-mcp-host", type=str, default="127.0.0.1", help="Host interface for --agent-as-mcp-server when transport is http (default: 127.0.0.1).")
    parser.add_argument("--agent-mcp-port", type=int, default=48200, help="Port for --agent-as-mcp-server when transport is http (default: 48200).")
    parser.add_argument("--agent-mcp-api-key", type=str, default=os.environ.get("AGENT_MCP_API_KEY"), help="Require this API key for --agent-as-mcp-server http requests (or AGENT_MCP_API_KEY env var).")
    parser.add_argument("--agent-mcp-name", type=str, default="Subagent", help="Server name (and base for the exposed tool name) for --agent-as-mcp-server (default: Subagent).")
    parser.add_argument("--subagent-mcp-main", action="store_true", help="Expose an in-process MCP server named 'Main' to the subagent with a 'processing_done(result)' tool. When the subagent calls it, that result is returned to the caller (the main agent) and the conversation ends. Without this flag, the subagent's final assistant text is returned instead.")

    args = parser.parse_args()

    # Startup header: app name + version (sourced from version.json).
    print(f"\033[96m{alexis_version.get_startup_header()}\033[0m", file=sys.stderr)
    print(f"\033[90m[*] Home: {alexis_home()} (override with AI_AGENT_ALEXIS_HOME)\033[0m", file=sys.stderr)

    # User config (~/.alexis/config.jsonc): resolve the selected provider and use
    # its driver/url/api-key/model as defaults. Explicit CLI flags always win;
    # below them comes the provider, then the built-in defaults / API_KEY env var.
    DEFAULT_URL = "http://127.0.0.1:8080/v1/chat/completions"
    try:
        _config = alexis_config.load_config(alexis_home())
    except ValueError as e:
        print(f"\033[91m[!] {e}\033[0m", file=sys.stderr)
        sys.exit(1)
    try:
        _provider_name, _provider = alexis_config.resolve_provider(_config, args.provider)
    except ValueError as e:
        print(f"\033[91m[!] {e}\033[0m", file=sys.stderr)
        sys.exit(1)
    if _provider_name:
        if args.llm_driver is None and _provider.get("driver"):
            _pd = _provider["driver"]
            if _pd not in get_llm_drivers():
                print(f"\033[91m[!] Provider '{_provider_name}' uses unknown driver '{_pd}'. Available: {', '.join(get_llm_drivers())}\033[0m", file=sys.stderr)
                sys.exit(1)
            args.llm_driver = _pd
        if args.url is None and _provider.get("url"):
            args.url = _provider["url"]
        if args.api_key is None and _provider.get("api_key") is not None:
            args.api_key = _provider["api_key"]
        if args.model is None and _provider.get("model"):
            args.model = _provider["model"]
        print(f"\033[94m[*] Provider '{_provider_name}' (from {alexis_config.config_path(alexis_home())})\033[0m", file=sys.stderr)
    # Fill any still-unset connection settings from the built-in defaults.
    if args.llm_driver is None:
        args.llm_driver = "llama"
    if args.url is None:
        args.url = DEFAULT_URL
    if args.model is None:
        args.model = "default"
    if args.api_key is None:
        args.api_key = os.environ.get("API_KEY")

    # Snapshot the user's explicit --mcp servers BEFORE the --agent-use-mcp-*
    # blocks append their own (workspace/skills) entries. These are forwarded
    # verbatim to internal subagents so a subagent gets the same MCP tools as the
    # parent (the bundled workspace/skills servers are forwarded as flags instead).
    _user_mcp_configs = [dict(c) for c in (getattr(args, 'mcp_configs', None) or [])]

    # Auto-detect UI driver from legacy arguments if not explicitly set
    if args.ui_driver == "simple":
        if args.api_port:
            args.ui_driver = "api"
        elif args.interactive:
            args.ui_driver = "interactive"

    # Bundled MCP servers: for each enabled --agent-use-mcp-<name>, attach
    # mcp/mcp-server-<name>.py (stdio), apply its env defaults, and remember the
    # name so it can be forwarded to subagents. This data-driven loop replaces the
    # former per-server (workspace/skills) blocks; special wiring lives in
    # SPECIAL_MCP_SERVERS, anything else gets a generic env-base of <NAME>.
    # The interpreter and script path are quoted so the command round-trips
    # through shlex.split at launch time (handles spaces/backslashes on Windows).
    _enabled_bundled_mcp: List[str] = []
    for _name in discover_bundled_mcp_servers():
        if not getattr(args, "agent_use_mcp_" + _name.replace("-", "_"), False):
            continue
        _script = resolve_mcp_server_path(_name)
        if not _script:
            print(f"\033[91m[!] Error: MCP server '{_name}' not found in {', '.join(mcp_server_dirs())}\033[0m", file=sys.stderr)
            sys.exit(1)
        _spec = bundled_mcp_server_spec(_name)
        _env_base = _spec.get("env_base")
        _endpoint = f"{shlex.quote(sys.executable)} {shlex.quote(_script)} --stdio"
        if getattr(args, 'mcp_configs', None) is None:
            args.mcp_configs = []
        args.mcp_configs.append({"endpoint": _endpoint, "api_key": None, "env_base": _env_base})
        # Apply env defaults (set only when unset) so the server works out of the
        # box; a user who sets these before launch keeps full control.
        _defaults = _spec.get("env_defaults") or {}
        if callable(_defaults):
            _defaults = _defaults()
        for _k, _v in _defaults.items():
            os.environ.setdefault(_k, _v)
        _enabled_bundled_mcp.append(_name)
        _extra = f" (env-base {_env_base})" if _env_base else ""
        print(f"\033[94m[*] MCP '{_name}' enabled: {_script}{_extra}\033[0m", file=sys.stderr)

    # --agent-internal-mcp-subagent: attach THIS script, relaunched in subagent
    # mode, as a bundled stdio MCP server — the same pattern as
    # --agent-use-mcp-skills, but the "server" is the agent itself. We forward the
    # main agent's LLM/generation config, the --agent-use-* capability flags, and
    # the user's explicit --mcp servers so the subagent matches the parent, and we
    # pass the full environment (env_base lets the stdio client copy os.environ;
    # SUBAGENT_*-prefixed vars are also mapped in for per-subagent overrides).
    #
    # Recursion is bounded by --agent-subagent-level (default 3): each spawned
    # subagent is given level-1, and a subagent is only registered while level>0
    # (at 0 the tree stops). --agent-subagent-tree is what actually re-forwards
    # --agent-internal-mcp-subagent to the child, letting subagents spawn their own
    # subagents; without it only a single layer is created.
    _subagent_level = getattr(args, 'agent_subagent_level', 3)
    if _subagent_level is None:
        _subagent_level = 3
    if getattr(args, 'agent_internal_mcp_subagent', False) and _subagent_level > 0:
        self_script = os.path.abspath(__file__)
        child_level = _subagent_level - 1
        tree_on = getattr(args, 'agent_subagent_tree', False)
        done_on = getattr(args, 'mcp_subagent_use_processing_done', False)
        parts = [sys.executable, self_script, "--agent-as-mcp-server",
                 "--agent-mcp-transport", "stdio"]
        # LLM connection + generation settings (mirror the main agent).
        parts += ["--llm-driver", args.llm_driver, "--url", args.url,
                  "--model", args.model, "--temp", str(args.temp)]
        if args.api_key:
            parts += ["--api-key", args.api_key]
        if args.max_tokens is not None and args.max_tokens != -1:
            parts += ["--max-tokens", str(args.max_tokens)]
        if args.context_limit is not None:
            parts += ["--context-limit", str(args.context_limit)]
        if args.reasoning_effort:
            parts += ["--reasoning-effort", args.reasoning_effort]
        if args.insecure:
            parts += ["--insecure"]
        if args.timeout is not None:
            parts += ["--timeout", str(args.timeout)]
        # Capability flags: let the subagent assemble the same SYSTEM.md/AGENTS.md/
        # skills context and attach the same bundled MCP servers. SUBAGENTS.md is
        # added automatically in subagent mode.
        if getattr(args, 'agent_use_system_md', False): parts += ["--agent-use-system-md"]
        if getattr(args, 'agent_use_agents_md', False): parts += ["--agent-use-agents-md"]
        if getattr(args, 'agent_use_skills', False): parts += ["--agent-use-skills"]
        # Forward every enabled bundled MCP server (--agent-use-mcp-<name>); the
        # subagent re-discovers them from its own mcp/ and attaches the same set.
        for _name in _enabled_bundled_mcp:
            parts += [f"--agent-use-mcp-{_name}"]
        # Forward the user's explicit --mcp servers verbatim (endpoint + optional
        # api-key / env-base) so the subagent gets the same external tools.
        for cfg in _user_mcp_configs:
            ep = cfg.get("endpoint")
            if not ep:
                continue
            parts += ["--mcp", ep]
            if cfg.get("api_key"):
                parts += ["--mcp-api-key", cfg["api_key"]]
            if cfg.get("env_base"):
                parts += ["--mcp-env-base", cfg["env_base"]]
        # Forward the processing_done switch so the subagent registers the Main
        # tool and returns its 'result' parameter as the output.
        if done_on:
            parts += ["--subagent-mcp-main"]
        # In tree mode, re-arm the child so it can spawn its own subagents, but
        # only while there is depth budget left (child_level>0). The child carries
        # its decremented level; processing_done re-forwards too so the whole tree
        # behaves consistently.
        recursion_on = tree_on and child_level > 0
        if recursion_on:
            parts += ["--agent-internal-mcp-subagent", "--agent-subagent-tree",
                      "--agent-subagent-level", str(child_level)]
            if done_on:
                parts += ["--mcp-subagent-use-processing-done"]
        endpoint = " ".join(shlex.quote(p) for p in parts)
        if getattr(args, 'mcp_configs', None) is None:
            args.mcp_configs = []
        # env_base="SUBAGENT" makes the stdio client copy the full parent
        # environment to the child (API keys, WORKSPACE_DIR, MCP_SKILLS_AGENT_DIR,
        # ...) and additionally map any SUBAGENT_*-prefixed vars without prefix.
        args.mcp_configs.append({"endpoint": endpoint, "api_key": None, "env_base": "SUBAGENT"})
        done_note = " (with processing_done)" if done_on else ""
        tree_note = f", tree -> children get level {child_level}" if recursion_on else ""
        print(f"\033[94m[*] Internal Subagent MCP enabled{done_note} (level {_subagent_level}{tree_note}): {self_script}\033[0m", file=sys.stderr)
    elif getattr(args, 'agent_internal_mcp_subagent', False):
        # Flag was set but the depth budget is exhausted — stop the tree here.
        print("\033[93m[!] Subagent tree level is 0; not registering a further subagent.\033[0m", file=sys.stderr)
    elif getattr(args, 'mcp_subagent_use_processing_done', False) or getattr(args, 'agent_subagent_tree', False):
        print("\033[93m[!] Note: --mcp-subagent-use-processing-done / --agent-subagent-tree have no effect without --agent-internal-mcp-subagent.\033[0m", file=sys.stderr)

    # Determine if this is an interactive/api mode that doesn't require input
    is_interactive_mode = args.ui_driver in ["interactive", "textual"]
    is_api_mode = args.ui_driver == "api" or args.api_port
    # Subagent mode: this process serves as an MCP server, so it has no up-front
    # prompt of its own — each prompt arrives per tool call.
    is_subagent_server = getattr(args, 'agent_as_mcp_server', False)
    requires_input = not (is_interactive_mode or is_api_mode or args.session or is_subagent_server)

    # Set timeout defaults based on mode: infinite for interactive, 15 min for batch
    if not (is_interactive_mode or is_api_mode):
        # Batch/background mode: 15 minutes (900 seconds) default if not provided
        if args.timeout is None:
            args.timeout = 900
        if args.prompt_timeout is None:
            args.prompt_timeout = 900
    # else: Interactive/API mode keeps None (infinite timeout)

    # Ensure at least some form of input or operational mode was provided
    # Only enforce input requirement for non-interactive/non-api modes (simple driver)
    if requires_input and not any([args.input, args.prompt, args.images, args.assets]):
        parser.error(
            f"UI driver '{args.ui_driver}' requires input. "
            "Provide: --prompt, input file, --images, or --assets. "
            "Or use --ui-driver interactive/textual/api for interactive modes."
        )

    # Truncate/initialize output file if specified
    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as f:
                pass
        except Exception as e:
            print(f"\033[91m[!] Error creating output file '{args.output}': {e}\033[0m", file=sys.stderr)
            sys.exit(1)

    if args.insecure:
        # Globally disable SSL verification for standard library functions
        ssl._create_default_https_context = ssl._create_unverified_context

    api_key = args.api_key

    # Create LLM driver instance
    try:
        llm_driver = create_llm_driver(args.llm_driver, args.url, api_key)
        print(f"\033[94m[*] Using LLM driver: {args.llm_driver}\033[0m", file=sys.stderr)
    except ValueError as e:
        print(f"\033[91m[!] Error: {e}\033[0m", file=sys.stderr)
        sys.exit(1)

    if args.url.endswith("/completion"):
        print("\033[93m[*] Notice: Auto-correcting URL from '/completion' to '/v1/chat/completions' for Chat API & MCP support.\033[0m", file=sys.stderr)
        args.url = args.url.replace("/completion", "/v1/chat/completions")
        llm_driver.url = args.url

    # Create UI driver instance (not needed when running as a subagent MCP server)
    ui_driver = None
    if not is_subagent_server:
        try:
            ui_driver = create_ui_driver(args.ui_driver)
            print(f"\033[94m[*] Using UI driver: {args.ui_driver}\033[0m", file=sys.stderr)
            if not ui_driver.validate_args(args):
                sys.exit(1)
        except ValueError as e:
            print(f"\033[91m[!] Error: {e}\033[0m", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"\033[94m[*] Running as Subagent MCP server (transport: {args.agent_mcp_transport})\033[0m", file=sys.stderr)

    # Verify MCP dependencies
    if getattr(args, 'mcp_configs', None):
        try:
            import mcp
            from mcp.client.stdio import stdio_client, StdioServerParameters
            from mcp.client.sse import sse_client
            from mcp.client.session import ClientSession
            try:
                from mcp.client.streamable_http import streamablehttp_client
            except ImportError:
                streamablehttp_client = None

        except ImportError:
            print("\033[91m[!] Error: The 'mcp' library is required to use MCP servers.\033[0m", file=sys.stderr)
            print("\033[93m    Install it with: pip install mcp\033[0m", file=sys.stderr)
            sys.exit(1)

    messages = []
    session_msg_count = 0
    usage_tracker = {}
    tool_history = []

    # State Loaders
    if args.session and os.path.exists(args.session):
        try:
            with open(args.session, 'r', encoding='utf-8') as f:
                messages = json.load(f)
            session_msg_count = len(messages)
            print(f"\033[94m[*] Loaded previous session from {args.session} ({session_msg_count} messages)\033[0m", file=sys.stderr)
        except Exception as e:
            print(f"\033[91m[!] Error loading session '{args.session}': {e}\033[0m", file=sys.stderr)
            sys.exit(1)
            
    if args.usage_file and os.path.exists(args.usage_file):
        try:
            with open(args.usage_file, 'r', encoding='utf-8') as f:
                usage_tracker = json.load(f)
            print(f"\033[94m[*] Loaded token usage tracking from {args.usage_file}\033[0m", file=sys.stderr)
        except Exception as e:
            print(f"\033[91m[!] Error loading usage file '{args.usage_file}': {e}\033[0m", file=sys.stderr)
            sys.exit(1)

    if args.tool_session and os.path.exists(args.tool_session):
        try:
            with open(args.tool_session, 'r', encoding='utf-8') as f:
                tool_history = json.load(f)
            print(f"\033[94m[*] Loaded tool history from {args.tool_session}\033[0m", file=sys.stderr)
        except Exception as e:
            print(f"\033[91m[!] Error loading tool session '{args.tool_session}': {e}\033[0m", file=sys.stderr)
            sys.exit(1)

    # System Message — assembled, in order, from:
    #   1. .agents/SYSTEM.md  (--agent-use-system-md, if the file exists)
    #   2. AGENTS.md          (--agent-use-agents-md, if the file exists)
    #   3. --system file      (explicit path, kept for backward compatibility)
    # Only injected when the session doesn't already carry a system message.
    if not any(m.get("role") == "system" for m in messages):
        system_parts = []

        def _read_system_source(path, label, required):
            """Append a source's text to system_parts. `required` sources error
            out if unreadable; optional agent files are skipped when absent."""
            if not os.path.isfile(path):
                if required:
                    print(f"\033[91m[!] Error reading system file '{path}': not found\033[0m", file=sys.stderr)
                    sys.exit(1)
                print(f"\033[90m[*] {label} not found at {path}, skipping.\033[0m", file=sys.stderr)
                return
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    system_parts.append(f.read())
                print(f"\033[94m[*] Loaded {label} from {path}\033[0m", file=sys.stderr)
            except Exception as e:
                print(f"\033[91m[!] Error reading '{path}': {e}\033[0m", file=sys.stderr)
                sys.exit(1)

        # User-global system prompt: ~/.alexis/SYSTEM.md (override the home via
        # AI_AGENT_ALEXIS_HOME). Always included when present so the user's
        # personal agent persona applies regardless of project-level flags. Goes
        # first so project .agents/SYSTEM.md and --system can refine it.
        _home_system = os.path.join(alexis_home(), "SYSTEM.md")
        if os.path.isfile(_home_system):
            _read_system_source(_home_system, "user system prompt (~/.alexis)", required=False)
        if getattr(args, 'agent_use_system_md', False):
            _read_system_source(os.path.join(".agents", "SYSTEM.md"), "agent system prompt", required=False)
        if getattr(args, 'agent_use_agents_md', False):
            _read_system_source("AGENTS.md", "agent guidance", required=False)
        if getattr(args, 'agent_use_skills', False):
            # Search every agent root (project first, then bundled). Dedupe by
            # skill name so an earlier (project) skill shadows a bundled one of
            # the same name — matching the skills MCP server's resolution order.
            searched_dirs = [os.path.join(r, "skills") for r in agent_skill_roots()]
            skills = []
            seen_names = set()
            for skills_dir in searched_dirs:
                for name, desc, path in discover_skills(skills_dir):
                    if name in seen_names:
                        continue
                    seen_names.add(name)
                    skills.append((name, desc, path))
            if skills:
                system_parts.append(build_skills_prompt(skills))
                print(f"\033[94m[*] Loaded {len(skills)} skill(s) from {', '.join(searched_dirs)}\033[0m", file=sys.stderr)
            else:
                print(f"\033[90m[*] No skills found under {', '.join(searched_dirs)}, skipping.\033[0m", file=sys.stderr)
        # In subagent mode, append SUBAGENTS.md (after SYSTEM.md/AGENTS.md/SKILLS)
        # so the agent knows it is acting as a subagent and what its role is.
        if is_subagent_server:
            _read_system_source("SUBAGENTS.md", "subagent role", required=False)
        if args.system:
            _read_system_source(args.system, "system message", required=True)

        combined = "\n\n".join(p.strip() for p in system_parts if p and p.strip())
        if combined:
            messages.insert(0, {"role": "system", "content": combined})
            session_msg_count += 1

    # Process Initial Assets & Images
    if getattr(args, 'assets', None):
        if args.images is None: args.images = []
        for asset_dir in args.assets:
            if os.path.isdir(asset_dir):
                print(f"\033[94m[*] Scanning assets folder: {asset_dir}...\033[0m", file=sys.stderr)
                for filename in sorted(os.listdir(asset_dir)):
                    filepath = os.path.join(asset_dir, filename)
                    if os.path.isfile(filepath):
                        ext = os.path.splitext(filename)[1].lower()
                        if ext in ['.png', '.jpg', '.jpeg'] and filepath not in args.images:
                            args.images.append(filepath)

    user_content = []
    prompt_text = ""
    
    if args.input:
        if os.path.isfile(args.input):
            try:
                with open(args.input, 'r', encoding='utf-8') as f:
                    prompt_text = f.read()
            except Exception as e:
                print(f"\033[91m[!] Error reading file '{args.input}': {e}\033[0m", file=sys.stderr)
                sys.exit(1)
        else:
            if len(args.input) < 256 and " " not in args.input and "." in args.input:
                print(f"\033[93m[*] Warning: '{args.input}' looks like a filename but was not found. Treating as text prompt.\033[0m", file=sys.stderr)
            prompt_text = args.input

    if args.prompt:
        if prompt_text: prompt_text += "\n\n" + args.prompt
        else: prompt_text = args.prompt

    if prompt_text and prompt_text.strip():
        user_content.append({"type": "text", "text": prompt_text.strip()})

    if args.images:
        for img_path in args.images:
            file_size = os.path.getsize(img_path)
            if file_size > 15 * 1024 * 1024:
                print(f"\033[93m[!] Warning: Image '{img_path}' is very large ({file_size / 1024 / 1024:.1f}MB).\033[0m", file=sys.stderr)
            print(f"\033[94m[*] Encoding image: {img_path}...\033[0m", file=sys.stderr)
            try:
                b64, mime = encode_image(img_path)
                user_content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
            except Exception as e:
                print(f"\033[91m[!] Error processing image '{img_path}': {e}\033[0m", file=sys.stderr)
                sys.exit(1)

    if user_content:
        messages.append({"role": "user", "content": user_content})

    # MCP Setup Context
    async with AsyncExitStack() as stack:
        tools_list = []
        tool_to_session = {}
        mcp_server_names = []
        
        mcp_configs = getattr(args, 'mcp_configs', None)
        if mcp_configs:
            for mcp_config in mcp_configs:
                endpoint = mcp_config["endpoint"]
                mcp_api_key = mcp_config["api_key"]
                mcp_env_base = mcp_config["env_base"]
                
                try:
                    if endpoint.startswith("http://") or endpoint.startswith("https://"):
                        kwargs = {}
                        if mcp_api_key: kwargs["headers"] = {"Authorization": f"Bearer {mcp_api_key}"}

                        if endpoint.rstrip('/').endswith('/mcp'):
                            if streamablehttp_client is None:
                                print(f"\033[91m[!] Error: 'streamablehttp_client' is not available in your 'mcp' library version.\033[0m", file=sys.stderr)
                                sys.exit(1)
                            print(f"\033[94m[*] Initializing MCP Server (Streamable HTTP): {endpoint}\033[0m", file=sys.stderr)
                            transport = await stack.enter_async_context(streamablehttp_client(endpoint, **kwargs))
                        else:
                            print(f"\033[94m[*] Initializing MCP Server (SSE): {endpoint}\033[0m", file=sys.stderr)
                            transport = await stack.enter_async_context(sse_client(endpoint, **kwargs))
                    else:
                        print(f"\033[94m[*] Initializing MCP Server (Stdio): {endpoint}\033[0m", file=sys.stderr)
                        parts = shlex.split(endpoint)
                        
                        server_env = None
                        if mcp_env_base:
                            server_env = os.environ.copy()
                            prefix = f"{mcp_env_base}_" if not mcp_env_base.endswith('_') else mcp_env_base
                            mapped_count = 0
                            for k, v in os.environ.items():
                                if k.startswith(prefix):
                                    server_env[k[len(prefix):]] = v
                                    mapped_count += 1
                            if mapped_count > 0:
                                print(f"\033[90m    - Injected {mapped_count} env vars mapped from prefix '{prefix}'\033[0m", file=sys.stderr)
                        
                        server_params = StdioServerParameters(command=parts[0], args=parts[1:], env=server_env)
                        transport = await stack.enter_async_context(stdio_client(server_params))
                    
                    read, write = transport[0], transport[1]
                    session = await stack.enter_async_context(ClientSession(read, write))
                    init_result = await session.initialize()
                    server_name = (
                        getattr(getattr(init_result, "serverInfo", None), "name", None)
                        or _mcp_display_name(endpoint)
                    )
                    mcp_server_names.append(server_name)

                    mcp_tools = await session.list_tools()
                    print(f"\033[92m    -> Connected. Extracted {len(mcp_tools.tools)} tools.\033[0m", file=sys.stderr)
                    
                    for t in mcp_tools.tools:
                        if t.name in tool_to_session:
                            tools_list = [tool for tool in tools_list if tool.get("function", {}).get("name") != t.name]
                        tool_to_session[t.name] = session
                        tools_list.append({
                            "type": "function",
                            "function": {
                                "name": t.name,
                                "description": t.description,
                                "parameters": t.inputSchema
                            }
                        })
                except BaseException as e:
                    if isinstance(e, (KeyboardInterrupt, SystemExit)): raise
                    print(f"\033[93m[!] Warning: Unable to connect to MCP server '{endpoint}'.\033[0m", file=sys.stderr)
                    print(f"\033[93m    Details: [{type(e).__name__}] {str(e)}\033[0m", file=sys.stderr)
                    raise

        if args.tool_session:
            tool_history.append({"timestamp": time.time(), "tools": tools_list})

        async def run_single_turn(queue=None, cancel_event=None):
            chat_coro = chat_loop(
                driver=llm_driver,
                messages=messages,
                tools=tools_list,
                tool_to_session=tool_to_session,
                temperature=args.temp,
                n_predict=args.max_tokens,
                model=args.model,
                context_limit=args.context_limit,
                session_msg_count=session_msg_count,
                usage_tracker=usage_tracker,
                insecure=args.insecure,
                timeout=args.timeout,
                debug_file=args.debug,
                no_spinner=args.no_spinner,
                output_file=args.output,
                reasoning_effort=args.reasoning_effort,
                include_thoughts=args.include_thoughts,
                stream_queue=queue,
                cancel_event=cancel_event
            )
            if args.prompt_timeout and args.prompt_timeout > 0:
                await asyncio.wait_for(chat_coro, timeout=args.prompt_timeout)
            else:
                await chat_coro

        # Helper to Save State
        def save_state():
            if args.session:
                try:
                    with open(args.session, 'w', encoding='utf-8') as f: json.dump(messages, f, indent=2)
                except Exception: pass
            if args.usage_file and usage_tracker:
                try:
                    with open(args.usage_file, 'w', encoding='utf-8') as f: json.dump(usage_tracker, f, indent=2)
                except Exception: pass
            if args.tool_session:
                try:
                    with open(args.tool_session, 'w', encoding='utf-8') as f: json.dump(tool_history, f, indent=2)
                except Exception: pass

        # Original session path, used as the base when /reset rotates to a new
        # file so repeated resets don't keep stacking timestamp suffixes.
        _session_base = args.session

        # Helper to start a fresh session for /reset. Clears the conversation
        # (keeping any system prompt), resets per-session counters and usage,
        # and points future saves at a new timestamped file so the previous
        # conversation is preserved on disk. Returns the new session path.
        def reset_session():
            nonlocal session_msg_count
            system_msgs = [m for m in messages if m.get("role") == "system"]
            messages.clear()
            messages.extend(system_msgs)
            session_msg_count = len(messages)
            try:
                usage_tracker.clear()
            except Exception:
                pass
            new_path = None
            if _session_base:
                base, ext = os.path.splitext(_session_base)
                new_path = f"{base}-{datetime.now():%Y%m%d-%H%M%S}{ext or '.json'}"
                args.session = new_path
            return new_path

        # Build a short display name for each configured MCP server.
        def _mcp_display_name(endpoint: str) -> str:
            if endpoint.startswith("http://") or endpoint.startswith("https://"):
                from urllib.parse import urlparse
                p = urlparse(endpoint)
                return p.netloc or endpoint
            # stdio: use the command name (first token)
            return shlex.split(endpoint)[0].split("/")[-1].split("\\")[-1]

        # Subagent MCP server mode: expose this whole agent as one MCP tool.
        async def run_as_subagent_server():
            try:
                from mcp.server.fastmcp import FastMCP
            except ImportError:
                print("\033[91m[!] Error: The 'mcp' library is required for --agent-as-mcp-server.\033[0m", file=sys.stderr)
                print("\033[93m    Install it with: pip install mcp\033[0m", file=sys.stderr)
                sys.exit(1)

            server_name = args.agent_mcp_name or "Subagent"
            subagent_mcp = FastMCP(server_name, stateless_http=True, json_response=False)

            # The assembled system prompt (messages[0]) is the per-call baseline;
            # each tool call starts from a fresh copy and appends the user prompt.
            base_messages = [dict(m) for m in messages]
            base_count = len(base_messages)

            # Calls share the connected MCP sessions, so serialize them.
            call_lock = asyncio.Lock()

            # In-process "Main" server: processing_done(result) lets the subagent
            # hand a final result straight back to the caller. The holder is reset
            # per call (safe because calls are serialized by call_lock).
            main_enabled = getattr(args, 'subagent_mcp_main', False)
            main_holder: Dict[str, Any] = {"done": False, "result": None}
            main_session: Optional[_MainToolSession] = None
            if main_enabled:
                main_session = _MainToolSession(main_holder)
                tool_to_session["processing_done"] = main_session
                tools_list.append(MAIN_PROCESSING_DONE_TOOL)
                mcp_server_names.append("Main")
                print("\033[94m[*] Main MCP enabled: subagent can call processing_done(result) to return its result.\033[0m", file=sys.stderr)

            if mcp_server_names:
                print(f"\033[94m[*] Subagent tools available from: {', '.join(mcp_server_names)}\033[0m", file=sys.stderr)

            async def run_subagent(prompt: str) -> str:
                """Run a full agentic conversation as a subagent and return the
                final result (no thinking / tool traces).

                Args:
                    prompt: The task or question for the subagent to work on.
                """
                async with call_lock:
                    main_holder["done"] = False
                    main_holder["result"] = None
                    cancel_event = threading.Event()
                    if main_session is not None:
                        main_session.cancel_event = cancel_event

                    call_messages = [dict(m) for m in base_messages]
                    call_messages.append({"role": "user", "content": prompt})

                    chat_coro = chat_loop(
                        driver=llm_driver,
                        messages=call_messages,
                        tools=tools_list,
                        tool_to_session=tool_to_session,
                        temperature=args.temp,
                        n_predict=args.max_tokens,
                        model=args.model,
                        context_limit=args.context_limit,
                        session_msg_count=base_count,
                        usage_tracker={},
                        insecure=args.insecure,
                        timeout=args.timeout,
                        debug_file=args.debug,
                        no_spinner=True,
                        output_file=None,
                        reasoning_effort=args.reasoning_effort,
                        include_thoughts=args.include_thoughts,
                        stream_queue=None,
                        cancel_event=cancel_event,
                    )

                    # Redirect stdout to stderr so the subagent's streamed text /
                    # progress never corrupts the MCP JSON-RPC channel (stdio) or
                    # the HTTP server's stdout, while staying visible for debugging.
                    try:
                        with contextlib.redirect_stdout(sys.stderr):
                            if args.prompt_timeout and args.prompt_timeout > 0:
                                await asyncio.wait_for(chat_coro, timeout=args.prompt_timeout)
                            else:
                                await chat_coro
                    except asyncio.TimeoutError:
                        return f"Error: subagent timed out after {args.prompt_timeout}s."
                    except Exception as e:
                        return f"Error running subagent: {type(e).__name__}: {e}"

                    if main_enabled and main_holder["done"]:
                        return main_holder["result"] or ""
                    return _extract_final_assistant_text(call_messages)

            tool_desc = (
                "Delegate a task to a subagent: it runs a full, autonomous agentic "
                "conversation (with its own tools/skills) on the given prompt and "
                "returns only the final answer text. Use it to offload a self-contained "
                "subtask and get back a clean result."
            )
            subagent_mcp.add_tool(run_subagent, name="subagent", description=tool_desc)

            if args.agent_mcp_transport == "stdio":
                print(f"\033[92m[+] Subagent MCP server '{server_name}' ready (stdio).\033[0m", file=sys.stderr)
                await subagent_mcp.run_stdio_async()
            else:
                try:
                    import uvicorn
                    from starlette.middleware.cors import CORSMiddleware
                    from starlette.middleware.base import BaseHTTPMiddleware
                    from starlette.responses import JSONResponse
                except ImportError:
                    print("\033[91m[!] Error: 'uvicorn' and 'starlette' are required for http transport.\033[0m", file=sys.stderr)
                    sys.exit(1)

                app = subagent_mcp.streamable_http_app()

                if args.agent_mcp_api_key:
                    class _SubagentAPIKeyMiddleware(BaseHTTPMiddleware):
                        def __init__(self, app, api_key: str):
                            super().__init__(app)
                            self.api_key = api_key

                        async def dispatch(self, request, call_next):
                            if request.method == "OPTIONS":
                                return await call_next(request)
                            auth = request.headers.get("Authorization")
                            xkey = request.headers.get("X-API-Key")
                            provided = None
                            if auth and auth.startswith("Bearer "):
                                provided = auth.split(" ", 1)[1]
                            elif xkey:
                                provided = xkey
                            if not provided or provided != self.api_key:
                                return JSONResponse({"detail": "Unauthorized: Invalid or missing API Key"}, status_code=401)
                            return await call_next(request)

                    app.add_middleware(_SubagentAPIKeyMiddleware, api_key=args.agent_mcp_api_key)

                app.add_middleware(
                    CORSMiddleware,
                    allow_origins=["*"],
                    allow_credentials=True,
                    allow_methods=["*"],
                    allow_headers=["*"],
                )

                print(f"\033[92m[+] Subagent MCP server '{server_name}' ready (http) on {args.agent_mcp_host}:{args.agent_mcp_port}\033[0m", file=sys.stderr)
                config = uvicorn.Config(app, host=args.agent_mcp_host, port=args.agent_mcp_port, log_level="warning")
                await uvicorn.Server(config).serve()

        if is_subagent_server:
            await run_as_subagent_server()
        else:
            # Run the UI driver
            await ui_driver.run(
                run_single_turn=run_single_turn,
                messages=messages,
                save_state=save_state,
                user_content=user_content,
                api_host=args.api_host,
                api_port=args.api_port,
                session_path=args.session,
                context_limit=args.context_limit,
                reasoning_effort=args.reasoning_effort,
                mcp_servers=mcp_server_names,
                reset_session=reset_session,
                join_tool_processing=args.join_tool_processing,
            )

def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print("\n\n\033[93m[!] Execution interrupted by user.\033[0m", file=sys.stderr)        
        sys.exit(1)
    except SystemExit as e:
        sys.exit(e.code)
    except BaseException as e:
        sys.exit(1)

if __name__ == "__main__":
    main()