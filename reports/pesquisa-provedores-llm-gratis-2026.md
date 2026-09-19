# 🔎 Pesquisa: pool de capacidade gratuita de LLM para o Atlas

**PESQUISA REALIZADA EM: 17/09/2026** (America/Sao_Paulo)

> ⚠️ **Teste ao vivo:** o sandbox onde esta pesquisa rodou **não tem rede de saída**
> (`curl https://api.llm7.io/v1/models` → `SSL_ERROR_SYSCALL`, igual para Groq). Portanto **nada
> abaixo foi validado por HTTP daqui**. Tudo vem de documentação oficial, páginas de pricing e
> trackers de terceiros, com a data da verificação em cada linha. O teste ao vivo pode ser feito em
> minutos pelo workflow `smoke.yml` do repositório (é só pedir: eu já deixo a sonda rodando para os
> candidatos novos).

---

## 1. O achado que muda o jogo: o Kilo não está morto — o caminho é outro

| O que sabíamos | O que a pesquisa mostra |
| --- | --- |
| `api.kilo.ai/v1/chat/completions` → **404 em HTML** | O gateway é **`https://api.kilo.ai/api/gateway`** (com o alias legado `/api/openrouter`) |
| "Kilo fora" | **Acesso anônimo, sem chave, sem cadastro: 200 requisições por hora por IP** em ~19 modelos `:free` |
| — | Catálogo público: **`GET https://api.kilo.ai/api/gateway/models`** (sem auth, formato OpenRouter com `isFree` e `pricing.* = "0"`) |
| — | Modelos com **128K a 1M de contexto** (`qwen/qwen3-coder:free` 262K, `z-ai/glm-5:free` 202K, `minimax/minimax-m3:free` ~205K-1M) |

🎯 Isso explica o 404: erramos a rota, não era o provedor que estava fora. **Kilo entra como um dos
melhores corredores gratuitos sem chave.**

---

## 2. Tabela Canal-2

Legenda: **GL** = grátis permanente · ⚠️ = incerto/relato de terceiros · 🚫 = exige cartão/trial.

