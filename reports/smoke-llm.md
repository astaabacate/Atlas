# 🛰️ Sonda ao vivo dos provedores LLM

- executada em: 2026-09-18T01:17:08Z
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
| kilo | 200 | thinkingmachines/inkling-small:free | 16347 ms | sim | 1M (vários) · 512K · 262K · 65K mínimo | 200 req/h por IP (anônimo) | - |

Protocolo obrigatório (GET /models → POST /chat/completions PT + tools → consecutivas → texto puro):

| corredor | GET /models | nº modelos | chat PT | tools nativo | fallback textual | 3 consecutivas | Retry-After |
|---|---|---:|---|---|---|---|---|
| kilo | 200 | 381 | 200 | sim | sim | 200/200/200 | - |


Resumo: 1/1 provedores responderam; 1 com tool_call nativo.
🟢 TESTADOS E FUNCIONANDO AGORA (protocolo completo): kilo (thinkingmachines/inkling-small:free)

### Candidatos sem credencial (entram no pool só com 200 ao vivo)

| candidato | GET /models | POST chat | resposta | erro |
|---|---|---|---|---|
| kilo-sem-header | 200 | 200/200 | Here's a thinking process: 1. **Analyze User Input:** The u… | - |
| opencode-zen | 200 | 400 | - | {"error":{"type":"server_error","message":"Error from provider (Console): Upstream request failed: Model is unavailable."}} |
| opencode-zen-big-pickle | 200 | 403 | - | {"type":"error","error":{"type":"FreeTierError","message":"Error from provider (Console): OpenCode's free tier can only be used from within… |
