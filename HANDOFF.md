# 🏮 HANDOFF — Atlas (bot do Discord) · 18/09/2026

Documento para **outra IA (ou outra pessoa) assumir este projeto**. Aqui está o que é, como está
AGORA (medido, não suposto), o que pode e o que não pode, como rodar e onde estão as armadilhas.

> **Repositório:** `github.com/astaabacate/Atlas` (público) · **Ramo de trabalho:** `arena/01a0b13c-atlas`
> **Bot:** "Atlas"/atlas, roda 24/7 no GitHub Actions atendendo vários servidores.

---

## 1. O que é

Um bot de Discord que **administra servidores por conversa em português**: cria/edita/apaga
canais, categorias, cargos, permissões, fóruns, palcos, importa/exporta estrutura, clona canal,
manda DM de diagnóstico, mede o próprio desempenho. A linguagem natural é interpretada por LLMs
**gratuitos** (sem chave paga) e as ações são executadas por ferramentas com schema estrito.

**31 ferramentas** (`brain/tools.py`), cada uma com schema + executor (`brain/executors.py`) +
política de permissão (`brain/policy.py`).

---

## 2. Estado AGORA (18/09/2026, ~20:40Z)

| Item | Situação medida |
| --- | --- |
| Suíte de testes local | **406 testes · OK** (`python -m unittest discover -s tests`) |
| E2E offline | `static,spy,policy` = **✅ 43 · ❌ 0** |
| E2E ao vivo (execução `35391125443`, commit `3ae66cc`) | **✅ 67 · ❌ 0 · ⚠️ 7 · ⏭️ 6** |
| Bot 24/7 | no ar; fatia mais recente subiu; há pedido de reinício pendente em `.github/bot-24x7-enabled` para assumir o código novo |
| Cargo do bot no servidor | **posição 27 de 27** (`Administrator`) — medido pela sonda na API crua |
| Cor do atlas | **ainda a reserva `#F1C40F`**: o bot **não tem foto de perfil própria** (`reports/cor-do-avatar.txt`) |
| PR aberta | https://github.com/astaabacate/Atlas/pull/4 |

**Últimos feitos (todos medidos):** respostas em Components V2 com a cor medida do avatar; o canal
da conversa nunca é apagado ("apague todos os canais menos esse"); cor remedida quando a foto do
bot trocar; `bot.yml` consertado (estava com YAML inválido → execução com zero jobs); limite por
fase no E2E + "onde travou" no relatório; vigia que derruba execução presa do E2E; cobertura que
diz o que **não** foi testado.

---

## 3. Regras ABSOLUTAS (vieram do dono — não negociar)

1. **NUNCA** fazer merge, fechar PR nem `gh pr merge`. Entrega = link + logs + testes, e a decisão é humana.
2. Atualizar com a `main` só via `git fetch origin` + `git rebase origin/main`. Nunca `merge`/`pull` sem rebase.
3. Trabalhar **só no ramo da sessão** (`arena/01a0b13c-atlas`); PR sempre a partir dele.
4. **Nunca** burlar rate limit, CAPTCHA, bloqueio de IP, limites de plano ou ToS. Nada de conta falsa, proxy ou rodízio de IP (isso foi explicitamente RECUSADO pelo dono).
5. Só LLM **gratuito**. Sem chave paga. Falha intermitente do grátis é aceitável e deve ser tratada com honestidade.
6. Respostas do bot: **português, curtas (~1000 caracteres no máximo)**, nunca o rascunho/raciocínio do modelo, nunca em inglês. Se o modelo devolver lixo, responder o motivo real em PT-BR curto.
7. **Não tocar na identidade do servidor real** (`edit_server`, `set_icon`) sem autorização explícita.
8. **Nunca dizer que fez quando não fez.** Se o Discord recusou, dizer o motivo e o caminho.
9. Testar tudo = todas as capacidades de cada ferramenta (parâmetros, valores válidos e inválidos, combinações, limites, hierarquia, permissões, repetição, linguagem natural, estado real no servidor). Chamada simbólica não vale.
10. **Segredos nunca** vão para chat, log, commit ou relatório. Este repositório é PÚBLICO.
11. O veredito sobre o Discord sai da **API crua** (`scripts/sonda_hierarquia.py`), nunca de suposição nossa.

