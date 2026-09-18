"""
Mapeamento e execução centralizada das ferramentas com verificação de policy pré-execução
e trava de coerência contra divergências de schema.
NÃO importa discord (duck-typing estrito).
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Awaitable, Callable

from brain.ops import (
    op_apply_template,
    op_clear_permissions,
    op_clone_channel,
    op_color_name,
    op_color_palette,
    op_clear_messages,
    op_conversation_clear,
    op_create_channels,
    op_create_roles,
    op_delete_channels,
    op_delete_role,
    op_edit_channel,
    op_edit_role,
    op_edit_server,
    op_emoji_search,
    op_export_structure,
    op_give_role,
    op_import_structure,
    op_list_roles,
    op_move_channel,
    op_diagnostic_report,
    op_performance_report,
    op_server_info,
    op_set_icon,
    op_set_permissions,
    op_show_permissions,
    op_sync_permissions,
    op_take_role,
    op_topic_suggest,
    op_translate_text,
)
from brain.policy import require
from brain.tools import ToolContext, ToolError, tool_names

logger = logging.getLogger("farol.brain.executors")

_OPS: dict[str, Callable[..., Awaitable[str]]] = {
    # Canais (5)
    "create_channels": op_create_channels,
    "edit_channel": op_edit_channel,
    "delete_channels": op_delete_channels,
    "move_channel": op_move_channel,
    "clone_channel": op_clone_channel,
    # Cargos (6)
    "create_roles": op_create_roles,
    "edit_role": op_edit_role,
    "delete_role": op_delete_role,
    "give_role": op_give_role,
    "take_role": op_take_role,
    "list_roles": op_list_roles,
    # Permissões (4)
    "set_permissions": op_set_permissions,
    "clear_permissions": op_clear_permissions,
    "sync_permissions": op_sync_permissions,
    "show_permissions": op_show_permissions,
    # Servidor (3)
    "edit_server": op_edit_server,
    "diagnostic_report": op_diagnostic_report,
    "performance_report": op_performance_report,
    "server_info": op_server_info,
    "set_icon": op_set_icon,
    # Modelos (1)
    "apply_template": op_apply_template,
    # Backup (2)
    "export_structure": op_export_structure,
    "import_structure": op_import_structure,
    # APIs (5)
    "color_palette": op_color_palette,
    "color_name": op_color_name,
    "emoji_search": op_emoji_search,
    "topic_suggest": op_topic_suggest,
    "translate_text": op_translate_text,
    # Sessão (2)
    "conversation_clear": op_conversation_clear,
    "clear_messages": op_clear_messages,
}

# Trava de coerência exigida na especificação:
# Se o conjunto de schemas e o de executores divergir, levanta RuntimeError no import.
_missing = set(tool_names()) ^ set(_OPS.keys())
if _missing:
    raise RuntimeError(
        f"Divergência detectada entre schemas de ferramentas e executores: {_missing}"
    )


async def execute_tool(name: str, args: dict[str, Any], ctx: ToolContext) -> str:
    """
    Executa a ferramenta solicitada pelo nome, aplicando a política de permissões ANTES da execução.
    """
    if name not in _OPS:
        raise ToolError(f"A ferramenta '{name}' não foi encontrada.")

    op_func = _OPS[name]

    # Checar permissões do autor e do bot antes de qualquer alteração
    actor_perms = getattr(ctx.actor, "guild_permissions", None)
    bot_member = getattr(ctx.guild, "me", None)
    bot_perms = getattr(bot_member, "guild_permissions", None) if bot_member else None

    require(
        tool_name=name,
        actor_perms=actor_perms,
        bot_perms=bot_perms,
        actor=ctx.actor,
        bot_member=bot_member,
        guild=ctx.guild,
    )

    try:
        # Filtrar argumentos para aceitar apenas os que a função recebe
        sig = inspect.signature(op_func)
        valid_kwargs = {}
        for param_name, param in sig.parameters.items():
            if param_name == "ctx":
                continue
            if param_name in args:
                valid_kwargs[param_name] = args[param_name]

        return await op_func(ctx, **valid_kwargs)
    except ToolError:
        raise
    except Exception as exc:
        logger.exception("Erro interno inesperado na ferramenta '%s': %s", name, exc)
        raise ToolError(f"Erro ao executar '{name}': {exc}")
