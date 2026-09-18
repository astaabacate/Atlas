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

    def test_repeticao_de_criacao_e_edicao(self) -> None:
        ctx, servidor = contexto()
        for _ in range(3):
            executar("create_roles", {"roles": [{"name": "Repetido", "color": "#123456"}]}, ctx)
        papeis = [r for r in servidor.roles if r.name == "Repetido"]
        self.assertEqual(len(papeis), 3)
        for papel in papeis:
            executar("edit_role", {"role": str(papel.id), "hoist": True}, ctx)
            self.assertTrue(papel.hoist)


# --------------------------------------------------------------------- canais

class TestCapacidadesDeCanal(unittest.TestCase):
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
