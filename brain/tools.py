"""
Definições dos schemas das ferramentas (ToolDef), contexto de execução (ToolContext)
e exceção controlada de ferramenta (ToolError).
NÃO importa o módulo discord (duck-typing estrito).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ToolError(Exception):
    """Erro amigável e acionável em PT-BR para ser retornado ao modelo/usuário."""
    pass


@dataclass
class ToolContext:
    guild: Any
    channel: Any
    actor: Any
    attachments: list[Any] = field(default_factory=list)
    api_registry: Any = None
    memory: Any = None
    # False (padrão): ação pedida de forma direta é executada e informada, sem perguntar.
    confirm_destructive: bool = False
    # Alvos (nome casefold/id) que a MESMA mensagem vai apagar. Serve para uma recriação
    # ("apague e crie de novo o canal X") NÃO ser tratada como duplicata da que já existe.
    alvos_apagados: set[str] = field(default_factory=set)
    # Tempo das últimas respostas do agente (só números, nenhum conteúdo de conversa).
    tempos: Any = None


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict[str, Any]

    def to_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# As ferramentas do atlas (o número sai de len(TOOLS), não de um comentário)
TOOLS: list[ToolDef] = [
    # Canais (5)
    ToolDef(
        name="create_channels",
        description=("Cria 1 ou múltiplos canais no servidor em lote: texto, voz, categoria, "
                     "stage ou fórum, com tópico, NSFW, slowmode, bitrate e limite de usuários."),
        parameters={
            "type": "object",
            "properties": {
                "channels": {
                    "type": "array",
                    "description": "Lista de canais a serem criados (1 a 25 itens).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Nome do canal."},
                            "type": {
                                "type": "string",
                                "enum": ["text", "voice", "category", "stage", "forum"],
                                "description": "Tipo do canal. Padrão: text.",
                            },
                            "category": {
                                "type": "string",
                                "description": "Nome ou ID da categoria onde o canal deve ficar (opcional).",
                            },
                            "topic": {
                                "type": "string",
                                "description": "Tópico/descrição do canal (opcional).",
                            },
                            "nsfw": {"type": "boolean", "description": "Marca o canal como NSFW."},
                            "slowmode_delay": {
                                "type": "integer",
                                "description": "Modo lento em segundos (0 a 21600), canais de texto.",
                            },
                            "bitrate": {
                                "type": "integer",
                                "description": "Bitrate em bits/s (8000 a 384000), canais de voz.",
                            },
                            "user_limit": {
                                "type": "integer",
                                "description": "Limite de usuários (0 a 99; 0 = sem limite), voz.",
                            },
                            "position": {"type": "integer", "description": "Posição na lista."},
                        },
                        "required": ["name"],
                    },
                }
            },
            "required": ["channels"],
        },
    ),
    ToolDef(
        name="edit_channel",
        description=("Edita um canal: nome, tópico, categoria, slowmode, NSFW, bitrate, "
                     "limite de usuários e posição."),
        parameters={
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Nome, menção ou ID do canal a ser editado."},
                "name": {"type": "string", "description": "Novo nome para o canal (opcional)."},
                "topic": {"type": "string", "description": "Novo tópico para o canal (opcional)."},
                "category": {"type": "string", "description": "Nova categoria para mover o canal (opcional)."},
                "slowmode_delay": {"type": "integer", "description": "Tempo de modo lento em segundos (0 a 21600)."},
                "nsfw": {"type": "boolean", "description": "Se o canal é marcado como NSFW (opcional)."},
                "bitrate": {"type": "integer", "description": "Bitrate em bits/s (8000 a 384000), voz."},
                "user_limit": {"type": "integer", "description": "Limite de usuários (0 a 99), voz."},
                "position": {"type": "integer", "description": "Posição do canal na lista."},
            },
            "required": ["channel"],
        },
    ),
    ToolDef(
        name="delete_channels",
        description=("Exclui um ou mais canais ou categorias. Deletar múltiplos canais requer "
                     "confirmed=true. O canal onde a conversa acontece NUNCA é apagado: se o "
                     "pedido disser \"menos esse\", não o inclua na lista."),
        parameters={
            "type": "object",
            "properties": {
                "channels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Lista de nomes, menções ou IDs dos canais/categorias a excluir. Para "
                        "\"apague todos os canais\" use exatamente [\"todos\"]: o servidor é lido "
                        "na hora da exclusão e a conferência é feita na API (não enumere nomes)."
                    ),
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "Confirmação explícita do usuário para ações destrutivas (obrigatório se >1 canal ou categoria inteira).",
                },
            },
            "required": ["channels"],
        },
    ),
    ToolDef(
        name="move_channel",
        description="Move um canal para uma categoria específica ou altera sua posição.",
        parameters={
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Nome, menção ou ID do canal."},
                "category": {"type": "string", "description": "Nome ou ID da categoria de destino (ou 'none' para remover da categoria)."},
                "position": {"type": "integer", "description": "Posição numérica de ordenação (opcional)."},
            },
            "required": ["channel"],
        },
    ),
    ToolDef(
        name="clone_channel",
        description="Clona um canal existente, duplicando suas permissões e configurações.",
        parameters={
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Nome, menção ou ID do canal a ser clonado."},
                "name": {"type": "string", "description": "Nome do canal clonado (opcional, padrão: cópia)."},
            },
            "required": ["channel"],
        },
    ),
    # Cargos (6)
    ToolDef(
        name="create_roles",
        description="Cria 1 ou múltiplos cargos no servidor com cores, hoist e permissões.",
        parameters={
            "type": "object",
            "properties": {
                "roles": {
                    "type": "array",
                    "description": "Lista de cargos a serem criados.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Nome do cargo."},
                            "color": {"type": "string", "description": "Cor hexadecimal (ex: #5865F2) ou nome da cor."},
                            "hoist": {"type": "boolean", "description": "Exibir membros com este cargo separadamente na lista."},
                            "mentionable": {"type": "boolean", "description": "Permitir que qualquer membro mencione este cargo."},
                            "permissions": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": ("Permissões do cargo, em português ou inglês "
                                                "(ex: ['ver canal', 'enviar mensagens'])."),
                            },
                            "position": {"type": "integer", "description": "Posição do cargo na hierarquia."},
                        },
                        "required": ["name"],
                    },
                },
                "permissions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Permissões para todos os cargos do lote (opcional).",
                },
                "position": {"type": "integer", "description": "Posição para todos os cargos do lote (opcional)."},
            },
            "required": ["roles"],
        },
    ),
    ToolDef(
        name="edit_role",
        description=("Edita um cargo: nome, cor, hoist, mentionable, permissões (substitui o "
                     "conjunto atual) e posição na hierarquia."),
        parameters={
            "type": "object",
            "properties": {
                "role": {"type": "string", "description": "Nome, menção ou ID do cargo a ser editado."},
                "name": {"type": "string", "description": "Novo nome para o cargo (opcional)."},
                "color": {"type": "string", "description": "Nova cor hexadecimal ou nome de cor (opcional)."},
                "hoist": {"type": "boolean", "description": "Exibir separadamente na lista de membros (opcional)."},
                "mentionable": {"type": "boolean", "description": "Permitir menção a este cargo (opcional)."},
                "permissions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": ("Conjunto de permissões do cargo, em português ou inglês "
                                    "(substitui o que ele tem hoje)."),
                },
                "position": {"type": "integer", "description": "Nova posição na hierarquia."},
            },
            "required": ["role"],
        },
    ),
    ToolDef(
        name="delete_role",
        description="Exclui um cargo do servidor permanentemente. Sempre requer confirmed=true.",
        parameters={
            "type": "object",
            "properties": {
                "role": {"type": "string", "description": "Nome, menção ou ID do cargo a excluir."},
                "confirmed": {"type": "boolean", "description": "Confirmação explícita do usuário."},
            },
            "required": ["role"],
        },
    ),
    ToolDef(
        name="give_role",
        description="Atribui um cargo a um membro do servidor.",
        parameters={
            "type": "object",
            "properties": {
                "member": {"type": "string", "description": "Nome, menção (<@id>) ou ID do membro."},
                "role": {"type": "string", "description": "Nome, menção (<@&id>) ou ID do cargo."},
            },
            "required": ["member", "role"],
        },
    ),
    ToolDef(
        name="take_role",
        description="Remove um cargo de um membro do servidor.",
        parameters={
            "type": "object",
            "properties": {
                "member": {"type": "string", "description": "Nome, menção (<@id>) ou ID do membro."},
                "role": {"type": "string", "description": "Nome, menção (<@&id>) ou ID do cargo."},
            },
            "required": ["member", "role"],
        },
    ),
    ToolDef(
        name="list_roles",
        description="Lista todos os cargos do servidor com IDs, posições, cores e contagem de membros.",
        parameters={"type": "object", "properties": {}},
    ),
    # Permissões (4)
    ToolDef(
        name="set_permissions",
        description="Define permissões específicas (permitir ou negar) para um cargo ou membro em um canal.",
        parameters={
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Nome, menção ou ID do canal."},
                "target": {"type": "string", "description": "Nome, menção ou ID do cargo ou membro."},
                "allow": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de permissões para permitir (ex: ['view_channel', 'send_messages']).",
                },
                "deny": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de permissões para negar (ex: ['send_messages', 'connect']).",
                },
            },
            "required": ["channel", "target"],
        },
    ),
    ToolDef(
        name="clear_permissions",
        description="Remove sobrescritas personalizadas de permissão de um canal para um cargo ou membro.",
        parameters={
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Nome, menção ou ID do canal."},
                "target": {"type": "string", "description": "Nome, menção ou ID do cargo ou membro."},
            },
            "required": ["channel", "target"],
        },
    ),
    ToolDef(
        name="sync_permissions",
        description="Sincroniza as permissões de um canal com a sua categoria mãe.",
        parameters={
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Nome, menção ou ID do canal a ser sincronizado."},
            },
            "required": ["channel"],
        },
    ),
    ToolDef(
        name="show_permissions",
        description="Exibe as permissões configuradas em um canal para um cargo ou membro específico.",
        parameters={
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Nome, menção ou ID do canal."},
                "target": {"type": "string", "description": "Nome, menção ou ID do cargo ou membro (opcional)."},
            },
            "required": ["channel"],
        },
    ),
    # Servidor (3)
    ToolDef(
        name="edit_server",
        description="Edita informações do servidor (nome, descrição).",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Novo nome do servidor (opcional)."},
                "description": {"type": "string", "description": "Nova descrição do servidor (opcional)."},
            },
        },
    ),
    ToolDef(
        name="delete_roles",
        description=("Apaga VÁRIOS cargos de uma vez (para quando pedirem 'apague todos os cargos' "
                     "ou vários de uma vez). Diz quantos apagou e, se algum não puder ser apagado, "
                     "explica o motivo e o que fazer."),
        parameters={
            "type": "object",
            "properties": {
                "roles": {"type": "array", "items": {"type": "string"},
                          "description": "Nomes, menções ou IDs dos cargos a apagar."},
                "confirmed": {"type": "boolean",
                              "description": "true quando o usuário já confirmou (modo cauteloso)."},
            },
            "required": ["roles"],
        },
    ),
    ToolDef(
        name="diagnostic_report",
        description=("Envia por mensagem direta (para quem pediu) um arquivo com a conversa recente "
                     "deste canal + o tempo das últimas respostas. Use quando alguém relatar que o "
                     "bot falhou, demorou ou pediu a mesma coisa várias vezes."),
        parameters={
            "type": "object",
            "properties": {
                "limit": {"type": "integer",
                          "description": "Quantas mensagens incluir (padrão 80, máximo 200)."},
            },
        },
    ),
    ToolDef(
        name="performance_report",
        description=("Mostra quanto tempo as últimas respostas do bot levaram (mediana, pior e "
                     "melhor) e o que pesou: modelo de linguagem ou execução das ações. Use "
                     "quando pedirem para investigar lentidão/demora do bot."),
        parameters={"type": "object", "properties": {}},
    ),
    ToolDef(
        name="server_info",
        description="Retorna informações e estatísticas completas sobre o servidor.",
        parameters={"type": "object", "properties": {}},
    ),
    ToolDef(
        name="set_icon",
        description="Altera o ícone do servidor a partir de uma URL de imagem válida ou estilo gerado.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL direta da imagem (PNG ou JPEG)."},
                "style": {"type": "string", "description": "Estilo de ícone caso deseje gerar (ex: 'gamer', 'minimal')."},
            },
        },
    ),
    # Modelos (1)
    ToolDef(
        name="apply_template",
        description="Aplica um modelo completo de servidor pré-estruturado ('gamer', 'estudos', 'comunidade').",
        parameters={
            "type": "object",
            "properties": {
                "template": {
                    "type": "string",
                    "enum": ["gamer", "estudos", "comunidade"],
                    "description": "Tipo de modelo para aplicar.",
                }
            },
            "required": ["template"],
        },
    ),
    # Backup (2)
    ToolDef(
        name="export_structure",
        description="Exporta a estrutura de categorias, canais e cargos do servidor em formato JSON.",
        parameters={"type": "object", "properties": {}},
    ),
    ToolDef(
        name="import_structure",
        description="Importa e recria a estrutura de canais e cargos a partir de JSON ou anexo da mensagem.",
        parameters={
            "type": "object",
            "properties": {
                "structure_json": {
                    "type": "string",
                    "description": "Conteúdo JSON com a estrutura a ser importada (opcional se houver arquivo anexo).",
                }
            },
        },
    ),
    # APIs externas (5)
    ToolDef(
        name="color_palette",
        description="Busca uma paleta de cores temática (gamer, pastel, dark, comunidade) com códigos hex.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Tema desejado (ex: 'gamer', 'dark', 'pastel', 'neon')."},
            },
        },
    ),
    ToolDef(
        name="color_name",
        description="Retorna o nome descritivo de uma cor a partir do seu código hexadecimal (#RRGGBB).",
        parameters={
            "type": "object",
            "properties": {
                "hex_code": {"type": "string", "description": "Código hexadecimal da cor (ex: '#5865F2')."},
            },
            "required": ["hex_code"],
        },
    ),
    ToolDef(
        name="emoji_search",
        description="Pesquisa emojis adequados para organizar categorias e canais por palavra-chave.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Termo de busca (ex: 'voz', 'jogos', 'regras', 'vip')."},
            },
            "required": ["query"],
        },
    ),
    ToolDef(
        name="topic_suggest",
        description="Gera uma sugestão criativa de tópico/descrição para canais de uma temática.",
        parameters={
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "Tema do canal (ex: 'geral', 'gamer', 'estudos', 'memes')."},
            },
        },
    ),
    ToolDef(
        name="translate_text",
        description="Traduz um texto para o português para criar canais, regras ou descrições bilíngues.",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Texto para traduzir."},
                "target_lang": {"type": "string", "description": "Idioma de destino (padrão: 'pt')."},
            },
            "required": ["text"],
        },
    ),
    # Sessão (2)
    ToolDef(
        name="conversation_clear",
        description=(
            "Limpa SÓ A MEMÓRIA do bot nesta conversa (ele esquece o que foi dito antes). "
            "NÃO apaga as mensagens do canal — para apagar mensagens use clear_messages."
        ),
        parameters={"type": "object", "properties": {}},
    ),
    ToolDef(
        name="clear_messages",
        description=(
            "Apaga mensagens de um canal de verdade (limpeza de conversa/chat). "
            "Use quando o pedido for apagar o chat, limpar as mensagens, 'exclua essa conversa'. "
            "Padrão: últimas 50 mensagens do canal atual."
        ),
        parameters={
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Canal (nome, menção ou ID). Padrão: o canal atual."},
                "limit": {"type": "integer", "description": "Quantas mensagens apagar (1 a 500; padrão 50)."},
                "confirmed": {"type": "boolean", "description": "Trabalha com o modo cauteloso; no modo direto é opcional."},
            },
        },
    ),
]


def get_tool_definitions() -> list[ToolDef]:
    return TOOLS


def tool_names() -> list[str]:
    return [t.name for t in TOOLS]
