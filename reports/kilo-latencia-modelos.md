# Latência real por modelo do gateway Kilo

Medida pelo CI com chamadas curtas (`max_tokens=64`) e **3 amostras por modelo por rodada**;
a coluna latência é a **mediana**. É o que define a ordem da fila do corredor: o bot usa o
primeiro que responder, então o rápido vai na frente. Uma rodada isolada oscila — a decisão
vem do histórico (`reports/kilo-latencia-historico.json`), não de um pico.

- última rodada: 2026-09-18T06:26:00Z
- rodadas no histórico: 7

## Agregado (todas as rodadas do histórico)

| modelo | resposta com conteúdo | mediana | amostras |
|---|---|---:|---:|
| `nex-agi/nex-n2.5-pro:free` | 100% (7/7) | 1.21s | 7 com conteúdo |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 100% (7/7) | 1.93s | 7 com conteúdo |
| `nvidia/nemotron-3.5-lightning:free` | 100% (7/7) | 2.48s | 7 com conteúdo |
| `nvidia/nemotron-3-super-120b-a12b:free` | 86% (6/7) | 0.97s | 6 com conteúdo |
| `dots-studio/dots-3-note-preview:free` | 86% (6/7) | 1.51s | 6 com conteúdo |
| `liquid/lfm-2.5-2.6b:free` | 71% (5/7) | 0.80s | 5 com conteúdo |
| `stepfun/step-3.7-flash:free` | 71% (5/7) | 2.21s | 5 com conteúdo |
| `cohere/north-mini-code:free` | 57% (4/7) | 0.96s | 4 com conteúdo |
| `kilo-auto/free` | 43% (3/7) | 1.55s | 3 com conteúdo |
| `thinkingmachines/inkling-small:free` | 0% (0/7) | - | 0 com conteúdo |
| `qwen/qwen3.8-27b:free` | 0% (0/7) | - | 0 com conteúdo |
| `poolside/laguna-s-2.1:free` | 0% (0/7) | - | 0 com conteúdo |

## Última rodada (2026-09-18T06:26:00Z)

| modelo | resultado | latência (mediana de 3 amostras) |
|---|---|---:|
| `thinkingmachines/inkling-small:free` | HTTP 429 | 0.36s |
| `liquid/lfm-2.5-2.6b:free` | 200 | 0.61s |
| `nex-agi/nex-n2.5-pro:free` | 200 | 1.21s |
| `kilo-auto/free` | 200 vazio | 1.50s |
| `dots-studio/dots-3-note-preview:free` | 200 | 1.60s |
| `nvidia/nemotron-3-super-120b-a12b:free` | 200 | 1.76s |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 200 | 1.93s |
| `qwen/qwen3.8-27b:free` | 200 vazio | 2.16s |
| `poolside/laguna-s-2.1:free` | 200 vazio | 2.34s |
| `cohere/north-mini-code:free` | 200 | 2.74s |
| `stepfun/step-3.7-flash:free` | 200 | 3.39s |
| `nvidia/nemotron-3.5-lightning:free` | 200 | 44.00s |

_Mediana com contagem par fica com a amostra mais lenta de propósito: melhor ordenar por
pessimismo do que por sorte._
