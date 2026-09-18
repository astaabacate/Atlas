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
from brain.tools import ToolContext, ToolError, get_tool_definitions
from llm.base import ChatProvider, parece_raciocinio, separar_raciocinio, LLMResponse, ToolCall

logger = logging.getLogger("farol.brain.agent")

SYSTEM_PROMPT_TEMPLATE = """Você é o `farol`, um bot de Discord especialista em construir, estruturar e organizar servidores.
Você executa ações reais no servidor chamando ferramentas.

REGRAS ABSOLUTAS:
1. TODAS as ferramentas listadas existem e estão disponíveis. NUNCA diga que uma ferramenta "não está disponível", "não existe" ou "está desativada". Se tiver dúvida, CHAME a ferramenta: a resposta dela é a verdade.
2. Não fique pedindo licença: se o pedido é claro e não destrutivo, execute agora e conte o resultado.
3. Se vier Erro de uma ferramenta, repasse o motivo do Erro e o que o usuário precisa fazer (exemplo: falta de permissão).
4. Nunca invente IDs ou nomes: use a ESTRUTURA ATUAL abaixo para localizar canais e cargos existentes.
   NUNCA diga que fez algo que uma ferramenta não confirmou — se não chamou, não aconteceu.
4.1. Limpar CONVERSA tem duas ferramentas e elas NÃO são a mesma coisa:
   - "exclua/apague esse chat", "limpe as mensagens", "apague a conversa daqui" → `clear_messages`
     (apaga as MENSAGENS do canal de verdade; informe quantas apagou);
   - "esqueça o que eu falei", "reinicie a conversa", "limpe meu histórico com você" →
     `conversation_clear` (limpa só a MEMÓRIA do bot; as mensagens do canal continuam).
   Na dúvida entre as duas, use `clear_messages`.
5. Prefira UMA chamada com listas a várias chamadas repetidas (ex: use create_channels com a lista completa).
6. IDIOMA E TAMANHO (regra dura): responda SEMPRE em português do Brasil, de forma curta, direta e
   amigável (no máximo 4 linhas), incluindo os links dos itens criados ou alterados (<#id>, <@&id>).
   NUNCA responda em inglês. NUNCA mostre seu raciocínio, plano, análise ou "thinking process":
   o usuário só quer o resultado. Se não houver nada a dizer, responda "Feito!".
7. Ações destrutivas e confirmação: {confirmacao}
8. FORA DE ESCOPO: moderação, punições, bans, expulsões, matchmaking, sorteios, jogos, enquetes. Quando pedirem isso, responda educadamente que seu foco exclusivo é montar e organizar a estrutura do servidor.

{snapshot}
"""


# Ferramentas que exigem confirmação EXPLÍCITA do usuário antes de um estrago grande.
# O modelo não pode se auto-confirmar: quem confirma é a pessoa (bug pego no teste ao vivo,
# em que o agente apagou 2 canais de uma vez sem perguntar nada).
CONFIRMATION_TOOLS = frozenset({"delete_channels", "delete_role"})

# Teto de tamanho da mensagem final. Acima disso não é resposta: é despejo de texto
# (rascunho de modelo grátis, lista imensa, etc.) — o Farol responde curto.
MAX_RESPOSTA_CHARS = 1000

# Palavras que aparecem MUITO em inglês e quase nunca em português (com espaço em volta,
# para não confundir com nomes de comando tipo "embed" ou "clear_messages").
_MARCADORES_INGLES = (
    " the ", " and ", " with ", " your ", " you ", " this ", " that ", " does ", " is ",
    " are ", " was ", " will ", " would ", " i'll ", " i will ", " let me ", " okay,",
    " first,", " then,", " here's ", " here is ", " about ", " because ", " should ",
    " user ", " request ", " need to ", " make sure ", " so the ", " if the ",
)

_MARCADORES_PORTUGUES = (
    " não ", " nao ", " você ", " voce ", " para ", " com ", " que ", " está ", " esta ",
    " canais ", " canal ", " cargos ", " cargo ", " servidor ", " mensagens ", " apaguei ",
    " criei ", " pronto", " feito", " tudo ", " agora ", " aqui ", " seu ", " sua ",
)

# Ferramentas cujo resultado JÁ é a resposta final: quando a única chamada do turno é uma
# delas e deu certo, responder com o próprio texto evita uma segunda ida ao LLM (o que
# corta quase metade do tempo até a mensagem aparecer). O resumo do modelo, nesses casos,
# só repetia o que a ferramenta já disse.
TERMINAL_TOOLS = frozenset({"delete_channels", "delete_role", "clear_messages"})

