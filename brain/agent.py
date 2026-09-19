"""
Loop do Agente Atlas: Prompt de sistema + Snapshot + Histórico → LLM → Tools → Resposta.
Suporta fallback de extração de ferramentas em texto puro (```tool {...}```).
NÃO importa discord (duck-typing estrito).
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import deque
from typing import Any

from brain.executors import execute_tool
from brain.memory import ChannelMemory, memory_key
from brain.snapshot import build_server_snapshot
from brain.tools import ToolContext, ToolError, get_tool_definitions
from llm.base import (ChatProvider, parece_raciocinio, separar_raciocinio, extract_text_tool_calls,
                      LLMResponse, ToolCall)

logger = logging.getLogger("atlas.brain.agent")

SYSTEM_PROMPT_TEMPLATE = """Você é o `atlas`, um bot de Discord especialista em construir, estruturar e organizar servidores.
Você executa ações reais no servidor chamando ferramentas.

REGRAS ABSOLUTAS:
1. TODAS as ferramentas listadas existem e estão disponíveis. NUNCA diga que uma ferramenta "não está disponível", "não existe" ou "está desativada". Se tiver dúvida, CHAME a ferramenta: a resposta dela é a verdade.
2. Não fique pedindo licença: se o pedido é claro e não destrutivo, execute agora e conte o resultado.
3. Se vier Erro de uma ferramenta, repasse o motivo do Erro e o que o usuário precisa fazer (exemplo: falta de permissão).
4. Nunca invente IDs ou nomes: use a ESTRUTURA ATUAL abaixo para localizar canais e cargos existentes.
   NUNCA diga que fez algo que uma ferramenta não confirmou — se não chamou, não aconteceu.
4.0. MENOS ESSE: quando o pedido disser "menos esse", "exceto esse", "tira esse", "não apague
   este" ou algo parecido, NÃO inclua o canal onde estamos conversando na lista de exclusão. Se
   incluir, o bot mantém o canal da conversa fora da lista e avisa — mas o certo é não pedir.
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
# (rascunho de modelo grátis, lista imensa, etc.) — o Atlas responde curto.
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

# Ordem de execução DENTRO da mesma mensagem. "Recriar o canal" vira clone + delete: se o
# delete rodar primeiro e a criação falhar, o canal some e não volta (foi o que o dono do
# servidor viu). Quem CRIA roda antes; quem APAGA roda depois — e só se a criação deu certo.
TOOLS_QUE_CRIAM = frozenset({
    "create_channels", "create_roles", "clone_channel", "import_structure", "apply_template",
    "edit_channel", "edit_role", "set_permissions", "clear_permissions", "sync_permissions",
    "give_role", "take_role", "move_channel",
})
TOOLS_QUE_APAGAM = frozenset({"delete_channels", "delete_role", "delete_roles", "clear_messages"})
# Destes, os que CRIAM algo novo. Só a FALHA de um deles bloqueia exclusões da mesma mensagem:
# uma edição que falha não pode travar o "apague o canal Y" que veio na mesma frase.
TOOLS_QUE_CRIAM_DE_VERDADE = frozenset({
    "create_channels", "create_roles", "clone_channel", "import_structure", "apply_template",
})

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


def _ordenar_por_seguranca(tool_calls: list[Any]) -> list[Any]:
    """
    Quem cria/copia vem antes de quem apaga, mantendo a ordem original dentro de cada grupo.

    Sem isso, "recrie o canal X" podia executar o `delete_channels` antes do clone: se a criação
    falhasse (modelo fora do ar, limite de requisições), o canal sumia e não voltava.
    """
    def peso(call: Any) -> int:
        nome = getattr(call, "name", "")
        if nome in TOOLS_QUE_APAGAM:
            return 2
        if nome in TOOLS_QUE_CRIAM:
            return 0
        return 1

    return sorted(tool_calls, key=peso)


def _assinatura_da_chamada(call: Any) -> str:
    """Identidade da chamada (nome + argumentos) para não executar a mesma coisa duas vezes."""
    try:
        args = json.dumps(call.args or {}, sort_keys=True, ensure_ascii=False)
    except Exception:  # noqa: BLE001 - argumento exótico não pode derrubar o turno
        args = repr(call.args)
    return f"{getattr(call, 'name', '')}:{args}"


