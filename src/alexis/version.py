# AI-Agent.Alexis
# SPDX-FileCopyrightText: 2026 Grigore Stefan <g_stefan@yahoo.com>
# SPDX-License-Identifier: Apache-2.0

"""Application identity and version, sourced from version.json.

Single source of truth for the app name and the version string shown in the
startup header and the interactive UI title.
"""

import json
import os
import importlib.resources

APP_NAME = "AI-Agent.Alexis"
APP_KEY = "ai-agent.alexis"


def _read_version_json() -> str:
    """Return the raw text of the bundled ``data/version.json``.

    Resolved via importlib.resources so it works from source, an editable
    install, or inside a wheel; falls back to a ``__file__``-relative path."""
    try:
        return (
            importlib.resources.files(__package__)
            .joinpath("data", "version.json")
            .read_text(encoding="utf-8")
        )
    except Exception:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "version.json")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()


def _load_info() -> dict:
    """Return the version info dict from version.json, or {} if unavailable."""
    try:
        data = json.loads(_read_version_json())
    except (OSError, ValueError):
        return {}
    info = data.get(APP_KEY)
    if not isinstance(info, dict):
        # Fall back to the first entry if the expected key is missing/renamed.
        info = next((v for v in data.values() if isinstance(v, dict)), {})
    return info


def get_version() -> str:
    """Return the bare version, e.g. '0.1.0' (or '0.0.0' if unknown)."""
    return str(_load_info().get("version", "0.0.0"))


# Module-level version string so packaging metadata (pyproject.toml dynamic
# version) can read a single source of truth derived from version.json.
__version__ = get_version()


def get_build() -> str:
    """Return the build number as a string (empty if unknown)."""
    return str(_load_info().get("build", ""))


def get_version_string() -> str:
    """Return the version prefixed with 'v', e.g. 'v0.1.0'."""
    return f"v{get_version()}"


def get_title() -> str:
    """Return the app name with version, e.g. 'AI-Agent.Alexis v0.1.0'."""
    return f"{APP_NAME} {get_version_string()}"


def get_startup_header() -> str:
    """Return a multi-line startup banner including the version and build/date."""
    info = _load_info()
    line = get_title()
    build = info.get("build")
    date = info.get("date")
    meta_parts = []
    if build:
        meta_parts.append(f"build {build}")
    if date:
        meta_parts.append(str(date))
    meta = f"  ({', '.join(meta_parts)})" if meta_parts else ""
    bar = "=" * max(len(line) + len(meta), 32)
    return f"{bar}\n{line}{meta}\n{bar}"
