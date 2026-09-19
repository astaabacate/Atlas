"""
Testes dos workflows do GitHub Actions.

Eles existem por causa de dois erros que custaram execução AO VIVO hoje (18/09):

1. Uma edição de indentação em `.github/workflows/bot.yml` deixou o arquivo com YAML INVÁLIDO.
   O GitHub não roda nada: cada push criava a run com **zero jobs** e "This run likely failed
   because of a workflow file issue" — o bot simplesmente não subia com o código novo.
2. O passo que publicava `reports/cor-do-avatar.txt` vinha ANTES do passo que mede a cor: o
   arquivo não existia ainda, o passo terminava "success" e nada era publicado.

Um teste de unidade barato pega os dois: parsear o YAML de todo workflow e conferir a ORDEM
dos passos que geram e publicam.
"""

from __future__ import annotations

import pathlib
import re
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import yaml  # noqa: E402

RAIZ = pathlib.Path(__file__).resolve().parents[1]
WORKFLOWS = RAIZ / ".github" / "workflows"
NOME_DE_VARIAVEL = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _carregar(nome: str) -> dict:
    caminho = WORKFLOWS / nome
    return yaml.safe_load(caminho.read_text(encoding="utf-8"))


def _passos(documento: dict) -> list[dict]:
    passos: list[dict] = []
    for trabalho in documento["jobs"].values():
        passos.extend(trabalho.get("steps") or [])
    return passos


def _indice_do_passo(documento: dict, trecho: str) -> int:
    for i, passo in enumerate(_passos(documento)):
        if trecho in str(passo.get("name", "")):
            return i
    raise AssertionError(f"nenhum passo com {trecho!r}")


class TestWorkflowsSaoValidos(unittest.TestCase):
    def test_ha_workflows(self) -> None:
        self.assertTrue(list(WORKFLOWS.glob("*.yml")), "não achei workflow nenhum")

    def test_todos_os_workflows_sao_yaml_valido_com_passos(self) -> None:
        """YAML inválido = run com 0 jobs: nenhuma edição pode quebrar o arquivo."""
        for caminho in sorted(WORKFLOWS.glob("*.yml")):
            with self.subTest(workflow=caminho.name):
                try:
                    documento = yaml.safe_load(caminho.read_text(encoding="utf-8"))
                except yaml.YAMLError as exc:  # pragma: no cover - falha esperada é reportada
                    self.fail(f"{caminho.name} não é YAML válido: {exc}")
                self.assertIsInstance(documento, dict, f"{caminho.name} vazio")
                self.assertIn("jobs", documento, f"{caminho.name} sem jobs")
                self.assertTrue(_passos(documento), f"{caminho.name} sem passos")

    def test_todo_passo_tem_nome(self) -> None:
        for caminho in sorted(WORKFLOWS.glob("*.yml")):
            for passo in _passos(yaml.safe_load(caminho.read_text(encoding="utf-8"))):
                self.assertTrue(passo.get("name"), f"{caminho.name}: passo sem nome")


class TestBotWorkflow(unittest.TestCase):
    """O bot só sobe com este arquivo sano — e com o env que o config.py lê."""

    def setUp(self) -> None:
        self.documento = _carregar("bot.yml")

    def test_passo_que_executa_o_bot_existe(self) -> None:
        self.assertEqual(self.documento["jobs"]["run"]["steps"][-2]["name"], "Executar bot")

    def test_env_do_bot_tem_as_variaveis_da_cara_nova(self) -> None:
        env = self.documento["jobs"]["run"]["steps"][-2]["env"]
        self.assertIn("ACCENT_COLOR", env)
        self.assertIn("MENSAGEM_V2", env)
        self.assertIn("DISCORD_TOKEN", env)

    def test_env_so_tem_nome_de_variavel(self) -> None:
        """Uma linha de texto solta dentro do env (indentação errada) quebraria o envio."""
        env = self.documento["jobs"]["run"]["steps"][-2]["env"]
        for chave, valor in env.items():
            self.assertRegex(chave, NOME_DE_VARIAVEL, f"chave estranha no env: {chave!r}")
            self.assertIsInstance(valor, str, f"{chave} não é texto")

    def test_vigia_do_bot_sobe_o_bot_quando_nao_ha_nenhum(self) -> None:
        """O vigia é quem garante o "24/7": consulta as execuções do bot e dispara se faltar."""
        documento = _carregar("bot-watchdog.yml")
        comandos = " ".join(str(p.get("run", "")) for p in _passos(documento))
        self.assertIn("gh run list --workflow bot.yml", comandos)
        self.assertIn("gh workflow run bot.yml", comandos)
        self.assertEqual(documento["permissions"].get("actions"), "write",
                         "sem actions: write o vigia não consegue acordar o bot")


