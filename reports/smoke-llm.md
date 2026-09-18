# 🛰️ Sonda ao vivo dos provedores LLM

- executada em: 2026-09-18T00:18:48Z
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
| kilo | 200 | kilo-auto/free | 5581 ms | sim | 262K (alguns 1M) | 200 req/h por IP (anônimo) | - |

Protocolo obrigatório (GET /models → POST /chat/completions PT + tools → consecutivas → texto puro):

| corredor | GET /models | nº modelos | chat PT | tools nativo | fallback textual | 3 consecutivas | Retry-After |
|---|---|---:|---|---|---|---|---|
| kilo | 200 | 380 | 200 | sim | sim | 200/200/- | - |


Resumo: 1/1 provedores responderam; 1 com tool_call nativo.
🟢 TESTADOS E FUNCIONANDO AGORA (protocolo completo): kilo (kilo-auto/free)