# Pedido extra na mesma frase ("apague os canais E MANDE OI", "e depois me diga"): nesse caso
# o resultado da ferramenta NÃO é a resposta completa — o modelo precisa continuar.
_PEDIDO_EXTRA_RE = re.compile(
    r"\b(?:e|depois|tambem|tb|em seguida|entao|ai|apos|apos isso)\s+"
    r"(?:mande|manda|diga|diz|fale|fala|responda|responde|avise|avisa|resuma|resume|conte|conta|"
    r"mostre|mostra|liste|lista|verifique|verifica|confira|confere|crie|cria|faca|"
    r"me\s+(?:diga|diz|fale|fala|conte|conta|mostre|mostra|explique|explica|resuma))"
)

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
        confirm_destructive: bool = False,
        direct_tool_reply: bool = True,
    ) -> None:
        self.llm = llm_provider
        self.confirm_destructive = confirm_destructive
        self.direct_tool_reply = direct_tool_reply
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

    @staticmethod
    def _parece_ingles(texto: str) -> bool:
        """Heurística conservadora: só acusa inglês quando ele domina o texto."""
        baixo = f" {texto.lower()} "
        pontos_en = sum(1 for marca in _MARCADORES_INGLES if marca in baixo)
        pontos_pt = sum(1 for marca in _MARCADORES_PORTUGUES if marca in baixo)
        if pontos_en < 2:
            return False
        # Texto curto com 2+ marcadores fortes já é suspeito; em texto longo exige domínio.
        if len(baixo) < 200:
            return pontos_en >= 2 and pontos_pt == 0
        return pontos_en > pontos_pt

    # Marcas que só existem DENTRO do prompt/plumbing do bot: se aparecem na resposta, o modelo
    # devolveu o contexto em vez de conversar (foi assim que um "oi" virou um textão).
    _MARCADORES_INTERNOS = (
        "[ação solicitada", "[acao solicitada", "```tool", "protocolo de ferramentas",
        "tool_protocol", '"tool_calls"', '"type": "function"', "system prompt",
        "ferramentas disponíveis",
    )

    @classmethod
    def _eco_de_contexto(cls, texto: str) -> str:
        """Devolve a marca encontrada quando a resposta é um eco do que o bot mandou ao modelo."""
        baixo = texto.lower()
        for marca in cls._MARCADORES_INTERNOS:
            if marca in baixo:
                return marca
        return ""

    @classmethod
    def resposta_ruim(cls, texto: str) -> str | None:
        """Motivo pelo qual a resposta não pode ir pro Discord (ou None se está boa)."""
        if not texto or not texto.strip():
            return "vazia"
        eco = cls._eco_de_contexto(texto)
        if eco:
            return f"eco do contexto interno ({eco})"
        if parece_raciocinio(texto):
            return "rascunho do modelo"
        if len(texto) > MAX_RESPOSTA_CHARS:
            return f"texto gigante ({len(texto)} chars)"
        if cls._parece_ingles(texto):
            return "inglês"
        return None

    def _resumo_do_que_foi_feito(
        self,
        channel_id: Any,
        execucoes: list[str],
        execucoes_finais: list[str],
    ) -> str:
        """
        Resposta honesta quando o LLM cai DEPOIS de a ação já ter sido executada.

        O que não pode acontecer: o bot apagar/criar algo e responder "não consegui falar com
        nenhum modelo" — o cliente acharia que nada aconteceu. Preferimos o resultado real da
        ferramenta (já em português) e, sem ele, dizemos exatamente quais ações rodaram.
        """
        for resultado in reversed(execucoes_finais):
            if resultado and not resultado.startswith("Erro") and self.resposta_ruim(resultado) is None:
                self.memory.add_message(channel_id, {"role": "assistant", "content": resultado})
                return resultado

        acoes = ", ".join(dict.fromkeys(execucoes))
        texto = (
            f"✅ Fiz o que você pediu ({acoes}), mas os modelos gratuitos ficaram instáveis agora "
            "e eu não consegui escrever o resumo. Confira no servidor e me diga se falta algo."
        )
        self.memory.add_message(channel_id, {"role": "assistant", "content": texto})
        return texto

    async def _garantir_resposta_apresentavel(
        self,
        channel_id: Any,
        texto: str,
        execucoes_finais: list[str],
        messages: list[dict[str, Any]],
    ) -> str:
        """
        Última barreira antes do Discord: nada de rascunho, textão ou inglês.

        1. tira rascunho que o provedor tenha deixado passar;
        2. se a resposta está ruim, pede UMA reescrita curta em português;
        3. se nem isso deu certo, responde com o resultado real da ferramenta (já em PT) —
           nunca com o texto ruim.
        """
        _, limpo = separar_raciocinio(texto or "")
        motivo = self.resposta_ruim(limpo)
        if motivo is None:
            return limpo

        logger.info("resposta descartada (%s); pedindo reescrita em PT-BR", motivo)
        reescrita = list(messages) + [{
            "role": "user",
            "content": (
                "Reescreva em português do Brasil, em NO MÁXIMO 3 linhas, apenas o resultado "
                f"para o usuário (motivo do descarte: {motivo}). Não mostre raciocínio, não "
                "responda em inglês, não repita instruções. Se não houver nada a dizer, "
                'responda apenas "Feito!".'
            ),
        }]
        try:
            resposta = await self.llm.chat(messages=reescrita, tools=None, timeout=self.llm_timeout)
            _, candidata = separar_raciocinio((resposta.content or "").strip())
            if self.resposta_ruim(candidata) is None:
                self.memory.add_message(channel_id, {"role": "assistant", "content": candidata})
                return candidata
        except Exception as exc:  # noqa: BLE001 - se o conserto falhar, cai no fallback
            logger.warning("reescrita em PT-BR falhou (%s)", exc)

        for resultado in reversed(execucoes_finais):
            if resultado and not resultado.startswith("Erro") and self.resposta_ruim(resultado) is None:
                self.memory.add_message(channel_id, {"role": "assistant", "content": resultado})
                return resultado

        seguro = "Feito! ✅ Confira no servidor e me diga se falta algo."
        self.memory.add_message(channel_id, {"role": "assistant", "content": seguro})
        return seguro

    @staticmethod
    def _pedido_extra(prompt: str) -> bool:
        """True quando a frase pede algo ALÉM do comando (ex.: 'apague X e mande oi')."""
        return bool(_PEDIDO_EXTRA_RE.search(_strip_accents(prompt.lower())))

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

        if not self.confirm_destructive:
            # Modo direto: o pedido do usuário já autorizou — o `confirmed=true` do modelo vale.
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
            confirm_destructive=self.confirm_destructive,
        )

        snapshot = build_server_snapshot(guild)
        if self.confirm_destructive:
            politica = (
                "o bot está em modo CAUTELOSO. Excluir UM canal indicado nominalmente executa direto; "
                "excluir 2+ canais, esvaziar categoria ou excluir cargo pede confirmação e espera um "
                '"sim" do usuário antes de mandar `confirmed=true`.'
            )
        else:
            politica = (
                "MODO DIRETO (padrão). O pedido do usuário JÁ é a autorização: execute a ferramenta "
                "IMEDIATAMENTE, com `confirmed=true` quando o schema pedir esse campo, e responda em "
                "UMA linha o que foi feito, com os nomes/links do que mudou. NUNCA peça confirmação, "
                "nunca pergunte 'posso apagar?', nunca espere um segundo 'sim'. Se a ferramenta "
                'responder "confirme com o usuário", chame de novo com `confirmed=true` e siga.'
            )
        system_content = SYSTEM_PROMPT_TEMPLATE.format(snapshot=snapshot, confirmacao=politica)

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
        execucoes_finais: list[str] = []

        while rounds < self.max_tool_rounds:
            rounds += 1

            response: LLMResponse
            try:
                response = await self.llm.chat(
                    messages=messages,
                    tools=self.tools_schema,
                    timeout=self.llm_timeout,
                )
            except Exception as exc:  # noqa: BLE001 - o que já foi executado não pode sumir
                if not execucoes:
                    raise
                logger.warning(
                    "LLM caiu na rodada %d depois de executar %s (%s); respondendo com o "
                    "resultado real", rounds, execucoes, exc)
                return self._resumo_do_que_foi_feito(channel_id, execucoes, execucoes_finais)

            tool_calls = response.tool_calls
            # Se não houver tool_calls nativas, verificar fallback em texto
            if not tool_calls and response.content:
                tool_calls = _extract_fallback_tool_calls(response.content)

            if not tool_calls:
                limpa = await self._garantir_resposta_apresentavel(
                    channel_id, (response.content or "").strip(), execucoes_finais, messages)
                final_text = self._com_pergunta_de_confirmacao(channel_id, limpa)
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
                execucoes_finais.append(result_str)

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

            # Atalho de velocidade: uma única ferramenta terminal que deu certo já produziu
            # a resposta final — devolvê-la direto evita a segunda chamada ao LLM.
            if (self.direct_tool_reply and len(tool_calls) == 1 and not pedindo_confirmacao
                    and tool_calls[0].name in TERMINAL_TOOLS
                    and not self._pedido_extra(prompt)):
                resultado = execucoes_finais[-1] if execucoes_finais else ""
                if resultado and not resultado.startswith("Erro"):
                    self.memory.add_message(channel_id, {"role": "assistant", "content": resultado})
                    return resultado

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
            return self._resumo_do_que_foi_feito(channel_id, execucoes, execucoes_finais)
        limpa = await self._garantir_resposta_apresentavel(
            channel_id, (final_resp.content or "").strip(), execucoes_finais, messages)
        final_text = self._com_pergunta_de_confirmacao(channel_id, limpa)
        if final_text:
            self.memory.add_message(channel_id, {"role": "assistant", "content": final_text})
        return final_text or "Operações concluídas."
