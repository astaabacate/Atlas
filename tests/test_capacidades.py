"""
Matriz de capacidades: para CADA ferramenta do Farol, cada parâmetro, cada valor (válido e
inválido) e as combinações — não "chamar uma vez e dizer que testou".

Protocolo do dono do projeto: testar tudo que o código implementa, e não apenas os exemplos
citados. O que estes testes cobrem (sem rede, com objetos falsos que registram toda chamada):

CANAIS
  * tipos suportados: text, voice, category, stage, forum (+ apelidos em PT-BR);
  * nome, categoria (dentro/fora), tópico, NSFW, slowmode, bitrate, limite de usuários, posição;
  * edição de cada propriedade e combinações; mover por categoria/posição; clonar; excluir;
  * valores inválidos e fora de faixa → erro claro em PT, sem chamar a API;
  * tipo desconhecido → erro (antes virava canal de texto silenciosamente).

CARGOS
  * nome, cor, hoist, mentionable, permissões (uma, várias, PT-BR e inglês), posição;
  * lote com propriedades próprias e globais; teto de lote; item sem nome;
  * edição de cada propriedade e combinação; erro quando nada foi pedido;
  * valor inválido (cor, posição negativa, permissão inexistente) → erro claro.

PERMISSÕES (overwrites, sync, leitura)
  * allow/deny em PT-BR e inglês; conflito allow∩deny; lista vazia; permissão desconhecida;
  * limpar override; sincronizar com a categoria; leitura do que está configurado.

ESTRUTURA (export/import)
  * export guarda tipo, tópico, nsfw, slowmode, bitrate, limite, posição, permissões do cargo;
  * import recria com os MESMOS campos (round-trip), incluindo canais sem categoria;
  * falha de um item não impede os outros e aparece no relatório.

MENSAGENS
  * limite 1..500 válido; 0, negativo, acima do teto e não numérico → erro claro.
"""

from __future__ import annotations

import asyncio
import json
import types
import unittest
import unittest.mock
from typing import Any

from brain import ops
from brain.executors import execute_tool
from brain.ops import Permissoes, resolver_permissao
from brain.tools import ToolContext, ToolError


# --------------------------------------------------------------------- duplos

class FakePerms:
    def __init__(self, **flags: bool) -> None:
        for nome, valor in flags.items():
            setattr(self, nome, bool(valor))


class Entidade:
    """Cargo ou membro: hashable (o discord.py usa como chave dos overwrites)."""

    def __init__(self, nome: str, eid: int, position: int = 1, cor: int = 0) -> None:
        self.name = nome
        self.id = eid
        self.position = position
        self.color = types.SimpleNamespace(value=cor)
        self.permissions = types.SimpleNamespace(value=0)
        self.hoist = False
        self.mentionable = False
        self.edits: list[dict[str, Any]] = []
        self.nick = None
        self.display_name = nome
        self.guild_permissions = FakePerms(administrator=True)
        self.top_role = None

    def is_default(self) -> bool:
        return False

    async def edit(self, **kwargs: Any) -> "Entidade":
        self.edits.append(kwargs)
        for chave in ("name", "hoist", "mentionable", "position", "color"):
            if chave in kwargs:
                setattr(self, chave, kwargs[chave])
        if "permissions" in kwargs:
            self.permissions = kwargs["permissions"]
        return self

    async def delete(self) -> None:
        self.deleted = True


class Canal:
    def __init__(self, nome: str, cid: int, tipo: str = "text", categoria: Any = None) -> None:
        self.name = nome
        self.id = cid
        self.type = types.SimpleNamespace(name=tipo)
        self.category = categoria
        self.topic: str | None = None
        self.nsfw = False
        self.slowmode_delay = 0
        self.bitrate: int | None = None
        self.user_limit: int | None = None
        self.position = 0
        self.overwrites: dict[Any, Any] = {}
        self.edits: list[tuple[str, dict[str, Any]]] = []
        self.channels: list[Any] = []  # só categorias usam (como no discord.py)
        self.clonado = False

    async def edit(self, **kwargs: Any) -> "Canal":
        self.edits.append(("edit", kwargs))
        for chave in ("name", "topic", "category", "nsfw", "slowmode_delay", "bitrate",
                      "user_limit", "position"):
            if chave in kwargs:
                setattr(self, chave, kwargs[chave])
        if kwargs.get("sync_permissions"):
            self.edits.append(("sync", {}))
        return self

    async def set_permissions(self, target: Any, **kwargs: Any) -> None:
        # igual ao discord.py: só mexe nos campos informados, o resto do override fica
        atual = self.overwrites.get(target)
        if kwargs.get("overwrite", "ausente") is None:
            self.overwrites[target] = {"overwrite": None}
            return
        kwargs.pop("overwrite", None)
        if not isinstance(atual, dict):
            atual = {}
        atual.pop("overwrite", None)
        atual.update(kwargs)
        self.overwrites[target] = atual

    async def delete(self) -> None:
        self.deleted = True

    async def clone(self, **kwargs: Any) -> "Canal":
        self.clonado = True
        novo = Canal(kwargs.get("name", self.name), self.id + 1000, self.type.name, self.category)
        novo.topic = self.topic
        novo.nsfw = self.nsfw
        novo.slowmode_delay = self.slowmode_delay
        novo.overwrites = dict(self.overwrites)
        return novo

    async def purge(self, limit: int = 50) -> list[Any]:
        self.purged = limit
        return [object()] * min(limit, 3)


class Servidor:
    def __init__(self) -> None:
        self.name = "Servidor Teste"
        self.id = 111
        self.description = ""
        self.icon = None
        self._seq = 100
        self.channels: list[Any] = []
        self.categories: list[Any] = []
        self.roles = [Entidade("@everyone", 1, 0)]
        self.members: list[Any] = []
        self.na_api: dict[int, Any] = {}  # existem no servidor, mas fora do cache local
        self.bitrate_limit = 96000  # sem boost, como no servidor real de teste
        self.criados: list[tuple[str, str, dict[str, Any]]] = []
        self.me = types.SimpleNamespace(id=999, name="farol",
                                        guild_permissions=FakePerms(administrator=True),
                                        top_role=Entidade("farol", 999, 50))
        self.edits: list[dict[str, Any]] = []

    def _id(self) -> int:
        self._seq += 1
        return self._seq

    async def fetch_roles(self) -> list[Any]:
        """Como no Discord: a lista real de cargos do servidor."""
        return list(self.roles)

    async def fetch_member(self, membro_id: int) -> Any:
        """Como no Discord: busca na API quem não está no cache."""
        if membro_id in self.na_api:
            return self.na_api[membro_id]
        for m in self.members:
            if getattr(m, "id", None) == membro_id:
                return m
        raise Exception("404 Not Found (10007): Unknown Member")

    # criação (registra TUDO que chegou)
    async def create_text_channel(self, name: str, **kwargs: Any) -> Canal:
        self.criados.append(("text", name, kwargs))
        ch = Canal(name, self._id(), "text", kwargs.get("category"))
        self.channels.append(ch)
        return ch

    async def create_voice_channel(self, name: str, **kwargs: Any) -> Canal:
        self.criados.append(("voice", name, kwargs))
        ch = Canal(name, self._id(), "voice", kwargs.get("category"))
        self.channels.append(ch)
        return ch

    async def create_category(self, name: str, **kwargs: Any) -> Canal:
        self.criados.append(("category", name, kwargs))
        cat = Canal(name, self._id(), "category")
        self.channels.append(cat)
        self.categories.append(cat)
        return cat

    async def create_stage_channel(self, name: str, **kwargs: Any) -> Canal:
        self.criados.append(("stage", name, kwargs))
        ch = Canal(name, self._id(), "stage", kwargs.get("category"))
        self.channels.append(ch)
        return ch

    async def create_forum(self, name: str, **kwargs: Any) -> Canal:
        self.criados.append(("forum", name, kwargs))
        ch = Canal(name, self._id(), "forum", kwargs.get("category"))
        self.channels.append(ch)
        return ch

    async def create_role(self, name: str, **kwargs: Any) -> Entidade:
        self.criados.append(("role", name, kwargs))
        papel = Entidade(name, self._id(), kwargs.get("position", 1))
        papel.hoist = kwargs.get("hoist", False)
        papel.mentionable = kwargs.get("mentionable", False)
        if "color" in kwargs:
            papel.color = kwargs["color"]
        if "permissions" in kwargs:
            papel.permissions = kwargs["permissions"]
        self.roles.append(papel)
        return papel

    async def edit(self, **kwargs: Any) -> "Servidor":
        self.edits.append(kwargs)
        return self

    def get_channel(self, cid: int) -> Any:
        return next((c for c in self.channels if c.id == cid), None)


