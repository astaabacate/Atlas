# 🛰️ Sonda ao vivo dos provedores LLM

- executada em: 2026-09-18T01:28:19Z
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
| kilo | 200 | thinkingmachines/inkling-small:free | 44009 ms | sim | 1M (vários) · 512K · 262K · 65K mínimo | 200 req/h por IP (anônimo) | - |

Protocolo obrigatório (GET /models → POST /chat/completions PT + tools → consecutivas → texto puro):

| corredor | GET /models | nº modelos | chat PT | tools nativo | fallback textual | 3 consecutivas | Retry-After |
|---|---|---:|---|---|---|---|---|
| kilo | 200 | 381 | 200 | sim | não | 200/200/200 | - |


Resumo: 1/1 provedores responderam; 1 com tool_call nativo.
🟢 TESTADOS E FUNCIONANDO AGORA (protocolo completo): kilo (thinkingmachines/inkling-small:free)

### Latência por modelo do pool `kilo` (uma chamada curta cada)

| modelo | resultado | latência |
|---|---|---:|
| `cohere/north-mini-code:free` | 200 vazio | 0.52s |
| `nvidia/nemotron-3-super-120b-a12b:free` | 200 | 0.54s |
| `qwen/qwen3.8-27b:free` | HTTP 429 | 0.56s |
| `liquid/lfm-2.5-2.6b:free` | 200 vazio | 0.66s |
| `thinkingmachines/inkling-small:free` | 200 vazio | 0.83s |
| `nex-agi/nex-n2.5-pro:free` | 200 | 0.92s |
| `kilo-auto/free` | 200 vazio | 0.99s |
| `nvidia/nemotron-3.5-lightning:free` | 200 | 1.02s |
| `dots-studio/dots-3-note-preview:free` | 200 vazio | 1.23s |
| `poolside/laguna-s-2.1:free` | 200 vazio | 1.40s |
| `stepfun/step-3.7-flash:free` | 200 vazio | 2.22s |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 200 | 7.50s |

### Candidatos sem credencial (entram no pool só com 200 ao vivo)

| candidato | GET /models | POST chat | resposta | erro |
|---|---|---|---|---|
| kilo-sem-header | 200 | 200/200 | Here's a thinking process: 1. **Analyze User Input:** The u… | - |
| opencode-zen | 200 | 400 | - | {"error":{"type":"server_error","message":"Error from provider (Console): Upstream request failed: Model is unavailable."}} |
| opencode-zen-big-pickle | 200 | 403 | - | {"type":"error","error":{"type":"FreeTierError","message":"Error from provider (Console): OpenCode's free tier can only be used from within… |
