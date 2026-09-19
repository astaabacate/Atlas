"""
O relatório do E2E não pode expor o servidor de quem usa o bot.

O repositório é público e os logs do Actions também: nome de servidor, de canal, de cargo,
ID, menção e link de mensagem têm que sair disfarçados ("Servidor-1", "Canal-2", "<id>").
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _carregar_harness():
    spec = importlib.util.spec_from_file_location("e2e_live_anon", ROOT / "scripts" / "e2e_live.py")
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["e2e_live_anon"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


e2e = _carregar_harness()


class _Cargo:
    def __init__(self, nome: str, default: bool = False) -> None:
        self.name = nome
        self.is_default = default


class _Canal:
    def __init__(self, nome: str) -> None:
        self.name = nome


class _Membro:
    def __init__(self, nome: str, cargos: list[_Cargo]) -> None:
        self.display_name = nome
        self.roles = cargos


class _Servidor:
    def __init__(self) -> None:
        self.name = "Servidor do Cliente"
        self.roles = [_Cargo("@everyone", default=True), _Cargo("Atlas"), _Cargo("Moderador"),
                      _Cargo("VIP")]
        self.channels = [_Canal("bate-papo"), _Canal("regras")]
        self.me = _Membro("Atlas", [self.roles[1]])


class TestRelatorioDisfarcado(unittest.TestCase):
    def setUp(self) -> None:
        self.rep = e2e.Reporter(["tools"])
        self.rep.registrar_servidor(_Servidor(), _Membro("dono-do-servidor", []))

    def test_nome_e_id_do_servidor_saem(self) -> None:
        self.rep.record("tools", "servidor e autor", "PASS",
                        "servidor de teste: Servidor do Cliente (1546763083005825084) · "
                        "autor: dono-do-servidor")
        detalhe = self.rep.phases["tools"][0].detail
        self.assertNotIn("Servidor do Cliente", detalhe)
        self.assertNotIn("1546763083005825084", detalhe)
        self.assertNotIn("dono-do-servidor", detalhe)
        self.assertIn("Servidor-1", detalhe)

    def test_canais_e_cargos_do_cliente_saem(self) -> None:
        self.rep.record("tools", "estrutura", "PASS", "criei <#1550640448442212453> na "
                        "categoria de bate-papo, com os cargos Moderador e VIP")
        detalhe = self.rep.phases["tools"][0].detail
        for proibido in ("bate-papo", "Moderador", "VIP", "1550640448442212453"):
            self.assertNotIn(proibido, detalhe)
        self.assertIn("<#canal>", detalhe)

    def test_o_cargo_do_proprio_bot_fica_visivel(self) -> None:
        self.rep.record("tools", "meu cargo", "PASS", "cargo do bot: Atlas")
        self.assertIn("Atlas", self.rep.phases["tools"][0].detail)

    def test_mencoes_e_links_saem(self) -> None:
        self.rep.record("tools", "mencoes", "PASS",
                        "mandei para <@&153>, <@1521612392105250836> em "
                        "https://discord.com/channels/1546763083005825084/1550640448442212453/1550651829866733669")
        detalhe = self.rep.phases["tools"][0].detail
        self.assertIn("<@&cargo>", detalhe)
        self.assertIn("<@pessoa>", detalhe)
        self.assertNotIn("1546763083005825084/", detalhe)

    def test_markdown_e_json_saem_disfarcados(self) -> None:
        self.rep.record("tools", "checagem", "PASS", "servidor Servidor do Cliente, id 1546763083005825084")
        self.rep.note("conectado em Servidor do Cliente")
        md = self.rep.to_markdown()
        js = json.dumps(self.rep.to_dict(), ensure_ascii=False)
        for texto in (md, js):
            self.assertNotIn("Servidor do Cliente", texto)
            self.assertNotIn("1546763083005825084", texto)

    def test_o_log_tambem_sai_disfarcado(self) -> None:
        """O log do Actions de repositório público é público."""
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.rep.record("tools", "log", "PASS", "servidor Servidor do Cliente (1546763083005825084)")
        self.assertNotIn("Servidor do Cliente", buffer.getvalue())

    def test_merge_de_partes_nao_desfaz_o_disfarce(self) -> None:
        """O relatório final é montado a partir das partes já disfarçadas."""
        with tempfile.TemporaryDirectory() as tmp:
            parte = pathlib.Path(tmp) / "partes"
            parte.mkdir()
            self.rep.record("tools", "checagem", "PASS", "servidor Servidor do Cliente")
            (parte / "1.json").write_text(json.dumps(self.rep.to_dict(), ensure_ascii=False),
                                          encoding="utf-8")
            saida = pathlib.Path(tmp) / "saida"
            with contextlib.redirect_stdout(io.StringIO()):
                e2e.merge_parts(parte, saida, "2026-09-18T00:00:00Z")
            md = (saida / "e2e-latest.md").read_text(encoding="utf-8")
        self.assertNotIn("Servidor do Cliente", md)


if __name__ == "__main__":
    unittest.main()
