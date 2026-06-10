# AI-Agent.Alexis
# SPDX-FileCopyrightText: 2026 Grigore Stefan <g_stefan@yahoo.com>
# SPDX-License-Identifier: Apache-2.0

from typing import Type

from .ui_driver import UIDriver
from .ui_driver_simple import SimpleUIDriver
from .ui_driver_interactive import InteractiveUIDriver
from .ui_driver_api import APIUIDriver

try:
    from .ui_driver_textual_interactive import TextualInteractiveUIDriver
    HAS_TEXTUAL = True
except ImportError:
    HAS_TEXTUAL = False


UI_DRIVERS = {
    "api": APIUIDriver,
    "interactive": InteractiveUIDriver,
    "textual": TextualInteractiveUIDriver,
    "simple": SimpleUIDriver,
    "ui": UIDriver,
}


def create_ui_driver(driver_type: str) -> UIDriver:
    if driver_type not in UI_DRIVERS:
        available = ", ".join(UI_DRIVERS.keys())
        raise ValueError(f"Unknown UI driver: {driver_type}. Available: {available}")
    return UI_DRIVERS[driver_type]()


def get_available_driver_names() -> list:
    names = ["simple", "interactive", "api"]
    if HAS_TEXTUAL:
        names.append("textual")
    return names
