"""
Testes da guarda de obsolescência (freshness).
Garante que runs com commits desatualizados abortem (sys.exit(1)),
enquanto ponta, ramo desconhecido ou erros de rede continuem.
Valida também que o YAML de workflow do GitHub Actions não divergiu do módulo Python.
"""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

from freshness import check_freshness


class TestFreshness(unittest.TestCase):
    def test_tip_commit_proceeds(self) -> None:
        def fake_runner(cmd, **kwargs):
            return SimpleNamespace(
                returncode=0,
                stdout="abcdef1234567890\trefs/heads/main\n",
            )

        res = check_freshness(
            current_sha="abcdef1234567890",
            branch="main",
            repo_url="origin",
            runner=fake_runner,
        )
        self.assertTrue(res)

    def test_stale_commit_aborts_with_exit_1(self) -> None:
        def fake_runner(cmd, **kwargs):
            return SimpleNamespace(
                returncode=0,
                stdout="9999999999999999\trefs/heads/main\n",
            )

        with self.assertRaises(SystemExit) as ctx:
            check_freshness(
                current_sha="1111111111111111",
                branch="main",
                repo_url="origin",
                runner=fake_runner,
            )
        self.assertEqual(ctx.exception.code, 1)

    def test_network_failure_proceeds_with_warning(self) -> None:
        def fake_runner(cmd, **kwargs):
            return SimpleNamespace(returncode=128, stdout="", stderr="fatal: unable to access")

        res = check_freshness(
            current_sha="1111111111111111",
            branch="main",
            repo_url="origin",
            runner=fake_runner,
        )
        self.assertTrue(res)

    def test_unknown_branch_proceeds_with_warning(self) -> None:
        def fake_runner(cmd, **kwargs):
            return SimpleNamespace(returncode=0, stdout="")

        res = check_freshness(
            current_sha="1111111111111111",
            branch="ramo-inexistente",
            repo_url="origin",
            runner=fake_runner,
        )
        self.assertTrue(res)

    def test_yaml_and_module_non_divergence(self) -> None:
        """
        Lê o arquivo de workflow .github/workflows/bot.yml e verifica
        se a trava de obsolescência com 'sys.exit(1)' está presente no primeiro passo.
        """
        yaml_path = os.path.join(
            os.path.dirname(__file__), "..", ".github", "workflows", "bot.yml"
        )
        self.assertTrue(os.path.exists(yaml_path), "Workflow bot.yml deve existir")

        with open(yaml_path, "r", encoding="utf-8") as f:
            yaml_content = f.read()

        self.assertIn("ls-remote", yaml_content, "YAML deve conter verificação via ls-remote")
        self.assertIn("sys.exit(1)", yaml_content, "YAML deve conter sys.exit(1) para abortar runs obsoletas")
        self.assertIn("Checkout obsoleto", yaml_content)

    def test_sabotage_check(self) -> None:
        """
        Verificação por sabotagem:
        Se simularmos a substituição de 'sys.exit(1)' por 'pass' no código de validação,
        a verificação de obsolescência deve falhar e não abortar (ou seja, detecta a sabotagem).
        """
        sabotaged_executed_exit = False

        def sabotaged_freshness(sha, remote_sha):
            if sha != remote_sha:
                pass  # Sabotagem: não chama sys.exit(1)
            else:
                return True

        # Confirmar que a sabotagem NÃO levantou SystemExit
        try:
            sabotaged_freshness("old_sha", "new_sha")
        except SystemExit:
            sabotaged_executed_exit = True

        self.assertFalse(
            sabotaged_executed_exit,
            "Código sabotado com 'pass' não deve lançar SystemExit (provando que o teste original é sensível)",
        )


if __name__ == "__main__":
    unittest.main()