class ServidorRedeLenta(Servidor):
    """
    Igual ao `Servidor`, mas cada criação espera a rede (como o Discord de verdade).

    O lote roda com concorrência 3: sem essa espera os objetos falsos nascem antes de qualquer
    outro item ser conferido, e a corrida que criou canais/cargos duplicados NO SERVIDOR do dono
    (uma chamada só, dois itens com o mesmo nome) não apareceria nos testes.
    """

    async def _espera_da_rede(self) -> None:
        await asyncio.sleep(0.01)

    async def create_text_channel(self, name: str, **kwargs: Any) -> Canal:
        await self._espera_da_rede()
        return await super().create_text_channel(name, **kwargs)

    async def create_voice_channel(self, name: str, **kwargs: Any) -> Canal:
        await self._espera_da_rede()
        return await super().create_voice_channel(name, **kwargs)

    async def create_role(self, name: str, **kwargs: Any) -> Entidade:
        await self._espera_da_rede()
        return await super().create_role(name, **kwargs)


def contexto(servidor: Servidor | None = None) -> tuple[ToolContext, Servidor]:
    servidor = servidor or Servidor()
    servidor.owner_id = None
    ator = types.SimpleNamespace(id=7, name="dono", guild_permissions=FakePerms(administrator=True),
                                 top_role=Entidade("dono", 7, 80))
    canal = Canal("geral", 123)
    servidor.channels.append(canal)
    return ToolContext(guild=servidor, channel=canal, actor=ator), servidor


def executar(nome: str, args: dict[str, Any], ctx: ToolContext) -> str:
    return asyncio.run(execute_tool(nome, args, ctx))


def falha(nome: str, args: dict[str, Any], ctx: ToolContext) -> str:
    """Executa esperando erro e devolve a mensagem (o teste cobra o texto)."""
    try:
        executar(nome, args, ctx)
    except ToolError as exc:
        return str(exc)
    raise AssertionError(f"'{nome}' deveria ter falhado, mas passou")


# --------------------------------------------------------------------- cargos

class TestCapacidadesDeCargo(unittest.TestCase):
    def test_todas_as_propriedades_em_uma_criacao(self) -> None:
        ctx, servidor = contexto()
        executar("create_roles", {"roles": [{
            "name": "Staff", "color": "#5865F2", "hoist": True, "mentionable": True,
            "permissions": ["ver canal", "gerenciar mensagens", "kick_members"],
            "position": 3,
        }]}, ctx)

        _, nome, kwargs = servidor.criados[-1]
        self.assertEqual(nome, "Staff")
        self.assertTrue(kwargs["hoist"])
        self.assertTrue(kwargs["mentionable"])
        self.assertEqual(kwargs["position"], 3)
        self.assertEqual(kwargs["color"].value, 0x5865F2)
        self.assertEqual(kwargs["permissions"].value,
                         Permissoes(["view_channel", "manage_messages", "kick_members"]).value)

    def test_varias_permissoes_juntas_em_portugues_e_ingles(self) -> None:
        ctx, servidor = contexto()
        executar("create_roles", {"roles": [{"name": "Mod"}],
                                  "permissions": ["Ver Canal", "enviar mensagens", "ADMINISTRADOR"]}, ctx)
        kwargs = servidor.criados[-1][2]
        self.assertEqual(set(kwargs["permissions"].nomes()),
                         {"view_channel", "send_messages", "administrator"})

    def test_permissao_tambem_por_item_do_lote(self) -> None:
        ctx, servidor = contexto()
        executar("create_roles", {"roles": [
            {"name": "A", "permissions": ["ver canal"]},
            {"name": "B", "permissions": ["banir membros", "expulsar membros"]},
        ]}, ctx)
        criados = [c for c in servidor.criados if c[0] == "role"]
        self.assertEqual(criados[0][2]["permissions"].nomes(), ["view_channel"])
        self.assertEqual(set(criados[1][2]["permissions"].nomes()), {"ban_members", "kick_members"})

    def test_lote_de_cargos_tem_teto(self) -> None:
        ctx, _ = contexto()
        msg = falha("create_roles", {"roles": [{"name": f"C{i}"} for i in range(26)]}, ctx)
        self.assertIn("25", msg)

    def test_cargo_sem_nome_nao_chega_na_api(self) -> None:
        ctx, servidor = contexto()
        antes = len(servidor.criados)
        falha("create_roles", {"roles": [{"name": "  "}]}, ctx)
        self.assertEqual(len(servidor.criados), antes)

    def test_permissao_inexistente_erro_claro(self) -> None:
        ctx, _ = contexto()
        msg = falha("create_roles", {"roles": [{"name": "X", "permissions": ["gerenciar pizza"]}]}, ctx)
        self.assertIn("Não conheço a permissão", msg)
        self.assertIn("gerenciar mensagens", msg)  # sugere o caminho certo

    def test_editar_cada_propriedade(self) -> None:
        for campo, valor in (("name", "Novo"), ("color", "#FF0000"), ("hoist", True),
                             ("mentionable", False), ("position", 5),
                             ("permissions", ["ver canal"])):
            with self.subTest(campo=campo):
                ctx, servidor = contexto()
                papel = Entidade("Alvo", 42, 2)
                servidor.roles.append(papel)
                executar("edit_role", {"role": "Alvo", campo: valor}, ctx)
                self.assertEqual(len(papel.edits), 1)
                self.assertIn(campo, papel.edits[0])

    def test_editar_combinacoes(self) -> None:
        ctx, servidor = contexto()
        papel = Entidade("Alvo", 42, 2)
        servidor.roles.append(papel)
        executar("edit_role", {"role": "Alvo", "name": "Renomeado", "color": "#00FF00",
                               "hoist": True, "mentionable": True, "position": 9,
                               "permissions": ["ver canal", "conectar"]}, ctx)
        envio = papel.edits[0]
        self.assertEqual(sorted(envio), ["color", "hoist", "mentionable", "name", "permissions", "position"])
        self.assertEqual(papel.name, "Renomeado")

    def test_editar_sem_nada_nao_chama_a_api(self) -> None:
        ctx, servidor = contexto()
        papel = Entidade("Alvo", 42, 2)
        servidor.roles.append(papel)
        msg = falha("edit_role", {"role": "Alvo"}, ctx)
        self.assertIn("Nada para editar", msg)
        self.assertEqual(papel.edits, [])

    def test_valores_invalidos_de_cargo(self) -> None:
        ctx, servidor = contexto()
        servidor.roles.append(Entidade("Alvo", 42, 2))
        self.assertIn("hexadecimal", falha("edit_role", {"role": "Alvo", "color": "roxo-neon"}, ctx))
        self.assertIn("negativa", falha("edit_role", {"role": "Alvo", "position": -1}, ctx))

    def test_repeticao_de_criacao_nao_duplica_cargo(self) -> None:
        """
        Repetir a MESMA ordem não pode criar cargo repetido — era o que o dono do servidor viu
        (o modelo repetia a chamada e cada repetição criava outro cargo igual).
        """
        ctx, servidor = contexto()
        primeira = executar("create_roles", {"roles": [{"name": "Repetido", "color": "#123456"}]}, ctx)
        self.assertIn("Criei 1 cargo", primeira)

        for _ in range(2):
            repetida = executar("create_roles", {"roles": [{"name": "Repetido"}]}, ctx)
            self.assertIn("já existiam", repetida, repetida)

        papeis = [r for r in servidor.roles if r.name == "Repetido"]
        self.assertEqual(len(papeis), 1, f"criou cargo duplicado: {[r.name for r in servidor.roles]}")

        # nome diferente continua criando, e a edição do que existe continua funcionando
        executar("create_roles", {"roles": [{"name": "Outro"}]}, ctx)
        self.assertEqual(len([r for r in servidor.roles if r.name == "Outro"]), 1)
        executar("edit_role", {"role": str(papeis[0].id), "hoist": True}, ctx)
        self.assertTrue(papeis[0].hoist)

    def test_recriacao_do_cargo_nao_e_pulada_como_duplicata(self) -> None:
        """Cargo que vai ser apagado na mesma mensagem pode ser recriado."""
        ctx, servidor = contexto()
        executar("create_roles", {"roles": [{"name": "Volta"}]}, ctx)
        ctx.alvos_apagados = {"volta"}
        saida = executar("create_roles", {"roles": [{"name": "Volta"}]}, ctx)
        self.assertIn("Criei 1 cargo", saida, saida)
        self.assertEqual([r.name for r in servidor.roles].count("Volta"), 2)

    def test_lote_com_o_mesmo_nome_nao_duplica(self) -> None:
        """O mesmo nome duas vezes NA MESMA chamada também não pode virar dois cargos."""
        ctx, servidor = contexto()
        saida = executar("create_roles", {"roles": [{"name": "Duplicado"}, {"name": "Duplicado"}]}, ctx)
        self.assertIn("Criei 1 cargo", saida)
        self.assertEqual(len([r for r in servidor.roles if r.name == "Duplicado"]), 1)


