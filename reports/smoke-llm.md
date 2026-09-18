# 🛰️ Sonda ao vivo dos provedores LLM

- executada em: 2026-09-18T10:41:22Z
- python: 3.11.16

Pool gratuito ativo: kilo
Fora do pool por falta de credencial (cadastre como secret para ativar):
- gemini (falta o secret GEMINI_API_KEY)
- groq (falta o secret GROQ_API_KEY)
- mistral (falta o secret MISTRAL_API_KEY)
- nvidia (falta o secret NVIDIA_API_KEY)
- zai (falta o secret ZAI_API_KEY)
- cloudflare (falta o secret CLOUDFLARE_API_TOKEN)
- ollama (falta o secret OLLAMA_API_KEY)
- openrouter (falta o secret OPENROUTER_API_KEY)
- modelscope (falta o secret MODELSCOPE_API_KEY)
- siliconflow (falta o secret SILICONFLOW_API_KEY)
- cohere (falta o secret COHERE_API_KEY)

Corredores sondados: kilo (AutoProvider.create_default)

| corredor | status HTTP | modelo que respondeu | latência | tool_call nativo? | contexto | cota | erro compactado |
|---|---:|---|---:|:---:|---|---|---|
| kilo | - | nex-agi/nex-n2.5-pro:free | 778 ms | não | 262K nos rápidos · 1M nas reservas · 65… | 200 req/h por IP (anônimo) | TypeError: install_openai_compatible_tracker. .tracked_post() takes 5 positional arguments but 6 were given |

Protocolo obrigatório (GET /models → POST /chat/completions PT + tools → consecutivas → texto puro):

| corredor | GET /models | nº modelos | chat PT | tools nativo | fallback textual | 3 consecutivas | Retry-After |
|---|---|---:|---|---|---|---|---|
| kilo | 200 | 380 | - | não | não | - | - |


Resumo: 0/1 provedores responderam; 0 com tool_call nativo.
🔴 não responderam nesta rodada: kilo

### Latência por modelo do pool `kilo` (uma chamada curta cada)

| modelo | resultado | latência |
|---|---|---:|
| `thinkingmachines/inkling-small:free` | HTTP 429 | 0.41s |
| `liquid/lfm-2.5-2.6b:free` | 200 | 0.61s |
| `nex-agi/nex-n2.5-pro:free` | 200 | 0.76s |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 200 | 0.90s |
| `kilo-auto/free` | 200 | 1.18s |
| `dots-studio/dots-3-note-preview:free` | 200 | 1.56s |
| `nvidia/nemotron-3-super-120b-a12b:free` | 200 | 1.58s |
| `cohere/north-mini-code:free` | 200 | 2.15s |
| `nvidia/nemotron-3.5-lightning:free` | 200 | 2.21s |
| `stepfun/step-3.7-flash:free` | 200 | 2.24s |
| `poolside/laguna-s-2.1:free` | 200 vazio | 3.76s |
| `qwen/qwen3.8-27b:free` | 200 vazio | 5.01s |

### Candidatos sem credencial (entram no pool só com 200 ao vivo)

| candidato | GET /models | POST chat | resposta | erro |
|---|---|---|---|---|
| kilo-sem-header | 200 | 200 | OK · catálogo em reports/kilo-modelos-free.md | - |
| opencode-zen | 200 | 400 | - | {"error":{"type":"server_error","message":"Error from provider (Console): Upstream request failed: Model is unavailable."}} |
| opencode-zen-big-pickle | 200 | 403 | - | {"type":"error","error":{"type":"FreeTierError","message":"Error from provider (Console): OpenCode's free tier can only be used from within… |
