# AI-Agent.Alexis
# SPDX-FileCopyrightText: 2026 Grigore Stefan <g_stefan@yahoo.com>
# SPDX-License-Identifier: Apache-2.0

"""User configuration loaded from ``<ALEXIS_HOME>/config.jsonc``.

The config file is JSONC (JSON with ``//`` and ``/* */`` comments and tolerant
of trailing commas). It defines named LLM *providers* and which one is the
default:

    {
      "default-provider": "local-llama",
      "providers": {
        "local-llama": { "driver": "llama",  "url": "...", "api-key": null,  "model": "default" },
        "gemini":      { "driver": "gemini", "url": "...", "api-key": "...", "model": "gemini-2.5-flash" }
      }
    }

Command-line flags always override the values resolved from here.
"""

import json
import os
import re
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
        with open(path, "r", encoding="utf-8") as f:
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
    }
    return name, params