class TestVigiaDoE2E(unittest.TestCase):
    """Execução do E2E travada não pode bloquear a fila — e o vigia não pode tocar no bot."""

    def setUp(self) -> None:
        self.documento = _carregar("vigia-e2e.yml")

    def test_pode_cancelar_execucoes(self) -> None:
        self.assertEqual(self.documento["permissions"].get("actions"), "write",
                         "sem actions: write o vigia não consegue derrubar a execução presa")

    def test_so_mexe_no_e2e(self) -> None:
        comandos = " ".join(str(p.get("run", "")) for p in _passos(self.documento))
        self.assertIn("--workflow=e2e.yml", comandos)
        self.assertNotIn("bot.yml", comandos, "o bot 24/7 é produção: só o dono derruba a fatia")
        self.assertEqual(comandos.count("gh run cancel"), 1, "um único ponto de cancelamento")
        self.assertIn('gh run cancel "$id"', comandos,
                      "o cancelamento tem que ser do id que veio da listagem")

    def test_limites_e_aviso_ao_dono(self) -> None:
        documento = self.documento["jobs"]["vigia"]
        self.assertIn("LIMITE_DO_PASSO_MIN", documento["env"])
        self.assertIn("LIMITE_DA_EXECUCAO_MIN", documento["env"])
        comandos = " ".join(str(p.get("run", "")) for p in _passos(self.documento))
        self.assertIn("::warning title=vigia e2e::", comandos,
                      "derrubar uma execução tem que aparecer no resumo do Actions")
        self.assertIn("in_progress", comandos, "o vigia olha o passo que ESTÁ rodando")


class TestSondaPublicaDepoisDeMedir(unittest.TestCase):
    def setUp(self) -> None:
        self.documento = _carregar("sonda-hierarquia.yml")

    def test_publicar_vem_depois_da_sonda(self) -> None:
        self.assertLess(_indice_do_passo(self.documento, "Rodar a sonda"),
                        _indice_do_passo(self.documento, "Publicar o resultado"),
                        "publicar antes de gerar termina em 'success' e arquivo nenhum")

    def test_publicar_inclui_a_cor_do_avatar(self) -> None:
        passos = _passos(self.documento)
        publicacao = str(passos[_indice_do_passo(self.documento, "Publicar o resultado")]["run"])
        for arquivo in ("reports/cor-do-avatar.txt",
                        "reports/sonda-hierarquia.md",
                        "reports/sonda-hierarquia.json"):
            self.assertIn(arquivo, publicacao, f"{arquivo} não é publicado")

    def test_sonda_roda_com_o_python_do_repositorio(self) -> None:
        passos = _passos(self.documento)
        comando = str(passos[_indice_do_passo(self.documento, "Rodar a sonda")]["run"])
        self.assertIn("scripts/sonda_hierarquia.py", comando)
        self.assertIn("--outdir reports", comando)


class TestE2EWorkflow(unittest.TestCase):
    FASES = ("static,spy,policy", "connect,audit", "tools", "agent", "mutate", "caps", "botloop",
             "sweep")

    def setUp(self) -> None:
        self.documento = _carregar("e2e.yml")

    def test_e2e_ao_vivo_leva_a_cara_nova(self) -> None:
        env = self.documento["jobs"]["e2e"]["env"]
        self.assertIn("ACCENT_COLOR", env, "o e2e ao vivo também responde em Components V2")
        self.assertIn("MENSAGEM_V2", env)
        self.assertIn("DISCORD_TOKEN", env)

    def test_e2e_roda_todas_as_fases(self) -> None:
        comandos = " ".join(str(p.get("run", "")) for p in _passos(self.documento))
        for fase in self.FASES:
            self.assertIn(f"--phases {fase}", comandos, f"fase {fase} não roda")

    def test_mutacoes_so_com_autorizacao_e_sem_derrubar_o_relatorio(self) -> None:
        """As fases que mexem no servidor real exigem o interruptor E2E_MUTATIONS."""
        for passo in _passos(self.documento):
            comando = str(passo.get("run", ""))
            if "--phases mutate" in comando or "--phases caps" in comando:
                with self.subTest(passo=passo.get("name")):
                    self.assertIn("steps.modo.outputs.autorizado == 'true'", str(passo.get("if")))
                    self.assertTrue(passo.get("continue-on-error"),
                                    "uma falha de teste não pode esconder o relatório")

    def test_relatorio_e_publicado_depois_de_todas_as_fases(self) -> None:
        passos = _passos(self.documento)
        self.assertIn("Consolidar relatório", str(passos[-1]["name"]))
        self.assertIn("reports/e2e-latest.md", str(passos[-1]["run"]))
        self.assertIn("exit $MERGE_STATUS", str(passos[-1]["run"]),
                      "a run termina refletindo o resultado dos testes")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
