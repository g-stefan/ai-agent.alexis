# AI-Agent.Alexis
# SPDX-FileCopyrightText: 2026 Grigore Stefan <g_stefan@yahoo.com>
# SPDX-License-Identifier: Apache-2.0

"""User configuration loaded from ``<ALEXIS_HOME>/config.jsonc``.

The config file is JSONC (JSON with ``//`` and ``/* */`` comments and tolerant
of trailing commas). It defines named LLM *providers* and which one is the
default, an optional per-provider ``context-limit``, and an optional ``agent``
section holding default capability flags / UI driver:

    {
      "default-provider": "local-llama",
      "providers": {
        "local-llama": { "driver": "llama",  "url": "...", "api-key": null,  "model": "default", "context-limit": 8192 },
        "gemini":      { "driver": "gemini", "url": "...", "api-key": "...", "model": "gemini-2.5-flash", "context-limit": 1048576 }
      },
      "agent": {
        "use-system-md": true,
        "use-agents-md": true,
        "use-skills": true,
        "use-mcp-workspace": true,
        "use-mcp-skills": true,
        "internal-mcp-subagent": true,
        "ui-driver": "textual"
      }
    }

Command-line flags always override the values resolved from here (the boolean
``agent`` flags only enable capabilities, so the effective value is the union of
the flag and the config).
"""

import json
import os
import re
import shutil
from typing import Any, Dict, Optional, Tuple

CONFIG_FILENAME = "config.jsonc"


def strip_jsonc(text: str) -> str:
    """Return ``text`` with JSONC comments and trailing commas removed, leaving
    valid JSON. String literals are respected so ``//`` or ``/*`` inside a string
    is preserved."""
    out = []
    i, n = 0, len(text)
    in_str = False
    quote = ""
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:        # keep escaped char verbatim
                out.append(text[i + 1])
                i += 2
                continue
            if c == quote:
                in_str = False
            i += 1
            continue
        if c in ('"', "'"):
            in_str = True
            quote = c
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":   # // line comment
            i += 2
            while i < n and text[i] not in "\n\r":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":   # /* block comment */
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(c)
        i += 1
    result = "".join(out)
    # Drop trailing commas before a closing } or ].
    result = re.sub(r",(\s*[}\]])", r"\1", result)
    return result


def config_path(home_dir: str) -> str:
    """Return the path to the config file inside ``home_dir``."""
    return os.path.join(home_dir, CONFIG_FILENAME)


def load_config(home_dir: str) -> Dict[str, Any]:
    """Load and parse ``<home_dir>/config.jsonc``. Returns {} when the file is
    absent; raises ValueError with a helpful message when it is malformed."""
    path = config_path(home_dir)
    if not os.path.isfile(path):
        return {}
    try:
        # utf-8-sig tolerates a leading BOM, which Windows editors (Notepad)
        # often add; plain utf-8 would choke on it.
        with open(path, "r", encoding="utf-8-sig") as f:
            raw = f.read()
    except OSError as e:
        raise ValueError(f"Could not read {path}: {e}") from e
    try:
        data = json.loads(strip_jsonc(raw))
    except ValueError as e:
        raise ValueError(f"Invalid JSONC in {path}: {e}") from e
    return data or {}


def _get(provider: Dict[str, Any], *keys: str) -> Optional[Any]:
    """Return the first present key from ``provider`` (supports a few spellings)."""
    for k in keys:
        if k in provider and provider[k] is not None:
            return provider[k]
    return None


def resolve_provider(config: Dict[str, Any],
                     requested: Optional[str] = None) -> Tuple[Optional[str], Dict[str, Any]]:
    """Resolve the provider to use.

    Precedence for the name: explicit ``requested`` (e.g. --provider) first, then
    the config's ``default-provider``. Returns ``(name, params)`` where ``params``
    is a normalised dict with ``driver`` / ``url`` / ``api_key`` / ``model`` keys
    (values may be None). Returns ``(None, {})`` when no provider applies.

    Raises ValueError if a name is selected but not defined in ``providers``."""
    providers = config.get("providers") or {}
    name = requested or config.get("default-provider") or config.get("default_provider")
    if not name:
        return None, {}
    if name not in providers:
        available = ", ".join(sorted(providers)) or "(none)"
        raise ValueError(f"provider '{name}' not found in config; available: {available}")
    raw = providers[name] or {}
    params = {
        "driver": _get(raw, "driver", "llm-driver", "llm_driver"),
        "url": _get(raw, "url"),
        "api_key": _get(raw, "api-key", "api_key", "apiKey"),
        "model": _get(raw, "model"),
        # Per-provider context window — different providers/models have different
        # limits, so this lives on the provider rather than in [agent]. Used only
        # to show the context-usage percentage; --context-limit overrides it.
        "context_limit": _get(raw, "context-limit", "context_limit", "contextLimit"),
    }
    return name, params


