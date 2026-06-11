# AI-Agent.Alexis
# SPDX-FileCopyrightText: 2026 Grigore Stefan <g_stefan@yahoo.com>
# SPDX-License-Identifier: Apache-2.0

"""Bundled MCP server scripts.

This is a package only so the ``mcp-server-*.py`` scripts ship inside the wheel
as package data and can be located on disk at runtime (they are launched as
standalone subprocesses, not imported as modules — their hyphenated filenames
are not valid module names by design).
"""