class TestExclusaoEmLoteDeCargos(unittest.TestCase):
    """
    "Apague todos os cargos": o bot tem que apagar o que PODE, dizer o que não pode e explicar
    o caminho — em vez de devolver erro solto (ou pior, dizer que fez).
    """

    def _servidor(self, quantidade: int = 24, bot_posicao: int = 1) -> tuple[ToolContext, Servidor]:
        """Cargos numa posição cada, e a regra do Discord: só apaga ABAIXO do topo do bot."""
        ctx, servidor = contexto()
        for i in range(1, quantidade + 1):
            papel = Entidade(f"cargo-{i}", 100 + i, i)
            papel.managed = False
            pap = papel  # nome curto só para o closure

            async def delete(_p: Any = pap) -> None:
                if _p.position >= bot_posicao:  # como o Discord: igual ou acima é recusado
                    raise Exception("403 Forbidden (50013): Missing Permissions")
                servidor.roles.remove(_p)

            papel.delete = delete
            servidor.roles.append(papel)
        servidor.me.top_role = Entidade("farol", 999, bot_posicao)
        return ctx, servidor

    def test_nao_apaga_nada_quando_esta_no_chao_e_explica_o_que_fazer(self) -> None:
        ctx, servidor = self._servidor(bot_posicao=1)
        antes = len(servidor.roles)
        saida = executar("delete_roles", {"roles": [f"cargo-{i}" for i in range(1, 25)]}, ctx)

        self.assertEqual(len(servidor.roles), antes, "não podia apagar nada mesmo")
        self.assertIn("Não consegui apagar 24 cargo(s)", saida)
        self.assertIn("Configurações do Servidor", saida, "tem que dizer ONDE resolver")
        self.assertIn("farol", saida)
        self.assertIn("Nada foi apagado nesta rodada", saida, "não pode fingir que fez")
        # antes: assertNotIn("@everyone") — o cargo @everyone nunca pode entrar na lista de
        # cargos que o bot tentou apagar. Agora a mensagem CITA o @everyone de propósito, para
        # explicar a direção da lista (o print do dono veio do celular, onde a tela é invertida):
        self.assertIn("a lista é invertida (o @everyone aparece primeiro)", saida)
        self.assertEqual(saida.count("@everyone"), 1,
                         "só a dica de direção pode citar @everyone")

    def test_apaga_o_que_pode_e_lista_o_que_nao_pode(self) -> None:
        ctx, servidor = self._servidor(bot_posicao=10)  # cargos 1..9 estão abaixo do bot
        saida = executar("delete_roles", {"roles": [f"cargo-{i}" for i in range(1, 25)]}, ctx)

        self.assertIn("Apaguei 9 cargo(s)", saida)
        self.assertIn("Não consegui apagar 15 cargo(s)", saida)
        nomes = [getattr(r, "name", "") for r in servidor.roles]
        self.assertNotIn("cargo-9", nomes)
        self.assertIn("cargo-10", nomes, "cargo acima do bot não pode ter sido apagado")

    def test_cargo_inexistente_nao_derruba_o_lote(self) -> None:
        ctx, servidor = self._servidor(bot_posicao=10)
        saida = executar("delete_roles", {"roles": ["cargo-3", "não-existe"]}, ctx)
        self.assertIn("Apaguei 1 cargo(s)", saida)
        self.assertIn("não-existe", saida)

    def test_lista_vazia_e_recusada(self) -> None:
        ctx, _ = self._servidor()
        self.assertIn("Nenhum cargo", falha("delete_roles", {"roles": []}, ctx))

    def test_modo_cauteloso_pede_confirmacao(self) -> None:
        ctx, servidor = self._servidor(bot_posicao=10)
        ctx.confirm_destructive = True
        msg = falha("delete_roles", {"roles": ["cargo-1", "cargo-2"]}, ctx)
        self.assertIn("confirme", msg.lower())
        self.assertEqual(len(servidor.roles), 25, "nada pode ser apagado antes do 'sim'")

    def test_posicao_empatada_tenta_apagar_de_verdade(self) -> None:
        """
        Cargo na MESMA posição do topo do bot: o cache do discord.py pode estar velho (já
        aconteceu) — em vez de recusar no chute, tenta e relata o que o Discord respondeu.
        """
        ctx, servidor = self._servidor(bot_posicao=5)
        papel = next(r for r in servidor.roles if getattr(r, "name", "") == "cargo-5")
        tentou: list[str] = []

        async def delete_que_funciona() -> None:
            tentou.append("cargo-5")
            servidor.roles.remove(papel)

        papel.delete = delete_que_funciona
        saida = executar("delete_roles", {"roles": ["cargo-5"]}, ctx)
        self.assertEqual(tentou, ["cargo-5"], "não tentou apagar o cargo empatado")
        self.assertIn("Apaguei 1 cargo(s)", saida)

    def test_discord_recusando_o_empatado_vira_instrucao_clara(self) -> None:
        ctx, servidor = self._servidor(bot_posicao=5)
        papel = next(r for r in servidor.roles if getattr(r, "name", "") == "cargo-5")

        async def delete_recusado() -> None:
            raise Exception("403 Forbidden (50013): Missing Permissions")

        papel.delete = delete_recusado
        saida = executar("delete_roles", {"roles": ["cargo-5"]}, ctx)
        self.assertIn("Configurações do Servidor", saida)
        self.assertIn("Nada foi apagado nesta rodada", saida)

    def test_delete_role_individual_com_recusa_explica_o_caminho(self) -> None:
        ctx, servidor = self._servidor(bot_posicao=1)
        msg = falha("delete_role", {"role": "cargo-24"}, ctx)
        self.assertIn("posição", msg)
        self.assertIn("Configurações do Servidor", msg)
        self.assertIn("arraste", msg)
        # Direção da lista: o print do dono (celular) mostrou a tela INVERTIDA — sem isso ele
        # arrastaria o cargo do bot para o lado errado.
        self.assertIn("celular", msg)
        self.assertIn("invertida", msg)


# --------------------------------------------------------------- diagnóstico

class TestDiagnostico(unittest.TestCase):
    """`diagnostic_report`: entrega a conversa recente + tempos por DM (sem virar log público)."""

    @staticmethod
    def _ctx_com_conversa(com_dm: bool = True) -> tuple[ToolContext, list[Any]]:
        ctx, _ = contexto()
        enviados: list[Any] = []

        class Msg:
            def __init__(self, autor: str, conteudo: str, bot: bool = False) -> None:
                self.created_at = "2026-09-18T12:00:00Z"
                self.author = types.SimpleNamespace(display_name=autor, bot=bot)
                self.content = conteudo
                self.attachments: list[Any] = []

        mensagens = [Msg("asta", "crie o canal avisos"),
                     Msg("farol", "Pronto! Criei 1 canal(is) 🎉", bot=True),
                     Msg("asta", "ele demorou demais")]

        async def history(limit: int = 80):  # noqa: ANN202 - gerador assíncrono como no discord.py
            for m in reversed(mensagens[-limit:]):
                yield m

        ctx.channel.history = history
        if com_dm:
            async def send(**kwargs: Any) -> None:
                enviados.append(kwargs)
            ctx.actor.send = send
        ctx.tempos = [{"total": 3.0, "llm": 2.2, "ferramentas": 0.5}]
        return ctx, enviados

    def test_entrega_por_dm_com_conversa_e_tempos(self) -> None:
        ctx, enviados = self._ctx_com_conversa()
        saida = executar("diagnostic_report", {}, ctx)
        self.assertIn("mensagem direta", saida)
        self.assertEqual(len(enviados), 1, "não mandou nada na DM")
        arquivo = enviados[0]["file"]
        self.assertEqual(arquivo.filename, "farol-diagnostico.txt")
        bruto = arquivo.fp.read() if hasattr(arquivo, "fp") else arquivo.content
        conteudo = bruto.decode() if isinstance(bruto, bytes) else bruto
        self.assertIn("crie o canal avisos", conteudo)
        self.assertIn("Pronto! Criei 1 canal", conteudo)
        self.assertIn("mediana", conteudo)
        self.assertIn("canal: #geral", conteudo)

    def test_dm_fechada_cai_no_canal(self) -> None:
        ctx, _ = self._ctx_com_conversa()
        async def send_dm(**kwargs: Any) -> None:
            raise RuntimeError("Cannot send messages to this user")
        ctx.actor.send = send_dm
        no_canal: list[Any] = []
        async def send_canal(**kwargs: Any) -> None:
            no_canal.append(kwargs)
        ctx.channel.send = send_canal
        saida = executar("diagnostic_report", {}, ctx)
        self.assertIn("aqui no canal", saida)
        self.assertEqual(len(no_canal), 1)

    def test_sem_historico_avisa_em_vez_de_mentir(self) -> None:
        ctx, _ = self._ctx_com_conversa()
        ctx.channel.history = None
        msg = falha("diagnostic_report", {}, ctx)
        self.assertIn("histórico", msg)


