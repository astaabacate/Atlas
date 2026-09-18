# Latência real por modelo do gateway Kilo

Medida pelo CI com chamadas curtas (`max_tokens=64`) e **3 amostras por modelo por rodada**;
a coluna latência é a **mediana**. É o que define a ordem da fila do corredor: o bot usa o
primeiro que responder, então o rápido vai na frente. Uma rodada isolada oscila — a decisão
vem do histórico (`reports/kilo-latencia-historico.json`), não de um pico.

- última rodada: 2026-09-18T05:22:22Z
- rodadas no histórico: 6

## Agregado (todas as rodadas do histórico)

| modelo | resposta com conteúdo | mediana | amostras |
|---|---|---:|---:|
| `nex-agi/nex-n2.5-pro:free` | 100% (6/6) | 1.56s | 6 com conteúdo |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 100% (6/6) | 2.01s | 6 com conteúdo |
| `nvidia/nemotron-3.5-lightning:free` | 100% (6/6) | 2.48s | 6 com conteúdo |
| `nvidia/nemotron-3-super-120b-a12b:free` | 83% (5/6) | 0.84s | 5 com conteúdo |
| `dots-studio/dots-3-note-preview:free` | 83% (5/6) | 1.45s | 5 com conteúdo |
| `liquid/lfm-2.5-2.6b:free` | 67% (4/6) | 1.50s | 4 com conteúdo |
| `stepfun/step-3.7-flash:free` | 67% (4/6) | 2.21s | 4 com conteúdo |
| `cohere/north-mini-code:free` | 50% (3/6) | 0.81s | 3 com conteúdo |
| `kilo-auto/free` | 50% (3/6) | 1.55s | 3 com conteúdo |
| `thinkingmachines/inkling-small:free` | 0% (0/6) | - | 0 com conteúdo |
| `qwen/qwen3.8-27b:free` | 0% (0/6) | - | 0 com conteúdo |
| `poolside/laguna-s-2.1:free` | 0% (0/6) | - | 0 com conteúdo |

## Última rodada (2026-09-18T05:22:22Z)

| modelo | resultado | latência (mediana de 3 amostras) |
|---|---|---:|
| `thinkingmachines/inkling-small:free` | HTTP 429 | 0.38s |
| `qwen/qwen3.8-27b:free` | HTTP 429 | 0.47s |
| `poolside/laguna-s-2.1:free` | HTTP 429 | 0.74s |
| `nex-agi/nex-n2.5-pro:free` | 200 | 0.79s |
| `liquid/lfm-2.5-2.6b:free` | 200 | 0.80s |
| `cohere/north-mini-code:free` | 200 | 0.80s |
| `nvidia/nemotron-3-super-120b-a12b:free` | 200 | 0.84s |
| `dots-studio/dots-3-note-preview:free` | 200 | 1.51s |
| `kilo-auto/free` | 200 | 1.91s |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 200 | 2.01s |
| `stepfun/step-3.7-flash:free` | 200 | 2.02s |
| `nvidia/nemotron-3.5-lightning:free` | 200 | 2.48s |

_Mediana com contagem par fica com a amostra mais lenta de propósito: melhor ordenar por
pessimismo do que por sorte._
