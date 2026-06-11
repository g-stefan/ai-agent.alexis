# AI-Agent.Alexis
# SPDX-FileCopyrightText: 2026 Grigore Stefan <g_stefan@yahoo.com>
# SPDX-License-Identifier: Apache-2.0

"""AI-Agent.Alexis — a multimodal LLM agent CLI with MCP support.

Kept import-light on purpose: importing the top-level package must not pull in
the heavy CLI / UI / model modules (those have optional third-party deps and are
also imported at build time to resolve the dynamic version). Import what you need
from the submodules instead, e.g. ``from alexis.cli import main``.
"""

from .version import __version__, get_version, get_version_string

__all__ = ["__version__", "get_version", "get_version_string"]
