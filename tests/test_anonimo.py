"""
Testes do disfarce dos relatórios (core/anonimo.py).

O repositório é público: nome de servidor, ID, canal, cargo e link de mensagem de um cliente
não podem sair em relatório nem em log do Actions.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from core.anonimo import Anonimizador  # noqa: E402


class TestMascaraDeDados(unittest.TestCase):
    def setUp(self) -> None:
        self.anon = Anonimizador()

    def test_id_de_servidor_some(self) -> None:
        self.assertEqual(self.anon.mascarar("servidor 1546763083005825084 pronto"),
                         "servidor <id> pronto")

    def test_numero_curto_nao_e_confundido_com_id(self) -> None:
        texto = "apaguei 3 canais, o cargo ficou na posição 27 e o limite é 150015 chars"
        self.assertEqual(self.anon.mascarar(texto), texto)

    def test_mencoes_viram_rotulo(self) -> None:
        self.assertEqual(self.anon.mascarar("mandei em <#1550640448442212453> e marquei <@&153>"),
                         "mandei em <#canal> e marquei <@&cargo>")
        self.assertEqual(self.anon.mascarar("o dono é <@1521612392105250836>"),
                         "o dono é <@pessoa>")

    def test_link_de_mensagem_some(self) -> None:
        self.assertEqual(
            self.anon.mascarar("https://discord.com/channels/1546763083005825084/1550640448442212453/1550651829866733669"),
            "https://discord.com/channels/<servidor>/<canal>/<mensagem>")

    def test_nome_de_servidor_ganha_apelido_estavel(self) -> None:
        self.anon.registrar("Servidor do Cliente", "servidor")
        self.assertIn("Servidor-1", self.anon.mascarar("Informações de Servidor do Cliente:"))
        self.assertIn("Servidor-1", self.anon.mascarar("Servidor do Cliente de novo"),
                      "o mesmo nome recebe sempre o mesmo apelido")

    def test_dois_servidores_diferentes_tem_apelidos_diferentes(self) -> None:
        self.anon.registrar_varios(["Servidor do Cliente", "Outro Servidor"], "servidor")
        self.assertEqual(self.anon.mascarar("Servidor do Cliente"), "Servidor-1")
        self.assertEqual(self.anon.mascarar("Outro Servidor"), "Servidor-2")

    def test_nome_de_canal_e_de_cargo_somem(self) -> None:
        self.anon.registrar_varios(["atlas-oi-da-ia"], "canal")
        self.anon.registrar_varios(["Cupido", "iTinder"], "cargo")
        saida = self.anon.mascarar("criei atlas-oi-da-ia com os cargos Cupido e iTinder")
        self.assertNotIn("atlas-oi-da-ia", saida)
        self.assertNotIn("Cupido", saida)
        self.assertNotIn("iTinder", saida)

    def test_nome_curto_nao_e_mascarado(self) -> None:
        # Mascarar nome de 1-2 letras destruiria o texto inteiro.
        self.anon.registrar("a", "canal")
        self.assertEqual(self.anon.mascarar("apaguei a mensagem"), "apaguei a mensagem")

    def test_nome_vazio_ou_none_nao_quebra(self) -> None:
        self.anon.registrar(None, "canal")
        self.anon.registrar("   ", "canal")
        self.assertEqual(self.anon.mascarar("nada a esconder"), "nada a esconder")

    def test_nao_levanta_com_entrada_estranha(self) -> None:
        class Explode:
            def __str__(self) -> str:
                raise RuntimeError("de propósito")

        self.assertEqual(self.anon.mascarar(Explode()), "")
        self.assertEqual(self.anon.mascarar(None), "")
        self.assertEqual(self.anon.mascarar(123), "123")

    def test_mascara_estrutura_do_json(self) -> None:
        self.anon.registrar("Servidor do Cliente", "servidor")
        dados = {"meta": {"servidor": "Servidor do Cliente"}, "checks": [
            {"detail": "1: Servidor do Cliente (1546763083005825084)", "ms": 12, "ok": True}]}
        saida = self.anon.mascarar_estrutura(dados)
        self.assertEqual(saida["meta"]["servidor"], "Servidor-1")
        self.assertEqual(saida["checks"][0]["detail"], "1: Servidor-1 (<id>)")
        self.assertEqual(saida["checks"][0]["ms"], 12, "número continua número")
        self.assertIs(saida["checks"][0]["ok"], True)


if __name__ == "__main__":
    unittest.main()
