# Latência real por modelo do gateway Kilo

Medida pelo CI com chamadas curtas (`max_tokens=64`) e **3 amostras por modelo por rodada**;
a coluna latência é a **mediana**. É o que define a ordem da fila do corredor: o bot usa o
primeiro que responder, então o rápido vai na frente. Uma rodada isolada oscila — a decisão
vem do histórico (`reports/kilo-latencia-historico.json`), não de um pico.

- última rodada: 2026-09-18T06:29:07Z
- rodadas no histórico: 8

## Agregado (todas as rodadas do histórico)

| modelo | resposta com conteúdo | mediana | amostras |
|---|---|---:|---:|
| `nex-agi/nex-n2.5-pro:free` | 100% (8/8) | 1.21s | 8 com conteúdo |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 100% (8/8) | 1.93s | 8 com conteúdo |
| `nvidia/nemotron-3.5-lightning:free` | 100% (8/8) | 2.48s | 8 com conteúdo |
| `nvidia/nemotron-3-super-120b-a12b:free` | 88% (7/8) | 0.84s | 7 com conteúdo |
| `dots-studio/dots-3-note-preview:free` | 88% (7/8) | 1.45s | 7 com conteúdo |
| `liquid/lfm-2.5-2.6b:free` | 75% (6/8) | 0.84s | 6 com conteúdo |
| `stepfun/step-3.7-flash:free` | 75% (6/8) | 2.22s | 6 com conteúdo |
| `cohere/north-mini-code:free` | 62% (5/8) | 0.81s | 5 com conteúdo |
| `kilo-auto/free` | 50% (4/8) | 1.55s | 4 com conteúdo |
| `qwen/qwen3.8-27b:free` | 12% (1/8) | 1.06s | 1 com conteúdo |
| `thinkingmachines/inkling-small:free` | 0% (0/8) | - | 0 com conteúdo |
| `poolside/laguna-s-2.1:free` | 0% (0/8) | - | 0 com conteúdo |

## Última rodada (2026-09-18T06:29:07Z)

| modelo | resultado | latência (mediana de 3 amostras) |
|---|---|---:|
| `thinkingmachines/inkling-small:free` | HTTP 429 | 0.40s |
| `cohere/north-mini-code:free` | 200 | 0.60s |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 200 | 0.63s |
| `nvidia/nemotron-3-super-120b-a12b:free` | 200 | 0.73s |
| `liquid/lfm-2.5-2.6b:free` | 200 | 0.84s |
| `nex-agi/nex-n2.5-pro:free` | 200 | 0.85s |
| `qwen/qwen3.8-27b:free` | 200 | 1.06s |
| `kilo-auto/free` | 200 | 1.13s |
| `dots-studio/dots-3-note-preview:free` | 200 | 1.36s |
| `nvidia/nemotron-3.5-lightning:free` | 200 | 2.10s |
| `stepfun/step-3.7-flash:free` | 200 | 2.22s |
| `poolside/laguna-s-2.1:free` | 200 vazio | 6.94s |

_Mediana com contagem par fica com a amostra mais lenta de propósito: melhor ordenar por
pessimismo do que por sorte._