| # | Provedor | Base URL | Modelo (exemplo) | Contexto | Free tier | Limite | Por IP/conta/key | Cartão? | OpenAI API? | /models | Tools | Datacenter | PT-BR | Status | Fonte oficial / data |
|---:|---|---|---|---:|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Cargo-1 | `generativelanguage.googleapis.com/v1beta/openai` | `gemini-2.5-flash` / `3-flash` | **1M** | GL | 10–15 RPM; **250–1.500 RPD** ⚠️ fontes divergem | **conta/projeto** ⭐ | Não | ✅ (openai-compat) | ✅ | ✅ nativo | ✅ | Excelente | [ai.google.dev/pricing](https://ai.google.dev/gemini-api/docs/rate-limits) · set/2026 |
| 2 | Cargo-2 | `api.cloudflare.com/client/v4/accounts/{id}/ai/v1` | `@cf/zai-org/glm-5.3-flash`, `@cf/google/gemma-4-26b-a4b-it` | **256K–1.3M** | GL | **10.000 neurônios/dia** (≈ 49k–287k tokens/dia conforme o modelo) | **conta** ⭐ | Não | ✅ (REST OpenAI-compat) | ⚠️ catálogo via API | ✅ | ✅ | Bom | [developers.cloudflare.com/workers-ai/platform/pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/) · 28/08/2026 |
| 3 | Cargo-3 | `api.groq.com/openai/v1` | `openai/gpt-oss-120b` | 128K | GL | 30 RPM · 1.000 RPD · **200K tokens/dia** (8B: 14.400 RPD/500K TPD) | **organização** (mais chaves não multiplicam) | Não | ✅ | ✅ | ✅ nativo | ✅ | Excelente | [console.groq.com/docs/rate-limits](https://console.groq.com/docs/rate-limits) · 06/09/2026 |
| 4 | Cargo-4 | `api.mistral.ai/v1` | `mistral-large-latest` | **256K** | GL | **~1 B tokens/mês** · ~1–2 RPM · 500K TPM | **workspace/conta** ⭐ | Não (telefone) | ✅ | ✅ | ✅ nativo | ✅ | Muito bom | [console.mistral.ai](https://docs.mistral.ai/deployment/laplateforme/tier/) · 28/07/2026 |
| 5 | Cargo-5 | `api.kilo.ai/api/gateway` | `qwen/qwen3-coder:free`, `z-ai/glm-5:free` | 128K–1M | GL | **200 req/h por IP** (anônimo) | **IP** (anônimo) / conta se logar | Não | ✅ | ✅ (`/api/gateway/models` sem auth) | ✅ | ✅ | Bom | [kilo.ai/docs](https://kilo.ai) + [itsfree.ai/provider/kilo-code](https://itsfree.ai/provider/kilo-code/) · 14/05/2026 |
| 6 | Cargo-6 | `integrate.api.nvidia.com/v1` | `moonshotai/kimi-k2.6`, `qwen/qwen3.5-*` | 128K–262K | GL | 1.000–5.000 créditos (⚠️ relatos: limite removido) · 40 RPM | **conta** ⭐ | Não | ✅ | ✅ | ✅ nativo | ✅ | Bom | [build.nvidia.com](https://build.nvidia.com) · 19/08/2026 |
| 7 | Cargo-7 | `api.z.ai/api/paas/v4` | `glm-4.7-flash`, `glm-4.5-flash` | 131K+ | GL ($0/token) | ~1 req/s · **~1.000 req/dia** ⚠️ (3ºs) | **conta** ⭐ | Não | ✅ | ⚠️ | ✅ nativo | ✅ | Bom | [docs.z.ai](https://docs.z.ai) · 07/09/2026 |
| 8 | **Ollama Cloud** | `api.ollama.com/v1` (wrapper OpenAI) | `gpt-oss:120b`, `minimax-m3` | 131K–**1M** | GL (créditos mensais iniciais) | créditos/mês · **1 requisição concorrente** | **conta** ⭐ | Não | ✅ (wrapper) | ✅ | ✅ (tools em vários) | ⚠️ | Potencial | [docs.ollama.com/cloud](https://docs.ollama.com/cloud) · 28/08/2026 |
| 9 | Cargo-8 | `oai.endpoints.kepler.ai.cloud.ovh.net/v1` | `Qwen3-Coder-30B-A3B-Instruct` | até 262K | GL | **anônimo: 2 req/min** · **com token: 400 RPM** ⚠️ (tracker, não doc oficial) | IP (anônimo) / **conta** (token) ⭐ | Não | ✅ | ✅ | ⚠️ | ✅ | **Corredor atual — candidato a ganho alto com token grátis** | [endpoints.ai.cloud.ovh.net](https://endpoints.ai.cloud.ovh.net) · 21/08/2026 |
| 10 | Cargo-9 | `api.llm7.io/v1` | `gpt-4o-mini`, `gpt-oss-120b` | 128K | GL | **~60 req/h** anônimo (mais com token) | IP / conta | Não | ✅ | ✅ | ✅ nativo | ✅ | **Corredor atual** | [llm7.io](https://llm7.io) · 08/2026 |
| 11 | Cargo-10 | `gen.pollinations.ai/v1` (novo) / `text.pollinations.ai/openai` | `openai`, `openai-fast` | ~128K | GL | **~1 req/15s** anônimo ("queue full" no pico) | IP / conta | Não | ✅ | ✅ | ⚠️ texto | ✅ | **Corredor atual** | [pollinations.ai](https://pollinations.ai) · 05/07/2026 |
| 12 | Cargo-11 | `api-inference.modelscope.cn/v1` | `Qwen/Qwen3.5-35B-A3B` | 131K–**1M** | GL | **2.000 req/dia** (≤200–500 por modelo) ⚠️ | **conta** ⭐ | Não (telefone, na prática chinês) ⚠️ | ✅ | ✅ | ✅ | ⚠️ | Bom, mas cadastro difícil | [modelscope.cn/docs](https://modelscope.cn/docs/model-service/API-Inference/limits) · 30/06/2026 |
| 13 | Cargo-12 | `openrouter.ai/api/v1` | `z-ai/glm-5.2:free`, Nemotron, Gemma 4 | até **1M** | GL | 20 RPM · **50 req/dia** (1.000/dia só pagando US$10 uma vez → fora do nosso caso) | **conta** | Não | ✅ | ✅ | ✅ nativo (varia) | ✅ | Reserva útil | [openrouter.ai/docs/api-reference/limits](https://openrouter.ai/docs/api-reference/limits) · 08/09/2026 |
| 14 | Cargo-13 | `api.cohere.ai/compatibility/v1` | `command-a` / `command-r` | 128K | GL (trial key) | **1.000 chamadas/mês** · 20 RPM · **não comercial** ⚠️ | chave | Não | ✅ (compat.) | ✅ | ✅ | ✅ | Ok como reserva | [docs.cohere.com](https://docs.cohere.com/docs/rate-limits) · 16/08/2026 |
| 15 | Cargo-14 | `ai-gateway.vercel.sh/v1` | roteia p/ vários | varia | 🟡 crédito **US$5/mês** (acaba se um dia comprar) | crédito mensal, não renova após 1ª compra | time/conta | Não p/ começar ⚠️ | ✅ | ✅ | ✅ | ✅ | 🟡 | [vercel.com/docs/ai-gateway/pricing](https://vercel.com/docs/ai-gateway/pricing) · 19/08/2026 |
| 16 | **LongCat (Meituan)** | `api.longcat.chat/openai/v1` ⚠️ | `LongCat-Flash` | ⚠️ | 🟡 **100K tokens/dia** | diário, renovável ⚠️ | conta | Não | ✅ (+ Anthropic) | ⚠️ | ✅ | ⚠️ | 🟡 investigar | [longcat.chat](https://longcat.chat) · 07/2026 |
| 17 | Cargo-15 | `zenmux.ai/api/v1` | `z-ai/glm-5.2-free` | 200K+ ⚠️ | 🟡 modelo `-free` | rate-limited (não publicado) | conta (e-mail) | Não | ✅ | ✅ | ⚠️ | ✅ | 🟡 | [zenmux.ai](https://zenmux.ai) · 13/07/2026 |
| 18 | Cargo-16 | `api.siliconflow.cn/v1` | `Qwen3-8B`, `R1-Distill-Qwen-7B` | 131K | 🟡 modelos $0 + US$1 inicial | ~1.000 RPM nos $0 | conta | Não | ✅ | ✅ | ✅ | ⚠️ **excluído na UE/UK/CH** | 🟡 | [siliconflow.com](https://siliconflow.com) · 06/2026 |
| 19 | **Nebius AI Studio** | `api.studio.nebius.ai/v1` ⚠️ | `Qwen3-235B-A22B` | 128K | 🟡 free tier reportado | tier-based ⚠️ | conta | ⚠️ relatos divergem | ✅ | ✅ | ✅ | ⚠️ | 🟡 | [studio.nebius.ai](https://studio.nebius.ai) · 17/09/2026 |
| 20 | **Nscale** | `inference.api.nscale.com/v1` ⚠️ | `Llama-3.3-70B`, `Qwen3-Coder` | 128K | 🟡 fair-use | não publicado | conta | ⚠️ | ✅ | ⚠️ | ✅ | ⚠️ | 🟡 | [nscale.com](https://nscale.com) · 17/09/2026 |
| 21 | Cargo-17 | `llm.chutes.ai/v1` | `DeepSeek-R1`, `Llama-3.1-70B` | 131K | 🟡 **contraditório** | comunidade, sem teto publicado | conta | Não | ✅ | ✅ | ✅ | ⚠️ | 🟡 confirmar antes de usar | [chutes.ai/pricing](https://chutes.ai/pricing) diz "no free tier"; trackers dizem grátis · 08/2026 |
| 22 | Cargo-18 | `api.orcarouter.ai/v1` | `z-ai/glm-5.3-flash-free`, `deepseek-v4-flash-free` | ⚠️ | 🟡 | quota **esgotada** quando testado (08/09/2026) | conta/IP ⚠️ | ⚠️ | ✅ | ✅ | ⚠️ | ⚠️ | 🟡 relato | issue [FreePeak/onegw#38](https://github.com/FreePeak/onegw/issues/38) · 17/09/2026 |
| 23 | **Aion Labs** | ⚠️ | 11 modelos | ⚠️ | 🟡 20K tokens/dia | diário | conta | Não | ⚠️ | ⚠️ | ⚠️ | ⚠️ | 🟡 baixo valor | tracker freellm · 17/09/2026 |
| 24 | **Agnes AI / Glhf.chat** | ⚠️ | 5 / 2 modelos | ⚠️ | 🟡 "permanent free" | não publicado | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | 🟡 pouca evidência | tracker freellm · 17/09/2026 |
| 25 | Cargo-19 | `api.reka.ai/v1` | Reka Flash/Core | 128K ⚠️ | 🟡 **US$10/mês recorrente** (raro: crédito mensal que renova) | mensal | conta | ⚠️ | ✅ | ⚠️ | ⚠️ | ⚠️ | 🟡 confirmar cartão | freellmapi · 24/08/2026 |

### 🟢 Gratuito permanente (no-card confirmado)
`Google AI Studio` · `Cloudflare Workers AI` · `Groq` · `Mistral Experiment` · `Kilo Gateway (anônimo)` ·
`NVIDIA NIM` · `Z.ai GLM Flash` · `Ollama Cloud` · `OVHcloud (anônimo/token)` · `LLM7` · `Pollinations` ·
`ModelScope` · `OpenRouter :free` · `Cohere trial`

### 🟡 Gratuito com restrições / incerto (usar como reserva, não como espinha dorsal)
`Vercel AI Gateway` (crédito que morre se comprar) · `LongCat` · `ZenMux` · `SiliconFlow` · `Nebius` ·
`Nscale` · `Chutes` (contraditório) · `orcarouter` (quota esgotada) · `Aion Labs` · `Agnes AI` ·
`Glhf.chat` · `Reka`

### 🔴 Não serve (e por quê)
| Provedor | Motivo em uma linha |
| --- | --- |
| **GitHub Models** | Serviço aposentado; endpoint Azure desligado (confirma o que já sabíamos). |
| **Cerebras** | Free tier passou a exigir cartão (US$5) — confirma o diagnóstico anterior. |
| **OpenCode Zen** | Anônimo devolve 401; rotas `:free` ficaram desativadas por padrão (opt-in). |
| **SambaNova** | Free tier aposentado / só 1 modelo responde, resto devolve 402. |
| **Alibaba Model Studio (Qwen API)** | 1M tokens **por modelo, válido 90 dias** = trial, não free permanente. O tier grátis OAuth do Qwen CLI foi desligado em 15/04/2026. |
| **Anthropic (Claude API)** | Só US$5 de crédito único de teste; sem free tier de API. |
| **OpenAI (API)** | Sem créditos grátis; só o programa de compartilhar tráfego (exige tier pago/empresa). |
| **Together AI / Fireworks / DeepSeek / AI21 / SambaNova** | Créditos únicos que expiram (trial). |
| **Hugging Face Inference Providers** | US$0,10/mês de crédito — não dá para um bot em produção. |

---

## 3. 🏆 Maiores janelas de contexto gratuitas

| Modelo | Contexto | Grátis? | Cota | API | Restrições |
|---|---:|---|---|---|---|
| **Gemini 2.5/3 Flash** (Google) | **1.048.576** | ✅ permanente | 10–15 RPM · 250–1.500 RPD | OpenAI-compat | Google usa os dados do tier grátis para treino |
| **GLM-5.3 Flash** (Cloudflare) | **1.310.000** | ✅ (neurônios) | ~10k neurônios/dia | REST OpenAI-compat | Consome neurônios rápido |
| **DeepSeek V4 Flash** (Cloudflare) | **1.000.000** | ✅ (neurônios) | idem | idem | idem |
| **MiniMax M3** (Ollama Cloud) | **1.000.000** | ✅ créditos mensais | 1 req concorrente | Ollama/OpenAI | Sem números publicados |
| **DeepSeek V4 Pro/Flash** (Ollama Cloud) | **1.000.000** | ✅ | idem | idem | idem |
| **Qwen3.5 / longos** (ModelScope) | até **1.000.000** | ✅ | 2.000 RPD total | OpenAI-compat | Cadastro com telefone (na prática CN) |
| **qwen/qwen3-coder:free** (Kilo) | **262.144** | ✅ anônimo | 200 req/h por IP | OpenAI-compat | Tráfego anônimo pode ter prompt registrado |
| **Qwen3.5-397B / Kimi K2.6** (NVIDIA NIM) | **262.144** | ✅ | 40 RPM · créditos | OpenAI-compat | Créditos podem acabar |
| **Mistral Large 3** | **262.144** | ✅ | ~1B tokens/mês | OpenAI-compat | Telefone; dados podem treinar |
| **Qwen3-Coder-30B** (OVH) | **262.144** | ✅ | 2 req/min anônimo / 400 RPM com token | OpenAI-compat | Melhor custo/benefício depois de criar token |

> 🚨 **"Reserva de emergência" de contexto gigante:** `Gemini Flash` (1M, 250–1.500 req/dia) e
> `Cloudflare GLM-5.3 Flash` (1.3M, dentro dos 10k neurônios/dia) são os dois melhores para jogar o
> snapshot INTEIRO do servidor + histórico longo sem cortar nada.

---

## 4. `/v1/models` — quem suporta descoberta automática

| Provedor | Endpoint | Auth? | Serve para o mecanismo do Atlas? |
|---|---|---|---|
| Kilo | `GET api.kilo.ai/api/gateway/models` | **não** | ✅ Melhor caso: a lista traz `isFree` e `pricing` — dá para filtrar só o que é grátis |
| LLM7 | `GET api.llm7.io/v1/models` | opcional | ✅ já usamos |
| OVH | `GET .../v1/models` | opcional | ✅ |
| Pollinations | `GET gen.pollinations.ai/models` | não | ✅ (nomes ≠ aliases — manter `discovery_can_replace=False` como está hoje) |
| Groq | `GET api.groq.com/openai/v1/models` | sim | ✅ |
| OpenRouter | `GET openrouter.ai/api/v1/models` | opcional | ✅ traz `pricing` (dá para filtrar `:free`) |
| NVIDIA NIM | `GET integrate.api.nvidia.com/v1/models` | sim | ✅ |
| Mistral | `GET api.mistral.ai/v1/models` | sim | ✅ |
| Cloudflare | catálogo por API (não é `/v1/models` puro) | sim | ⚠️ exige adaptador |
| Gemini | `GET /v1beta/models` (não é OpenAI) | sim | ⚠️ exige adaptador |
| ModelScope | `GET api-inference.modelscope.cn/v1/models` ⚠️ | sim | ✅ provável |
| Ollama Cloud | `GET api.ollama.com/api/tags` ⚠️ | sim | ⚠️ formato próprio |
| Cohere | `GET api.cohere.ai/v1/models` | sim | ✅ (não é o mesmo host do chat) |

---

## 5. 🏗️ Arquitetura proposta: **FREE LLM POOL** (pool de capacidade gratuita)

> Nome correto do conceito: **pool de capacidade gratuita** / **capacidade gratuita agregada**.
> Nunca "tokens infinitos" — cada provedor tem teto; o que cresce é a soma.

### 5.1 O que o Atlas já tem (e está certo)

Corrida paralela · retry em 429 com `Retry-After` · castigo de ~30 s · redescoberta de catálogo em
`/v1/models` (cache 30 min) · duas ondas · fallback de tools para protocolo de texto · mensagem
amigável ao cliente. **Isso é 70% do FREE LLM POOL.** Falta o registro com orçamento e o disjuntor.

### 5.2 O que falta — e a minha opinião técnica sobre a sua ideia

Sua ideia de um `FREE_PROVIDERS` com `name/base_url/api_key/models/context_window/rpm/rpd/
tokens_per_day/supports_tools/supports_models/cooldown/health/last_error/last_success` é **a
arquitetura certa**. Recomendações concretas:

1. **Orçamento é por tokens, não por requisições.** O gargalo real hoje: Groq 200K tokens/dia, Gemini
   ~250K TPM, Cloudflare em neurônios. Guardar `tokens_restantes_dia` e estimar o custo da mensagem
   (prompt + tools ≈ 12k tokens) **antes** de escolher os corredores evita gCargo-12r cota em quem já
   estourou.
2. **Concorrência por provedor** (`asyncio.Semaphore` por corredor): evita que 5 mensagens simultâneas
   disparem 20 chamadas no Kilo anônimo (200/h!) e queimem a cota em 30 segundos.
3. **Disjuntor com half-open:** depois de N falhas seguidas, o corredor sai do sorteio por T segundos;
   depois disso, **uma** sonda (half-open) decide se volta. Hoje o castigo é fixo em 30 s.
4. **Detecção de 401/403 → chave inválida** (castigo longo, 30 min–24 h) e alerta no log; 404/400
   "model unavailable" → redescoberta (já pronto); 200 vazio → castigo curto (já pronto).
5. **Prioridade dinâmica:** quem respondeu ganha peso temporário (as 5 min seguintes); quem falhou
   perde peso. Simples e eficaz: `score = base + bônus_sucesso − penalidade_falha`.
6. **Terceira onda "barata":** só corredores de contexto grande e cota por conta (Gemini, Mistral,
   Cloudflare) — a primeira onda usa os anônimos (cota gratuita "infinita" mas instável) e as ondas
   seguintes gCargo-12m os corredores com cota contada.
7. **⚠️ Cuidado com quota de organização:** no Groq o limite é **por organização** — várias chaves da
   mesma conta **não** multiplicam nada. O mesmo vale no Gemini (por projeto, e projeto novo = cota
   nova **só se for uso legítimo**, nunca para burlar limite).
8. **Nunca** rotacionar contas para escapar de limite: além de violar ToS, o IP do GitHub Actions é
   compartilhado e o banimento derruba o bot inteiro.

### 5.3 Ordem de entrada sugerida (por mensagem do usuário)

```text
ONDA 1 — anônimos (custo zero de cota, IP do runner)
  kilo (200/h)  →  llm7 (~60/h)  →  pollinations (~4/min)  →  ovh anônimo (2/min)

ONDA 2 — contas com cota (usar só se a onda 1 falhar)
  ovh com token (400 RPM)  →  gemini flash (1M ctx)  →  groq (gpt-oss)  →
  zai glm-flash  →  cloudflare  →  ollama cloud

ONDA 3 — reserva de emergência (cota mensal/diária pequena, qualidade alta)
  mistral (~1B tok/mês)  →  nvidia nim  →  openrouter :free (50/dia)  →  cohere (1k/mês)
```

---

## 6. TOP 10 para colocar no Atlas primeiro

**1) KILO GATEWAY** — BASE `https://api.kilo.ai/api/gateway` · MODELO `qwen/qwen3-coder:free` (+`kilo-auto/free`) ·
CONTEXTO 262K–1M · FREE permanente · LIMITE **200 req/h por IP** · POR: IP (anônimo) · CARTÃO não ·
DATACENTER sim · TOOLS sim (nativo) · MODELS `GET /api/gateway/models` sem auth · PT-BR bom · RISCO
prompts anônimos podem ser registrados; instabilidade de gateway · OBS **maior ganho imediato: é
plug-and-play sem cadastro**.

**2) GOOGLE AI STUDIO (GEMINI)** — BASE `https://generativelanguage.googleapis.com/v1beta/openai` ·
MODELO `gemini-2.5-flash` / `gemini-3-flash` · CONTEXTO **1M** · FREE permanente · LIMITE 10–15 RPM,
250–1.500 RPD (ver console) · POR conta/projeto ⭐ · CARTÃO não · DATACENTER sim · TOOLS nativo ·
MODELS sim (adaptador) · PT-BR excelente · RISCO dados do tier grátis podem treinar modelos ·
OBS melhor combinação de contexto + cota por conta.

**3) OVHCOM AI ENDPOINTS (com token grátis)** — BASE `.../v1` · MODELO `Qwen3-Coder-30B-A3B-Instruct` /
`Meta-Llama-3_3-70B-Instruct` · CONTEXTO até 262K · FREE · LIMITE anônimo 2 req/min, **com token 400 RPM** ·
POR conta ⭐ · CARTÃO não · DATACENTER sim · TOOLS via protocolo de texto · MODELS sim · RISCO já
estouramos 429 sem token · OBS **só criar o token gratuito multiplica por ~200 o limite atual**.

**4) GROQ** — BASE `https://api.groq.com/openai/v1` · MODELO `openai/gpt-oss-120b` · CONTEXTO 128K ·
FREE · LIMITE 30 RPM · 1.000 RPD · 200K tokens/dia · POR organização · CARTÃO não · TOOLS nativo ·
MODELS sim · PT-BR ótimo · RISCO cota por organização (não multiplica com chaves extras) · OBS o mais
rápido e o mais confiável da lista.

**5) MISTRAL (EXPERIMENT)** — BASE `https://api.mistral.ai/v1` · MODELO `mistral-large-latest` /
`mistral-small-latest` · CONTEXTO até 256K · FREE · LIMITE **~1 bilhão de tokens/mês** (~1–2 RPM) ·
POR workspace ⭐ · CARTÃO não (telefone) · TOOLS nativo · RISCO 2 RPM é apertado; dados podem treinar ·
OBS a maior cota mensal gratuita que existe hoje.

**6) CLOUDFLARE WORKERS AI** — BASE `api.cloudflare.com/client/v4/accounts/{id}/ai/v1` · MODELO
`@cf/zai-org/glm-5.3-flash` (1.3M) / `@cf/google/gemma-4-26b-a4b-it` (256K) · FREE 10k neurônios/dia ·
POR conta ⭐ · CARTÃO não · TOOLS sim · MODELS via API própria · RISCO neurônios acabam rápido em
modelo grande · OBS a maior janela de contexto gratuita.

**7) Z.AI GLM FLASH** — BASE `https://api.z.ai/api/paas/v4` · MODELO `glm-4.7-flash` · CONTEXTO 131K+ ·
FREE ($0/token) · LIMITE ~1 req/s, ~1.000 req/dia ⚠️ · POR conta ⭐ · TOOLS nativo · RISCO limites não
publicados oficialmente; já cortaram limites antes · OBS excelente custo/qualidade para PT-BR.

**8) NVIDIA NIM** — BASE `https://integrate.api.nvidia.com/v1` · MODELO `moonshotai/kimi-k2.6` /
`meta/llama-3.3-70b-instruct` · CONTEXTO 128–262K · FREE (créditos; ⚠️ relatos de teto removido) ·
LIMITE 40 RPM · POR conta ⭐ · CARTÃO não · TOOLS sim · MODELS sim · RISCO créditos podem acabar ·
OBS catálogo enorme com uma chave só.

**9) LLM7.IO** — BASE `https://api.llm7.io/v1` · MODELO `gpt-4o-mini`, `gpt-oss-120b` · CONTEXTO 128K ·
FREE · LIMITE ~60 req/h anônimo (mais com token grátis) · POR IP/conta · TOOLS nativo · MODELS sim ·
RISCO catálogo muda sem aviso (já nos mordeu) · OBS **já é corredor: só precisa do token para subir a cota**.

**10) POLLINATIONS** — BASE `https://gen.pollinations.ai/v1` (novo) e `text.pollinations.ai/openai`
(atual) · MODELO `openai`, `openai-fast` · FREE · LIMITE ~1 req/15 s anônimo · POR IP · TOOLS via texto ·
RISCO "queue full for IP" no pico (nosso 429 atual) · OBS migrar para o domínio novo `gen.pollinations.ai`
pode melhorar a fila.

*(Reservas fora do top 10: Ollama Cloud, ModelScope, OpenRouter `:free`, Cohere.)*

---

## 7. Configuração pronta para os 5 melhores

### 7.1 Kilo (sem chave!)
```text
LLM_PROVIDER=kilo
LLM_BASE_URL=https://api.kilo.ai/api/gateway
LLM_MODEL=qwen/qwen3-coder:free
LLM_MODELS=kilo-auto/free,z-ai/glm-5:free,minimax/minimax-m3:free
# Sem API key: use a chave literal "anonymous"
```
**Como obter a chave:** não precisa — a comunidade usa a chave literal `anonymous` ⚠️ (confirmar no primeiro teste).
```bash
curl -sS https://api.kilo.ai/api/gateway/chat/completions \
  -H "Authorization: Bearer anonymous" -H "Content-Type: application/json" \
  -d '{"model":"qwen/qwen3-coder:free","messages":[{"role":"user","content":"Responda apenas: OK"}],"max_tokens":16}'
```
```bash
curl -sS https://api.kilo.ai/api/gateway/chat/completions \
  -H "Authorization: Bearer anonymous" -H "Content-Type: application/json" \
  -d '{"model":"qwen/qwen3-coder:free","messages":[{"role":"user","content":"Chame a ferramenta ping com ok=true."}],"tools":[{"type":"function","function":{"name":"ping","parameters":{"type":"object","properties":{"ok":{"type":"boolean"}},"required":["ok"]}}}]}'
```
Catálogo (sem auth): `curl -sS https://api.kilo.ai/api/gateway/models | head`

### 7.2 Google Gemini
```text
LLM_PROVIDER=gemini
LLM_MODEL=gemini-2.5-flash
LLM_MODELS=gemini-2.5-flash-lite
# Secret: GEMINI_API_KEY
```
**Chave:** `aistudio.google.com/apikey` → *Create API key* (só conta Google, sem cartão).
```bash
curl -sS https://generativelanguage.googleapis.com/v1beta/openai/chat/completions \
  -H "Authorization: Bearer $GEMINI_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"gemini-2.5-flash","messages":[{"role":"user","content":"Responda apenas: OK"}],"max_tokens":16}'
```

### 7.3 Groq
```text
LLM_PROVIDER=groq
LLM_MODEL=openai/gpt-oss-120b
LLM_MODELS=openai/gpt-oss-20b,llama-3.1-8b-instant
# Secret: GROQ_API_KEY
```
**Chave:** `console.groq.com/keys` (e-mail, sem cartão).
```bash
curl -sS https://api.groq.com/openai/v1/chat/completions \
  -H "Authorization: Bearer $GROQ_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"openai/gpt-oss-120b","messages":[{"role":"user","content":"Responda apenas: OK"}],"max_tokens":16}'
```

### 7.4 Mistral
```text
LLM_PROVIDER=mistral
LLM_MODEL=mistral-small-latest
LLM_MODELS=mistral-large-latest,codestral-latest
# Secret: MISTRAL_API_KEY
```
**Chave:** `console.mistral.ai` → *Experiment plan* (telefone, sem cartão).
```bash
curl -sS https://api.mistral.ai/v1/chat/completions \
  -H "Authorization: Bearer $MISTRAL_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"mistral-small-latest","messages":[{"role":"user","content":"Responda apenas: OK"}],"max_tokens":16}'
```

### 7.5 OVHcloud (token gratuito → 400 RPM)
```text
LLM_PROVIDER=meu-ovh
LLM_BASE_URL=https://oai.endpoints.kepler.ai.cloud.ovh.net/v1
LLM_MODEL=Qwen3-Coder-30B-A3B-Instruct
# Secret: LLM_API_KEY=<token do console OVH>
```
**Chave:** `endpoints.ai.cloud.ovh.net` → conta OVH → *API keys* (sem cartão).
```bash
curl -sS https://oai.endpoints.kepler.ai.cloud.ovh.net/v1/chat/completions \
  -H "Authorization: Bearer $LLM_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"Qwen3-Coder-30B-A3B-Instruct","messages":[{"role":"user","content":"Responda apenas: OK"}],"max_tokens":16}'
```

### 7.6 Teste de function calling (genérico)
Funciona em qualquer um trocando `<BASE>`/`<MODEL>`/`<CHAVE>`:
```bash
curl -sS <BASE>/chat/completions \
  -H "Authorization: Bearer <CHAVE>" -H "Content-Type: application/json" \
  -d '{"model":"<MODEL>","messages":[{"role":"user","content":"Chame a ferramenta ping com ok=true."}],
       "tools":[{"type":"function","function":{"name":"ping","description":"Teste",
       "parameters":{"type":"object","properties":{"ok":{"type":"boolean"}},"required":["ok"]}}}],"max_tokens":64}'
```

---

## 8. Respostas diretas (as 12 perguntas)

1. **Quantos provedores realmente gratuitos?** **14 com free tier permanente plausível** (🟢) +
   **12 incertos/restritos** (🟡). **4 funcionam sem cadastro nenhum**: Kilo, LLM7, Pollinations e
   OVH anônimo.
2. **Quantos com ≥128k?** **17** (praticamente todos os 🟢, menos Cohere/OpenRouter em modelos menores).
3. **Quantos com ≥200k?** **9**: Gemini (1M), Cloudflare (256K–1.3M), Mistral (256K), Kilo (262K–1M),
   NIM (262K), ModelScope (256K–1M), Ollama Cloud (262K–1M), OVH (262K), ZenMux (200K+) ⚠️.
4. **Quantos com ≥1M?** **5–6**: Gemini Flash, Cloudflare (GLM-5.3 Flash 1.3M / DeepSeek V4 Flash 1M),
   Ollama Cloud (MiniMax M3 / DeepSeek V4 = 1M), ModelScope (modelos longos), Kilo (teto do gateway).
5. **Quantos aceitam GitHub Actions/datacenter?** Praticamente todos usam API pública; nenhum documento
   exige IP residencial. **Risco maior:** os **anônimos por IP** (Kilo/LLM7/Pollinations/OVH sem token),
   porque vários usuários do Atlas compartilham o mesmo IP do runner.
6. **Quantos têm limite por conta/API key?** **12** ⭐: Gemini, Groq (por org), NIM, Cloudflare,
   Mistral, Z.ai, ModelScope, Ollama Cloud, OpenRouter, Cohere, Vercel, Chutes/SiliconFlow/Nebius/Nscale.
7. **Quantos têm function calling?** **~14** com tools nativos (Gemini, Groq, NIM, Cloudflare, Mistral,
   Z.ai, ModelScope, OpenRouter, Ollama Cloud, Kilo, Chutes, Cohere, SiliconFlow, Nebius).
8. **Quantos possuem `/v1/models`?** **12** (lista completa na seção 4); os melhores: Kilo (sem auth,
   com `isFree`) e OpenRouter (com `pricing`).
9. **Os 5 primeiros do Atlas:** **Kilo**, **OVH com token**, **Gemini Flash**, **Groq**, **Z.ai GLM Flash**.
   (Kilo e OVH são mudanças de configuração que você faz **hoje**, sem cadastro novo.)
10. **Pool final recomendado:** **8 corredores** — onda 1: kilo, llm7, pollinations, ovh-anônimo;
    onda 2: ovh-token, gemini, groq, zai; onda 3: mistral, cloudflare, ollama.
11. **Maior risco:** os gratuitos **estourarem juntos no pico** (já aconteceu) e a **quota por
    organização** (Groq/Gemini) não crescer com chaves extras — sem contar o risco de banimento se
    alguém tentar burlar limite com contas falsas. **Mitigação:** pool + ondas + mensagem amigável +
    um provedor pago opcional de US$0,50/dia como "seguro".
12. **Alternativa melhor que só somar APIs?** Sim, duas: (a) **cache de prompt** (Groq e outros dão
    desconto/tokens grátis no system prompt repetido — o nosso tem 11k chars de tools, caching ajudaria
    muito); (b) **enxugar o payload**: 27 ferramentas = 11.386 chars por chamada. Enviar só o
    subconjunto de tools relevante para o pedido reduz o consumo de cota de todos os provedores de
    uma vez (é a otimização de maior impacto e não custa nada).

---

## 9. Ação imediata recomendada (custo US$0, sem cadastro novo)

1. **Corrigir o Kilo no código** (era 404 por rota errada) → ganha um corredor de 200 req/h com 262K.
2. **Criar o token gratuito do OVH** → 2 req/min → **400 RPM**.
3. **Criar chave do Gemini** → 1M de contexto e 250–1.500 req/dia por projeto.
4. Criar chave do Groq (opcional, mas é o mais confiável).
5. Rodar a sonda ao vivo (`smoke.yml`) nos candidatos novos antes de confiar.
