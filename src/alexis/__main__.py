# AI-Agent.Alexis
# SPDX-FileCopyrightText: 2026 Grigore Stefan <g_stefan@yahoo.com>
# SPDX-License-Identifier: Apache-2.0

"""Enable ``python -m alexis`` (and the in-tree subagent relaunch) to run the
CLI exactly like the installed ``alexis`` console script."""

from .cli import main

if __name__ == "__main__":
    main()