# --------------------------------------------------------------------- canais

class TestCapacidadesDeCanal(unittest.TestCase):
    def test_repeticao_de_criacao_nao_duplica_canal(self) -> None:
        """Repetir a MESMA ordem não pode criar canal repetido no mesmo lugar."""
        ctx, servidor = contexto()
        primeira = executar("create_channels",
                            {"channels": [{"name": "Repetido", "type": "text"}]}, ctx)
        self.assertIn("Criei 1 canal", primeira)
        repetida = executar("create_channels",
                            {"channels": [{"name": "Repetido", "type": "text"}]}, ctx)
        self.assertIn("já existia", repetida, repetida)
        nomes = [c.name for c in servidor.channels]
        self.assertEqual(nomes.count("Repetido"), 1, f"criou canal duplicado: {nomes}")

    def test_mesmo_nome_em_categoria_diferente_cria(self) -> None:
        """Pedir o MESMO nome em OUTRO lugar é escolha do usuário, não duplicata."""
        ctx, servidor = contexto()
        executar("create_channels", {"channels": [
            {"name": "Avisos", "type": "text"},
            {"name": "📁 Gente", "type": "category"},
        ]}, ctx)
        saida = executar("create_channels", {"channels": [
            {"name": "Avisos", "type": "text", "category": "📁 Gente"}]}, ctx)
        self.assertIn("Criei 1 canal", saida, saida)
        self.assertEqual([c.name for c in servidor.channels].count("Avisos"), 2)

    def test_recriacao_do_canal_nao_e_pulada_como_duplicata(self) -> None:
        """
        "Apague e crie de novo o canal X" (mesma mensagem): o alvo que vai ser apagado pode ser
        recriado — a trava de duplicata não pode comer a recriação.
        """
        ctx, servidor = contexto()
        executar("create_channels", {"channels": [{"name": "Vai nascer de novo", "type": "text"}]}, ctx)
        ctx.alvos_apagados = {"vai nascer de novo"}
        saida = executar("create_channels",
                         {"channels": [{"name": "Vai nascer de novo", "type": "text"}]}, ctx)
        self.assertIn("Criei 1 canal", saida, saida)
        self.assertEqual([c.name for c in servidor.channels].count("Vai nascer de novo"), 2,
                         "a recriação precisa criar de fato (o antigo ainda não foi apagado)")

    def test_lote_com_o_mesmo_nome_nao_duplica_canal(self) -> None:
        """O mesmo nome duas vezes NA MESMA chamada também não pode virar dois canais."""
        ctx, servidor = contexto()
        saida = executar("create_channels",
                         {"channels": [{"name": "Duplicado", "type": "text"},
                                       {"name": "duplicado", "type": "text"}]}, ctx)
        self.assertIn("Criei 1 canal", saida)
        self.assertEqual([c.name.lower() for c in servidor.channels].count("duplicado"), 1)

    def test_lote_repetido_com_rede_lenta_cria_um_canal_so(self) -> None:
        """
        Regressão do que o E2E pegou AO VIVO no servidor do dono: o lote é concorrente (3 por
        vez) e a conferência de nome feita DEPOIS do await deixava os dois itens passarem —
        "crie 5 canais" com nomes repetidos criava canais iguais.
        """
        ctx, servidor = contexto(ServidorRedeLenta())
        saida = executar("create_channels",
                         {"channels": [{"name": "Corrida", "type": "text"},
                                       {"name": "Corrida", "type": "text"},
                                       {"name": "Corrida", "type": "text"}]}, ctx)
        criados = [c.name for c in servidor.channels].count("Corrida")
        self.assertEqual(criados, 1, f"a corrida criou {criados} canais iguais")
        self.assertIn("Criei 1 canal", saida)

    def test_lote_repetido_de_cargos_com_rede_lenta_cria_um_cargo_so(self) -> None:
        """Mesma corrida do lado dos cargos."""
        ctx, servidor = contexto(ServidorRedeLenta())
        saida = executar("create_roles",
                         {"roles": [{"name": "Corrida"}, {"name": "corrida"}, {"name": "CORRIDA"}]}, ctx)
        criados = [r.name for r in servidor.roles if r.name.lower() == "corrida"]
        self.assertEqual(len(criados), 1, f"a corrida criou {len(criados)} cargos iguais")
        self.assertIn("Criei 1 cargo", saida)


    def test_todos_os_tipos_suportados(self) -> None:
        casos = {"text": "text", "voice": "voice", "category": "category",
                 "stage": "stage", "forum": "forum",
                 "texto": "text", "voz": "voice", "categoria": "category", "palco": "stage"}
        for pedido, esperado in casos.items():
            with self.subTest(tipo=pedido):
                ctx, servidor = contexto()
                executar("create_channels", {"channels": [{"name": f"canal-{pedido}", "type": pedido}]}, ctx)
                self.assertEqual(servidor.criados[-1][0], esperado)

    def test_tipo_desconhecido_nao_vira_canal_de_texto(self) -> None:
        ctx, servidor = contexto()
        antes = len(servidor.criados)
        msg = falha("create_channels", {"channels": [{"name": "x", "type": "holograma"}]}, ctx)
        self.assertIn("não existe", msg)
        self.assertIn("forum", msg)
        self.assertEqual(len(servidor.criados), antes)

    def test_texto_com_todas_as_propriedades(self) -> None:
        ctx, servidor = contexto()
        executar("create_channels", {"channels": [{
            "name": "avisos", "type": "text", "topic": "Só avisos", "nsfw": True,
            "slowmode_delay": 30, "position": 2,
        }]}, ctx)
        _, _, kwargs = servidor.criados[-1]
        self.assertEqual(kwargs["topic"], "Só avisos")
        self.assertTrue(kwargs["nsfw"])
        self.assertEqual(kwargs["slowmode_delay"], 30)
        self.assertEqual(kwargs["position"], 2)

    def test_voz_com_bitrate_e_limite(self) -> None:
        ctx, servidor = contexto()
        servidor.bitrate_limit = 384000  # servidor com boosts: teto de 384 kbps
        executar("create_channels", {"channels": [{
            "name": "Sala", "type": "voice", "bitrate": 96000, "user_limit": 5,
        }]}, ctx)
        _, _, kwargs = servidor.criados[-1]
        self.assertEqual(kwargs["bitrate"], 96000)
        self.assertEqual(kwargs["user_limit"], 5)

    def test_canal_dentro_e_fora_de_categoria(self) -> None:
        ctx, servidor = contexto()
        executar("create_channels", {"channels": [{"name": "📁 Cat", "type": "category"}]}, ctx)
        executar("create_channels", {"channels": [{"name": "dentro", "type": "text", "category": "📁 Cat"},
                                                  {"name": "fora", "type": "text"}]}, ctx)
        dentro = [c for c in servidor.criados if c[1] == "dentro"][0]
        fora = [c for c in servidor.criados if c[1] == "fora"][0]
        self.assertIsNotNone(dentro[2].get("category"))
        self.assertIsNone(fora[2].get("category") or None)

    def test_valores_fora_de_faixa_na_criacao(self) -> None:
        casos = [
            ({"name": "x", "type": "text", "slowmode_delay": -1}, "slowmode"),
            ({"name": "x", "type": "text", "slowmode_delay": 21601}, "slowmode"),
            ({"name": "x", "type": "voice", "bitrate": 1000}, "bitrate"),
            ({"name": "x", "type": "voice", "bitrate": 500000}, "bitrate"),
            ({"name": "x", "type": "voice", "user_limit": 500}, "limite de usuários"),
        ]
        for item, esperado in casos:
            with self.subTest(item=item):
                ctx, servidor = contexto()
                antes = len(servidor.criados)
                msg = falha("create_channels", {"channels": [item]}, ctx)
                self.assertIn(esperado, msg)
                self.assertEqual(len(servidor.criados), antes)

    def test_editar_cada_propriedade_do_canal(self) -> None:
        ctx, servidor = contexto()
        canal = servidor.channels[0]
        executar("create_channels", {"channels": [{"name": "📁 Cat", "type": "category"}]}, ctx)
        executar("edit_channel", {"channel": "geral", "name": "bate-papo", "topic": "novo tópico",
                                  "category": "📁 Cat", "slowmode_delay": 10, "nsfw": True,
                                  "position": 4}, ctx)
        envio = canal.edits[-1][1]
        self.assertEqual(set(envio), {"name", "topic", "category", "slowmode_delay", "nsfw", "position"})
        self.assertEqual(canal.name, "bate-papo")
        self.assertEqual(canal.nsfw, True)

    def test_editar_voz_com_bitrate_e_limite(self) -> None:
        ctx, servidor = contexto()
        voz = Canal("Sala", 321, "voice")
        servidor.channels.append(voz)
        executar("edit_channel", {"channel": "Sala", "bitrate": 64000, "user_limit": 10}, ctx)
        self.assertEqual(voz.bitrate, 64000)
        self.assertEqual(voz.user_limit, 10)

    def test_editar_sem_propriedade_e_erro(self) -> None:
        ctx, servidor = contexto()
        self.assertIn("Nenhum parâmetro", falha("edit_channel", {"channel": "geral"}, ctx))

    def test_nome_vazio_nao_apaga_o_nome_do_canal(self) -> None:
        ctx, servidor = contexto()
        msg = falha("edit_channel", {"channel": "geral", "name": "   "}, ctx)
        self.assertIn("não pode ficar vazio", msg)
        self.assertEqual(servidor.channels[0].name, "geral")

    def test_mover_por_categoria_e_por_posicao(self) -> None:
        ctx, servidor = contexto()
        canal = servidor.channels[0]
        executar("create_channels", {"channels": [{"name": "📁 Cat", "type": "category"}]}, ctx)
        executar("move_channel", {"channel": "geral", "category": "📁 Cat"}, ctx)
        self.assertIsNotNone(canal.category)
        executar("move_channel", {"channel": "geral", "position": 3}, ctx)
        self.assertEqual(canal.position, 3)
        executar("move_channel", {"channel": "geral", "category": "none"}, ctx)
        self.assertIsNone(canal.category)

    def test_mover_sem_destino_e_erro(self) -> None:
        ctx, servidor = contexto()
        msg = falha("move_channel", {"channel": "geral"}, ctx)
        self.assertIn("Diga para onde mover", msg)
        self.assertIn("negativa", falha("move_channel", {"channel": "geral", "position": -2}, ctx))

    def test_clonar_leva_as_configuracoes(self) -> None:
        ctx, servidor = contexto()
        canal = servidor.channels[0]
        canal.topic = "tópico original"
        canal.nsfw = True
        canal.slowmode_delay = 15
        saida = executar("clone_channel", {"channel": "geral", "name": "cópia"}, ctx)
        self.assertIn("posição", saida, "o clone tem que copiar a posição (senão a cópia cai no fim)")
        self.assertIn("continua aí", saida, "a resposta tem que dizer que o original não sumiu")
        self.assertTrue(canal.clonado)
        self.assertIn("clonado", saida)

    def test_limite_de_lote_de_canais(self) -> None:
        ctx, _ = contexto()
        self.assertIn("25", falha("create_channels",
                                  {"channels": [{"name": f"C{i}"} for i in range(26)]}, ctx))
        self.assertIn("vazia", falha("create_channels", {"channels": []}, ctx))


