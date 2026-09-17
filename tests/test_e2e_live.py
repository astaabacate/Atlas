"""
Testes offline do harness de E2E (scripts/e2e_live.py).

Cobrem a maquinaria do harness: extração de corpo de função, mesclagem de relatórios,
contagem de status, guardas de propriedade e a fidelidade dos duplos de teste em relação
ao discord.py (é isso que faz a fase `spy` detectar "sucesso falso").
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _carregar_harness() -> object:
    spec = importlib.util.spec_from_file_location("e2e_live", ROOT / "scripts" / "e2e_live.py")
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    # o módulo precisa estar em sys.modules para o dataclass resolver as anotações (PEP 563)
    sys.modules["e2e_live"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


e2e = _carregar_harness()


class TestCorpoDeFuncao(unittest.TestCase):
    """A checagem de parâmetro declarado e ignorado depende de olhar só o corpo."""

    def test_extrai_corpo_sem_assinatura(self) -> None:
        async def op_exemplo(ctx, alvo: str, ignorado: str | None = None) -> str:
            return f"usei {alvo}"

        corpo = e2e.Harness._function_body(op_exemplo)
        self.assertIn("alvo", corpo)
        self.assertNotIn("ignorado", corpo)
        self.assertNotIn("def op_exemplo", corpo)

    def test_assinatura_multilinha(self) -> None:
        async def op_grande(
            ctx,
            primeiro: str,
            segundo: str | None = None,
        ) -> str:
            return primeiro

        corpo = e2e.Harness._function_body(op_grande)
        self.assertIn("primeiro", corpo)
        self.assertNotIn("segundo", corpo)
        self.assertNotIn("async def", corpo)


class TestDoblesDiscord(unittest.TestCase):
    """Os duplos precisam espelhar o discord.py, senão a fase spy mente."""

    def test_categoria_injeta_category_e_duplica_estoura(self) -> None:
        import asyncio

        guild = e2e.SpyGuild()
        categoria = asyncio.run(guild.create_category("cat"))
        with self.assertRaises(TypeError):
            # exatamente o que acontece em produção quando se passa category de novo
            asyncio.run(categoria.create_text_channel("x", category=categoria))

    def test_categoria_sem_repetir_category_funciona(self) -> None:
        import asyncio

        guild = e2e.SpyGuild()
        categoria = asyncio.run(guild.create_category("cat"))
        canal = asyncio.run(categoria.create_text_channel("x"))
        self.assertEqual(canal.category_id, categoria.id)
        self.assertIn("create_text_channel", guild.actions())

    def test_is_default_e_metodo_como_no_discord_py(self) -> None:
        papel = e2e.SpyRole("@everyone", is_default=True)
        self.assertTrue(papel.is_default())
        self.assertFalse(e2e.SpyRole("outro").is_default())

    def test_voz_dentro_de_categoria_tambem_estoura(self) -> None:
        import asyncio

        guild = e2e.SpyGuild()
        categoria = asyncio.run(guild.create_category("cat"))
        with self.assertRaises(TypeError):
            asyncio.run(categoria.create_voice_channel("voz", category=categoria))


class TestRelatorio(unittest.TestCase):
    def test_contagem_e_codigo_de_saida(self) -> None:
        rep = e2e.Reporter(["a"])
        rep.record("a", "ok", e2e.PASS, "")
        rep.record("a", "ruim", e2e.FAIL, "detalhe")
        rep.record("a", "aviso", e2e.WARN, "")
        rep.record("a", "pulada", e2e.SKIP, "")
        self.assertEqual(rep.counts(), {e2e.PASS: 1, e2e.FAIL: 1, e2e.WARN: 1, e2e.SKIP: 1})
        self.assertEqual(rep.exit_code(), 1)
        self.assertIn("❌ 1", rep.to_markdown())
        self.assertIn("detalhe", rep.to_markdown())

    def test_sem_falhas_zera_codigo(self) -> None:
        rep = e2e.Reporter(["a"])
        rep.record("a", "ok", e2e.PASS, "")
        self.assertEqual(rep.exit_code(), 0)

    def test_detalhe_com_pipe_nao_quebra_tabela(self) -> None:
        rep = e2e.Reporter(["a"])
        rep.record("a", "x", e2e.FAIL, "tem | pipe")
        self.assertIn("tem \\| pipe", rep.to_markdown())


class TestMerge(unittest.TestCase):
    def test_mescla_partes_e_grava_relatorio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            partes = Path(tmp) / "parts"
            partes.mkdir()
            (partes / "1.json").write_text(json.dumps({
                "started_at": "2026-01-01T00:00:00+00:00",
                "finished_at": "2026-01-01T00:01:00+00:00",
                "meta": {"fases": "static"},
                "notes": ["nota 1"],
                "phases": {"static": {"title": "t", "checks": [
                    {"phase": "static", "name": "a", "status": e2e.PASS, "detail": "", "ms": 1, "data": {}}]}},
            }), encoding="utf-8")
            (partes / "2.json").write_text(json.dumps({
                "started_at": "2026-01-01T00:02:00+00:00",
                "finished_at": "2026-01-01T00:03:00+00:00",
                "meta": {"mutações reais": "não"},
                "notes": ["nota 2"],
                "phases": {"spy": {"title": "s", "checks": [
                    {"phase": "spy", "name": "b", "status": e2e.FAIL, "detail": "quebrou", "ms": 2, "data": {}}]}},
            }), encoding="utf-8")

            saida = Path(tmp) / "out"
            codigo = e2e.merge_parts(partes, saida)

            self.assertEqual(codigo, 1)
            json_final = json.loads((saida / "e2e-latest.json").read_text(encoding="utf-8"))
            self.assertEqual(json_final["summary"][e2e.FAIL], 1)
            self.assertEqual(sorted(json_final["phases"]), ["spy", "static"])
            self.assertIn("nota 2", json_final["notes"])
            self.assertEqual(json_final["meta"]["mutações reais"], "não")
            self.assertIn("quebrou", (saida / "e2e-latest.md").read_text(encoding="utf-8"))

    def test_sem_partes_falha(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(e2e.merge_parts(Path(tmp) / "vazio", Path(tmp) / "out"), 1)


class TestGuardas(unittest.TestCase):
    def test_reporter_nao_duplica_checagem(self) -> None:
        rep = e2e.Reporter(["x"])
        rep.record("x", "nome", e2e.PASS)
        self.assertTrue(rep.had("x", "nome", e2e.PASS))
        self.assertFalse(rep.had("x", "nome", e2e.FAIL))

    def test_ownership_por_marca_e_por_nome_conhecido(self) -> None:
        harness = e2e.Harness.__new__(e2e.Harness)
        harness.owned_channels = set()
        harness.owned_roles = set()
        self.assertTrue(harness._is_ours(f"{e2e.TEMP_MARK}-teste"))
        self.assertTrue(harness._is_ours("Lobby 1", ["Lobby 1"]))
        self.assertFalse(harness._is_ours("geral"))

    def test_limpeza_so_apaga_o_que_foi_registrado(self) -> None:
        import asyncio

        class FakeCanal:
            def __init__(self, cid: int, nome: str) -> None:
                self.id, self.name, self.deletado = cid, nome, False

            async def delete(self) -> None:
                self.deletado = True

        class FakeGuilda:
            def __init__(self, canais: list[FakeCanal]) -> None:
                self.canais = canais

            def get_channel(self, cid: int) -> FakeCanal | None:
                return next((c for c in self.canais if c.id == cid), None)

            async def fetch_channel(self, cid: int) -> FakeCanal | None:
                return self.get_channel(cid)

            def get_role(self, rid: int) -> None:
                return None

            async def fetch_roles(self) -> list[object]:
                return []

        canal_nosso = FakeCanal(1, "nosso 🧪")
        canal_alheio = FakeCanal(999, "geral")  # não registrado: NÃO pode ser tocado
        harness = e2e.Harness.__new__(e2e.Harness)
        harness.owned_channels = {1}
        harness.owned_roles = set()
        harness.rep = e2e.Reporter(["mutate"])
        asyncio.run(harness._cleanup(FakeGuilda([canal_nosso, canal_alheio]), "mutate"))
        self.assertTrue(canal_nosso.deletado)
        self.assertFalse(canal_alheio.deletado)

    def test_phases_all(self) -> None:
        self.assertEqual(e2e.phases_list("all"), list(e2e.PHASE_ORDER))
        self.assertEqual(e2e.phases_list(" static , spy "), ["static", "spy"])

    def test_argumentos_padrao(self) -> None:
        args = e2e.parse_args([])
        self.assertFalse(args.mutate)
        self.assertFalse(args.allow_template)
        self.assertEqual(args.phases, "static,spy,policy")


class TestAnotacoes(unittest.TestCase):
    def test_annotations_de_falha(self) -> None:
        import contextlib
        import io

        rep = e2e.Reporter(["a"])
        rep.record("a", "ruim", e2e.FAIL, "linha\nquebrada")
        rep.record("a", "aviso", e2e.WARN, "cuidado")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rep.emit_annotations()
        saida = buffer.getvalue()
        self.assertIn("::error title=e2e a/ruim::linha quebrada", saida)
        self.assertIn("::warning title=e2e a/aviso::cuidado", saida)
        self.assertIn("::notice title=e2e resumo", saida)


class TestMetadados(unittest.TestCase):
    def test_relatorio_tem_comeco_fim_e_meta(self) -> None:
        rep = e2e.Reporter(["static"], {"fases": "static"})
        rep.started = datetime(2026, 1, 1, tzinfo=timezone.utc)
        dado = rep.to_dict()
        self.assertEqual(dado["meta"]["fases"], "static")
        self.assertTrue(dado["started_at"].startswith("2026-01-01"))
        self.assertIn("finished_at", dado)
        self.assertEqual(dado["phases"]["static"]["title"], e2e.PHASE_TITLES["static"])


if __name__ == "__main__":
    unittest.main()
