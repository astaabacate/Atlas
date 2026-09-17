"""
Módulo core do FarolBot.
"""

from core.bot import FarolBot, build_intents
from core.bulk import BulkResult, run_bulk
from core.health import start_health_server
from core.helpers import split_message

__all__ = [
    "FarolBot",
    "build_intents",
    "BulkResult",
    "run_bulk",
    "split_message",
    "start_health_server",
]