# --------------------------------------------------------------- permissões

class TestCapacidadesDePermissao(unittest.TestCase):
    def test_allow_e_deny_em_portugues_viram_atributos_do_discord(self) -> None:
        ctx, servidor = contexto()
        canal = servidor.channels[0]
        executar("set_permissions", {"channel": "geral", "target": "@everyone",
                                     "allow": ["ver canal", "enviar mensagens"],
                                     "deny": ["mencionar todos"]}, ctx)
        envio = canal.overwrites[servidor.roles[0]]
        self.assertTrue(envio["view_channel"])
        self.assertTrue(envio["send_messages"])
        self.assertFalse(envio["mention_everyone"])

    def test_allow_e_deny_juntos_e_separados(self) -> None:
        ctx, servidor = contexto()
        canal = servidor.channels[0]
        papel = Entidade("Membros", 55, 3)
        servidor.roles.append(papel)
        executar("set_permissions", {"channel": "geral", "target": "Membros", "allow": ["conectar"]}, ctx)
        executar("set_permissions", {"channel": "geral", "target": "Membros", "deny": ["falar"]}, ctx)
        self.assertTrue(canal.overwrites[papel]["connect"])
        self.assertFalse(canal.overwrites[papel]["speak"])

    def test_conflito_e_lista_vazia_sao_recusados(self) -> None:
        ctx, _ = contexto()
        msg = falha("set_permissions", {"channel": "geral", "target": "@everyone",
                                        "allow": ["ver canal"], "deny": ["view_channel"]}, ctx)
        self.assertIn("permitida e negada", msg)
        msg = falha("set_permissions", {"channel": "geral", "target": "@everyone"}, ctx)
        self.assertIn("allow", msg)

    def test_permissao_desconhecida_nao_estoura_typeerror(self) -> None:
        ctx, _ = contexto()
        msg = falha("set_permissions", {"channel": "geral", "target": "@everyone",
                                        "allow": ["gerenciar pizza"]}, ctx)
        self.assertIn("Não conheço a permissão", msg)

    def test_limpar_permissao_e_sincronizar(self) -> None:
        ctx, servidor = contexto()
        canal = servidor.channels[0]
        executar("clear_permissions", {"channel": "geral", "target": "@everyone"}, ctx)
        self.assertIsNone(canal.overwrites[servidor.roles[0]]["overwrite"])
        canal.edits.clear()
        executar("sync_permissions", {"channel": "geral"}, ctx)
        self.assertTrue(any(e[1].get("sync_permissions") for e in canal.edits))

    def test_leitura_das_permissoes_configuradas(self) -> None:
        ctx, servidor = contexto()
        canal = servidor.channels[0]
        canal.overwrites[servidor.roles[0]] = {"view_channel": True, "send_messages": False}
        saida = executar("show_permissions", {"channel": "geral"}, ctx)
        self.assertIn("@everyone", saida)

    def test_mapa_de_permissoes_bate_com_o_discord_py(self) -> None:
        """Se a biblioteca renomear/alterar bits, este teste avisa antes de ir para produção."""
        import discord

        for nome, bit in ops.PERMISSOES.items():
            with self.subTest(permissao=nome):
                try:
                    real = discord.Permissions(**{nome: True})
                except TypeError:  # nome que a versão instalada não tem mais
                    continue
                self.assertEqual(real.value, bit, f"bit de {nome} divergiu do discord.py")
        for alias, destino in ops.ALIASES_PERMISSOES.items():
            with self.subTest(alias=alias):
                self.assertEqual(resolver_permissao(alias), destino)


# --------------------------------------------------------------- estrutura

class TestCapacidadesDeEstrutura(unittest.TestCase):
    def _servidor_com_estrutura(self) -> Servidor:
        servidor = Servidor()
        cat = Canal("📁 Geral", 900, "category")
        servidor.channels.append(cat)
        servidor.categories.append(cat)
        texto = Canal("avisos", 901, "text", cat)
        cat.channels.append(texto)
        texto.topic = "Só avisos"
        texto.nsfw = True
        texto.slowmode_delay = 12
        texto.position = 3
        servidor.channels.append(texto)
        voz = Canal("Sala", 902, "voice", cat)
        cat.channels.append(voz)
        voz.bitrate = 96000
        voz.user_limit = 4
        voz.position = 4
        servidor.channels.append(voz)
        fora = Canal("solto", 903, "text")
        fora.position = 9
        servidor.channels.append(fora)
        papel = Entidade("Staff", 904, 5, cor=0x5865F2)
        papel.hoist = True
        papel.mentionable = True
        papel.permissions = Permissoes(["view_channel", "manage_messages"])
        servidor.roles.append(papel)
        return servidor

    def test_export_guarda_as_capacidades_todas(self) -> None:
        ctx, servidor = contexto(self._servidor_com_estrutura())
        saida = executar("export_structure", {}, ctx)
        dados = json.loads(saida[saida.find("{"): saida.rfind("}") + 1])

        papel = next(r for r in dados["roles"] if r["name"] == "Staff")
        self.assertTrue(papel["hoist"])
        self.assertTrue(papel["mentionable"])
        self.assertEqual(papel["color"], "#5865f2")
        self.assertEqual(set(papel["permissions"]), {"view_channel", "manage_messages"})

        canais = [c for cat in dados["categories"] for c in cat["channels"]]
        texto = next(c for c in canais if c["name"] == "avisos")
        self.assertEqual(texto["topic"], "Só avisos")
        self.assertTrue(texto["nsfw"])
        self.assertEqual(texto["slowmode_delay"], 12)
        self.assertEqual(texto["position"], 3)
        voz = next(c for c in canais if c["name"] == "Sala")
        self.assertEqual(voz["bitrate"], 96000)
        self.assertEqual(voz["user_limit"], 4)
        self.assertIn("solto", [c["name"] for c in dados["uncategorized_channels"]])

    def test_import_recria_com_os_mesmos_campos(self) -> None:
        ctx, servidor = contexto()
        estrutura = {
            "roles": [{"name": "Staff", "color": "#5865f2", "hoist": True, "mentionable": True,
                       "permissions": ["view_channel", "manage_messages"]}],
            "categories": [{"name": "📁 Novo", "channels": [
                {"name": "avisos", "type": "text", "topic": "Só avisos", "nsfw": True,
                 "slowmode_delay": 12, "position": 3},
                {"name": "Sala", "type": "voice", "bitrate": 96000, "user_limit": 4},
            ]}],
            "uncategorized_channels": [{"name": "solto", "type": "text", "position": 9}],
        }
        saida = executar("import_structure", {"structure_json": json.dumps(estrutura)}, ctx)

        papel = next(c for c in servidor.criados if c[0] == "role")
        self.assertEqual(papel[1], "Staff")
        self.assertTrue(papel[2]["hoist"])
        self.assertEqual(papel[2]["permissions"].nomes(), ["view_channel", "manage_messages"])

        criados = {c[1]: c for c in servidor.criados if c[0] in ("text", "voice")}
        self.assertTrue(criados["avisos"][2]["nsfw"])
        self.assertEqual(criados["avisos"][2]["slowmode_delay"], 12)
        self.assertEqual(criados["avisos"][2]["category"].name, "📁 Novo")
        self.assertEqual(criados["Sala"][2]["bitrate"], 96000)
        self.assertEqual(criados["Sala"][2]["user_limit"], 4)
        self.assertEqual(criados["solto"][2].get("category"), None)
        self.assertIn("3 canal(is)", saida)

    def test_import_relata_item_que_falhou_sem_parar_o_resto(self) -> None:
        ctx, servidor = contexto()
        estrutura = {"categories": [{"name": "📁 C", "channels": [
            {"name": "ruim", "type": "holograma"},
            {"name": "bom", "type": "text"},
        ]}]}
        saida = executar("import_structure", {"structure_json": json.dumps(estrutura)}, ctx)
        self.assertIn("1 canal(is)", saida)
        self.assertIn("ruim", saida)
        self.assertTrue(any(c[1] == "bom" for c in servidor.criados))

    def test_import_sem_json_e_erro(self) -> None:
        ctx, _ = contexto()
        self.assertIn("Nenhum JSON", falha("import_structure", {}, ctx))
        self.assertIn("inválido", falha("import_structure", {"structure_json": "{quebrado"}, ctx))


