"""
Testes offline do harness de E2E (scripts/e2e_live.py).

Cobrem a maquinaria do harness: extração de corpo de função, mesclagem de relatórios,
contagem de status, guardas de propriedade e a fidelidade dos duplos de teste em relação
ao discord.py (é isso que faz a fase `spy` detectar "sucesso falso").
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


class TestDadosReaisCitados(unittest.TestCase):
    """O check "o agente conhece a estrutura" aceita o resumo REAL do servidor (server_info)."""

    def setUp(self) -> None:
        self.harness = _carregar_harness()

    def test_aceita_resumo_do_servidor_conferido_na_api(self) -> None:
        import asyncio

        class ServidorFalso:
            name = "Servidor-Teste"
            owner_id = 42

            async def fetch_channels(self) -> list[Any]:
                return [1]

            async def fetch_roles(self) -> list[Any]:
                return [1, 2, 3]

        resposta = ("📊 **Informações de Servidor-Teste:**\n• **ID:** `1`\n• **Dono:** <@42>\n"
                    "• **Membros:** 4\n• **Canais:** 1\n• **Cargos:** 3")
        confere = asyncio.run(self.harness.Harness._dados_reais_citados(ServidorFalso(), resposta))
        self.assertIn("canais=1", " ".join(confere))
        self.assertIn("cargos=3", " ".join(confere))
        self.assertTrue(any("Servidor-Teste" in c for c in confere), confere)

    def test_nao_aceita_contagem_errada_nem_invencao(self) -> None:
        import asyncio

        class ServidorFalso:
            name = "Servidor-Teste"
            owner_id = 42

            async def fetch_channels(self) -> list[Any]:
                return [1]

            async def fetch_roles(self) -> list[Any]:
                return [1, 2, 3]

        resposta = "Claro! O servidor tem 99 canais e 500 cargos, é bem grande."
        confere = asyncio.run(self.harness.Harness._dados_reais_citados(ServidorFalso(), resposta))
        self.assertEqual(confere, [], f"aceitou dados inventados: {confere}")


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


class TestSilenciarMensagensReais(unittest.TestCase):
    """O clone de teste não pode responder cliente real: o bot 24/7 usa o mesmo token."""

    def _bot_falso(self) -> Any:
        class BotFalso:
            def __init__(self) -> None:
                self.eventos: list[str] = []

            def dispatch(self, event: str, *args: Any, **kwargs: Any) -> None:
                self.eventos.append(event)

        return BotFalso()

    def test_ignora_message_mas_mantem_os_outros_eventos(self) -> None:
        bot = self._bot_falso()
        original = e2e.Harness.silenciar_mensagens_reais(bot)

        bot.dispatch("message", "mensagem de um cliente real")
        bot.dispatch("ready")
        bot.dispatch("message_delete", 123)

        self.assertEqual(bot.eventos, ["ready", "message_delete"])

        bot.dispatch = original
        bot.dispatch("message", "de novo")
        self.assertEqual(bot.eventos[-1], "message")


class TestClassificacaoLLM(unittest.TestCase):
    """Sem chave paga o provedor gratuito falha; o relatório precisa dizer que a culpa é do LLM."""

    def test_reconhece_falha_do_provedor(self) -> None:
        self.assertTrue(e2e.Harness._culpa_do_llm(
            "RuntimeError: Nenhum dos 2 provedores de LLM respondeu (kilo/tools, groq)"))
        self.assertTrue(e2e.Harness._culpa_do_llm("kilo: HTTP 429 — rate limit exceeded"))
        self.assertTrue(e2e.Harness._culpa_do_llm("Operações concluídas."))
        self.assertTrue(e2e.Harness._culpa_do_llm(
            "🤖 Os modelos gratuitos estão com a fila cheia agora (limite de uso). Tente de novo."))
        self.assertTrue(e2e.Harness._culpa_do_llm(
            "🤖 Não consegui falar com nenhum modelo de linguagem agora. Tente de novo em instantes."))
        self.assertTrue(e2e.Harness._culpa_do_llm(
            "✅ Fiz o que você pediu (create_channels), mas os modelos gratuitos ficaram instáveis "
            "agora e eu não consegui escrever o resumo."))
        self.assertTrue(e2e.Harness._culpa_do_llm("Operação concluída com sucesso."))

    def test_nao_confunde_bug_do_bot_com_llm(self) -> None:
        self.assertFalse(e2e.Harness._culpa_do_llm("Canal #🧪-efemero excluído com sucesso."))
        self.assertFalse(e2e.Harness._culpa_do_llm(""))
        self.assertFalse(e2e.Harness._culpa_do_llm("O cargo 'x' está acima do meu cargo mais alto."))

    def test_llm_nao_chamou_distingue_modelo_de_bot(self) -> None:
        registro = [
            {"ferramentas_chamadas": ["list_roles"], "chars": 40, "vencedor": "kilo"},
            {"ferramentas_chamadas": [], "chars": 12, "vencedor": "groq"},
        ]
        self.assertTrue(e2e.Harness.llm_nao_chamou(registro, "delete_channels"))
        self.assertFalse(e2e.Harness.llm_nao_chamou(registro, "list_roles"))
        self.assertTrue(e2e.Harness.llm_nao_chamou([], "delete_channels"))

    def test_registro_do_llm_anota_as_chamadas(self) -> None:
        import asyncio

        from llm.base import LLMResponse, ToolCall

        class Fake:
            last_winner = "kilo"

            async def chat(self, messages, tools=None, timeout=60.0, max_tokens=1024):
                return LLMResponse(content="ok", tool_calls=[ToolCall(id="1", name="create_channels", args={})])

            def describe(self):
                return "fake"

            async def close(self):
                return None

        registro: list[dict] = []
        espiao = e2e.LLMRegistro(Fake(), registro)
        asyncio.run(espiao.chat([{"role": "user", "content": "oi"}]))
        self.assertEqual(registro[0]["ferramentas_chamadas"], ["create_channels"])
        self.assertEqual(registro[0]["vencedor"], "kilo")
        self.assertEqual(espiao.describe(), "fake")

    def test_checagem_que_ja_registrou_warn_nao_vira_pass(self) -> None:
        """Sem isso o relatório mostrava a mesma checagem duas vezes (WARN + PASS)."""
        import asyncio

        rep = e2e.Reporter(["mutate"])
        h = object.__new__(e2e.Harness)
        h.rep = rep

        async def nao_conclusiva() -> str:
            return h.degradar_llm("mutate", "agente apaga canal", "não apagou", "Operações concluídas.")

        asyncio.run(h.check("mutate", "agente apaga canal", nao_conclusiva))
        self.assertEqual(len(rep.phases["mutate"]), 1)
        self.assertEqual(rep.phases["mutate"][0].status, e2e.WARN)

        async def normal() -> str:
            return "tudo certo"

        asyncio.run(h.check("mutate", "outra checagem", normal))
        self.assertEqual([c.status for c in rep.phases["mutate"]], [e2e.WARN, e2e.PASS])

    def test_degradar_llm_vira_warn_no_relatorio(self) -> None:
        rep = e2e.Reporter(["mutate"])
        h = object.__new__(e2e.Harness)
        h.rep = rep
        texto = h.degradar_llm("mutate", "agente apaga canal", "não apagou", "Operações concluídas.")
        self.assertIn("não conclusivo", texto)
        registro = rep.phases["mutate"][0]
        self.assertEqual(registro.status, e2e.WARN)
        self.assertIn("provedor gratuito", registro.detail)
        self.assertEqual(rep.counts()[e2e.FAIL], 0)


class TestCoberturaDasFerramentas(unittest.TestCase):
    """A execução tem que dizer o que NÃO testou — lacuna invisível vira ✅ de fachada."""

    def _fonte(self) -> str:
        return (ROOT / "scripts" / "e2e_live.py").read_text(encoding="utf-8")

    def test_o_contador_pega_todas_as_fases(self) -> None:
        fonte = self._fonte()
        self.assertIn("executors.execute_tool = contando", fonte,
                      "o contador tem que entrar no MÓDULO: cada fase importa execute_tool dentro")
        self.assertIn("self._contar_ferramentas()", fonte)
        self.assertIn("usadas[nome] = usadas.get(nome, 0) + 1", fonte)

    def test_a_execucao_fecha_com_o_que_ficou_de_fora(self) -> None:
        fonte = self._fonte()
        self.assertIn("await self._registrar_cobertura()", fonte,
                      "sem isso o relatório termina sem dizer o que não foi exercitado")
        self.assertIn("não exercitadas:", fonte)
        self.assertIn("from brain.tools import tool_names", fonte,
                      "a comparação é com o conjunto real de ferramentas")
        self.assertIn('"cobertura":', fonte, "a fase nova tem título próprio no relatório")

    def test_o_contador_de_verdade_conta(self) -> None:
        """Liga o contador do harness e confere que a ferramenta executada entra na conta."""
        import asyncio
        from types import SimpleNamespace

        from brain import executors

        harness = e2e.Harness(e2e.parse_args(["--phases", "static"]), e2e.Reporter(["static"]))
        harness._contar_ferramentas()
        try:
            async def chamada() -> None:
                with contextlib.suppress(Exception):
                    # contexto incompleto de propósito: o contador anota ANTES da execução
                    await executors.execute_tool("delete_channels", {"channels": []},
                                                 SimpleNamespace(actor=None))

            asyncio.run(chamada())
        finally:
            executors.execute_tool = harness._execute_tool_original
        self.assertEqual(harness.usadas.get("delete_channels"), 1,
                         "a ferramenta executada pelo módulo tem que aparecer no contador")



class TestHierarquiaMedidaNaAPI(unittest.TestCase):
    """
    Regressão do bug que a matriz acusou por 3 rodadas: o harness (e o produto) mediam a
    hierarquia pelo cache do discord.py, que devolve @everyone (posição 0) quando o cache de
    cargos do servidor está vazio — e aí "todo cargo parece acima do bot".
    """

    def test_helper_acha_a_posicao_real_com_cache_quebrado(self) -> None:
        import asyncio
        import types

        modulo = _carregar_harness()

        class Cargo:
            def __init__(self, cid: int, pos: int) -> None:
                self.id, self.position = cid, pos

        servidor = types.SimpleNamespace()
        servidor.me = types.SimpleNamespace(
            top_role=types.SimpleNamespace(id=1, position=0, is_default=lambda: True),
            roles=[],  # cache de cargos vazio: discord.py descarta os cargos do membro
            _roles={999},
        )

        async def fetch_roles() -> list[Any]:
            return [Cargo(1, 0), Cargo(999, 7), Cargo(500, 3)]

        servidor.fetch_roles = fetch_roles
        self.assertEqual(asyncio.run(modulo.posicao_do_topo_do_bot(servidor)), 7)

    def test_helper_prefere_a_api_quando_os_cargos_resolvem(self) -> None:
        import asyncio
        import types

        modulo = _carregar_harness()

        class Cargo:
            def __init__(self, cid: int, pos: int) -> None:
                self.id, self.position = cid, pos

        servidor = types.SimpleNamespace()
        servidor.me = types.SimpleNamespace(top_role=Cargo(999, 2), roles=[Cargo(999, 2)],
                                            _roles={999})

        async def fetch_roles() -> list[Any]:
            return [Cargo(999, 9)]  # a API diz outra coisa: a API manda

        servidor.fetch_roles = fetch_roles
        self.assertEqual(asyncio.run(modulo.posicao_do_topo_do_bot(servidor)), 9)

    def test_sem_api_cai_no_cache_sem_explodir(self) -> None:
        import asyncio
        import types

        modulo = _carregar_harness()
        servidor = types.SimpleNamespace()
        servidor.me = types.SimpleNamespace(
            top_role=types.SimpleNamespace(id=1, position=0, is_default=lambda: True), roles=[])

        async def fetch_roles() -> list[Any]:
            raise RuntimeError("sem rede")

        servidor.fetch_roles = fetch_roles
        self.assertEqual(asyncio.run(modulo.posicao_do_topo_do_bot(servidor)), 0)


class TestFaseCapsNaoSeEngana(unittest.TestCase):
    """Guardas de leitura do fonte: o harness não pode voltar a medir pelo cache."""

    def _fonte(self) -> str:
        return (ROOT / "scripts" / "e2e_live.py").read_text(encoding="utf-8")

    def test_caps_nao_usa_top_role_do_cache(self) -> None:
        fonte = self._fonte()
        inicio = fonte.index("async def phase_caps")
        fim = fonte.index("async def phase_botloop")
        trecho = fonte[inicio:fim]
        self.assertNotIn("guild.me.top_role.position", trecho,
                         "a matriz voltou a medir a hierarquia pelo cache do discord.py")
        self.assertIn("posicao_do_topo_do_bot", trecho)

    def test_captura_de_novos_aceita_cargos(self) -> None:
        fonte = self._fonte()
        self.assertIn("incluir_cargos: bool = False", fonte)
        self.assertIn("incluir_cargos=True", fonte,
                      "as verificações de cargo precisam pedir os cargos ao _capture_new")

    def test_cargo_que_nao_nasce_vira_aviso_nao_cascata(self) -> None:
        fonte = self._fonte()
        self.assertIn("aviso_de_hierarquia", fonte)
        self.assertIn("culpa_do_discord", fonte,
                      "5xx do Discord não pode ser ❌ do produto")


class TestGuardaDeTempoDasFases(unittest.TestCase):
    """
    Uma fase travada tem que ser interrompida — com o "onde" no relatório.

    Aconteceu ao vivo (execução 35387325952): a fase de mutações ficou 20+ minutos presa numa
    chamada e a execução inteira morreu no teto do job, levando as evidências embora.
    """

    def _fases_com_handler(self) -> set[str]:
        return {nome[len("phase_"):] for nome in dir(e2e.Harness) if nome.startswith("phase_")}

    def test_toda_fase_tem_limite_proprio(self) -> None:
        faltando = self._fases_com_handler() - set(e2e.LIMITE_DA_FASE)
        self.assertEqual(faltando, set(), "fase sem limite de tempo na tabela")

    def test_fase_e_rodada_com_wait_for_e_interrupcao_registrada(self) -> None:
        fonte = (ROOT / "scripts" / "e2e_live.py").read_text(encoding="utf-8")
        self.assertIn("asyncio.wait_for(handler(), timeout=limite)", fonte)
        self.assertIn("except asyncio.TimeoutError", fonte)
        self.assertIn("fase interrompida por tempo", fonte,
                      "sem registro, uma fase travada desaparece do relatório")

    def test_diz_onde_a_fase_estava_pendurada(self) -> None:
        import asyncio

        async def cenario() -> str:
            async def travada() -> None:
                await asyncio.sleep(30)  # simula a chamada que não volta

            tarefa = asyncio.create_task(travada())
            await asyncio.sleep(0.05)  # deixa a tarefa entrar no sleep
            try:
                return e2e.Harness._onde_esta_pendurado()
            finally:
                tarefa.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await tarefa

        onde = asyncio.run(cenario())
        self.assertIn("test_e2e_live.py:", onde, f"a pilha não aponta o ponto: {onde!r}")

    def test_limite_pode_ser_forcado_pela_linha_de_comando(self) -> None:
        args = e2e.parse_args(["--phases", "static", "--phase-timeout", "42"])
        self.assertEqual(args.phase_timeout, 42.0)


if __name__ == "__main__":
    unittest.main()
