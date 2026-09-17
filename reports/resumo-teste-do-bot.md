# 🏮 Farol — resumo do teste ao vivo do bot

Pedido: *"se conecte ao bot e teste as coisas dele"*.
Resultado: o bot foi testado **de verdade** no servidor `asta`, 5 bugs foram encontrados (3 deles
só apareceram quando as mutações reais foram autorizadas) e todos foram corrigidos com prova
registrada. O PR #4 segue **aberto** — o merge é manual.

## Como o teste roda

O ambiente de desenvolvimento não tem rota para `discord.com` nem para os provedores de LLM, então
os testes ao vivo rodam no **GitHub Actions** (workflow *E2E ao vivo do Farol*), onde o
`DISCORD_TOKEN` está nos secrets do repositório. Cada execução publica o relatório completo no
próprio branch (`reports/e2e-latest.json` e `.md`) e comenta no PR.

São 10 fases: `static`, `spy`, `policy` (offline, sem rede) · `connect`, `audit`, `tools`, `agent`
(leitura no servidor real) · `mutate`, `botloop`, `sweep` (criam e apagam objetos de teste).

Tudo que as fases destrutivas criam fica marcado com 🧪, é registrado por diferença de estado na API
do Discord e removido no fim (a fase `sweep` limpa o que sobrar). Nome/ícone do servidor **não** são
tocados.

## Evolução das execuções

| Execução | Resultado | O que mudou |
| --- | --- | --- |
| 35277780929 | ✅ 49 · ❌ 4 · ⚠️ 2 | primeira suíte completa (só leitura): os 4 FAILs eram os bugs reais |
| 35277915862 · 35278183016 | ✅ 49 · ❌ 4 · ⚠️ 2 | isolamento de memória do agente, metadados e interruptor de mutação |
| 35279295683 | ✅ 72 · ❌ 5 · ⚠️ 1 | **1ª execução com mutações reais** — provou os bugs 1 e 3 no servidor |
| 35280087191 | ✅ 73 · ❌ 5 · ⚠️ 2 | `set_icon`/`show_permissions.target` corrigidos; +bug 4 (auto-confirmação) |
| 35281262866 | ✅ 77 · ❌ 1 · ⚠️ 5 | `apply_template` provado no servidor; bug 5 (pergunta de confirmação) |
| 35282123546 | ✅ 75 · ❌ 3 · ⚠️ 4 | relatório passou a distinguir "LLM fraco" de "bug do bot" |
| **35283256079** | **✅ 78 · ❌ 0 · ⚠️ 7 · ⏭️ 1** | execução verde (commit `b0e70a7`) |

## Bugs encontrados e corrigidos

1. **Canais dentro de categoria quebravam** — `create_channels`, `apply_template` e
   `import_structure` estouravam `TypeError: got multiple values for keyword argument 'category'`
   (no discord.py o método da categoria já injeta `category=self`). Corrigido com o helper
   `_create_guild_channel`; provado no servidor real: canais criados dentro da categoria existente e
   template `estudos` com 3 categorias + 6 canais dentro delas + cargos.
2. **`set_icon` mentia** — respondia "sucesso" sem chamar `guild.edit`. Agora baixa a imagem
   (limite de 8 MB, checagem de content-type), aceita data URI ou gera PNG do `style` e envia os
   bytes em `guild.edit(icon=...)`; se o download falhar, o erro é honesto.
3. **`show_permissions.target` era ignorado** — agora filtra cargo/membro, mostra allow/deny legíveis
   e busca o membro na API quando o cache está vazio (intent de membros desligada).
4. **O agente se auto-confirmava** (achado na 1ª execução com mutações reais) — pedi "apague os 2
   canais" e ele chamou `delete_channels` com `confirmed=true` sozinho. O `confirmed` que vem do
   modelo agora é descartado, a menos que o usuário tenha confirmado depois de o bot perguntar.
5. **A pergunta de confirmação podia não chegar** — com o modelo devolvendo um resumo vago
   ("a tentativa falhou"), o usuário ficava sem saber que só faltava um "sim". O agente agora
   garante a pergunta na resposta final.

## Pendências honestas

- ⚠️ **Ação do dono do servidor:** os cargos `Atlas`, `iTinder` e `Cupido` estão no nível ou acima do
  cargo do `farol`. Enquanto isso, o bot não edita nem os cargos que ele mesmo cria — arraste o cargo
  do `farol` para cima (README, Passo 3).
- ⚠️ **LLM gratuito é intermitente:** llm7, ovh e pollinations devolvem 429/modelo indisponível e às
  vezes respondem vago. O relatório separa isso (WARN, com a resposta crua) de comportamento do bot
  (FAIL). Sem chave paga, "rode de novo" é o caminho.
- ⏭️ `edit_server` e `set_icon` **não** são executados no servidor real (mudariam nome/ícone da
  comunidade); a fase `spy` prova que os bytes chegam em `guild.edit(icon=...)`.

## Onde ver

- Relatório completo: `reports/e2e-latest.md` (legível) e `reports/e2e-latest.json` (dados).
- Suíte offline: `python -W error::ResourceWarning -m unittest discover -s tests` → **123 testes OK**.
- Harness: `scripts/e2e_live.py` · testes dele: `tests/test_e2e_live.py` · workflow: `.github/workflows/e2e.yml`.
- PR: https://github.com/astaabacate/Atlas/pull/4 (aberto de propósito; **sem merge**).