# --------------------------------------------------------------- mensagens

class TestCapacidadesDeMensagens(unittest.TestCase):
    def test_limite_valido_vai_para_o_purge(self) -> None:
        ctx, servidor = contexto()
        executar("clear_messages", {"channel": "geral", "limit": 1}, ctx)
        self.assertEqual(servidor.channels[0].purged, 1)
        executar("clear_messages", {"channel": "geral", "limit": 500}, ctx)
        self.assertEqual(servidor.channels[0].purged, 500)

    def test_limite_invalido_nao_finge_limpeza(self) -> None:
        for limite in (0, -3, 501, "muitas"):
            with self.subTest(limite=limite):
                ctx, servidor = contexto()
                msg = falha("clear_messages", {"channel": "geral", "limit": limite}, ctx)
                self.assertIn("entre 1 e 500", msg)
                self.assertFalse(hasattr(servidor.channels[0], "purged"))


class TestApplyTemplateHonesto(unittest.TestCase):
    def test_resumo_nao_esconde_item_que_falhou(self) -> None:
        """Se um canal do modelo não nasce, o resumo diz — não pode ser 'tudo criado com sucesso'."""
        from brain import ops as mod

        ctx, servidor = contexto()

        async def create_category_ok(name: str, **kwargs: Any) -> Any:
            return await Servidor.create_category(servidor, name=name, **kwargs)

        servidor.create_category = create_category_ok  # type: ignore[assignment]
        original = mod.TEMPLATES_DATA["gamer"]
        mod.TEMPLATES_DATA["gamer"] = {
            "roles": [{"name": "Ok"}],
            "categories": [{"name": "📁 C", "channels": [
                {"name": "bom", "type": "text"},
                {"name": "ruim", "type": "holograma"},
            ]}],
        }
        try:
            saida = executar("apply_template", {"template": "gamer"}, ctx)
        finally:
            mod.TEMPLATES_DATA["gamer"] = original

        self.assertIn("sucesso", saida.lower())
        self.assertIn("NÃO foram criados", saida)
        self.assertIn("ruim", saida)

    def test_template_desconhecido_lista_as_opcoes(self) -> None:
        ctx, _ = contexto()
        msg = falha("apply_template", {"template": "inexistente"}, ctx)
        self.assertIn("gamer", msg)
        self.assertIn("estudos", msg)


class TestAchadosDaMatrizAoVivo(unittest.TestCase):
    """Regressões dos achados da fase `caps` no Discord real (18/09)."""

    def test_bitrate_acima_do_teto_do_servidor_e_explicado(self) -> None:
        """O Discord recusa acima do teto do servidor (96 kbps sem boost): recusar com o número."""
        ctx, servidor = contexto()
        voz = Canal("Sala", 321, "voice")
        servidor.channels.append(voz)
        servidor.bitrate_limit = 96000

        msg = falha("edit_channel", {"channel": "Sala", "bitrate": 128000}, ctx)
        self.assertIn("96000", msg)
        self.assertIn("boost", msg)
        self.assertIsNone(voz.bitrate, "não pode ter aplicado nada antes de recusar")

        msg = falha("create_channels", {"channels": [
            {"name": "Voz2", "type": "voice", "bitrate": 128000}]}, ctx)
        self.assertIn("96000", msg)

        # dentro do teto continua funcionando
        executar("edit_channel", {"channel": "Sala", "bitrate": 96000}, ctx)
        self.assertEqual(voz.bitrate, 96000)

    def test_stage_sem_comunidade_vira_explicacao_em_portugues(self) -> None:
        ctx, servidor = contexto()

        async def recusa(name: str, **kwargs: Any) -> Any:
            raise Exception("400 Bad Request (error code: 50024): Cannot execute action on this "
                            "channel type")

        servidor.create_stage_channel = recusa  # type: ignore[assignment]
        msg = falha("create_channels", {"channels": [{"name": "Palco", "type": "stage"}]}, ctx)
        self.assertIn("Comunidade", msg)
        self.assertIn("palco", msg.lower())

    def test_export_avisa_quando_o_json_nao_cabe_na_mensagem(self) -> None:
        """Antes o JSON era cortado no meio, sem aviso, e não podia ser importado de volta."""
        ctx, servidor = contexto()
        cat = Canal("📁 C", 900, "category")
        servidor.categories.append(cat)
        servidor.channels.append(cat)
        for i in range(120):  # servidor grande: JSON maior que uma mensagem do Discord
            canal = Canal(f"canal-{i:03d}-com-nome-longo", 1000 + i, "text", cat)
            canal.topic = "tópico de teste " * 2
            cat.channels.append(canal)
            servidor.channels.append(canal)

        saida = executar("export_structure", {}, ctx)
        self.assertIn("NÃO serve para importar", saida)
        self.assertIn("não cabe", saida)
        self.assertIn("daria", saida, "o aviso tem que dizer em quantas mensagens o JSON caberia")
        self.assertIn("por partes", saida)
        # o recorte corta o JSON no meio: o aviso TEM que dizer o que ficou fora dele (os cargos,
        # com as permissões, vêm depois dos canais e não aparecem no pedaço mostrado)
        self.assertIn("cargo(s)", saida, "o aviso não conta os cargos exportados")
        self.assertIn("permissões", saida, "o aviso não diz que os cargos vêm com as permissões")
        self.assertIn("121 canal(is)", saida, "o aviso não conta os canais exportados")

        pequeno = Servidor()  # servidor pequeno: o JSON vem inteiro e parseável
        ctx_pequeno, _ = contexto(pequeno)
        saida_ok = executar("export_structure", {}, ctx_pequeno)
        dados = json.loads(saida_ok[saida_ok.find("{"): saida_ok.rfind("}") + 1])
        self.assertIn("categories", dados)

    def test_mover_relata_a_posicao_real_e_nao_so_a_pedida(self) -> None:
        """O Discord ordena o canal junto com os vizinhos: a mensagem tem que dizer a real."""
        ctx, servidor = contexto()
        canal = servidor.channels[0]

        async def edit_com_ordem_do_discord(**kwargs: Any) -> Any:
            canal.edits.append(("edit", kwargs))
            if "position" in kwargs:
                canal.position = kwargs["position"] + 2  # vizinhos empurram, como acontece lá
            return canal

        canal.edit = edit_com_ordem_do_discord  # type: ignore[assignment]
        saida = executar("move_channel", {"channel": "geral", "position": 0}, ctx)
        self.assertIn("pedida 0", saida)
        self.assertIn("real 2", saida)


