"""
Testes do teste do OmniRoute — com um servidor falso no lugar da API (nada sai para a internet).

O que importa aqui: o script tem que dizer a VERDADE sobre o que o gateway respondeu (inclusive
quando ele responde sem chamar ferramenta) e nunca deixar a chave aparecer no relatório.
"""

from __future__ import annotations

import json
import pathlib
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from scripts.testar_omniroute import main  # noqa: E402

CHAVE = "chave-de-teste-nao-vaza"


def _servidor(comportamento: dict) -> tuple[ThreadingHTTPServer, str]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # silêncio no teste
            pass

        def _responder(self, status: int, corpo: dict) -> None:
            dados = json.dumps(corpo).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)

        def do_GET(self):  # noqa: N802 - API do http.server
            if comportamento.get("models_status", 200) != 200:
                self._responder(comportamento["models_status"], {"erro": "sem permissão"})
                return
            self._responder(200, {"data": [{"id": "auto"}, {"id": "kr/claude"}]})

        def do_POST(self):  # noqa: N802
            tamanho = int(self.headers.get("Content-Length", 0))
            pedido = json.loads(self.rfile.read(tamanho) or b"{}")
            if comportamento.get("chat_status", 200) != 200:
                self._responder(comportamento["chat_status"], {"erro": "limite atingido"})
                return
            tem_tools = bool(pedido.get("tools"))
            mensagem: dict = {"content": "ok", "role": "assistant"}
            if tem_tools and comportamento.get("chama_ferramenta", True):
                mensagem = {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "1", "type": "function",
                     "function": {"name": "criar_canal", "arguments": '{"nome":"teste"}'}}]}
            self._responder(200, {"model": "auto", "choices": [{"message": mensagem}]})

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return servidor, f"http://127.0.0.1:{servidor.server_address[1]}/v1"


class TestTestarOmniRoute(unittest.TestCase):
    def setUp(self) -> None:
        self.destino = pathlib.Path("/tmp/omniroute-teste")
        self.destino.mkdir(parents=True, exist_ok=True)

    def _rodar(self, base: str) -> int:
        import os

        os.environ["OMNIROUTE_API_KEY"] = CHAVE
        try:
            return main(["--base-url", base, "--outdir", str(self.destino), "--timeout", "5"])
        finally:
            del os.environ["OMNIROUTE_API_KEY"]

    def test_gateway_bom_passa_em_tudo(self) -> None:
        servidor, base = _servidor({})
        try:
            codigo = self._rodar(base)
        finally:
            servidor.shutdown()
        self.assertEqual(codigo, 0)
        md = (self.destino / "omniroute-latest.md").read_text(encoding="utf-8")
        self.assertIn("lista de modelos", md)
        self.assertIn("function calling", md)
        self.assertIn("✅", md)

    def test_gateway_que_nao_chama_ferramenta_e_reprovado(self) -> None:
        servidor, base = _servidor({"chama_ferramenta": False})
        try:
            codigo = self._rodar(base)
        finally:
            servidor.shutdown()
        self.assertEqual(codigo, 1, "sem function calling o bot não consegue agir: é falha")
        md = (self.destino / "omniroute-latest.md").read_text(encoding="utf-8")
        self.assertIn("sem chamar ferramenta", md)

    def test_chave_recusada_para_na_primeira_checagem(self) -> None:
        servidor, base = _servidor({"models_status": 401})
        try:
            codigo = self._rodar(base)
        finally:
            servidor.shutdown()
        self.assertEqual(codigo, 1)
        md = (self.destino / "omniroute-latest.md").read_text(encoding="utf-8")
        self.assertIn("HTTP 401", md)
        self.assertNotIn("function calling", md, "sem porta aberta não se testa o resto")

    def test_relatorio_esconde_a_chave_e_o_endereco(self) -> None:
        servidor, base = _servidor({})
        try:
            self._rodar(base)
        finally:
            servidor.shutdown()
        md = (self.destino / "omniroute-latest.md").read_text(encoding="utf-8")
        self.assertNotIn(CHAVE, md)
        self.assertNotIn("127.0.0.1", md)
        self.assertIn("://HOST", md)

    def test_sem_configuracao_avisa_e_nao_testa(self) -> None:
        import os

        for var in ("OMNIROUTE_API_KEY", "OMNIROUTE_BASE_URL"):
            os.environ.pop(var, None)
        codigo = main(["--outdir", str(self.destino)])
        self.assertEqual(codigo, 3, "sem endereço/chave o código é 'não configurado'")


if __name__ == "__main__":
    unittest.main()
