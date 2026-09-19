"""
Política de permissões do AtlasBot.
Verifica os dois lados: permissões do autor e permissões do bot, além da hierarquia de cargos.
NÃO importa discord (duck-typing estrito).
"""

from __future__ import annotations

from typing import Any

from brain.tools import ToolError

# Mapeamento de ferramentas para permissões necessárias
TOOL_PERMISSIONS: dict[str, list[str]] = {
    # Canais
    "create_channels": ["manage_channels"],
    "edit_channel": ["manage_channels"],
    "delete_channels": ["manage_channels"],
    "move_channel": ["manage_channels"],
    "clone_channel": ["manage_channels"],
    # Cargos
    "create_roles": ["manage_roles"],
    "edit_role": ["manage_roles"],
    "delete_role": ["manage_roles"],
    "delete_roles": ["manage_roles"],
    "give_role": ["manage_roles"],
    "take_role": ["manage_roles"],
    # Permissões de canais
    "set_permissions": ["manage_roles"],
    "clear_permissions": ["manage_roles"],
    "sync_permissions": ["manage_roles"],
    # Servidor
    "edit_server": ["manage_guild"],
    "set_icon": ["manage_guild"],
    "export_structure": ["manage_guild"],
    # Modelos e importação
    "apply_template": ["manage_channels", "manage_roles"],
    "import_structure": ["manage_channels", "manage_roles"],
    # Consultas e utilitários públicos (nenhuma permissão exigida)
    "list_roles": [],
    "show_permissions": [],
    "server_info": [],
    "performance_report": [],
    "diagnostic_report": ["read_message_history"],
    "color_palette": [],
    "color_name": [],
    "emoji_search": [],
    "topic_suggest": [],
    "translate_text": [],
    "conversation_clear": [],
    "clear_messages": ["manage_messages"],
}

PERMISSION_LABELS: dict[str, str] = {
    "manage_channels": "Gerenciar canais",
    "manage_roles": "Gerenciar cargos",
    "manage_guild": "Gerenciar servidor",
    "manage_messages": "Gerenciar mensagens",
    "administrator": "Administrador",
}


def _has_permission(perms: Any, perm_name: str) -> bool:
    if perms is None:
        return False
    if getattr(perms, "administrator", False):
        return True
    return bool(getattr(perms, perm_name, False))


def _get_top_role_position(entity: Any, override: int | None = None) -> int:
    """Posição do cargo mais alto. `override` vem de quem já conferiu na API (cache engana)."""
    if override is not None:
        return int(override)
    top_role = getattr(entity, "top_role", None)
    if top_role is not None:
        return getattr(top_role, "position", 0)
    roles = getattr(entity, "roles", None)
    if roles:
        return max((getattr(r, "position", 0) for r in roles), default=0)
    return 0


def require(
    tool_name: str,
    actor_perms: Any,
    bot_perms: Any,
    actor: Any = None,
    bot_member: Any = None,
    guild: Any = None,
    target_role: Any = None,
    bot_top_position: int | None = None,
    actor_top_position: int | None = None,
) -> None:
    """
    Valida as permissões do autor e do bot antes de executar uma ferramenta.
    Valida também a hierarquia de cargos caso `target_role` seja informado.
    """
    needed_perms = TOOL_PERMISSIONS.get(tool_name, [])

    for perm in needed_perms:
        perm_label = PERMISSION_LABELS.get(perm, perm)

        # 1. Checa autor (administrador faz bypass do lado do autor)
        if not _has_permission(actor_perms, perm):
            raise ToolError(
                f"Você precisa da permissão '{perm_label}' para usar a ferramenta '{tool_name}'."
            )

        # 2. Checa bot (administrador faz bypass do lado do bot, mas admin do autor NÃO supre o bot)
        if not _has_permission(bot_perms, perm):
            raise ToolError(
                f"Eu preciso da permissão '{perm_label}' no meu cargo para executar '{tool_name}'. "
                "Ajuste meu cargo e tente de novo."
            )

    # 3. Hierarquia de cargos
    if target_role is not None:
        role_name = getattr(target_role, "name", "cargo")

        # Regra @everyone
        if role_name == "@everyone" or getattr(target_role, "is_default", lambda: False)():
            raise ToolError("Não é possível alterar ou excluir o cargo @everyone.")

        # Regra de cargo gerenciado (bot/integração)
        if getattr(target_role, "managed", False):
            raise ToolError(
                f"O cargo '{role_name}' é gerenciado por uma integração ou aplicativo e não pode ser modificado."
            )

        # Posição em relação ao bot
        if bot_member is not None:
            bot_pos = _get_top_role_position(bot_member, bot_top_position)
            target_pos = getattr(target_role, "position", 0)
            if target_pos >= bot_pos:
                raise ToolError(
                    f"O cargo '{role_name}' (posição {target_pos}) está acima ou na mesma posição "
                    f"do meu cargo mais alto (posição {bot_pos}). Suba o cargo do atlas nas "
                    "configurações de cargos do servidor."
                )

        # Posição em relação ao autor (dono do servidor faz bypass de hierarquia)
        if actor is not None and guild is not None:
            owner_id = getattr(guild, "owner_id", None)
            actor_id = getattr(actor, "id", None)
            is_owner = owner_id is not None and actor_id is not None and owner_id == actor_id

            if not is_owner:
                actor_pos = _get_top_role_position(actor, actor_top_position)
                target_pos = getattr(target_role, "position", 0)
                if target_pos >= actor_pos:
                    raise ToolError(
                        f"Você não pode gerenciar o cargo '{role_name}' (posição {target_pos}) "
                        f"porque a posição dele é maior ou igual à do seu cargo mais alto "
                        f"(posição {actor_pos})."
                    )
