"""
Módulo cerebral do FarolBot (agente, ferramentas, executores, políticas e memória).
Nenhum arquivo neste pacote importa discord.
"""

from brain.agent import Agent
from brain.executors import execute_tool
from brain.memory import ChannelMemory
from brain.ops import *
from brain.policy import require
from brain.resolve import resolve_channel, resolve_member, resolve_role
from brain.snapshot import build_server_snapshot
from brain.tools import ToolContext, ToolDef, ToolError, get_tool_definitions, tool_names

__all__ = [
    "Agent",
    "ToolContext",
    "ToolDef",
    "ToolError",
    "get_tool_definitions",
    "tool_names",
    "execute_tool",
    "require",
    "resolve_channel",
    "resolve_role",
    "resolve_member",
    "build_server_snapshot",
    "ChannelMemory",
]