# Marca do resultado devolvido quando o modelo repete a MESMA chamada: entra no histórico para
# o modelo entender que já foi feito, mas NUNCA é a resposta mostrada ao usuário.
_REPETIDA_PREFIXO = "(já executei esta mesma chamada nesta mensagem)"


def _texto_das_falhas(falhas: list[str]) -> str:
    """Motivo real das falhas, sem o prefixo interno 'Erro:' e sem repetir a mesma coisa."""
    limpos = []
    for f in falhas:
        texto = f[5:].strip() if f.startswith("Erro:") else f
        if texto and texto not in limpos:
            limpos.append(texto)
    return ("❌ Não deu para concluir: " + " ".join(limpos))[:900]


def _resultado_apresentavel(resultado: str) -> bool:
    """True para resultado real de ferramenta (não erro, não aviso de chamada repetida)."""
    return bool(resultado) and not resultado.startswith(("Erro", _REPETIDA_PREFIXO))


def _normalizar_alvo(valor: Any) -> str:
    """Nome/id de um alvo em forma comparável ("#Geral", "<#123>", "123" → "geral"/"123")."""
    txt = str(valor).strip().casefold()
    m = re.fullmatch(r"<(?:#|@&?)?(\d+)>", txt) or re.fullmatch(r"[#@&]?(\d+)", txt)
    if m:
        return m.group(1)
    return txt.lstrip("#@&").strip()


def _alvos_de_exclusao(tool_calls: list[Any]) -> set[str]:
    """Nomes/ids que esta mensagem vai apagar (para não confundir recriação com duplicata)."""
    alvos: set[str] = set()
    for call in tool_calls:
        args = dict(getattr(call, "args", None) or {})
        nome = getattr(call, "name", "")
        if nome == "delete_channels":
            alvos.update(_normalizar_alvo(c) for c in (args.get("channels") or []))
        elif nome == "delete_role":
            if args.get("role"):
                alvos.add(_normalizar_alvo(args["role"]))
        elif nome == "delete_roles":
            alvos.update(_normalizar_alvo(r) for r in (args.get("roles") or []))
    return alvos


# O modelo grátis, muitas vezes, responde com PLANO/PROMESSA ("Vou criar o canal agora!",
# "Deixa comigo, primeiro eu verifico…") sem chamar ferramenta nenhuma. O bot mandava esse texto
# para o Discord como se fosse resposta e o cliente tinha de pedir DE NOVO — era o "tive que pedir
# várias vezes". Aqui o pedido de ação sem ação vira uma cobrança ao modelo antes de desistir.
_VERBO_DE_ACAO_RE = re.compile(
    r"\b(crie|cria|criar|criem|apague|apaga|apagar|delete|deletar|exclua|excluir|renomeie|renomear|"
    r"mude|mudar|edite|editar|mova|mover|clone|clonar|recrie|recriar|adicione|adicionar|remova|"
    r"remover|suba|subir|des[cç]a|descer|ajuste|ajustar|configure|configurar|defina|definir|"
    r"permita|permitir|negue|negar|sincronize|sincronizar|limpe|limpar|exporte|exportar|importe|"
    r"importar|liste|listar|mostre|mostrar|atualize|atualizar|troque|trocar|tire|tirar|"
    r"coloque|colocar|arraste|arrastar|ative|ativar|desative|desativar|monte|montar|organize|"
    r"organizar|quero|preciso|pode\s+(?:criar|apagar|editar|mover|renomear|excluir))\b"
)
_PROMESSA_RE = re.compile(
    r"\b(vou |vamos |irei |iremos |estou criando|estou apagando|estou editando|estou ajustando|"
    r"deixa comigo|deixe comigo|primeiro|passo 1|passo a passo|plano|planejando|a seguir|"
    r"come[çc]ando|vou come[çc]ar|agora vou|em seguida vou|meu plano)\b"
)
_IMPEDIMENTO_RE = re.compile(
    r"\b(n[ãa]o posso|n[ãa]o vou|n[ãa]o consigo|n[ãa]o deu|n[ãa]o tenho permiss|sem permiss|"
    r"fora do meu escopo|n[ãa]o [ée] minha [áa]rea|meu foco|deu erro|falhou|indispon[íi]vel|"
    r"fila cheia|tente de novo|limite de uso)\b"
)

