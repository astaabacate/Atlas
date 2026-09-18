"""
Testes da sonda de hierarquia (scripts/sonda_hierarquia.py).

A sonda é o experimento CRU: ela pergunta à API do Discord se o bot consegue editar/apagar
um cargo na MESMA posição do cargo mais alto dele — sem passar pelo gate de política do
produto. Estes testes garantem que a sonda monta a visão certa e que o veredito dela sai
do que o Discord respondeu, nunca de suposição.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from scripts import sonda_hierarquia as sonda  # noqa: E402


CARGO_BOT = {"id": "1", "name": "Atlas", "position": 1, "managed": True,
             "permissions": str(1 << 28)}
CARGOS = [
    {"id": "9", "name": "@everyone", "position": 0, "is_default": True, "permissions": "0"},
    CARGO_BOT,
    {"id": "2", "name": "Cupido", "position": 25, "permissions": "0"},
    {"id": "3", "name": "asta", "position": 24, "permissions": "0"},
]


class FakeAPI:
    """Duplo da API do Discord: devolve exatamente o que o teste mandar."""

    def __init__(self, token: str, roteiro: "RoteiroDeRespostas") -> None:
        self.roteiro = roteiro

    async def __aenter__(self) -> "FakeAPI":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def pedir(self, metodo: str, caminho: str, **kwargs: Any) -> tuple[int, Any]:
        return self.roteiro(metodo, caminho, kwargs)


class RoteiroDeRespostas:
    """Respostas fixas do Discord + registro das chamadas feitas."""

    RECUSA = (403, {"code": 50013, "message": "Missing Permissions"})

    def __init__(self, *, editar: tuple[int, Any] | None = None,
                 apagar: tuple[int, Any] | None = None,
                 empate: tuple[int, Any] | None = None,
                 editar_empatado: tuple[int, Any] | None = None,
                 apagar_empatado: tuple[int, Any] | None = None,
                 mover: tuple[int, Any] | None = None,
                 apagar_depois_de_mover: tuple[int, Any] | None = None,
                 posicao_depois_do_empate: int = 1) -> None:
        # O padrão é o cenário do relato do dono: o Discord recusa TUDO por hierarquia.
        self.editar = editar or self.RECUSA
        self.apagar = apagar or self.RECUSA
        self.empate = empate or self.RECUSA
        self.editar_empatado = editar_empatado or self.RECUSA
        self.apagar_empatado = apagar_empatado or self.RECUSA
        self.mover = mover or self.RECUSA
        self.apagar_depois_de_mover = apagar_depois_de_mover or (204, None)
        # posição que a API devolve depois do empate (1 = a mesma do topo do bot em CARGOS)
        self.posicao_lida = posicao_depois_do_empate
        self.chamadas: list[tuple[str, str]] = []
        self.edicoes = 0
        self.movimentos = 0
        self.exclusoes = 0
        self.empate_aceito = False
        self.apagou = False
        self.apagou_empatado = False
        self.fase = "inicial"
        self.sobra = True

    def __call__(self, metodo: str, caminho: str, kwargs: dict[str, Any]) -> tuple[int, Any]:
        self.chamadas.append((metodo, caminho))
        if metodo == "GET" and caminho == "/users/@me":
            return 200, {"id": "555", "username": "Atlas"}
        if metodo == "GET" and caminho == "/users/@me/guilds":
            return 200, [{"id": "777", "name": "Pinguim"}]
        if metodo == "GET" and caminho == "/guilds/777/roles":
            return 200, CARGOS
        if metodo == "GET" and caminho == "/guilds/777/roles/42":
            return 200, {"id": "42", "name": "x", "position": self.posicao_lida}
        if metodo == "GET" and caminho == "/guilds/777/members/555":
            return 200, {"roles": ["1"]}
        if metodo == "GET" and caminho == "/guilds/777/members/999":
            return 200, {"roles": ["2"]}
        if metodo == "GET" and caminho == "/guilds/777":
            return 200, {"owner_id": "999", "name": "Pinguim"}
        if metodo == "POST" and caminho == "/guilds/777/roles":
            return 201, {"id": "42", "name": kwargs["json"]["name"], "position": 1}
        if metodo == "PATCH" and caminho == "/guilds/777/roles/42":
            self.edicoes += 1
            return self.editar_empatado if self.fase == "empate" else self.editar
        if metodo == "PATCH" and caminho == "/guilds/777/roles":
            posicao = int(kwargs["json"][0]["position"])
            if posicao > 0:  # mover para a MESMA posição do topo do bot = forçar o empate
                self.empate_aceito = self.empate[0] < 400
                if self.empate_aceito:
                    self.fase = "empate"
                return self.empate
            self.fase = "apos_mover"
            return self.mover
        if metodo == "DELETE" and caminho == "/guilds/777/roles/42":
            self.exclusoes += 1
            if self.fase == "empate" and not self.apagou_empatado:
                self.apagou_empatado = True
                if self.apagar_empatado[0] < 400:
                    self.sobra = False
                return self.apagar_empatado
            if not self.apagou:
                self.apagou = True
                if self.apagar[0] < 400:
                    self.sobra = False
                return self.apagar
            if self.apagar_depois_de_mover[0] < 400:
                self.sobra = False
            return self.apagar_depois_de_mover
        raise AssertionError(f"chamada não prevista no roteiro: {metodo} {caminho}")


class TestVisaoDosCargos(unittest.TestCase):
    def test_topo_do_membro_e_o_cargo_de_maior_posicao(self) -> None:
        membro = {"roles": ["1", "2"]}
        topo = sonda._topo_do_membro(membro, CARGOS)
        assert topo is not None
        self.assertEqual(topo["name"], "Cupido")
        self.assertEqual(topo["position"], 25)

    def test_topo_do_membro_sem_cargos(self) -> None:
        self.assertIsNone(sonda._topo_do_membro({"roles": []}, CARGOS))
        self.assertIsNone(sonda._topo_do_membro(None, CARGOS))

    def test_tem_permissao_conta_cargo_do_bot_e_everyone(self) -> None:
        self.assertTrue(sonda._tem_permissao([CARGO_BOT], CARGOS, sonda.MANAGE_ROLES))
        self.assertFalse(sonda._tem_permissao([{"id": "2", "permissions": "0"}], CARGOS,
                                              sonda.MANAGE_ROLES))
        sem_acesso = [{"id": "9", "name": "@everyone", "is_default": True,
                       "permissions": str(sonda.MANAGE_ROLES)}]
        self.assertTrue(sonda._tem_permissao([{"id": "2", "permissions": "0"}], sem_acesso,
                                             sonda.MANAGE_ROLES))

    def test_erro_resume_o_corpo_do_discord(self) -> None:
        self.assertEqual(sonda._erro({"code": 50013, "message": "Missing Permissions"}),
                         "code=50013 message=Missing Permissions")
        self.assertEqual(sonda._erro("texto solto"), "texto solto")
        self.assertEqual(sonda._erro(None), "None")


class TestSondaAoVivoComDuplo(unittest.TestCase):
    def _rodar(self, roteiro: RoteiroDeRespostas) -> tuple[int, str, dict[str, Any]]:
        original = sonda.Sondagem
        sonda.Sondagem = lambda token: FakeAPI(token, roteiro)  # type: ignore[assignment]
        os.environ["DISCORD_TOKEN"] = "token-falso-de-teste"
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            try:
                rc = asyncio.run(sonda.sondar(None, pathlib.Path(tmp)))
                texto = (pathlib.Path(tmp) / "sonda-hierarquia.md").read_text(encoding="utf-8")
                dados = json.loads((pathlib.Path(tmp) / "sonda-hierarquia.json").read_text("utf-8"))
            finally:
                sonda.Sondagem = original  # type: ignore[assignment]
        return rc, texto, dados

    def test_recusa_em_tudo_deixa_o_cargo_preso_registrado(self) -> None:
        """Cenário do relato: o cargo do bot no fundo — o Discord recusa tudo (e a sonda diz)."""
        rc, texto, dados = self._rodar(RoteiroDeRespostas())
        self.assertEqual(rc, 0)
        self.assertIn("Renomear ABAIXO do meu topo: recusado", texto)
        self.assertIn("APAGAR: o Discord **RECUSOU**", texto)
        self.assertIn("Sobrou o cargo de teste", texto)
        self.assertEqual(dados["guilds"][0]["experimento"]["sobra"]["id"], "42")
        self.assertNotIn("token-falso-de-teste", texto)

    def test_apagar_aceito_nao_deixa_sobra(self) -> None:
        rc, texto, dados = self._rodar(RoteiroDeRespostas(editar=(200, None), apagar=(204, None)))
        self.assertEqual(rc, 0)
        self.assertIn("APAGAR: o Discord ACEITOU", texto)
        self.assertIsNone(dados["guilds"][0]["experimento"]["sobra"])
        self.assertNotIn("Sobrou", texto)

    def test_apagar_recusado_mas_mover_e_apagar_funciona(self) -> None:
        roteiro = RoteiroDeRespostas(mover=(200, None), apagar_depois_de_mover=(204, None))
        rc, texto, dados = self._rodar(roteiro)
        self.assertEqual(rc, 0)
        self.assertIn("Mover para a posição 0: o Discord ACEITOU", texto)
        self.assertIn("APAGAR funcionou", texto)
        self.assertIsNone(dados["guilds"][0]["experimento"]["sobra"])

    def test_empate_apagar_aceito_prova_que_a_regra_nao_bloqueia_posicao_igual(self) -> None:
        """O caso do dono: cargo na MESMA posição do topo do bot — o Discord aceita apagar?"""
        roteiro = RoteiroDeRespostas(
            editar=(200, None), empate=(200, None), editar_empatado=(200, None),
            apagar_empatado=(204, None))
        rc, texto, dados = self._rodar(roteiro)
        exp = dados["guilds"][0]["experimento"]
        self.assertEqual(rc, 0)
        self.assertIn("EMPATE: RENOMEAR foi ACEITO", texto)
        self.assertIn("EMPATE: APAGAR foi ACEITO", texto)
        # confere a posição REAL depois do movimento: sem isso não se sabe se o Discord
        # deixou o cargo empatado ou o empurrou para baixo
        self.assertIn("continua na MESMA posição do meu topo", texto)
        self.assertEqual(dados["guilds"][0]["experimento"]["posicao_depois_do_empate"], 1)
        self.assertIsNone(exp["sobra"])
        self.assertEqual(exp["mover_para_empate"]["status"], 200)

    def test_empate_recusado_cai_para_mover_e_apagar(self) -> None:
        roteiro = RoteiroDeRespostas(
            editar=(200, None), empate=(200, None), editar_empatado=None, apagar_empatado=None,
            mover=(200, None), apagar_depois_de_mover=(204, None))
        rc, texto, dados = self._rodar(roteiro)
        self.assertEqual(rc, 0)
        self.assertIn("EMPATE: RENOMEAR RECUSADO", texto)
        self.assertIn("EMPATE: apagar recusado", texto)
        self.assertIn("APAGAR funcionou", texto)
        self.assertIsNone(dados["guilds"][0]["experimento"]["sobra"])

    def test_permissao_conta_administrator(self) -> None:
        """Administrator vale por Gerenciar Cargos — a 1ª versão disso imprimiu 'NÃO' (alarme falso)."""
        cargos = [{"id": "1", "name": "Atlas", "position": 1, "managed": True,
                   "permissions": str(sonda.ADMINISTRATOR)}]
        todos = cargos + [{"id": "9", "is_default": True, "permissions": "0"}]
        self.assertTrue(sonda._tem_permissao(cargos, todos, sonda.MANAGE_ROLES))
        self.assertEqual(sonda._permissao_do_bot(cargos, todos), sonda.ADMINISTRATOR)

    def test_mesma_posicao_do_bot_aparece_na_tabela(self) -> None:
        _, texto, _ = self._rodar(RoteiroDeRespostas())
        self.assertIn("MESMA posição do meu cargo", texto)
        self.assertIn("ACIMA do meu cargo", texto)
        self.assertIn("@everyone (sempre intocável)", texto)

    def test_sem_token_ainda_grava_o_motivo(self) -> None:
        original = sonda.Sondagem
        sonda.Sondagem = lambda token: FakeAPI(token, RoteiroDeRespostas())  # type: ignore[assignment]
        os.environ.pop("DISCORD_TOKEN", None)
        try:
            with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
                rc = asyncio.run(sonda.sondar(None, pathlib.Path(tmp)))
                texto = (pathlib.Path(tmp) / "sonda-hierarquia.md").read_text(encoding="utf-8")
        finally:
            sonda.Sondagem = original  # type: ignore[assignment]
        self.assertEqual(rc, 2)
        self.assertIn("ABORTADA", texto)
        self.assertIn("`DISCORD_TOKEN` está VAZIO", texto)

    def test_token_recusado_grava_o_motivo(self) -> None:
        def recusado(metodo: str, caminho: str, kwargs: dict[str, Any]) -> tuple[int, Any]:
            return 401, {"code": 0, "message": "401: Unauthorized"}

        original = sonda.Sondagem
        sonda.Sondagem = lambda token: FakeAPI(token, recusado)  # type: ignore[assignment]
        os.environ["DISCORD_TOKEN"] = "token-falso-de-teste"
        try:
            with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
                rc = asyncio.run(sonda.sondar(None, pathlib.Path(tmp)))
                texto = (pathlib.Path(tmp) / "sonda-hierarquia.md").read_text(encoding="utf-8")
        finally:
            sonda.Sondagem = original  # type: ignore[assignment]
        self.assertEqual(rc, 2)
        self.assertIn("recusou o token", texto)
        self.assertIn("HTTP 401", texto)

    def test_excecao_inesperada_publica_o_rastro(self) -> None:
        original = sonda.sondar

        async def explode(guild_id: str | None, outdir: pathlib.Path) -> int:
            raise RuntimeError("quebrou de propósito")

        sonda.sondar = explode  # type: ignore[assignment]
        argv = sys.argv
        sys.argv = ["sonda", "--outdir", tempfile.mkdtemp()]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = sonda.main()
                texto = (pathlib.Path(sys.argv[2]) / "sonda-hierarquia.md").read_text("utf-8")
        finally:
            sonda.sondar = original  # type: ignore[assignment]
            sys.argv = argv
        self.assertEqual(rc, 1)
        self.assertIn("FALHOU", texto)
        self.assertIn("quebrou de propósito", texto)

    def test_sem_token_nao_roda(self) -> None:
        original = sonda.Sondagem
        sonda.Sondagem = lambda token: FakeAPI(token, RoteiroDeRespostas())  # type: ignore[assignment]
        os.environ.pop("DISCORD_TOKEN", None)
        try:
            with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
                rc = asyncio.run(sonda.sondar(None, pathlib.Path(tmp)))
        finally:
            sonda.Sondagem = original  # type: ignore[assignment]
        self.assertEqual(rc, 2)

    def test_token_recusado_sai_com_erro(self) -> None:
        def recusado(metodo: str, caminho: str, kwargs: dict[str, Any]) -> tuple[int, Any]:
            return 401, {"code": 0, "message": "401: Unauthorized"}

        original = sonda.Sondagem
        sonda.Sondagem = lambda token: FakeAPI(token, recusado)  # type: ignore[assignment]
        os.environ["DISCORD_TOKEN"] = "token-falso-de-teste"
        try:
            with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
                rc = asyncio.run(sonda.sondar(None, pathlib.Path(tmp)))
        finally:
            sonda.Sondagem = original  # type: ignore[assignment]
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
