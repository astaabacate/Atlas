# 🏮 Atlas — resumo do teste ao vivo do bot

Pedido: *"se conecte ao bot e teste as coisas dele"*.
Resultado: o bot foi testado **de verdade** no servidor `asta`, 5 bugs foram encontrados (3 deles
só apareceram quando as mutações reais foram autorizadas) e todos foram corrigidos com prova
registrada. O PR #4 segue **aberto** — o merge é manual.

## Como o teste roda

O ambiente de desenvolvimento não tem rota para `discord.com` nem para os provedores de LLM, então
os testes ao vivo rodam no **GitHub Actions** (workflow *E2E ao vivo do Atlas*), onde o
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
| **35286288799** | **✅ 75 · ❌ 0 · ⚠️ 6 · ⏭️ 1** | verde já com o isolamento entre servidores (commit `315c98b`) |

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
  cargo do `atlas`. Enquanto isso, o bot não edita nem os cargos que ele mesmo cria — arraste o cargo
  do `atlas` para cima (README, Passo 3).
- ⚠️ **LLM gratuito é intermitente — e agora o bot se defende:** quando os três corredores gratuitos
  falharam juntos (ovh 429, llm7 com modelo aposentado, pollinations "Queue full for IP"), o cliente
  recebia a parede de erro. Correção aplicada: `429` tem nova tentativa + castigo temporário do
  corredor, modelo indisponível dispara redescoberta do catálogo (`/v1/models`), a corrida tenta
  **duas ondas** e, se ainda assim nada responder, o cliente lê uma frase curta ("tente de novo em
  segundos") — o relatório técnico completo só aparece no log. O relatório do E2E continua separando
  isso (WARN) de bug do bot (FAIL). Sem chave paga, "rode de novo" segue sendo o caminho nos picos.
- ⏭️ `edit_server` e `set_icon` **não** são executados no servidor real (mudariam nome/ícone da
  comunidade); a fase `spy` prova que os bytes chegam em `guild.edit(icon=...)`.

## Vários servidores ao mesmo tempo (isolamento) — pedido de produto

Como o bot vai ser vendido e ficará em vários servidores com **um único processo**, tudo que é
"por conversa" passou a usar a chave `servidor:canal`:

- **histórico** — o que foi dito no servidor A nunca entra no prompt do servidor B;
- **pendência de confirmação** — o "sim" de um servidor não autoriza exclusão em outro;
- **lock de processamento** — só a mesma conversa entra em fila;
- **memória limitada (LRU)** — as conversas mais antigas saem (400 por padrão) e o histórico por
  canal tem teto: o bot pode ficar meses no ar sem crescer.

Provas: `tests/test_isolation.py` (12 testes, incluindo **dois servidores com o mesmo id de canal**),
a checagem *conversa isolada por servidor* da fase `spy` e o `show_permissions` agora lendo o estado
atual do servidor (o cache local atrasado escondia permissões recém-criadas).

## Ficar no ar infinito no GitHub Actions

| Peça | Para que serve |
| --- | --- |
| `bot.yml` (fatias de ~5h35m + encadeamento) | mantém o bot online continuamente; o encadeamento continua **no mesmo ramo** |
| Gatilho por push em `.github/bot-24x7-enabled` | ligar/reiniciar o bot tocando no arquivo (foi assim que ele voltou ao ar) |
| `.github/bot-disabled` | parar de vez (o bot não sobe e o vigia respeita) |
| Frescor que **reagenda** em vez de abortar | antes, um push no meio da run matava a corrente do bot; agora ele agenda uma run nova, já atualizada |
| `.github/workflows/bot-watchdog.yml` | a cada 30 min reergue o bot se não houver execução ativa e grava um "batimento" quando o repositório fica 45+ dias parado (evita a suspensão de crons do GitHub no 60º dia) |

O clone de teste do harness também foi silenciado: com o bot de produção online usando o mesmo token,
ele não responde mais as mensagens reais dos clientes (só as mensagens falsas do teste).

## Duas coisas que dependem de você

1. **Suba o cargo do `atlas`** acima de `Atlas`, `iTinder` e `Cupido` (README Passo 3). Enquanto ele
   estiver no chão, o bot não edita nem os cargos que ele mesmo cria.
2. **Faça o merge do PR #4** para o código corrigido virar `main`. Enquanto o bot rodar a partir do
   ramo da sessão ele usa o código corrigido; o cron de 5 em 5 horas pode pegá-lo a partir da `main`
   (ainda sem as correções) até o merge acontecer. O vigia (`bot-watchdog.yml`) também só passa a
   rodar depois do merge, porque o GitHub só executa `schedule` de workflow que existe no ramo padrão.

## Onde ver

- Relatório completo: `reports/e2e-latest.md` (legível) e `reports/e2e-latest.json` (dados).
- Suíte offline: `python -W error::ResourceWarning -m unittest discover -s tests` → **149 testes OK**
  (11 novos cobrem a corrida de LLM: 429/Retry-After, castigo, redescoberta de catálogo, segunda onda
  e mensagem amigável ao cliente).
- Bot 24/7: workflow *Atlas Bot 24/7* (execução em andamento no ramo da sessão).
- Harness: `scripts/e2e_live.py` · testes dele: `tests/test_e2e_live.py` · workflow: `.github/workflows/e2e.yml`.
- PR: https://github.com/astaabacate/Atlas/pull/4 (aberto de propósito; **sem merge**).
