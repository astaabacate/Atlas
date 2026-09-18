"""
Empate de posição: o bot TEM que perguntar ao Discord, não decidir por ele.

O caso do dono (18/09): "como assim ele não apaga um cargo que ele MESMO criou? essa de
posição está errada". O cargo criado pelo bot nasce na MESMA posição do cargo mais alto dele
(no servidor dele, o cargo do bot está no chão da hierarquia), e o gate antigo recusava
ANTES de falar com o Discord — o teste ao vivo então anotava "o Discord recusa" sem nunca ter
perguntado. Agora:

  * posição ACIMA do topo do bot  → recusa na hora, com o caminho da solução (não gasta chamada);
  * posição IGUAL                  → tenta DE VERDADE e traduz a resposta do Discord;
  * posição abaixo                 → segue normalmente.

Estes testes travam esse contrato para editar cargo, apagar cargo, dar e tirar cargo.
"""

from __future__ import annotations

import asyncio
import types
import unittest
from typing import Any

from tests.test_capacidades import Entidade, Servidor, contexto, executar, falha

RECUSA_DO_DISCORD = "403 Forbidden (error code: 50013): Missing Permissions"


class CargoTeimoso(Entidade):
    """Cargo que o Discord recusa editar/apagar (como no servidor do dono)."""

    def __init__(self, nome: str, eid: int, position: int = 1) -> None:
        super().__init__(nome, eid, position)
        self.tentativas_de_editar = 0
        self.tentativas_de_apagar = 0

    async def edit(self, **kwargs: Any) -> "CargoTeimoso":
        self.tentativas_de_editar += 1
        raise Exception(RECUSA_DO_DISCORD)

    async def delete(self) -> None:
        self.tentativas_de_apagar += 1
        raise Exception(RECUSA_DO_DISCORD)


def _servidor_com_bot_no_chao() -> tuple[Any, Servidor]:
    """O cenário do dono: o cargo do bot está na posição 1 e tudo mais está acima."""
    ctx, servidor = contexto()
    servidor.me.top_role = Entidade("farol", 999, 1)
    ctx.guild.me.top_role = servidor.me.top_role
    return ctx, servidor


class TestEmpateDePosicaoPerguntaAoDiscord(unittest.TestCase):
    def test_editar_cargo_no_empate_tenta_e_funciona(self) -> None:
        """Se o Discord aceitar, o bot tem que ter EDITADO — antes nem tentava."""
        ctx, servidor = _servidor_com_bot_no_chao()
        cargo = Entidade("🧪 teste-papel", 55, 1)
        servidor.roles.append(cargo)

        saida = executar("edit_role", {"role": str(cargo.id), "name": "renomeado"}, ctx)

        self.assertEqual(cargo.name, "renomeado")
        self.assertEqual(len(cargo.edits), 1)
        self.assertIn("atualizado com sucesso", saida)

    def test_editar_cargo_no_empate_traduz_a_recusa_do_discord(self) -> None:
        ctx, servidor = _servidor_com_bot_no_chao()
        cargo = CargoTeimoso("🧪 teste-papel", 56, 1)
        servidor.roles.append(cargo)

        msg = falha("edit_role", {"role": str(cargo.id), "name": "renomeado"}, ctx)

        self.assertEqual(cargo.tentativas_de_editar, 1, "o bot não chegou a perguntar ao Discord")
        self.assertIn("O Discord recusou editar", msg)
        self.assertIn("Missing Permissions", msg)
        self.assertIn("posição 1", msg)
        self.assertIn("Configurações do Servidor", msg)

    def test_editar_cargo_acima_do_bot_nao_gasta_chamada(self) -> None:
        ctx, servidor = _servidor_com_bot_no_chao()
        cargo = CargoTeimoso("alto demais", 57, 9)
        servidor.roles.append(cargo)

        msg = falha("edit_role", {"role": str(cargo.id), "name": "x"}, ctx)

        self.assertEqual(cargo.tentativas_de_editar, 0, "chamou o Discord sabendo que ia falhar")
        self.assertIn("posição 9", msg)
        self.assertIn("posição 1", msg)
        self.assertIn("Configurações do Servidor", msg)

    def test_apagar_cargo_no_empate_tenta_de_verdade(self) -> None:
        ctx, servidor = _servidor_com_bot_no_chao()
        cargo = CargoTeimoso("🧪 criado-pelo-bot", 58, 1)
        servidor.roles.append(cargo)

        msg = falha("delete_role", {"role": str(cargo.id)}, ctx)

        self.assertEqual(cargo.tentativas_de_apagar, 1, "não perguntou ao Discord")
        self.assertIn("O Discord recusou apagar", msg)
        self.assertIn("Configurações do Servidor", msg)

    def test_apagar_cargo_acima_do_bot_nao_gasta_chamada(self) -> None:
        ctx, servidor = _servidor_com_bot_no_chao()
        cargo = CargoTeimoso("Cupido", 59, 25)
        servidor.roles.append(cargo)

        msg = falha("delete_role", {"role": str(cargo.id)}, ctx)

        self.assertEqual(cargo.tentativas_de_apagar, 0)
        self.assertIn("posição 25", msg)
        self.assertIn("posição 1", msg)

    def test_lote_de_cargos_no_empate_tenta_cada_um(self) -> None:
        ctx, servidor = _servidor_com_bot_no_chao()
        no_chao = CargoTeimoso("🧪 no-chao", 60, 1)
        acima = CargoTeimoso("Cupido", 61, 25)
        servidor.roles.extend([no_chao, acima])

        saida = executar("delete_roles", {"roles": [str(no_chao.id), str(acima.id)]}, ctx)

        self.assertEqual(no_chao.tentativas_de_apagar, 1, "o empate não foi tentado")
        self.assertEqual(acima.tentativas_de_apagar, 0, "gastou chamada em cargo acima")
        self.assertIn("Nada foi apagado nesta rodada", saida)


