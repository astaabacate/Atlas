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
    {"id": "2", "name": "Cargo Teste", "position": 25, "permissions": "0"},
    {"id": "3", "name": "Cargo Antigo", "position": 24, "permissions": "0"},
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
            return 200, [{"id": "777", "name": "Servidor-Teste"}]
        if metodo == "GET" and caminho == "/guilds/777/roles":
            return 200, CARGOS
        if metodo == "GET" and caminho == "/guilds/777/roles/42":
            return 200, {"id": "42", "name": "x", "position": self.posicao_lida}
        if metodo == "GET" and caminho == "/guilds/777/members/555":
            return 200, {"roles": ["1"]}
        if metodo == "GET" and caminho == "/guilds/777/members/999":
            return 200, {"roles": ["2"]}
        if metodo == "GET" and caminho == "/guilds/777":
            return 200, {"owner_id": "999", "name": "Servidor-Teste"}
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
        self.assertEqual(topo["name"], "Cargo Teste")
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

        async def explode(guild_id: str | None, outdir: pathlib.Path, _anon: Any = None) -> int:
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


class _Resposta:
    """Resposta mínima da CDN do Discord para a sonda medir a cor do avatar."""

    def __init__(self, status: int, corpo: bytes = b"") -> None:
        self.status = status
        self._corpo = corpo

    async def read(self) -> bytes:
        return self._corpo

    async def __aenter__(self) -> "_Resposta":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


class _Sessao:
    def __init__(self, resposta: _Resposta) -> None:
        self.resposta = resposta
        self.urls: list[str] = []

    def get(self, url: str) -> _Resposta:
        self.urls.append(url)
        return self.resposta


class _ApiDaCor:
    """Duplo com a mesma peça que a sonda usa para baixar a foto (`_sessao`)."""

    def __init__(self, resposta: _Resposta) -> None:
        self._sessao = _Sessao(resposta)


