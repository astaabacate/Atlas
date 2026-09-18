# Latência real por modelo do gateway Kilo

Medida pelo CI com chamadas curtas (`max_tokens=64`) e **3 amostras por modelo por rodada**;
a coluna latência é a **mediana**. É o que define a ordem da fila do corredor: o bot usa o
primeiro que responder, então o rápido vai na frente. Uma rodada isolada oscila — a decisão
vem do histórico (`reports/kilo-latencia-historico.json`), não de um pico.

- última rodada: 2026-09-18T07:03:23Z
- rodadas no histórico: 9

## Agregado (todas as rodadas do histórico)

| modelo | resposta com conteúdo | mediana | amostras |
|---|---|---:|---:|
| `nex-agi/nex-n2.5-pro:free` | 100% (9/9) | 0.85s | 9 com conteúdo |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 100% (9/9) | 1.30s | 9 com conteúdo |
| `nvidia/nemotron-3.5-lightning:free` | 100% (9/9) | 2.48s | 9 com conteúdo |
| `nvidia/nemotron-3-super-120b-a12b:free` | 89% (8/9) | 0.84s | 8 com conteúdo |
| `dots-studio/dots-3-note-preview:free` | 89% (8/9) | 1.45s | 8 com conteúdo |
| `liquid/lfm-2.5-2.6b:free` | 78% (7/9) | 0.84s | 7 com conteúdo |
| `stepfun/step-3.7-flash:free` | 78% (7/9) | 2.21s | 7 com conteúdo |
| `cohere/north-mini-code:free` | 67% (6/9) | 0.96s | 6 com conteúdo |
| `kilo-auto/free` | 44% (4/9) | 1.55s | 4 com conteúdo |
| `qwen/qwen3.8-27b:free` | 22% (2/9) | 1.06s | 2 com conteúdo |
| `thinkingmachines/inkling-small:free` | 0% (0/9) | - | 0 com conteúdo |
| `poolside/laguna-s-2.1:free` | 0% (0/9) | - | 0 com conteúdo |

## Última rodada (2026-09-18T07:03:23Z)

| modelo | resultado | latência (mediana de 3 amostras) |
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

_Mediana com contagem par fica com a amostra mais lenta de propósito: melhor ordenar por
pessimismo do que por sorte._