class TestDarETirarCargoNoEmpate(unittest.TestCase):
    def _membro(self, servidor: Servidor, *, recusa: bool) -> Entidade:
        membro = Entidade("membro", 424242, 0)
        membro.add_roles = self._acao(recusa, "add")  # type: ignore[attr-defined]
        membro.remove_roles = self._acao(recusa, "remove")  # type: ignore[attr-defined]
        servidor.members.append(membro)
        return membro

    @staticmethod
    def _acao(recusa: bool, tipo: str) -> Any:
        async def chamada(*args: Any, **kwargs: Any) -> None:
            if recusa:
                raise Exception(RECUSA_DO_DISCORD)
            return None

        return chamada

    def test_dar_cargo_no_empate_tenta_e_funciona(self) -> None:
        ctx, servidor = _servidor_com_bot_no_chao()
        cargo = Entidade("🧪 cargo", 70, 1)
        servidor.roles.append(cargo)
        membro = self._membro(servidor, recusa=False)

        saida = executar("give_role", {"member": str(membro.id), "role": str(cargo.id)}, ctx)

        self.assertIn("atribuído", saida)

    def test_dar_cargo_no_empate_traduz_a_recusa(self) -> None:
        ctx, servidor = _servidor_com_bot_no_chao()
        cargo = Entidade("🧪 cargo", 71, 1)
        servidor.roles.append(cargo)
        membro = self._membro(servidor, recusa=True)

        msg = falha("give_role", {"member": str(membro.id), "role": str(cargo.id)}, ctx)

        self.assertIn("O Discord recusou atribuir", msg)
        self.assertIn("Configurações do Servidor", msg)

    def test_tirar_cargo_no_empate_traduz_a_recusa(self) -> None:
        ctx, servidor = _servidor_com_bot_no_chao()
        cargo = Entidade("🧪 cargo", 72, 1)
        servidor.roles.append(cargo)
        membro = self._membro(servidor, recusa=True)

        msg = falha("take_role", {"member": str(membro.id), "role": str(cargo.id)}, ctx)

        self.assertIn("O Discord recusou tirar", msg)


class TestPosicaoMedidaNaApiAntesDeRecusar(unittest.TestCase):
    """O empate é decidido com a posição MEDIDA — cache velho não pode virar recusa."""

    def test_cargo_criado_agora_mesmo_com_cache_vazio(self) -> None:
        ctx, servidor = contexto()
        servidor.me.top_role = types.SimpleNamespace(position=0, is_default=lambda: True)
        ctx.guild.me.top_role = servidor.me.top_role
        # a API diz que o meu cargo é o de posição 3; o alvo está na 1 (abaixo) — pode
        cargo = Entidade("abaixo do bot", 80, 1)
        servidor.roles.append(cargo)
        posicao_de_topo = Entidade("farol", 999, 3)
        servidor.roles.append(posicao_de_topo)
        servidor.me._roles = [999]

        saida = executar("edit_role", {"role": str(cargo.id), "name": "ok"}, ctx)

        self.assertIn("atualizado com sucesso", saida)
        self.assertEqual(cargo.name, "ok")


if __name__ == "__main__":
    asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
    unittest.main()
