# Latência real por modelo do gateway Kilo

Medida pelo CI com uma chamada curta por modelo (`max_tokens=24`). É o que define a
ordem da fila do corredor: o bot usa o primeiro que responder, então o rápido vai na frente.

- executada em: 2026-09-18T02:53:24Z

| modelo | resultado | latência |
|---|---|---:|
| `thinkingmachines/inkling-small:free` | HTTP 429 | 0.35s |
| `qwen/qwen3.8-27b:free` | HTTP 429 | 0.46s |
| `poolside/laguna-s-2.1:free` | HTTP 429 | 0.49s |
| `liquid/lfm-2.5-2.6b:free` | 200 vazio | 0.55s |
| `nex-agi/nex-n2.5-pro:free` | 200 | 0.66s |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 200 | 0.69s |
| `cohere/north-mini-code:free` | 200 vazio | 0.85s |
| `nvidia/nemotron-3-super-120b-a12b:free` | 200 vazio | 1.10s |
| `dots-studio/dots-3-note-preview:free` | 200 | 1.18s |
| `kilo-auto/free` | 200 vazio | 1.43s |
| `nvidia/nemotron-3.5-lightning:free` | 200 | 1.58s |
| `stepfun/step-3.7-flash:free` | 200 vazio | 1.98s |
