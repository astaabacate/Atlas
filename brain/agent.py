"""
Loop do Agente Farol: Prompt de sistema + Snapshot + Histórico → LLM → Tools → Resposta.
Suporta fallback de extração de ferramentas em texto puro (```tool {...}```).
NÃO importa discord (duck-typing estrito).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from brain.executors import execute_tool
from brain.memory import ChannelMemory, memory_key
from brain.snapshot import build_server_snapshot
from brain.tools import ToolContext, ToolDef, ToolError, get_tool_definitions
from llm.base import ChatProvider, LLMResponse, ToolCall

logger = logging.getLogger("farol.brain.agent")

SYSTEM_PROMPT_TEMPLATE = """Você é o `farol`, um bot de Discord especialista em construir, estruturar e organizar servidores.
Você executa ações reais no servidor chamando ferramentas.

REGRAS ABSOLUTAS:
1. TODAS as ferramentas listadas existem e estão disponíveis. NUNCA diga que uma ferramenta "não está disponível", "não existe" ou "está desativada". Se tiver dúvida, CHAME a ferramenta: a resposta dela é a verdade.
2. Não fique pedindo licença: se o pedido é claro e não destrutivo, execute agora e conte o resultado.
3. Se vier Erro de uma ferramenta, repasse o motivo do Erro e o que o usuário precisa fazer (exemplo: falta de permissão).
4. Nunca invente IDs ou nomes: use a ESTRUTURA ATUAL abaixo para localizar canais e cargos existentes.
5. Prefira UMA chamada com listas a várias chamadas repetidas (ex: use create_channels com a lista completa).
6. Responda em português (PT-BR), de forma curta, direta e amigável, incluindo os links dos itens criados ou alterados (<#id>, <@&id>).
7. Ações destrutivas e confirmação:
   - Excluir UM canal indicado nominalmente NÃO pede confirmação: execute imediatamente!
   - Peça confirmação SOMENTE quando o estrago for grande: excluir 2 ou mais canais, esvaziar/excluir uma categoria inteira, ou excluir um cargo.
   - NUNCA invente confirmação: só use `confirmed=true` DEPOIS que o usuário confirmar explicitamente
     ("sim", "pode apagar", "confirmo"). Se ele ainda não confirmou, chame a ferramenta SEM `confirmed`.
   - Se a ferramenta responder "confirme com o usuário e chame de novo com confirmed=true", PARE de tentar:
     pergunte no texto ("Confirma que posso apagar X e Y?") e encerre a resposta sem chamar mais nada.
8. FORA DE ESCOPO: moderação, punições, bans, expulsões, matchmaking, sorteios, jogos, enquetes. Quando pedirem isso, responda educadamente que seu foco exclusivo é montar e organizar a estrutura do servidor.

{snapshot}
"""


# Ferramentas que exigem confirmação EXPLÍCITA do usuário antes de um estrago grande.
# O modelo não pode se auto-confirmar: quem confirma é a pessoa (bug pego no teste ao vivo,
# em que o agente apagou 2 canais de uma vez sem perguntar nada).
CONFIRMATION_TOOLS = frozenset({"delete_channels", "delete_role"})

_AFFIRMATIVE_RE = re.compile(
    r"\b(sim|s|ss|confirmo|confirmado|confirma|pode|pode apagar|pode sim|manda|manda ver|claro|"
    r"isso|isso mesmo|beleza|blz|ok|okay|autorizo|autorizado|vai|executa|execute|apaga)\b"
)


def _strip_accents(text: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def user_confirmed(prompt: str) -> bool:
    """True quando a mensagem do usuário é uma confirmação explícita ("sim, pode apagar")."""
    return bool(_AFFIRMATIVE_RE.search(_strip_accents(prompt.lower())))


_ASKING_RE = re.compile(r"confirm|posso apagar|tem certeza|certeza disso|autoriza|devo (apagar|excluir)")


def asks_for_confirmation(text: str) -> bool:
    """True quando a resposta do agente está pedindo um 'sim' antes de destruir algo."""
    return bool(_ASKING_RE.search(_strip_accents((text or "").lower())))


def _extract_fallback_tool_calls(text: str) -> list[ToolCall]:
    """
    Fallback para provedores gratuitos anônimos sem suporte nativo a function calling:
    procura blocos markdown do tipo ```tool ... ``` ou ```json ... ``` com {"name": ..., "args": ...}.
    """
    calls: list[ToolCall] = []
    # Procura por blocos ```tool ou ```json
    pattern = r"```(?:tool|json)?\s*(\{\s*\"name\"\s*:\s*.*?\})\s*```"
    matches = re.finditer(pattern, text, re.DOTALL)
    idx = 0
    for match in matches:
        raw_json = match.group(1)
        try:
            data = json.loads(raw_json)
            name = data.get("name")
            args = data.get("args", {})
            if name and isinstance(args, dict):
                calls.append(ToolCall(id=f"fallback_{idx}", name=name, args=args))
                idx += 1
        except Exception:
            continue
    return calls


class Agent:
    def __init__(
        self,
        llm_provider: ChatProvider,
        memory: ChannelMemory | None = None,
        max_tool_rounds: int = 3,
        llm_timeout: float = 60.0,
        api_registry: Any = None,
    ) -> None:
        self.llm = llm_provider
        self.memory = memory if memory is not None else ChannelMemory()
        self.max_tool_rounds = max_tool_rounds
        self.llm_timeout = llm_timeout
        self.api_registry = api_registry
        self.tools_schema = [t.to_openai() for t in get_tool_definitions()]
        # conversa → ferramentas destrutivas que pediram confirmação no último turno
        self._aguardando_confirmacao: dict[Any, set[str]] = {}
        self.max_pending_confirmations: int = 200

    def pending_confirmation(self, channel_id: Any) -> set[str]:
        """Ferramentas que estão esperando um 'sim' do usuário naquela conversa."""
        return set(self._aguardando_confirmacao.get(channel_id, set()))

    def _marcar_pendencia(self, channel_id: Any, ferramentas: set[str]) -> None:
        """Guarda a pendência de confirmação sem deixar o dicionário crescer sem fim."""
        if len(self._aguardando_confirmacao) >= self.max_pending_confirmations:
            # descarta a pendência mais antiga (em Python 3.7+ dict mantém ordem de inserção)
            mais_antiga = next(iter(self._aguardando_confirmacao))
            self._aguardando_confirmacao.pop(mais_antiga, None)
        self._aguardando_confirmacao[channel_id] = set(ferramentas)

    def _com_pergunta_de_confirmacao(self, channel_id: int, texto: str) -> str:
        """
        Garante que o usuário VEJA a pergunta quando algo ficou pendente de confirmação.

        Sem isso, um modelo fraco (dos provedores gratuitos) pode responder "tentativa falhou"
        e deixar a pessoa sem entender que a ação só espera um "sim" — foi o que o teste ao vivo
        pegou depois do guarda de confirmação entrar.
        """
        if not self._aguardando_confirmacao.get(channel_id):
            return texto
        if asks_for_confirmation(texto):
            return texto
        pergunta = 'Confirma que posso apagar? Responda "sim, pode apagar" que eu executo na hora.'
        return f"{texto}\n\n{pergunta}".strip() if texto else pergunta

    def _authorize_confirmed(self, channel_id: int, tool_name: str, args: dict[str, Any],
                             prompt: str) -> dict[str, Any]:
        """
        Tira o `confirmed=true` que o MODELO inventou.

        Só é aceito quando a ferramenta já tinha pedido confirmação no turno anterior E a
        mensagem atual do usuário é uma confirmação explícita. Sem isso, a chamada segue sem
        `confirmed` e a própria ferramenta devolve o pedido de confirmação.
        """
        if not args.get("confirmed") or tool_name not in CONFIRMATION_TOOLS:
            return args

        pendentes = self._aguardando_confirmacao.get(channel_id, set())
        if ("*" in pendentes or tool_name in pendentes) and user_confirmed(prompt):
            return args

        logger.info("confirmação do modelo ignorada em %s (pendentes=%s)", tool_name, pendentes or "nenhuma")
        limpo = dict(args)
        limpo.pop("confirmed", None)
        return limpo

    async def process_turn(
        self,
        guild: Any,
        channel: Any,
        actor: Any,
        prompt: str,
        attachments: list[Any] | None = None,
    ) -> str:
        # Isolamento por servidor: a conversa é sempre (servidor, canal).
        channel_id = memory_key(getattr(guild, "id", None), getattr(channel, "id", 0))
        ctx = ToolContext(
            guild=guild,
            channel=channel,
            actor=actor,
            attachments=attachments or [],
            api_registry=self.api_registry,
            memory=self.memory,
        )

        snapshot = build_server_snapshot(guild)
        system_content = SYSTEM_PROMPT_TEMPLATE.format(snapshot=snapshot)

        # Montar histórico de mensagens para a LLM
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_content}]
        history = self.memory.get_history(channel_id)
        messages.extend(history)

        user_content = prompt.strip()
        if not user_content and attachments:
            user_content = "Execute a ação baseada no arquivo anexado."

        user_msg = {"role": "user", "content": user_content}
        messages.append(user_msg)
        self.memory.add_message(channel_id, user_msg)

        rounds = 0
        final_text = ""
        execucoes: list[str] = []

        while rounds < self.max_tool_rounds:
            rounds += 1

            response: LLMResponse = await self.llm.chat(
                messages=messages,
                tools=self.tools_schema,
                timeout=self.llm_timeout,
            )

            tool_calls = response.tool_calls
            # Se não houver tool_calls nativas, verificar fallback em texto
            if not tool_calls and response.content:
                tool_calls = _extract_fallback_tool_calls(response.content)

            if not tool_calls:
                final_text = self._com_pergunta_de_confirmacao(channel_id, response.content.strip())
                if final_text:
                    self.memory.add_message(channel_id, {"role": "assistant", "content": final_text})
                    if asks_for_confirmation(final_text):
                        # perguntou no TEXTO (sem chamar a ferramenta): o "sim" da próxima
                        # mensagem precisa valer para a ferramenta destrutiva que vier
                        self._marcar_pendencia(channel_id, {"*"})
                return final_text or "Operação concluída com sucesso."

            # O modelo chamou ferramentas
            # Montar mensagem do assistente para o contexto
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.args, ensure_ascii=False),
                        },
                    }
                    for call in tool_calls
                ],
            }
            messages.append(assistant_msg)
            self.memory.add_message(channel_id, assistant_msg)

            # Executar cada ferramenta
            pedindo_confirmacao: set[str] = set()
            for call in tool_calls:
                args = self._authorize_confirmed(channel_id, call.name, dict(call.args or {}), prompt)
                try:
                    result_str = await execute_tool(call.name, args, ctx)
                except ToolError as exc:
                    result_str = f"Erro: {exc}"
                except Exception as exc:
                    result_str = f"Erro inesperado: {exc}"

                execucoes.append(call.name)

                if call.name in CONFIRMATION_TOOLS and "confirmed=true" in result_str:
                    pedindo_confirmacao.add(call.name)

                tool_result_msg = {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": call.name,
                    "content": result_str,
                }
                messages.append(tool_result_msg)
                self.memory.add_message(channel_id, tool_result_msg)

            if pedindo_confirmacao:
                self._marcar_pendencia(channel_id, pedindo_confirmacao)
            elif any(c.name in CONFIRMATION_TOOLS for c in tool_calls):
                # a ferramenta destrutiva rodou de verdade (o usuário já havia confirmado)
                self._aguardando_confirmacao.pop(channel_id, None)

        # Se atingiu o limite de rodadas de ferramentas, pede resumo final
        summary_prompt = {
            "role": "user",
            "content": "Por favor, faça um resumo final breve e direto em português de tudo o que foi realizado.",
        }
        messages.append(summary_prompt)
        try:
            final_resp = await self.llm.chat(messages=messages, tools=None, timeout=self.llm_timeout)
        except Exception as exc:  # noqa: BLE001 - o trabalho já foi feito; não devolver erro ao cliente
            if not execucoes:
                raise
            logger.warning("Resumo final falhou (%s); respondendo com o que já foi executado", exc)
            acoes = ", ".join(dict.fromkeys(execucoes))
            return (f"✅ Fiz o que você pediu ({acoes}), mas os modelos gratuitos ficaram instáveis "
                    "agora e eu não consegui escrever o resumo. Confira no servidor e me diga se "
                    "falta algo.")
        final_text = self._com_pergunta_de_confirmacao(channel_id, final_resp.content.strip())
        if final_text:
            self.memory.add_message(channel_id, {"role": "assistant", "content": final_text})
        return final_text or "Operações concluídas."
