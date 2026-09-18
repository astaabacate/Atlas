# Latência real por modelo do gateway Kilo

Medida pelo CI com chamadas curtas (`max_tokens=64`) e **3 amostras por modelo por rodada**;
a coluna latência é a **mediana**. É o que define a ordem da fila do corredor: o bot usa o
primeiro que responder, então o rápido vai na frente. Uma rodada isolada oscila — a decisão
vem do histórico (`reports/kilo-latencia-historico.json`), não de um pico.

- última rodada: 2026-09-18T10:20:39Z
- rodadas no histórico: 10

## Agregado (todas as rodadas do histórico)

| modelo | resposta com conteúdo | mediana | amostras |
|---|---|---:|---:|
| `nex-agi/nex-n2.5-pro:free` | 100% (10/10) | 0.85s | 10 com conteúdo |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 100% (10/10) | 1.93s | 10 com conteúdo |
| `nvidia/nemotron-3.5-lightning:free` | 100% (10/10) | 3.10s | 10 com conteúdo |
| `nvidia/nemotron-3-super-120b-a12b:free` | 90% (9/10) | 0.84s | 9 com conteúdo |
| `dots-studio/dots-3-note-preview:free` | 90% (9/10) | 1.43s | 9 com conteúdo |
| `liquid/lfm-2.5-2.6b:free` | 80% (8/10) | 0.84s | 8 com conteúdo |
| `stepfun/step-3.7-flash:free` | 80% (8/10) | 2.21s | 8 com conteúdo |
| `cohere/north-mini-code:free` | 70% (7/10) | 0.91s | 7 com conteúdo |
| `kilo-auto/free` | 50% (5/10) | 1.23s | 5 com conteúdo |
| `qwen/qwen3.8-27b:free` | 20% (2/10) | 1.06s | 2 com conteúdo |
| `thinkingmachines/inkling-small:free` | 0% (0/10) | - | 0 com conteúdo |
| `poolside/laguna-s-2.1:free` | 0% (0/10) | - | 0 com conteúdo |

## Última rodada (2026-09-18T10:20:39Z)

| modelo | resultado | latência (mediana de 3 amostras) |
|---|---|---:|
| `qwen/qwen3.8-27b:free` | HTTP 429 | 0.31s |
| `poolside/laguna-s-2.1:free` | HTTP 429 | 0.39s |
| `thinkingmachines/inkling-small:free` | HTTP 429 | 0.40s |
| `liquid/lfm-2.5-2.6b:free` | 200 | 0.55s |
| `nex-agi/nex-n2.5-pro:free` | 200 | 0.67s |
| `nvidia/nemotron-3-super-120b-a12b:free` | 200 | 0.70s |
| `cohere/north-mini-code:free` | 200 | 0.91s |
| `kilo-auto/free` | 200 | 1.20s |
| `dots-studio/dots-3-note-preview:free` | 200 | 1.26s |
| `stepfun/step-3.7-flash:free` | 200 | 2.01s |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 200 | 2.73s |
| `nvidia/nemotron-3.5-lightning:free` | 200 | 4.17s |

_Mediana com contagem par fica com a amostra mais lenta de propósito: melhor ordenar por
pessimismo do que por sorte._
