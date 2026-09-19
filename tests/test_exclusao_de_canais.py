"""
Testes da exclusão de canais — o bug ao vivo de 18/09.

O dono pediu "apague todos os canais e deixe esse": o bot apagou 13 e **sobraram canais**. Duas
causas reais, cada uma com teste aqui:

1. a lista vinha do que o modelo tinha em mãos (o servidor muda durante a conversa — outro
   processo criou canais no meio do caminho);
2. ninguém conferia depois: a resposta dizia "concluído" sem reler o servidor.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import unittest
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from brain import ops_delete  # noqa: E402


class CanalFalso:
    """Duplo de canal: `delete()` pode falhar (como o Discord faz com canal de sistema)."""

    def __init__(self, cid: int, nome: str, *, apagavel: bool = True) -> None:
        self.id = cid
        self.name = nome
        self.apagavel = apagavel
        self.apagado = False

    async def delete(self) -> None:
        if not self.apagavel:
            raise PermissionError("Missing Permissions")
        self.apagado = True


class ServidorFalso:
    """
    Duplo com `fetch_channels()` de verdade: devolve o que ESTÁ no servidor agora.

    É isso que permite testar a corrida ("um canal nasceu depois da lista") e a conferência
    pós-exclusão.
    """

    def __init__(self, canais: list[CanalFalso]) -> None:
        self.canais = canais
        self.leituras = 0

    @property
    def channels(self) -> list[CanalFalso]:
        """Cache do discord.py: só o que ainda existe."""
        return [c for c in self.canais if not c.apagado]

    @property
    def categories(self) -> list[Any]:
        return []

    async def fetch_channels(self) -> list[CanalFalso]:
        self.leituras += 1
        return self.channels


class TestDeteccaoDeTodos(unittest.TestCase):
    def test_palavras_que_significam_todos(self) -> None:
        for item in ("*", "todos", "todos os canais", "todas as categorias", "tudo",
                     "Todos os canais", "todos os canais e categorias"):
            with self.subTest(item=item):
                self.assertTrue(ops_delete.e_pedido_de_todos([item]))

    def test_nomes_de_canal_nao_sao_confundidos_com_todos(self) -> None:
        for item in ("geral", "bate-papo", "canal-teste", "categoria do time"):
            with self.subTest(item=item):
                self.assertFalse(ops_delete.e_pedido_de_todos([item]))

    def test_lista_normal_com_um_todos_dentro_conta_como_todos(self) -> None:
        self.assertTrue(ops_delete.e_pedido_de_todos(["geral", "todos os canais"]))


class TestExpansaoELeituraNaHora(unittest.TestCase):
    def test_todos_traz_canal_que_nasceu_depois_da_lista(self) -> None:
        """A corrida do bug: o modelo listou 2, mas o servidor tinha 3 quando a exclusão rodou."""
        antigo = CanalFalso(1, "antigo")
        novo = CanalFalso(2, "nasceu-agora")
        servidor = ServidorFalso([antigo, novo])

        alvos = asyncio.run(ops_delete.expandir_tudo(servidor, ["todos os canais"]))
        self.assertEqual({a.id for a in alvos}, {1, 2},
                         "o canal criado depois da lista do modelo tem que entrar")
        self.assertEqual(servidor.leituras, 1, "a lista vem da API, na hora da exclusão")

    def test_o_canal_da_conversa_fica_fora_da_expansao(self) -> None:
        conversa = CanalFalso(1, "aqui")
        outro = CanalFalso(2, "outro")
        servidor = ServidorFalso([conversa, outro])
        alvos = asyncio.run(ops_delete.expandir_tudo(servidor, ["todos"], fora=conversa))
        self.assertEqual([a.id for a in alvos], [2])

    def test_sem_fetch_channels_usa_o_cache(self) -> None:
        class SemApi:
            channels = [CanalFalso(1, "a"), CanalFalso(2, "b")]
            categories: list[Any] = []

        alvos = asyncio.run(ops_delete.expandir_tudo(SemApi(), ["todos"]))
        self.assertEqual({a.id for a in alvos}, {1, 2})


class TestConferenciaDepoisDeApagar(unittest.TestCase):
    def test_conferencia_pega_o_canal_que_recusou_sair(self) -> None:
        teimoso = CanalFalso(1, "teimoso", apagavel=False)
        normal = CanalFalso(2, "normal")
        servidor = ServidorFalso([teimoso, normal])
        async def apagar(canal: CanalFalso) -> None:
            try:
                await canal.delete()
            except PermissionError:
                pass

        asyncio.run(apagar(teimoso))
        asyncio.run(apagar(normal))
        restantes = asyncio.run(ops_delete.ainda_existem(servidor, [teimoso, normal]))
        self.assertEqual([c.name for c in restantes], ["teimoso"],
                         "quem não saiu tem que aparecer na conferência")

    def test_conferencia_vazia_quando_tudo_saiu(self) -> None:
        canais = [CanalFalso(1, "a"), CanalFalso(2, "b")]
        servidor = ServidorFalso(canais)
        for canal in canais:
            asyncio.run(canal.delete())
        self.assertEqual(asyncio.run(ops_delete.ainda_existem(servidor, canais)), [])

    def test_sem_leitura_da_api_nao_inventa_sobra(self) -> None:
        """Duplo sem fetch_channels: não dá para conferir — e a resposta não pode mentir."""
        class SemApi:
            channels: list[Any] = []

        self.assertEqual(asyncio.run(ops_delete.ainda_existem(SemApi(), [CanalFalso(1, "x")])), [])


class TestNomesParaAResposta(unittest.TestCase):
    def test_nomes_em_texto(self) -> None:
        canais = [CanalFalso(1, "um"), CanalFalso(2, "dois")]
        self.assertEqual(ops_delete.nomes(canais), "#um, #dois")


if __name__ == "__main__":
    unittest.main()


class TestFluxoCompletoDaExclusao(unittest.TestCase):
    """
    O pedido real do dono, de ponta a ponta no op_delete_channels, com servidor que responde à
    API (é assim que a exclusão pode ser conferida de verdade).
    """

    def _ctx(self, canais: list[CanalFalso], conversa: CanalFalso):
        from types import SimpleNamespace

        ServidorFalso.fetch_roles = lambda self: []  # type: ignore[attr-defined]
        guild = ServidorFalso(canais)
        guild.get_channel = lambda cid: next((c for c in canais if c.id == cid), None)  # type: ignore[attr-defined]
        perms = SimpleNamespace(administrator=True, manage_channels=True, manage_roles=True)
        guild.me = SimpleNamespace(id=99, guild_permissions=perms,  # type: ignore[attr-defined]
                                   top_role=SimpleNamespace(position=100))
        guild.owner_id = 1  # type: ignore[attr-defined]
        actor = SimpleNamespace(id=1, guild_permissions=perms)
        from brain.tools import ToolContext

        return ToolContext(guild=guild, channel=conversa, actor=actor,
                           confirm_destructive=False)

    def test_apaga_tudo_menos_o_canal_da_conversa_com_prova_na_api(self) -> None:
        conversa = CanalFalso(100, "aqui-Conversa")
        um = CanalFalso(1, "um")
        dois = CanalFalso(2, "dois")
        # o canal 3 "nasceu" durante a conversa: não está em nenhuma lista do modelo
        tres = CanalFalso(3, "nasceu-depois")
        ctx = self._ctx([conversa, um, dois, tres], conversa)

        from brain.ops import op_delete_channels

        res = asyncio.run(op_delete_channels(ctx, ["todos os canais menos esse"], confirmed=True))

        self.assertTrue(all(c.apagado for c in (um, dois, tres)),
                        "todos os canais do servidor têm que sair, não só os que o modelo listou")
        self.assertFalse(conversa.apagado, "o canal da conversa fica")
        self.assertIn("conferida na API", res)
        self.assertIn("3/3", res, f"a resposta tem que contar os 3 apagados: {res}")
        self.assertIn("menos esse", res)

    def test_canal_que_o_discord_recusa_nao_vira_concluido(self) -> None:
        conversa = CanalFalso(100, "aqui")
        teimoso = CanalFalso(1, "teimoso", apagavel=False)
        normal = CanalFalso(2, "normal")
        ctx = self._ctx([conversa, teimoso, normal], conversa)

        from brain.ops import op_delete_channels

        res = asyncio.run(op_delete_channels(ctx, ["todos"], confirmed=True))

        self.assertNotIn("Exclusão concluída", res,
                         "nunca dizer concluído com canal sobrando")
        self.assertIn("#teimoso", res)
        self.assertIn("NÃO consegui apagar", res)
        self.assertTrue(normal.apagado)

    def test_nome_errado_que_o_discord_recusa_nao_vira_concluido(self) -> None:
        """Exclusão nominal em que NADA saiu: erro explícito, jamais 'concluído'."""
        conversa = CanalFalso(100, "aqui")
        teimoso = CanalFalso(1, "teimoso", apagavel=False)
        ctx = self._ctx([conversa, teimoso], conversa)

        from brain.ops import op_delete_channels
        from brain.tools import ToolError

        with self.assertRaises(ToolError) as erro:
            asyncio.run(op_delete_channels(ctx, ["teimoso"], confirmed=True))
        texto = str(erro.exception)
        self.assertIn("Missing Permissions", texto)
        self.assertIn("#teimoso", texto, "o erro tem que dizer QUAL canal falhou")


class TestNaoApagaNoEscuro(unittest.TestCase):
    """Sem a lista lida da API, 'todos' NÃO pode virar um chute (apagar parte e chamar de tudo)."""

    def test_api_fora_do_ar_recusa_com_motivo(self) -> None:
        from types import SimpleNamespace

        from brain.ops import op_delete_channels
        from brain.tools import ToolContext, ToolError

        class ServidorMudo:
            channels: list[Any] = []
            categories: list[Any] = []
            owner_id = 1

            async def fetch_channels(self) -> list[Any]:
                raise TimeoutError("o Discord não respondeu")

        perms = SimpleNamespace(administrator=True, manage_channels=True)
        guild = ServidorMudo()
        guild.me = SimpleNamespace(id=9, guild_permissions=perms)  # type: ignore[attr-defined]
        ctx = ToolContext(guild=guild, channel=SimpleNamespace(id=5, name="aqui"),
                          actor=SimpleNamespace(id=1, guild_permissions=perms),
                          confirm_destructive=False)

        with self.assertRaises(ToolError) as erro:
            asyncio.run(op_delete_channels(ctx, ["todos"], confirmed=True))
        self.assertIn("no escuro", str(erro.exception))