def resolve_agent_defaults(config: Dict[str, Any]) -> Dict[str, Any]:
    """Return the ``[agent]`` section: persistent defaults for the agent
    capability flags and the UI driver, the config equivalent of passing
    ``--agent-use-*`` / ``--agent-internal-mcp-subagent`` / ``--ui-driver`` on the
    command line. Keys mirror the flag names without the ``--agent-`` prefix, e.g.
    ``use-skills``, ``use-mcp-workspace``, ``internal-mcp-subagent``, plus
    ``ui-driver``. Returns ``{}`` when the section is absent.

    Raises ValueError if present but not a JSON object."""
    agent = config.get("agent")
    if agent is None:
        agent = config.get("agent-defaults") or config.get("agent_defaults")
    if agent is None:
        return {}
    if not isinstance(agent, dict):
        raise ValueError("config 'agent' section must be an object")
    return agent


def resolve_ui_settings(config: Dict[str, Any]) -> Dict[str, Any]:
    """Return the ``[ui]`` section: persistent UI preferences such as which
    right-panel widgets are shown in detailed form. Keys are kebab-case, e.g.
    ``detailed-statistics`` / ``detailed-context``. Returns ``{}`` when absent.

    Raises ValueError if present but not a JSON object."""
    ui = config.get("ui")
    if ui is None:
        ui = config.get("ui-settings") or config.get("ui_settings")
    if ui is None:
        return {}
    if not isinstance(ui, dict):
        raise ValueError("config 'ui' section must be an object")
    return ui


def _ui_section(config: Dict[str, Any]) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Return ``(key, section)`` for the existing ``[ui]`` object, trying the
    accepted spellings. ``section`` is None when no such object exists yet (the
    caller then creates one under the returned ``key``, defaulting to ``"ui"``)."""
    for key in ("ui", "ui-settings", "ui_settings"):
        sec = config.get(key)
        if isinstance(sec, dict):
            return key, sec
    return "ui", None


def set_ui_flag(config: Dict[str, Any], key: str, enabled: bool) -> None:
    """Set ``ui.<key>`` to ``enabled`` in ``config`` (in place), creating the
    ``[ui]`` section when absent. ``key`` is a config flag name such as
    ``detailed-statistics`` or ``detailed-context``."""
    sect_key, sec = _ui_section(config)
    if sec is None:
        sec = {}
        config[sect_key] = sec
    sec[key] = bool(enabled)


def _agent_section(config: Dict[str, Any]) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Return ``(key, section)`` for the existing ``[agent]`` object, trying the
    accepted spellings. ``section`` is None when no such object exists yet (the
    caller then creates one under the returned ``key``, which defaults to
    ``"agent"``)."""
    for key in ("agent", "agent-defaults", "agent_defaults"):
        sec = config.get(key)
        if isinstance(sec, dict):
            return key, sec
    return "agent", None


def set_agent_flag(config: Dict[str, Any], key: str, enabled: bool) -> None:
    """Set ``agent.<key>`` to ``enabled`` in ``config`` (in place), creating the
    ``[agent]`` section when absent. ``key`` is a config flag name such as
    ``use-mcp-workspace`` or ``internal-mcp-subagent``."""
    sect_key, sec = _agent_section(config)
    if sec is None:
        sec = {}
        config[sect_key] = sec
    sec[key] = bool(enabled)


def set_mcp_server_enabled(config: Dict[str, Any], name: str, enabled: bool) -> None:
    """Set ``agent.use-mcp-<name>`` to ``enabled`` in ``config`` (in place).
    Mirrors the ``--agent-use-mcp-<name>`` / ``--no-...`` CLI flag, so the choice
    is honoured on the next launch."""
    set_agent_flag(config, f"use-mcp-{name}", enabled)


def save_config(home_dir: str, config: Dict[str, Any]) -> str:
    """Write ``config`` back to ``<home_dir>/config.jsonc`` as formatted JSON
    (which is valid JSONC), and return the path written.

    The previous file is first copied to ``config.jsonc.bak``. NOTE: JSONC
    comments and original formatting in the existing file are NOT preserved — the
    file is re-serialised from the parsed data — so the backup is the way to
    recover any hand-written comments."""
    path = config_path(home_dir)
    os.makedirs(home_dir, exist_ok=True)
    if os.path.isfile(path):
        try:
            shutil.copyfile(path, path + ".bak")
        except OSError:
            pass
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)
    return path
