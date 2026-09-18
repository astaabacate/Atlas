# Latência real por modelo do gateway Kilo

Medida pelo CI com uma chamada curta por modelo (`max_tokens=24`). É o que define a
ordem da fila do corredor: o bot usa o primeiro que responder, então o rápido vai na frente.

- executada em: 2026-09-18T01:40:02Z

| modelo | resultado | latência |
|---|---|---:|
| `thinkingmachines/inkling-small:free` | 200 vazio | 0.60s |
| `liquid/lfm-2.5-2.6b:free` | 200 vazio | 0.77s |
| `cohere/north-mini-code:free` | 200 vazio | 0.80s |
| `poolside/laguna-s-2.1:free` | 200 vazio | 1.20s |
| `kilo-auto/free` | 200 vazio | 1.30s |
| `dots-studio/dots-3-note-preview:free` | 200 vazio | 1.45s |
| `qwen/qwen3.8-27b:free` | HTTP 429 | 1.49s |
| `nvidia/nemotron-3-super-120b-a12b:free` | 200 | 1.89s |
| `stepfun/step-3.7-flash:free` | 200 vazio | 1.91s |
| `nex-agi/nex-n2.5-pro:free` | 200 | 2.23s |
| `nvidia/nemotron-3.5-lightning:free` | 200 | 3.10s |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 200 | 6.66s |