class TestErroTransitorioDoDiscord(unittest.TestCase):
    """5xx do Discord não é defeito do pedido: uma segunda tentativa antes de desistir."""

    def test_criacao_de_cargo_repete_uma_vez_no_503(self) -> None:
        ctx, servidor = contexto()
        original = servidor.create_role
        chamadas: list[int] = []

        class Erro503(Exception):
            status = 503

        async def instavel(name: str, **kwargs: Any) -> Any:
            chamadas.append(1)
            if len(chamadas) == 1:
                raise Erro503("503 Service Unavailable (error code: 0): Service error -27")
            return await original(name, **kwargs)

        servidor.create_role = instavel  # type: ignore[assignment]
        with unittest.mock.patch("brain.ops.asyncio.sleep", new=unittest.mock.AsyncMock()):
            saida = executar("create_roles", {"roles": [{"name": "🧪-instavel"}]}, ctx)
        self.assertEqual(len(chamadas), 2, "o 503 tinha que ter sido repetido uma vez")
        self.assertIn("Criei 1 cargo", saida)

    def test_erro_de_pedido_ruim_nao_e_repetido(self) -> None:
        ctx, servidor = contexto()
        chamadas: list[int] = []

        class Erro403(Exception):
            status = 403

        async def recusa(name: str, **kwargs: Any) -> Any:
            chamadas.append(1)
            raise Erro403("403 Forbidden (50013): Missing Permissions")

        servidor.create_role = recusa  # type: ignore[assignment]
        msg = falha("create_roles", {"roles": [{"name": "🧪-proibido"}]}, ctx)
        self.assertEqual(len(chamadas), 1, "403 não pode ser repetido")
        self.assertIn("Missing Permissions", msg)

    def test_clear_messages_avisa_quando_sobram_mensagens_antigas(self) -> None:
        """O bulk delete ignora o que tem mais de 14 dias: não pode dizer 'chat limpo'."""
        ctx, servidor = contexto()
        canal = servidor.channels[0]

        async def history(limit: int = 1, oldest_first: bool = False) -> Any:
            yield object()  # sobrou uma mensagem antiga

        canal.history = history  # type: ignore[assignment]
        saida = executar("clear_messages", {"channel": "geral", "limit": 3}, ctx)
        self.assertIn("SOBRARAM", saida)
        self.assertNotIn("chat está limpo", saida)

        canal.history = None  # sem histórico: nada a afirmar (mantém o texto de sucesso)
        saida = executar("clear_messages", {"channel": "geral", "limit": 3}, ctx)
        self.assertIn("chat está limpo", saida)

    def test_clear_messages_repete_o_purge_no_503(self) -> None:
        """A rodada 35307204220 falhou em 'clear_messages apaga mensagens reais' com 503 do Discord."""
        ctx, servidor = contexto()
        canal = servidor.channels[0]
        original = canal.purge
        chamadas: list[int] = []

        class Erro503(Exception):
            status = 503

        async def instavel(limit: int = 50) -> Any:
            chamadas.append(limit)
            if len(chamadas) == 1:
                raise Erro503("503 Service Unavailable: upstream connect error")
            return await original(limit=limit)

        canal.purge = instavel  # type: ignore[assignment]
        with unittest.mock.patch("brain.ops.asyncio.sleep", new=unittest.mock.AsyncMock()):
            saida = executar("clear_messages", {"channel": "geral", "limit": 3}, ctx)
        self.assertEqual(len(chamadas), 2, "o 503 do bulk delete tinha que ser repetido")
        self.assertIn("3", saida)

    def test_5xx_na_criacao_de_canal_tambem_repete(self) -> None:
        ctx, servidor = contexto()
        original = servidor.create_text_channel
        chamadas: list[int] = []

        class Erro502(Exception):
            status = 502

        async def instavel(name: str, **kwargs: Any) -> Any:
            chamadas.append(1)
            if len(chamadas) == 1:
                raise Erro502("502 Bad Gateway")
            return await original(name, **kwargs)

        servidor.create_text_channel = instavel  # type: ignore[assignment]
        with unittest.mock.patch("brain.ops.asyncio.sleep", new=unittest.mock.AsyncMock()):
            executar("create_channels", {"channels": [{"name": "🧪-gateway"}]}, ctx)
        self.assertEqual(len(chamadas), 2)


class TestMembroForaDoCache(unittest.TestCase):
    """Cache vazio (intent de membros desligada no portal) não pode impedir dar/tirar cargo."""

    def test_give_e_take_role_acham_o_membro_pela_api(self) -> None:
        ctx, servidor = contexto()
        cargo = Entidade("🧪-cargo", 77, 1)
        servidor.roles.append(cargo)
        membro = Entidade("dono", 1521612392105250836, 0)
        async def add_roles(*a: Any, **k: Any) -> None:
            return None

        membro.add_roles = add_roles  # type: ignore[attr-defined]
        servidor.na_api[membro.id] = membro  # existe no servidor, mas fora do cache

        saida = executar("give_role", {"member": str(membro.id), "role": str(cargo.id)}, ctx)
        self.assertIn(str(membro.id), saida)

        removidos: list[Any] = []

        async def remove_roles(r: Any) -> None:
            removidos.append(r)

        membro.remove_roles = remove_roles  # type: ignore[attr-defined]
        executar("take_role", {"member": str(membro.id), "role": str(cargo.id)}, ctx)
        self.assertEqual(len(removidos), 1)

    def test_membro_que_realmente_nao_existe_da_erro_claro(self) -> None:
        ctx, _ = contexto()
        msg = falha("give_role", {"member": "111222333444555666", "role": "geral"}, ctx)
        self.assertIn("não foi encontrado", msg)


class TestHierarquiaComCacheQuebrado(unittest.TestCase):
    """
    Cache de cargos vazio: `Member.top_role` cai no @everyone (posição 0) e o bot passava a
    recusar TUDO — inclusive um cargo que ele mesmo tinha acabado de criar. A hierarquia tem
    que ser conferida na API antes de recusar.
    """

    def _servidor_com_cache_ruim(self) -> tuple[Any, Servidor]:
        ctx, servidor = contexto()
        farol = Entidade("farol", 999, 3)
        servidor.roles.append(farol)
        # o cache do membro do bot perdeu os cargos: top_role vira @everyone
        servidor.me.top_role = types.SimpleNamespace(id=1, name="@everyone", position=0,
                                                     is_default=lambda: True)
        servidor.me.roles = []
        servidor.me._roles = {999}
        return ctx, servidor

    def test_edita_cargo_abaixo_do_bot_mesmo_com_cache_quebrado(self) -> None:
        ctx, servidor = self._servidor_com_cache_ruim()
        criado = Entidade("🧪-novo", 4242, 1)  # nasceu embaixo, como no Discord
        servidor.roles.append(criado)

        saida = executar("edit_role", {"role": str(criado.id), "name": "🧪-renomeado"}, ctx)
        self.assertIn("atualizado", saida)
        self.assertEqual(criado.name, "🧪-renomeado", "o cargo tinha que ter sido renomeado")

    def test_ainda_recusa_cargo_de_verdade_acima_do_bot(self) -> None:
        ctx, servidor = self._servidor_com_cache_ruim()
        alto = Entidade("chefe", 4243, 9)
        servidor.roles.append(alto)

        msg = falha("edit_role", {"role": str(alto.id), "name": "x"}, ctx)
        self.assertIn("posição 9", msg)
        self.assertIn("posição 3", msg)

    def test_cargos_do_membro_sem_cache_sao_recuperados(self) -> None:
        """`Member.roles` vem vazio quando o cache falha — os IDs crus ainda estão no membro."""
        ctx, servidor = self._servidor_com_cache_ruim()
        from brain import ops

        self.assertEqual(ops._cargos_do_membro(servidor.me), {999})

    def test_create_roles_avisa_quando_nascem_na_altura_do_bot(self) -> None:
        ctx, servidor = contexto()
        servidor.me.top_role.position = 1  # cargo do farol no chão do servidor
        saida = executar("create_roles", {"roles": [{"name": "🧪-no-chao"}]}, ctx)
        self.assertIn("Suba o meu cargo", saida)

        servidor.me.top_role.position = 50  # bem acima: nada a avisar
        saida = executar("create_roles", {"roles": [{"name": "🧪-tranquilo"}]}, ctx)
        self.assertNotIn("Suba o meu cargo", saida)

class TestRecusaDeHierarquiaComNumeros(unittest.TestCase):
    """A recusa diz AS POSIÇÕES — sem isso a matriz ao vivo não conseguiu diagnosticar nada."""

    def test_recusa_do_bot_mostra_as_posicoes(self) -> None:
        ctx, servidor = contexto()
        servidor.me.top_role.position = 1
        cargo = Entidade("alto", 99, 7)
        servidor.roles.append(cargo)

        msg = falha("edit_role", {"role": str(cargo.id), "name": "x"}, ctx)
        self.assertIn("posição 7", msg)
        self.assertIn("posição 1", msg)

    def test_recusa_do_autor_mostra_as_posicoes(self) -> None:
        ctx, _ = contexto()
        ctx.actor.top_role.position = 40
        alvo = Entidade("alto", 97, 41)
        ctx.guild.roles.append(alvo)
        msg = falha("edit_role", {"role": str(alvo.id), "name": "x"}, ctx)
        self.assertIn("posição 41", msg)
        self.assertIn("posição 40", msg)