---

## 4. Mapa do código

| Arquivo | O que é |
| --- | --- |
| `main.py` | Entrada: carrega config, sobe o bot + servidor de saúde |
| `config.py` | Configuração por variável de ambiente (inclui `ACCENT_COLOR`, `MENSAGEM_V2`) |
| `core/bot.py` | `AtlasBot` (discord.py): `on_message` → agente → resposta (em Components V2, caindo para texto) |
| `core/look.py` | A "cara": decodificador PNG sem lib externa, medição da cor do avatar, montagem da mensagem V2, cache (`Aparencia`) |
| `core/bulk.py` | Execução em lote com concorrência limitada |
| `core/health.py` | Servidor HTTP de saúde (usado em hospedagem com porta) |
| `brain/agent.py` | Cérebro: prompt de sistema, histórico por (servidor, canal), protocolo de ferramentas, corrida de LLMs, barreira de resposta |
| `brain/tools.py` | **31 schemas** das ferramentas |
| `brain/executors.py` | Despacho nome → executor |
| `brain/ops.py` | Implementação das operações no Discord (a maior parte da lógica) |
| `brain/policy.py` | Permissões: quem pode pedir o quê; cargos gerenciados; hierarquia; confirmação |
| `brain/memory.py`, `brain/snapshot.py`, `brain/resolve.py` | Histórico, diff de estrutura, resolução de nomes/IDs |
| `llm/` | Provedores: `auto.py` (corrida + hedge, catálogo, espera inteligente), `free_providers.py` (pool gratuito), `key_providers.py` (chaves opcionais) |
| `apis/` | APIs de apoio: cores, emojis, tópicos, tradução |
| `scripts/e2e_live.py` | Harness E2E ao vivo/offline (11 fases) |
| `scripts/sonda_hierarquia.py` | Sonda crua na API do Discord: hierarquia de cargos + cor do avatar |
| `scripts/smoke_llm.py` | Medição dos provedores LLM gratuitos (latência, conteúdo, erros) |
| `tests/` | 406 testes offline |

Documentos: `README.md` (uso do dono), `AUDITORIA-CAPACIDADES.md` (o que já foi auditado ao vivo),
`reports/` (relatórios das execuções, sonda e pesquisas).

---

## 5. Como rodar (comandos exatos)

```bash
# ambiente (o .venv NÃO persiste entre sessões: recrie)
python3 -m venv .venv && .venv/bin/pip install aiohttp discord.py pyyaml pyflakes

# testes offline (sempre isto, não há pytest)
.venv/bin/python -W error::ResourceWarning -m unittest discover -s tests

# e2e offline (sem Discord): 43 checks
.venv/bin/python scripts/e2e_live.py --phases static,spy,policy --outdir /tmp/e2e --tag offline

# e2e AO VIVO (precisa do token); as fases que mexem no servidor exigem --mutate
DISCORD_TOKEN=... .venv/bin/python scripts/e2e_live.py --phases connect,audit,tools,agent \
    --outdir reports/parts --tag manual

# sonda crua (hierarquia de cargos + cor do avatar)
DISCORD_TOKEN=... .venv/bin/python scripts/sonda_hierarquia.py --outdir reports

# lint rápido
.venv/bin/python -m pyflakes <arquivos alterados>
```

O CI roda a suíte em todo push (`.github/workflows/ci.yml`).

---

## 6. Workflows (GitHub Actions) e configuração

| Workflow | Papel |
| --- | --- |
| `bot.yml` | **Bot 24/7**: fatias de ~5h35m, encadeadas + cron a cada 5h. Reiniciar = tocar em `.github/bot-24x7-enabled`. Desligar = criar `.github/bot-disabled` |
| `bot-watchdog.yml` | A cada 30 min: se nenhuma execução do bot está no ar, sobe uma |
| `e2e.yml` | E2E ao vivo (8 fases), publica `reports/e2e-latest.{md,json}` e comenta na PR |
| `sonda-hierarquia.yml` | Roda a sonda e publica `reports/sonda-hierarquia.{md,json}` + `reports/cor-do-avatar.txt` |
| `vigia-e2e.yml` | Derruba execução do E2E **presa** (passo > 35 min ou run > 60 min) — nunca toca no bot |
| `ci.yml`, `smoke.yml` | Testes de unidade; medição dos LLMs gratuitos |

