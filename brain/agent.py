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
from brain.memory import ChannelMemory
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
   - Quando o usuário confirmar (disser "sim", "pode apagar", "confirmo"), chame a ferramenta novamente com `confirmed=true`.
8. FORA DE ESCOPO: moderação, punições, bans, expulsões, matchmaking, sorteios, jogos, enquetes. Quando pedirem isso, responda educadamente que seu foco exclusivo é montar e organizar a estrutura do servidor.

{snapshot}
"""


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

    async def process_turn(
        self,
        guild: Any,
        channel: Any,
        actor: Any,
        prompt: str,
        attachments: list[Any] | None = None,
    ) -> str:
        channel_id = getattr(channel, "id", 0)
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
                final_text = response.content.strip()
                if final_text:
                    self.memory.add_message(channel_id, {"role": "assistant", "content": final_text})
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
            for call in tool_calls:
                try:
                    result_str = await execute_tool(call.name, call.args, ctx)
                except ToolError as exc:
                    result_str = f"Erro: {exc}"
                except Exception as exc:
                    result_str = f"Erro inesperado: {exc}"

                tool_result_msg = {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": call.name,
                    "content": result_str,
                }
                messages.append(tool_result_msg)
                self.memory.add_message(channel_id, tool_result_msg)

        # Se atingiu o limite de rodadas de ferramentas, pede resumo final
        summary_prompt = {
            "role": "user",
            "content": "Por favor, faça um resumo final breve e direto em português de tudo o que foi realizado.",
        }
        messages.append(summary_prompt)
        final_resp = await self.llm.chat(messages=messages, tools=None, timeout=self.llm_timeout)
        final_text = final_resp.content.strip()
        if final_text:
            self.memory.add_message(channel_id, {"role": "assistant", "content": final_text})
        return final_text or "Operações concluídas."