class TestCorDoAvatarDaSonda(unittest.TestCase):
    """A sonda mede a cor do avatar — e isso NÃO pode derrubar a sonda.

    Bug pego ao vivo (run 35388580915): o passo "Rodar a sonda" morreu com
    `No module named 'core'`, porque `import core.look` puxa o `__init__` do pacote e o
    discord.py não está instalado lá. A sonda roda com uma dependência só (aiohttp).
    """

    def test_medidor_carrega_sem_o_pacote_core_nem_o_discord(self) -> None:
        """No CI a sonda roda só com aiohttp: nem `core` (pacote) nem `discord` podem ser exigidos."""
        guardados = {nome: sys.modules.get(nome) for nome in ("core", "discord")}
        for nome in ("core", "discord"):
            sys.modules[nome] = None  # type: ignore[assignment] - faz `import <nome>` explodir
        try:
            look = sonda._modulo_do_core("look")
        finally:
            for nome, antes in guardados.items():
                if antes is None:
                    sys.modules.pop(nome, None)
                else:
                    sys.modules[nome] = antes
        self.assertTrue(hasattr(look, "cor_de_destaque"))
        self.assertEqual(look.__file__, str(pathlib.Path(sonda.__file__).resolve().parents[1]
                                            / "core" / "look.py"))
        anon = sonda._modulo_do_core("anonimo")
        self.assertTrue(hasattr(anon, "Anonimizador"),
                        "o disfarce dos relatórios também tem que carregar sem o discord.py")

    def test_sem_avatar_registra_o_motivo_e_nao_quebra(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outdir = pathlib.Path(tmp)
            api = _ApiDaCor(_Resposta(200))
            with contextlib.redirect_stdout(io.StringIO()):
                cor = asyncio.run(sonda._cor_do_avatar(api, {"id": "1", "username": "atlas"}, outdir))
            texto = (outdir / "cor-do-avatar.txt").read_text(encoding="utf-8")
            self.assertIsNone(cor)
            self.assertIn("NÃO MEDIDA", texto)
            self.assertIn("avatar padrão do Discord", texto)
            self.assertEqual(api._sessao.urls, [], "sem foto não se chama a CDN")

    def test_com_foto_mede_e_grava_o_hex(self) -> None:
        from tests.test_look import _cor_de, _fundo_branco, _png

        px = _cor_de(_fundo_branco(8, 8), (230, 40, 60, 255), amostra=2)
        api = _ApiDaCor(_Resposta(200, _png(8, 8, px, alfa=True)))
        eu = {"id": "42", "username": "atlas", "avatar": "abc123"}
        with tempfile.TemporaryDirectory() as tmp:
            outdir = pathlib.Path(tmp)
            with contextlib.redirect_stdout(io.StringIO()):
                cor = asyncio.run(sonda._cor_do_avatar(api, eu, outdir))
            texto = (outdir / "cor-do-avatar.txt").read_text(encoding="utf-8")
        self.assertIsNotNone(cor)
        self.assertIn(f"ACCENT_COLOR={sonda.hex_da_cor(cor)}", texto)
        self.assertEqual(api._sessao.urls,
                         ["https://cdn.discordapp.com/avatars/42/abc123.png?size=64"],
                         "a sonda pede o PNG de verdade, no tamanho que o bot usa")

    def test_cdn_fora_do_ar_registra_e_nao_quebra(self) -> None:
        api = _ApiDaCor(_Resposta(503))
        with tempfile.TemporaryDirectory() as tmp:
            outdir = pathlib.Path(tmp)
            with contextlib.redirect_stdout(io.StringIO()):
                cor = asyncio.run(sonda._cor_do_avatar(
                    api, {"id": "42", "username": "atlas", "avatar": "abc"}, outdir))
            texto = (outdir / "cor-do-avatar.txt").read_text(encoding="utf-8")
        self.assertIsNone(cor)
        self.assertIn("HTTP 503", texto)


class TestRelatorioNaoExpoeOCliente(unittest.TestCase):
    """O relatório da sonda vai para um repositório PÚBLICO (e o log do Actions também)."""

    def _rodar(self) -> tuple[str, str]:
        original = sonda.Sondagem
        sonda.Sondagem = lambda token: FakeAPI(token, RoteiroDeRespostas())  # type: ignore[assignment]
        os.environ["DISCORD_TOKEN"] = "token-falso-de-teste"
        try:
            with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
                rc = asyncio.run(sonda.sondar(None, pathlib.Path(tmp)))
                self.assertEqual(rc, 0)
                md = (pathlib.Path(tmp) / "sonda-hierarquia.md").read_text(encoding="utf-8")
                js = (pathlib.Path(tmp) / "sonda-hierarquia.json").read_text(encoding="utf-8")
        finally:
            sonda.Sondagem = original  # type: ignore[assignment]
        return md, js

    def test_nomes_de_cargo_do_cliente_saem(self) -> None:
        md, js = self._rodar()
        self.assertNotIn("Cargo Teste", md + js, "cargo de cliente não pode ir para o repositório")
        self.assertNotIn("Cargo Antigo", md + js)
        self.assertIn("Cargo-", md, "o lugar vira apelido estável, para o relatório continuar útil")

    def test_id_do_servidor_sai(self) -> None:
        md, js = self._rodar()
        import re

        for texto, nome in ((md, "markdown"), (js, "json")):
            self.assertIsNone(re.search(r"(?<!\d)\d{17,20}(?!\d)", texto),
                              f"sobrou ID no {nome} da sonda")

    def test_o_cargo_do_proprio_bot_fica_visivel(self) -> None:
        # É ele que o dono precisa achar na lista do Discord para arrastar para cima.
        md, _ = self._rodar()
        self.assertIn("Atlas", md)

    def test_sem_disfarce_nao_publica_o_relatorio(self) -> None:
        """Falha FECHADO: sem o disfarce, sai aviso em vez do relatório com os dados."""
        class SemDisfarce:
            def registrar(self, *_a: Any, **_k: Any) -> str:
                return ""

            def registrar_varios(self, *_a: Any, **_k: Any) -> None:
                return None

            def mascarar(self, *_a: Any, **_k: Any) -> str:
                raise RuntimeError("disfarce fora do ar")

            def mascarar_estrutura(self, *_a: Any, **_k: Any) -> Any:
                raise RuntimeError("disfarce fora do ar")

        with tempfile.TemporaryDirectory() as tmp:
            sonda._gravar(pathlib.Path(tmp), ["## Servidor Servidor-Teste (`987654321098765432`)"],
                          {"guilds": [{"nome": "Servidor-Teste"}]}, SemDisfarce())
            md = (pathlib.Path(tmp) / "sonda-hierarquia.md").read_text(encoding="utf-8")
            js = (pathlib.Path(tmp) / "sonda-hierarquia.json").read_text(encoding="utf-8")
        self.assertIn("retido", md)
        self.assertNotIn("Servidor-Teste", md + js)
        self.assertNotIn("987654321098765432", md + js)


if __name__ == "__main__":
    unittest.main()
