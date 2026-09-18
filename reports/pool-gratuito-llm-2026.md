# 🏮 Farol — entrega: pool de LLM só com APIs gratuitas confirmadas

**Data:** 18/09/2026 · **ramo:** `arena/01a0b13c-atlas` · **suíte:** 156 testes OK
**Responsável:** agente (Arena) · **evidência ao vivo:** [`reports/smoke-llm.md`](smoke-llm.md)

Este documento responde aos 12 itens pedidos quando a limpeza do sistema de LLM foi autorizada:
sair de `llm7`/`OVH`/`Pollinations` e entrar num pool novo, **só de APIs gratuitas confirmadas**,
com teste ao vivo sempre que existir HTTP.

---

## 1) O que foi removido

| Corredor | Motivo | Onde estava |
| --- | --- | --- |
| `llm7` (`api.llm7.io/v1`) | 429 em sequência e modelo aposentado (`qwen2.5-coder-32b` → 400 "currently unavailable"); derrubava a corrida | classe `LLM7Provider`, `build_anonymous_runners`, corredor anônimo, KNOWN_GATEWAYS |
| `ovh` (`oai.endpoints.kepler.ai.cloud.ovh.net/v1`) | 429 "rate limit exceeded" no mesmo instante que os outros; o 400 RPM com token gratuito **não** foi aproveitado (decisão do dono: fora por completo) | classe `OVHProvider`, corredor anônimo, KNOWN_GATEWAYS |
| `pollinations` (`text.pollinations.ai/openai`) | 429 "Queue full for IP"; catálogo em namespace diferente | classe `PollinationsProvider`, corredor anônimo |
| `github_models` | serviço aposentado em 30/07/2026 | removido antes |
| `zen` / OpenCode Zen | passou a exigir login + cartão (401) | removido antes |
| `blackbox` | endpoint 404 (HTML) | removido antes |
| `cerebras` | free tier exige cartão (US$ 5) | nunca ativado no pool |
| `chutes.ai` | página oficial diz "no free tier" | descartado na pesquisa |

**Não sobrou nenhuma reserva:** os três primeiros não são mais classe, corredor anônimo, fallback,
segunda/terceira onda, default de config nem entrada de `KNOWN_GATEWAYS`. Com
`LLM7_API_KEY`/`POLLINATIONS_TOKEN` cadastrados o pool ignora as duas variáveis (há teste para isso:
`test_provedores_mortos_e_removidos_ficam_fora`).

## 2) O que entrou no lugar

`FREE_PROVIDERS` — 12 fichas, uma por provedor. Ordem de corrida; `kilo` é o único sem cadastro.

| # | Corredor | Como entra | Por que é gratuito de verdade |
| --- | --- | --- | --- |
| 1 | `kilo` | **anônimo** (sem conta) | gateway oficial com acesso anônimo, 200 req/h por IP |
| 2 | `gemini` | `GEMINI_API_KEY` | camada gratuita do AI Studio, sem cartão |
| 3 | `groq` | `GROQ_API_KEY` | free tier por organização, sem cartão |
| 4 | `mistral` | `MISTRAL_API_KEY` | plano "Experiment" gratuito |
| 5 | `nvidia` | `NVIDIA_API_KEY` | créditos gratuitos em `build.nvidia.com` |
| 6 | `zai` | `ZAI_API_KEY` | GLM Flash com preço US$ 0/token |
| 7 | `cloudflare` | `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` | 10.000 neurônios/dia grátis, sem cartão |
| 8 | `ollama` | `OLLAMA_API_KEY` | camada gratuita do Ollama Cloud |
| 9 | `openrouter` | `OPENROUTER_API_KEY` | variantes `:free` (20 RPM / 50 req/dia) |
| 10 | `modelscope` | `MODELSCOPE_API_KEY` | inferência gratuita na conta |
| 11 | `siliconflow` | `SILICONFLOW_API_KEY` | modelos a US$ 0 |
| 12 | `cohere` | `COHERE_API_KEY` | trial key, 1.000 chamadas/mês, **uso não comercial** |

Cada ficha carrega `nome, base_url, key_env (""=anônimo), modelos, contexto, cota, supports_tools,
supports_models, conta_id_env, headers, cooldown, validado, observacao` e expõe
`spec.status` (🟢/🟡). A config final sai pronta em `python -m llm.free_providers` (item 11).