NUDGE_SEM_ACAO = (
    "Você descreveu o que pretende fazer, mas NÃO chamou nenhuma ferramenta e nada foi feito. "
    "Se o pedido do usuário exige ação, chame AGORA a ferramenta certa (uma chamada, com os "
    "argumentos completos). Não escreva plano, passo a passo, promessa nem pedido de desculpas. "
    "Se faltar alguma informação para executar, faça UMA pergunta curta."
)


def _extract_fallback_tool_calls(text: str, nomes_de_ferramenta: set[str] | None = None) -> list[ToolCall]:
    """
    Chamadas escritas em TEXTO (provedores grátis sem function calling).

    O parser vive em `llm/base.py` porque o PROVEDOR também precisa dele: o modelo às vezes
    escreve a chamada dentro do "rascunho interno" e o corte do rascunho apagava a ação — o
    cliente pedia de novo e nada acontecia.
    """
    return extract_text_tool_calls(text, nomes_de_ferramenta)


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
        nudge_promise: bool = True,
    ) -> None:
        self.llm = llm_provider
        self.confirm_destructive = confirm_destructive
        self.direct_tool_reply = direct_tool_reply
        self.memory = memory if memory is not None else ChannelMemory()
        self.max_tool_rounds = max_tool_rounds
        self.llm_timeout = llm_timeout
        self.api_registry = api_registry
        definicoes = get_tool_definitions()
        self.tools_schema = [t.to_openai() for t in definicoes]
        self._nomes_de_ferramenta = {t.name for t in definicoes}
        # Cobrar a ferramenta quando o modelo só prometeu (desligável por NUDGE_PROMISE=false).
        self.nudge_promise = nudge_promise
        # Tempo das últimas respostas (nenhum conteúdo de conversa, só números).
        self.tempos: deque[dict[str, float]] = deque(maxlen=20)
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
        falhas = [r for r in execucoes_finais if r.startswith("Erro")]
        reais = [r for r in execucoes_finais
                 if _resultado_apresentavel(r) and self.resposta_ruim(r) is None]
        if not reais and falhas:
            # Nada foi executado com sucesso: dizer "fiz o que você pediu" seria mentira.
            texto = _texto_das_falhas(falhas)
            self.memory.add_message(channel_id, {"role": "assistant", "content": texto})
            return texto
        if reais:
            # 2+ ações no mesmo pedido ("recrie o canal" = criou + apagou): mostrar só a última
            # esconderia metade do que foi feito. Junta as duas, desde que continue curto.
            combinado = " · ".join(dict.fromkeys(reais))
            texto = combinado if len(reais) > 1 and len(combinado) <= 500 else reais[-1]
            self.memory.add_message(channel_id, {"role": "assistant", "content": texto})
            return texto

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
            if _resultado_apresentavel(resultado) and self.resposta_ruim(resultado) is None:
                self.memory.add_message(channel_id, {"role": "assistant", "content": resultado})
                return resultado

        falhas = [r for r in execucoes_finais if r.startswith("Erro")]
        if falhas:
            # Antes daqui saía "Feito! ✅" mesmo quando NADA foi feito — pior do que o erro.
            texto = _texto_das_falhas(falhas)
            self.memory.add_message(channel_id, {"role": "assistant", "content": texto})
            return texto

        seguro = "Feito! ✅ Confira no servidor e me diga se falta algo."
        self.memory.add_message(channel_id, {"role": "assistant", "content": seguro})
        return seguro

    def _registrar_tempo(self, total: float, llm: list[float], ferramentas: list[float]) -> None:
        """
        Guarda e LOGA o tempo do turno (nada de conteúdo de conversa): é assim que se mede
        "demora" de verdade sem ler o chat de ninguém.
        """
        registro = {
            "total": round(total, 3),
            "llm": round(sum(llm), 3),
            "ferramentas": round(sum(ferramentas), 3),
        }
        self.tempos.append(registro)
        logger.info(
            "turno: %.1fs no total (LLM %.1fs em %d chamada(s); ferramentas %.1fs em %d chamada(s))",
            registro["total"], registro["llm"], len(llm),
            registro["ferramentas"], len(ferramentas),
        )

    def resumo_de_tempos(self) -> str:
        """Resumo (em português) do tempo das últimas respostas — sem nenhum texto de conversa."""
        from brain.ops import resumo_de_tempos as _formatar

        return _formatar(self.tempos)

    @staticmethod
    def _pedido_de_acao(prompt: str) -> bool:
        """True quando a frase PEDE uma ação (criar, apagar, editar, listar, mover...)."""
        texto = _strip_accents((prompt or "").lower())
        return bool(_VERBO_DE_ACAO_RE.search(texto))

    @classmethod
    def _promessa_sem_acao(cls, prompt: str, texto: str) -> bool:
        """
        True quando o modelo respondeu com PLANO/PROMESSA (ou "Pronto!" sem nada) em vez de agir.

        É o caso que faz o cliente repetir o pedido: o bot manda "Vou criar o canal agora!" e nada
        acontece. Pergunta de esclarecimento (com "?") e recusa legítima NÃO entram — são
        respostas finais válidas.
        """
        if not cls._pedido_de_acao(prompt):
            return False
        bruto = (texto or "").strip()
        if not bruto or "?" in bruto or asks_for_confirmation(bruto):
            return False
        limpo = _strip_accents(bruto.lower())
        if _IMPEDIMENTO_RE.search(limpo):
            return False
        if _PROMESSA_RE.search(limpo):
            return True
        # Sem promessa explícita, ainda vale cobrar quando a resposta não traz NENHUMA evidência
        # de resultado (sem menção de canal/cargo, sem número): "Certo, feito!" mentiroso.
        evidencia = re.search(r"<[#@]", bruto) or re.search(r"\d", bruto)
        return not evidencia and len(bruto) < 400

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
        ctx.tempos = self.tempos  # a ferramenta performance_report lê daqui (só números)

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
        # Tempo do turno por etapa (medir "demora" sem depender de ler o chat de ninguém)
        inicio_turno = time.monotonic()
        segundos_llm: list[float] = []
        segundos_ferramentas: list[float] = []

        def _fechar_turno(texto: str) -> str:
            self._registrar_tempo(time.monotonic() - inicio_turno, segundos_llm, segundos_ferramentas)
            return texto

        while rounds < self.max_tool_rounds:
            rounds += 1

            response: LLMResponse
            _t = time.monotonic()
            try:
                response = await self.llm.chat(
                    messages=messages,
                    tools=self.tools_schema,
                    timeout=self.llm_timeout,
                )
            except Exception as exc:  # noqa: BLE001 - o que já foi executado não pode sumir
                segundos_llm.append(time.monotonic() - _t)
                if not execucoes:
                    raise
                logger.warning(
                    "LLM caiu na rodada %d depois de executar %s (%s); respondendo com o "
                    "resultado real", rounds, execucoes, exc)
                return _fechar_turno(
                    self._resumo_do_que_foi_feito(channel_id, execucoes, execucoes_finais))
            segundos_llm.append(time.monotonic() - _t)

            tool_calls = response.tool_calls
            # Se não houver tool_calls nativas, verificar fallback em texto
            if not tool_calls and response.content:
                tool_calls = _extract_fallback_tool_calls(response.content, self._nomes_de_ferramenta)

            if not tool_calls:
                if (self.nudge_promise and not execucoes and rounds < self.max_tool_rounds
                        and self._promessa_sem_acao(prompt, response.content or "")):
                    # Cobrar a ação é uma ida a mais ao modelo, mas evita o pior: o cliente ler
                    # uma promessa, nada acontecer e ter de pedir tudo de novo.
                    logger.info("O modelo prometeu e não chamou ferramenta; cobrando a ação "
                                "(rodada %d)", rounds)
                    messages.append({"role": "assistant", "content": response.content or ""})
                    messages.append({"role": "user", "content": NUDGE_SEM_ACAO})
                    continue
                limpa = await self._garantir_resposta_apresentavel(
                    channel_id, (response.content or "").strip(), execucoes_finais, messages)
                final_text = self._com_pergunta_de_confirmacao(channel_id, limpa)
                if final_text:
                    self.memory.add_message(channel_id, {"role": "assistant", "content": final_text})
                    if asks_for_confirmation(final_text):
                        # perguntou no TEXTO (sem chamar a ferramenta): o "sim" da próxima
                        # mensagem precisa valer para a ferramenta destrutiva que vier
                        self._marcar_pendencia(channel_id, {"*"})
                return _fechar_turno(final_text or "Operação concluída com sucesso.")

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

            # Executar cada ferramenta — na ordem segura, sem repetir a mesma chamada e sem
            # apagar nada quando a criação da mesma mensagem falhou.
            _t_ferramentas = time.monotonic()
            pedindo_confirmacao: set[str] = set()
            falhou_criacao = False
            # "recrie o canal X" manda apagar X e criar X: a criação não pode ser pulada como
            # duplicata só porque X ainda existe (o delete roda depois, na ordem segura).
            ctx.alvos_apagados = _alvos_de_exclusao(tool_calls)
            ja_executadas: dict[str, str] = {}
            for call in _ordenar_por_seguranca(tool_calls):
                assinatura = _assinatura_da_chamada(call)
                if assinatura in ja_executadas:
                    # O modelo repetiu a MESMA chamada (acontece com os gratuitos): rodar de novo
                    # criava cargo/canal duplicado. Devolve o primeiro resultado e segue.
                    anterior = ja_executadas[assinatura]
                    result_str = f"{_REPETIDA_PREFIXO} {anterior}"
                    logger.info("Chamada repetida ignorada: %s", call.name)
                else:
                    args = self._authorize_confirmed(channel_id, call.name,
                                                     dict(call.args or {}), prompt)
                    if call.name in TOOLS_QUE_APAGAM and falhou_criacao:
                        result_str = ("Erro: não apaguei nada porque a criação pedida na mesma "
                                      "mensagem falhou — apagar agora deixaria o servidor sem o "
                                      "substituto. Corrija a criação e me peça de novo.")
                        logger.warning("Exclusão bloqueada: a criação da mesma mensagem falhou")
                    else:
                        try:
                            result_str = await execute_tool(call.name, args, ctx)
                        except ToolError as exc:
                            result_str = f"Erro: {exc}"
                        except Exception as exc:
                            result_str = f"Erro inesperado: {exc}"
                    ja_executadas[assinatura] = result_str
                    if call.name in TOOLS_QUE_CRIAM_DE_VERDADE and result_str.startswith("Erro"):
                        falhou_criacao = True

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

            segundos_ferramentas.append(time.monotonic() - _t_ferramentas)

            if pedindo_confirmacao:
                self._marcar_pendencia(channel_id, pedindo_confirmacao)
            elif any(c.name in CONFIRMATION_TOOLS for c in tool_calls):
                # a ferramenta destrutiva rodou de verdade (o usuário já havia confirmado)
                self._aguardando_confirmacao.pop(channel_id, None)

            # Atalho de velocidade: uma única ferramenta que deu certo já produziu a resposta
            # final (todas as ferramentas respondem em PT-BR). Devolver direto evita a segunda
            # chamada ao LLM — era esse ida-e-volta extra que fazia o bot "demorar para agir".
            if (self.direct_tool_reply and len(tool_calls) == 1 and not pedindo_confirmacao
                    and not self._pedido_extra(prompt)):
                resultado = next((r for r in reversed(execucoes_finais)
                                  if _resultado_apresentavel(r)), "")
                if resultado:
                    self.memory.add_message(channel_id, {"role": "assistant", "content": resultado})
                    return _fechar_turno(resultado)

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
            return _fechar_turno(
                self._resumo_do_que_foi_feito(channel_id, execucoes, execucoes_finais))
        limpa = await self._garantir_resposta_apresentavel(
            channel_id, (final_resp.content or "").strip(), execucoes_finais, messages)
        final_text = self._com_pergunta_de_confirmacao(channel_id, limpa)
        if final_text:
            self.memory.add_message(channel_id, {"role": "assistant", "content": final_text})
            return _fechar_turno(final_text)
        falhas = [r for r in execucoes_finais if r.startswith("Erro")]
        if falhas:
            texto = _texto_das_falhas(falhas)
            self.memory.add_message(channel_id, {"role": "assistant", "content": texto})
            return _fechar_turno(texto)
        return _fechar_turno("Operações concluídas.")
