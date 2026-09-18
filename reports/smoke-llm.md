# 🛰️ Sonda ao vivo dos provedores LLM

- executada em: 2026-09-18T07:03:26Z
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
| kilo | 200 | nex-agi/nex-n2.5-pro:free | 7325 ms | sim | 262K nos rápidos · 1M nas reservas · 65… | 200 req/h por IP (anônimo) | - |

Protocolo obrigatório (GET /models → POST /chat/completions PT + tools → consecutivas → texto puro):

| corredor | GET /models | nº modelos | chat PT | tools nativo | fallback textual | 3 consecutivas | Retry-After |
|---|---|---:|---|---|---|---|---|
| kilo | 200 | 380 | 200 | sim | sim | 200/200/200 | - |


Resumo: 1/1 provedores responderam; 1 com tool_call nativo.
🟢 TESTADOS E FUNCIONANDO AGORA (protocolo completo): kilo (nex-agi/nex-n2.5-pro:free)

### Latência por modelo do pool `kilo` (uma chamada curta cada)

| modelo | resultado | latência |
|---|---|---:|
| `thinkingmachines/inkling-small:free` | HTTP 429 | 0.26s |
| `poolside/laguna-s-2.1:free` | HTTP 429 | 0.58s |
| `nex-agi/nex-n2.5-pro:free` | 200 | 0.64s |
| `nvidia/nemotron-3-super-120b-a12b:free` | 200 | 0.84s |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 200 | 0.94s |
| `qwen/qwen3.8-27b:free` | 200 | 0.99s |
| `kilo-auto/free` | 200 vazio | 1.25s |
| `dots-studio/dots-3-note-preview:free` | 200 | 1.43s |
| `liquid/lfm-2.5-2.6b:free` | 200 | 1.98s |
| `stepfun/step-3.7-flash:free` | 200 | 2.04s |
| `cohere/north-mini-code:free` | 200 | 2.68s |
| `nvidia/nemotron-3.5-lightning:free` | 200 | 14.31s |

### Candidatos sem credencial (entram no pool só com 200 ao vivo)

| candidato | GET /models | POST chat | resposta | erro |
|---|---|---|---|---|
| kilo-sem-header | 200 | 200/200 | Here's a thinking process: 1. **Analyze User Input**: The u… | - |
| opencode-zen | 200 | 400 | - | {"error":{"type":"server_error","message":"Error from provider (Console): Upstream request failed: Model is unavailable."}} |
| opencode-zen-big-pickle | 200 | 403 | - | {"type":"error","error":{"type":"FreeTierError","message":"Error from provider (Console): OpenCode's free tier can only be used from within… |