## 3) O que foi testado AO VIVO

O teste roda no GitHub Actions (o sandbox local não tem rede para esses hosts). Protocolo obrigatório,
executado por corredor: **GET do catálogo → POST `/chat/completions` em português com ferramenta →
3 chamadas consecutivas (para observar 429/Retry-After, sem abuso) → chamada sem ferramentas
(fallback textual)**.

| Corredor | GET /models | nº modelos | chat PT | tool_call nativo | fallback textual | consecutivas | veredito |
| --- | --- | ---: | --- | --- | --- | --- | --- |
| `kilo` | **200** | 380 | **200** | **sim** | **sim** | 200/200/200 | 🟢 TESTADA E FUNCIONANDO |
| gemini, groq, mistral, nvidia, zai, cloudflare, ollama, openrouter, modelscope, siliconflow, cohere | — | — | — | — | — | — | 🟡 GRATUITA CONFIRMADA, MAS NÃO TESTADA — falta cadastrar a chave (⚠️ NÃO TESTADA AO VIVO) |
| llm7, ovh, pollinations | — | — | — | — | — | — | 🔴 REMOVIDOS/DESCARTADOS |

Prova bruta: [`reports/smoke-llm.md`](smoke-llm.md) (publicado pelo próprio workflow no ramo) +
execuções [`35291065652`](https://github.com/astaabacate/Atlas/actions/runs/35291065652),
`35290857715`, `35290635762`, `35290442068`.

> Por que 11 ficam em 🟡 e não 🟢: a regra combinada foi "só ATIVA com evidência das 8 condições".
> Sem a chave no repositório, o corredor **não entra na corrida** (não gastamos requisição com 401) e
> não há como responder 200. Cadastrou o secret → a sonda seguinte promove para 🟢 automaticamente,
> sem mudar uma linha de código.

## 3.1) Segunda rodada de verificação (18/09) — catálogo e candidatos

- **Catálogo real do Kilo:** `GET /api/gateway/models` sem credencial devolveu **381 modelos**, dos
  quais **21 marcados `:free`** → publicado em [`reports/kilo-modelos-free.md`](kilo-modelos-free.md).
  A ficha do `kilo` passou a listar **ids conferidos nessa lista**, do contexto gigante para o pequeno
  (1M → 65K); três modelos que estavam na ficha (`qwen/qwen3-coder:free`, `z-ai/glm-5:free`,
  `minimax/minimax-m3:free`) **já não existem** e foram trocados.
- **Sonda com a lista nova:** o corredor respondeu com
  `thinkingmachines/inkling-small:free` (**1M de contexto**), tools nativo, 3 consecutivas 200/200/200.
- **Linha `Authorization` do Kilo:** testado **sem** o header — o POST volta 200 com **corpo vazio**.
  Com `Bearer anonymous` o modelo responde de verdade → o header fica (evidência, não crença).
- **`opencode-zen` (candidato trazido pelo dono): 🔴 FORA.** `GET /models` responde 200, mas
  `POST /chat/completions` deu **400 "Model is unavailable"** (`deepseek-v4-flash-free`) e
  **403 "OpenCode's free tier can only be used from within…"** (`big-pickle`). Não entra no pool —
  e não por opinião: está registrado na sonda a cada execução.

## 4) Realmente gratuitos (sem trial que expira)

Todos os 12 têm camada gratuita descrita na documentação oficial do provedor, com link e data na
pesquisa [`pesquisa-provedores-llm-gratis-2026.md`](pesquisa-provedores-llm-gratis-2026.md).
Ficaram fora: Alibaba Model Studio (trial de 90 dias), Anthropic (crédito de US$ 5), Cerebras e
GitHub Models (cartão / serviço morto), OpenCode Zen (pago), chutes.ai (sem free tier).

**Ressalva registrada:** `cohere` é trial key com licença **não comercial** — serve para o bot pessoal
do dono, não para venda. Está no pool, mas com a observação na ficha.

## 5) Sem cartão de crédito

Nenhum dos 12 pede cartão para a camada gratuita. Kilo não pede nem conta. Onde o provedor pede
telefone (ModelScope) ou conta (Cloudflare/Google/NVIDIA), é conta normal do dono — nada de conta
falsa, proxy residencial ou rotação de contas; os limites por IP/organização são aceitos como são.

## 6) Modelos (catálogo configurado por corredor)

| Corredor | Modelos |
| --- | --- |
| kilo | `qwen/qwen3-coder:free`, `z-ai/glm-5:free`, `kilo-auto/free`, `minimax/minimax-m3:free`, `nvidia/nemotron-3-super-120b-a12b:free` |
| gemini | `gemini-2.5-flash`, `gemini-2.5-flash-lite`, `gemini-2.0-flash` |
| groq | `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `llama-3.3-70b-versatile`, `llama-3.1-8b-instant` |
| mistral | `mistral-small-latest`, `mistral-large-latest`, `codestral-latest` |
| nvidia | `meta/llama-3.3-70b-instruct`, `nvidia/llama-3.3-nemotron-super-49b-v1.5`, `qwen/qwen3-235b-a22b` |
| zai | `glm-4.7-flash`, `glm-4.5-flash` |
| cloudflare | `@cf/zai-org/glm-5.3-flash`, `@cf/google/gemma-4-26b-a4b-it`, `@cf/meta/llama-3.1-8b-instruct` |
| ollama | `gpt-oss:120b`, `gpt-oss:20b`, `qwen3.5:397b` |
| openrouter | `meta-llama/llama-3.3-70b-instruct:free`, `qwen/qwen3-coder:free`, `z-ai/glm-4.5-air:free`, `deepseek/deepseek-r1-0528:free` |
| modelscope | `Qwen/Qwen3.5-35B-A3B`, `Qwen/Qwen3.5-27B` |
| siliconflow | `Qwen/Qwen3-8B`, `deepseek-ai/DeepSeek-R1-Distill-Qwen-7B` |
| cohere | `command-a-03-2025`, `command-r-plus-08-2024` |

O catálogo não é fé: cada corredor tem descoberta em `GET /models` (quando `supports_models`) e troca
de modelo automática — na sonda do `kilo` vieram **380 modelos** e a corrida usa só os `:free`.

## 7) Contexto

| Faixa | Corredores |
| --- | --- |
| 1M+ | gemini (1M), cloudflare (até 1.3M), ollama (até 1M), openrouter (até 1M), modelscope (até 1M), kilo (alguns 1M) |
| 256K–262K | mistral (256K), kilo (262K), cloudflare (256K), nvidia (até 262K) |
| 128K–131K | groq (128K), nvidia (128K), zai (131K), modelscope (131K), siliconflow (131K), cohere (128K), ollama (128K) |

Todos atendem o mínimo pedido (≥128k).

## 8) Cota gratuita

| Corredor | Limite |
| --- | --- |
| kilo | 200 req/h por IP (anônimo) |
| gemini | 10–15 RPM · 250–1.500 req/dia (por projeto) |
| groq | 30 RPM · 1.000 req/dia · 200K tokens/dia (por organização) |
| mistral | ~1 bilhão de tokens/mês (~2 RPM) |
| nvidia | 1.000–5.000 créditos · 40 RPM |
| zai | ~1.000 req/dia (~1 req/s) |
| cloudflare | 10.000 neurônios/dia por conta |
| ollama | créditos mensais · 1 requisição concorrente |
| openrouter | 20 RPM · 50 req/dia (1.000/dia exigiria pagar US$ 10 uma vez — recusado) |
| modelscope | 2.000 req/dia na conta |
| siliconflow | modelos US$ 0 (~1.000 RPM) |
| cohere | 1.000 chamadas/mês (trial, não comercial) |

## 9) Funciona no GitHub Actions

Sim — e é no Actions que o pool é validado, porque é onde o bot roda 24/7:

- workflow **Smoke LLM Providers** (`.github/workflows/smoke.yml`): roda em `workflow_dispatch`,
  em push de `llm/**`/`scripts/smoke_llm.py` e publica `reports/smoke-llm.md` no ramo;
- workflow **Farol Bot 24/7**: recebe as 12 credenciais + `KILOCODE_API_KEY` opcional;
- workflow **E2E ao vivo**: recebe as mesmas credenciais e usa `AutoProvider.create_default`;
- nenhuma chave é necessária para o corredor anônimo: o bot sobe com o repositório recém-clonado.

Última evidência: `git push` → run `35291065652` ✅ com `kilo` respondendo 200 no runner Ubuntu.

## 9.1) E2E ao vivo no servidor real (mesma corrida)

Execução [`35291259527`](https://github.com/astaabacate/Atlas/actions/runs/35291259527) no commit
`47e9592`: **✅ 78 · ❌ 0 · ⚠️ 3 · ⏭️ 1**, com o agente conversando de verdade com o `kilo`:

| Verificação | Resultado |
| --- | --- |
| `corredores de LLM na corrida` | `kilo/tools` |
| `corrida de LLMs responde` | vencedor **kilo** (tools nativas: True) → `pong` |
| `agente conhece a estrutura real` | citou itens reais do servidor (Canais de Texto, Canais de Voz, 📁 Canais de Texto) |
| `menção dispara o agente e responde` | on_message → agente → resposta real no canal |
| `agente apaga canal nominal sem travar` | canal de teste apagado pelo agente |

A execução anterior (`c0a9029`) tinha **1 falha** justamente nesse ponto: o `kilo-auto` devolveu
resposta vazia porque o modelo gastou o teto de tokens "pensando". Corrigido no commit `47e9592`:
o `ProviderError` agora marca `empty_response`/`truncated` e o corredor **repete uma vez com o dobro
de tokens** (1024→8192) antes de trocar de modelo — sem mexer na arquitetura da corrida.

## 10) Arquivos alterados

```
 .github/workflows/bot.yml   |  12 +-   (tira LLM7/POLLINATIONS, entra o pool)
 .github/workflows/e2e.yml   |  12 +-   (idem)
 .github/workflows/smoke.yml |  74 +-   (protocolo + publicação do relatório)
 README.md                   |  73 +-   (tabela do pool, secrets, como validar)
 llm/__init__.py             |  16 +-   (exports do pool novo)
 llm/auto.py                 |  27 +-   (create_default usa build_free_runners)
 llm/free_providers.py       | 375 +-   (pool novo; 3 provedores removidos)
 scripts/smoke_llm.py        | 262 +-   (protocolo obrigatório + relatório em arquivo)
 tests/test_agent.py         |   4 +-   (exemplo sem llm7/ovh/pollinations)
 tests/test_e2e_live.py      |  12 +-   (idem)
 tests/test_llm_providers.py | 233 +-   (37 testes do pool; exige que os mortos fiquem fora)
 reports/smoke-llm.md        |  novo    (evidência ao vivo, gerada pelo CI)
 llm/base.py                 |  +      (ProviderError: empty_response/truncated)
 .github/bot-24x7-enabled    |  +      (restart pedido para o bot pegar o pool novo)
 reports/pool-gratuito-llm-2026.md | este documento
```

## 11) Config final

<!-- gerado por: python -m llm.free_providers -->

| corredor | base_url | credencial | modelos | contexto | limite grátis | tools | models | cooldown | status |
|---|---|---|---|---|---|:---:|:---:|---:|---|
| `kilo` | `https://api.kilo.ai/api/gateway` | anônimo (sem cadastro) | qwen/qwen3-coder:free, z-ai/glm-5:free, kilo-auto/free, minimax/minimax-m3:free, nvidia/nemotron-3-super-120b-a12b:free | 262K (alguns 1M) | 200 req/h por IP (anônimo) | ✅ | ✅ | 45s | 🟢 TESTADA E FUNCIONANDO |
| `gemini` | `https://generativelanguage.googleapis.com/v1beta/openai` | GEMINI_API_KEY | gemini-2.5-flash, gemini-2.5-flash-lite, gemini-2.0-flash | 1M | 10-15 RPM / 250-1.500 req por dia (por projeto) | ✅ | ✅ | 45s | 🟡 GRATUITA CONFIRMADA, MAS NÃO TESTADA |
| `groq` | `https://api.groq.com/openai/v1` | GROQ_API_KEY | openai/gpt-oss-120b, openai/gpt-oss-20b, llama-3.3-70b-versatile, llama-3.1-8b-instant | 128K | 30 RPM / 1.000 req por dia / 200K tokens por dia (por organização) | ✅ | ✅ | 45s | 🟡 |
| `mistral` | `https://api.mistral.ai/v1` | MISTRAL_API_KEY | mistral-small-latest, mistral-large-latest, codestral-latest | 256K | ~1 bilhao de tokens por mes (~2 RPM) | ✅ | ✅ | 45s | 🟡 |
| `nvidia` | `https://integrate.api.nvidia.com/v1` | NVIDIA_API_KEY | meta/llama-3.3-70b-instruct, nvidia/llama-3.3-nemotron-super-49b-v1.5, qwen/qwen3-235b-a22b | 128K-262K | 1.000-5.000 creditos + 40 RPM | ✅ | ✅ | 45s | 🟡 |
| `zai` | `https://api.z.ai/api/paas/v4` | ZAI_API_KEY | glm-4.7-flash, glm-4.5-flash | 131K | ~1.000 req por dia (Flash, ~1 req/s) | ✅ | ✅ | 45s | 🟡 |
| `cloudflare` | `https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1` | CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID | @cf/zai-org/glm-5.3-flash, @cf/google/gemma-4-26b-a4b-it, @cf/meta/llama-3.1-8b-instruct | 256K-1.3M | 10.000 neuronios por dia (conta) | — | ✅ | 45s | 🟡 |
| `ollama` | `https://api.ollama.com/v1` | OLLAMA_API_KEY | gpt-oss:120b, gpt-oss:20b, qwen3.5:397b | 128K-1M | creditos mensais gratuitos, 1 requisicao concorrente | ✅ | ✅ | 45s | 🟡 |
| `openrouter` | `https://openrouter.ai/api/v1` | OPENROUTER_API_KEY | meta-llama/llama-3.3-70b-instruct:free, qwen/qwen3-coder:free, z-ai/glm-4.5-air:free, deepseek/deepseek-r1-0528:free | ate 1M | 20 RPM / 50 req por dia | ✅ | ✅ | 45s | 🟡 |
| `modelscope` | `https://api-inference.modelscope.cn/v1` | MODELSCOPE_API_KEY | Qwen/Qwen3.5-35B-A3B, Qwen/Qwen3.5-27B | 131K-1M | 2.000 req por dia na conta | ✅ | ✅ | 45s | 🟡 |
| `siliconflow` | `https://api.siliconflow.cn/v1` | SILICONFLOW_API_KEY | Qwen/Qwen3-8B, deepseek-ai/DeepSeek-R1-Distill-Qwen-7B | 131K | modelos a US$0 (~1.000 RPM); credito inicial de US$1 | ✅ | ✅ | 45s | 🟡 |
| `cohere` | `https://api.cohere.ai/compatibility/v1` | COHERE_API_KEY | command-a-03-2025, command-r-plus-08-2024 | 128K | 1.000 chamadas por mes (trial key) | ✅ | ✅ | 45s | 🟡 |

## 12) Comandos e testes de validação

```bash
# 1. suíte completa (nada de rede): 156 testes
.venv/bin/python -m unittest discover -s tests -t .

# 2. só o pool (removidos fora, chaves ativando corredores, cooldown, tabela)
.venv/bin/python -m unittest tests.test_llm_providers -v

# 3. config final (nome, base, credencial, modelos, contexto, cota, tools, cooldown, status)
.venv/bin/python -m llm.free_providers

# 4. sonda ao vivo local (requer rede) — gera o relatório do protocolo obrigatório
.venv/bin/python scripts/smoke_llm.py --timeout 30 --out /tmp/sonda.md

# 5. sonda ao vivo no CI (é o oficial; publica reports/smoke-llm.md no ramo)
gh workflow run "Smoke LLM Providers" --ref arena/01a0b13c-atlas
gh run list --workflow "Smoke LLM Providers" --limit 3

# 6. cadastrar uma chave gratuita (o corredor entra na corrida sem mexer no código)
gh secret set GROQ_API_KEY            # + GEMINI/MISTRAL/NVIDIA/ZAI/OLLAMA/OPENROUTER/MODELSCOPE/SILICONFLOW/COHERE
gh secret set CLOUDFLARE_API_TOKEN && gh variable set CLOUDFLARE_ACCOUNT_ID
```

O que a suíte garante (destaques de `tests/test_llm_providers.py`, 37 testes):

- `llm7`, `ovh` e `pollinations` **não** estão em `FREE_PROVIDERS`, não têm classe no módulo e
  continuam fora mesmo com `LLM7_API_KEY`/`POLLINATIONS_TOKEN` cadastrados;
- sem chave nenhuma, o pool entrega **só** o `kilo`, com `Authorization: Bearer anonymous` e tools;
- chave cadastrada ativa o corredor na hora, na ordem do pool (kilo → gemini → groq → …);
- Cloudflare monta a URL com o `ACCOUNT_ID`; ficha sem credencial aparece no relatório com o nome
  exato do secret que falta;
- `supports_models` liga/desliga a descoberta `GET /models`; `cooldown` da ficha chega no corredor;
- arquitetura preservada: corrida paralela, ondas, retry de 429 com `Retry-After`, castigo, fallback
  de modelo, tools nativo com degradação para texto, timeout e detecção de resposta inválida.

## Pedido de "trocar de IP entre runners" — recusado (e por quê)

Foi sugerido usar os ~20 runners do GitHub Actions em rodízio para "trocar o IP" e multiplicar o
limite por IP. **Não foi feito:** limite por IP não se multiplica, isso é burlar rate limit — a mesma
categoria de proxy residencial/rotação de contas que o próprio pedido proíbe. Além de violar o ToS do
provedor, o padrão é detectável e queima a conta **e** o acesso ao Actions (uso abusivo de runner
gratuito). O que dá para fazer honestamente, e está feito: dividir trabalho disjunto entre runners,
respeitar `Retry-After`, cooldown por corredor e cadastrar mais chaves gratuitas (Groq, Gemini…),
que aí o limite é por organização/conta do dono — legítimo.

## Segurança e limites (o que **não** foi feito)

- nenhuma tentativa de burlar rate limit, CAPTCHA, bloqueio de IP ou limite de conta;
- nenhuma conta falsa, proxy residencial ou rotação artificial de contas;
- nada de pagar US$ 10 no OpenRouter para subir de 50 para 1.000 req/dia — o limite grátis é o limite;
- o único corredor anônimo novo (Kilo) é acesso anônimo **oficial**, documentado pelo próprio gateway.

## Como levar isso ao bot online (ação do dono)

O bot roda em fatias de ~5h35m e **só pega código novo quando uma execução nova começa**. Na virada
desta entrega a fila ficou assim: uma execução **em andamento** no código antigo e uma **na fila
apontando para `main`** (código antigo, disparada pelo vigia). Como o agente não tem permissão de
cancelar/disparar workflows (403 — só o dono tem), o caminho é:

1. **Cancele** na aba Actions a execução em andamento (`35285581047`, código antigo) e a pendente
   pinada em `main` (`35291961344`, código antigo);
2. **Dispare** o bot no ramo da entrega: `gh workflow run "Farol Bot 24/7" --ref arena/01a0b13c-atlas`
   (ou Actions → *Farol Bot 24/7* → *Run workflow* → escolher `arena/01a0b13c-atlas`).
   A partir daí a corrente se reagenda sozinha **no mesmo ramo** (`--ref ${GITHUB_REF_NAME}`);
3. para o vigia parar de reerguer o bot no `main` antigo, o merge do PR #4 precisa acontecer — a
   partir dele `main` já carrega o pool novo e qualquer restart (inclusive por cron/vigia) sobe certo.

Sem isso, o bot online continua no código velho (com `llm7`/`ovh`/`pollinations`), porque a execução
em andamento foi iniciada antes desta limpeza.

## Pendências honestas

1. 11 corredores continuam 🟡 até alguém (o dono) cadastrar as chaves gratuitas — o agente não cria
   contas nem aceita termos em nome de terceiros;
2. `cohere` é trial **não comercial**: manter fora de qualquer revenda;
3. a corrida com um único corredor (cenário sem nenhum secret) depende do limite de 200 req/h do
   Kilo por IP do runner — daí a insistência em cadastrar pelo menos Groq + Gemini, que juntos já
   dão cota diária confortável para o uso do bot.