**Segredos do repositório (só os NOMES — os valores vivem no GitHub, nunca aqui):**
`DISCORD_TOKEN` (obrigatório), `CHAIN_TOKEN` (opcional), `GITHUB_TOKEN` (automático), e as chaves
opcionais de LLM: `LLM_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`,
`MISTRAL_API_KEY`, `NVIDIA_API_KEY`, `CEREBRAS_API_KEY`, `DEEPSEEK_API_KEY`, `COHERE_API_KEY`,
`ZAI_API_KEY`, `OLLAMA_API_KEY`, `ZENMUX_API_KEY`, `MODELSCOPE_API_KEY`, `SILICONFLOW_API_KEY`,
`OPENCODE_API_KEY`, `KILOCODE_API_KEY`, `CLOUDFLARE_API_TOKEN`, `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`.

**Variáveis (vars) úteis:** `ACCENT_COLOR` (vazio = medir a cor do avatar), `MENSAGEM_V2` (`true`),
`LLM_PROVIDER`, `LLM_MODELS`, `LLM_TIMEOUT`, `MAX_TOOL_ROUNDS`, `HISTORY_LEN`, `LOG_LEVEL`,
`DISABLE_FREE_LLMS`, `E2E_GUILD_ID`, `E2E_MUTATIONS`, `ALLOWED_CHANNEL_IDS`.

**O que o dono precisa fazer (a IA não consegue):** `gh secret set` / `gh run cancel` dão 403 —
cancelar uma fatia do bot, criar/editar segredos e variáveis é ação do dono no GitHub.

---

## 7. Armadilhas conhecidas (todas já doeram — não repetir)

1. **YAML de workflow inválido = execução com ZERO jobs.** Aconteceu: a run nasce com
   "workflow file issue" e nada roda. `tests/test_workflows.py` parseia todos os workflows para
   pegar isso na CI.
2. **Passo que publica arquivo ANTES do passo que gera o arquivo** termina em "success" e não
   publica nada. Publicar sempre depois.
3. **`.venv` e `/tmp` somem** entre sessões do ambiente — recriar e não guardar nada importante
   em `/tmp`.
4. **Publicar relatório no ramo exige `fetch` + `rebase` antes do `push`** (o CI faz commits de
   relatório; o push bate non-fast-forward). Nunca `merge`.
5. **Cron do bot roda a partir da `main`** — se o código novo está no ramo da sessão e a fatia
   pendente não existe, o bot volta ao código VELHO. Pedido de reinício vai em
   `.github/bot-24x7-enabled`.
6. **Hierarquia de cargos é regra do Discord, não nossa:** o bot só gerencia cargo estritamente
   abaixo do mais alto dele; **empatado não basta** e "Administrator" não ignora hierarquia.
   Medido na API crua: pedir a mesma posição do topo faz o Discord colocar logo ABAIXO.
7. **Fase travada não pode levar a execução inteira:** há limite por fase (`asyncio.wait_for`) e o
   relatório diz onde estava pendurada (`client.py:...:connect`).
8. **Cuidado com o `connect` do discord.py em CI**: foi ali que a fase de mutações ficou presa.
9. **Nunca editar strings grandes com escape por script** (já gerou erro de sintaxe); conferir
   sempre com `pyflakes` antes de rodar a suíte.
10. **`set_icon` e `diagnostic_report` ficam fora dos testes ao vivo de propósito** (identidade do
    atlas / DM ao dono). Ficam registrados como lacuna no relatório — não como ✅.

---

## 8. Pendências abertas

- [ ] **O dono colocar a foto do bot** → a cor passa a ser medida sozinha (e remedida se a foto
      trocar). Hoje: reserva `#F1C40F`.
- [ ] **Chaves gratuitas de LLM** (as que o dono quiser colar nos segredos): hoje o pool roda com
      poucas opções, e é isso que faz a resposta demorar quando o modelo da frente está na fila.
- [ ] Cancelar a fatia antiga do bot (ação do dono) para a pendência nova assumir na hora.
- [ ] Fora do escopo autorizado até agora: controle de clientes (lista de permitidos, limite de
      uso por pessoa, status).
