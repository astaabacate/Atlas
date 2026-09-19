# Latência real por modelo do gateway Kilo

Medida pelo CI com chamadas curtas (`max_tokens=64`) e **3 amostras por modelo por rodada**;
a coluna latência é a **mediana**. É o que define a ordem da fila do corredor: o bot usa o
primeiro que responder, então o rápido vai na frente. Uma rodada isolada oscila — a decisão
vem do histórico (`reports/kilo-latencia-historico.json`), não de um pico.

- última rodada: 2026-09-19T00:49:31Z
- rodadas no histórico: 12

## Agregado (todas as rodadas do histórico)

| modelo | resposta com conteúdo | mediana | amostras |
|---|---|---:|---:|
| `nex-agi/nex-n2.5-pro:free` | 100% (12/12) | 0.85s | 12 com conteúdo |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 100% (12/12) | 1.93s | 12 com conteúdo |
| `nvidia/nemotron-3-super-120b-a12b:free` | 92% (11/12) | 0.84s | 11 com conteúdo |
| `dots-studio/dots-3-note-preview:free` | 92% (11/12) | 1.45s | 11 com conteúdo |
| `nvidia/nemotron-3.5-lightning:free` | 92% (11/12) | 2.48s | 11 com conteúdo |
| `liquid/lfm-2.5-2.6b:free` | 83% (10/12) | 0.84s | 10 com conteúdo |
| `stepfun/step-3.7-flash:free` | 83% (10/12) | 2.21s | 10 com conteúdo |
| `cohere/north-mini-code:free` | 75% (9/12) | 0.96s | 9 com conteúdo |
| `kilo-auto/free` | 50% (6/12) | 1.23s | 6 com conteúdo |
| `qwen/qwen3.8-27b:free` | 25% (3/12) | 0.99s | 3 com conteúdo |
| `thinkingmachines/inkling-small:free` | 8% (1/12) | 0.74s | 1 com conteúdo |
| `poolside/laguna-s-2.1:free` | 0% (0/12) | - | 0 com conteúdo |

## Última rodada (2026-09-19T00:49:31Z)

| modelo | resultado | latência (mediana de 3 amostras) |
|---|---|---:|
| `thinkingmachines/inkling-small:free` | 200 | 0.74s |
| `qwen/qwen3.8-27b:free` | 200 | 0.95s |
| `liquid/lfm-2.5-2.6b:free` | 200 | 1.08s |
| `nvidia/nemotron-3-super-120b-a12b:free` | 200 | 1.20s |
| `dots-studio/dots-3-note-preview:free` | 200 | 1.68s |
| `nex-agi/nex-n2.5-pro:free` | 200 | 1.71s |
| `cohere/north-mini-code:free` | 200 | 1.77s |
| `stepfun/step-3.7-flash:free` | 200 | 1.91s |
| `kilo-auto/free` | 200 vazio | 2.73s |
| `poolside/laguna-s-2.1:free` | 200 vazio | 2.92s |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 200 | 5.48s |
| `nvidia/nemotron-3.5-lightning:free` | TimeoutError | 60.54s |

_Mediana com contagem par fica com a amostra mais lenta de propósito: melhor ordenar por
pessimismo do que por sorte._