class TestFerramentasDeConsulta(unittest.TestCase):
    """As ferramentas que não mexem em nada também têm capacidades — e limites."""

    def test_server_info_mostra_dono_mesmo_sem_cache_de_membro(self) -> None:
        """`guild.owner` é None quando o membro não está no cache: aparecia 'Dono: None'."""
        ctx, servidor = contexto()
        servidor.member_count = 42
        servidor.owner_id = 1521612392105250836

        saida = executar("server_info", {}, ctx)
        self.assertIn("1521612392105250836", saida)
        self.assertNotIn("None", saida)
        self.assertIn("42", saida)
        self.assertIn("Servidor Teste", saida)
        self.assertIn("Cargos", saida)

    def test_server_info_conta_canais_e_cargos_reais(self) -> None:
        ctx, servidor = contexto()
        servidor.member_count = None  # cai no len(members)
        servidor.members = [object(), object()]
        saida = executar("server_info", {}, ctx)
        self.assertIn("**Membros:** 2", saida)
        self.assertIn(f"**Canais:** {len(servidor.channels)}", saida)

    def test_color_name_aceita_as_variacoes_de_hex(self) -> None:
        ctx, _ = contexto()
        for entrada in ("#5865F2", "5865f2", "#5865F2".lower()):
            saida = executar("color_name", {"hex_code": entrada}, ctx)
            self.assertIn("5865F2", saida.upper())

    def test_color_name_recusa_o_que_nao_e_hex(self) -> None:
        """Antes respondia 'A cor `zzzz` é conhecida como **Cor #ZZZZ**' — inventava nome."""
        ctx, _ = contexto()
        for ruim in ("zzzz", "", "roxo", "#12345", "#1234567"):
            msg = falha("color_name", {"hex_code": ruim}, ctx)
            self.assertIn("HEX", msg)

    def test_color_palette_lista_hex_e_nomes(self) -> None:
        ctx, _ = contexto()
        saida = executar("color_palette", {"query": "gamer"}, ctx)
        self.assertIn("gamer", saida)
        self.assertIn("`#", saida)

    def test_emoji_search_acha_e_avisa_quando_nao_acha(self) -> None:
        ctx, _ = contexto()
        saida = executar("emoji_search", {"query": "festa"}, ctx)
        self.assertTrue(saida.strip(), "emoji_search devolveu vazio")

        vazio = executar("emoji_search", {"query": "zzzznaoexiste"}, ctx)
        self.assertTrue(vazio, "sem resultado tem que dizer algo")

    def test_topic_suggest_avisa_categoria_desconhecida(self) -> None:
        ctx, _ = contexto()
        conhecida = executar("topic_suggest", {"category": "geral"}, ctx)
        self.assertIn("geral", conhecida)
        self.assertNotIn("não conheço a categoria", conhecida)

        estranha = executar("topic_suggest", {"category": "aquarismo"}, ctx)
        self.assertIn("não conheço a categoria", estranha)

    def test_translate_nao_finge_quando_o_tradutor_nao_responde(self) -> None:
        """O fallback devolve o próprio texto: dizer 'Tradução: <original>' seria mentira."""
        ctx, _ = contexto()
        saida = executar("translate_text", {"text": "hello world", "target_lang": "es"}, ctx)
        self.assertIn("NÃO traduzi", saida)
        self.assertIn("hello world", saida)

    def test_translate_recusa_texto_vazio(self) -> None:
        ctx, _ = contexto()
        msg = falha("translate_text", {"text": "   ", "target_lang": "es"}, ctx)
        self.assertIn("Não há texto", msg)

    def test_edit_server_recusa_edicao_vazia(self) -> None:
        ctx, servidor = contexto()
        msg = falha("edit_server", {}, ctx)
        self.assertIn("Nenhum dado", msg)
        self.assertEqual(servidor.edits, [], "nada pode ter sido editado")

        servidor.edit = None  # type: ignore[assignment]
        msg = falha("edit_server", {"name": "Novo"}, ctx)
        self.assertIn("não suporta", msg)

    def test_edit_server_aplica_so_o_que_foi_pedido(self) -> None:
        ctx, servidor = contexto()
        edits: list[dict[str, Any]] = []

        async def edit(**kwargs: Any) -> None:
            edits.append(kwargs)

        servidor.edit = edit  # type: ignore[assignment]
        executar("edit_server", {"description": "só a descrição"}, ctx)
        self.assertEqual(edits, [{"description": "só a descrição"}],
                         "edit_server tem que mandar SÓ o campo pedido")


class TestAlcanceEmLinguagemNatural(unittest.TestCase):
    """
    Nos provedores SEM function calling nativo (boa parte dos gratuitos), o modelo só conhece as
    ferramentas pela lista do protocolo de texto. Ferramenta fora da lista = capacidade
    inalcançável por linguagem natural, por melhor que o código esteja.
    """

    def test_o_protocolo_de_texto_lista_todas_as_ferramentas(self) -> None:
        from brain.tools import get_tool_definitions
        from llm.base import summarize_tools

        schemas = [t.to_openai() for t in get_tool_definitions()]
        resumo = summarize_tools(schemas, limit=None)
        faltando = [t.name for t in get_tool_definitions()
                    if f"- {t.name}(" not in resumo]
        self.assertEqual(faltando, [], f"ferramentas invisíveis para o modelo: {faltando}")

    def test_toda_ferramenta_tem_descricao_e_parametros_marcados(self) -> None:
        from brain.tools import get_tool_definitions

        sem_descricao: list[str] = []
        for t in get_tool_definitions():
            schema = t.to_openai()
            fn = schema["function"]
            if not (fn.get("description") or "").strip():
                sem_descricao.append(t.name)
        self.assertEqual(sem_descricao, [], f"ferramentas sem descrição: {sem_descricao}")

    def test_o_resumo_mostra_os_obrigatorios_com_asterisco(self) -> None:
        from brain.tools import get_tool_definitions
        from llm.base import summarize_tools

        schemas = [t.to_openai() for t in get_tool_definitions()]
        resumo = summarize_tools(schemas, limit=None)
        for t in get_tool_definitions():
            schema = t.to_openai()
            obrigatorios = schema["function"].get("parameters", {}).get("required", []) or []
            for nome_param in obrigatorios:
                self.assertIn(f"{nome_param}*", resumo,
                              f"o parâmetro obrigatório {nome_param} de {t.name} não aparece "
                              "marcado no protocolo")

    def test_limitacao_do_resumo_nao_esconde_ferramenta_por_acidente(self) -> None:
        from brain.tools import get_tool_definitions
        from llm.base import summarize_tools

        schemas = [t.to_openai() for t in get_tool_definitions()]
        if len(schemas) > 40:
            self.fail("passamos de 40 ferramentas: o protocolo de texto precisa de outra estratégia")
        completo = summarize_tools(schemas, limit=None)
        self.assertEqual(completo, summarize_tools(schemas, limit=40),
                         "com 28 ferramentas o padrão (40) e o completo têm que dar no mesmo")


class TestCoerenciaSchemaExecucao(unittest.TestCase):
    """
    Trava do inventário: schema, função e executor falam a mesma língua.

    `execute_tool` filtra os argumentos pela assinatura da função — se o schema usar um nome
    diferente do parâmetro, o valor some sem erro nenhum (o bot pede e a ferramenta não
    recebe). E se a função aceitar um parâmetro que o schema não expõe, a capacidade existe
    mas o modelo nunca consegue usar. Os dois lados são cobrados aqui.
    """

    def test_nenhum_parametro_do_schema_e_descartado(self) -> None:
        import inspect

        from brain.executors import _OPS
        from brain.tools import TOOLS

        problemas: list[str] = []
        for td in TOOLS:
            props = set(td.parameters.get("properties", {}))
            sig = set(inspect.signature(_OPS[td.name]).parameters) - {"ctx"}
            if props - sig:
                problemas.append(f"{td.name}: schema manda {sorted(props - sig)} e a função não recebe")
        self.assertEqual(problemas, [], "parâmetros que somem silenciosamente")

    def test_toda_capacidade_da_funcao_esta_no_schema(self) -> None:
        import inspect

        from brain.executors import _OPS
        from brain.tools import TOOLS

        problemas: list[str] = []
        for td in TOOLS:
            props = set(td.parameters.get("properties", {}))
            sig = set(inspect.signature(_OPS[td.name]).parameters) - {"ctx"}
            if sig - props:
                problemas.append(f"{td.name}: função aceita {sorted(sig - props)} e o schema esconde")
        self.assertEqual(problemas, [], "capacidades inalcançáveis pelo modelo")

    def test_schema_e_executor_cobrem_as_mesmas_ferramentas(self) -> None:
        from brain.executors import _OPS
        from brain.tools import tool_names

        self.assertEqual(set(tool_names()), set(_OPS))


if __name__ == "__main__":
    unittest.main()
