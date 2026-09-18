# Latência real por modelo do gateway Kilo

Medida pelo CI com chamadas curtas (`max_tokens=64`) e **3 amostras por modelo por rodada**;
a coluna latência é a **mediana**. É o que define a ordem da fila do corredor: o bot usa o
primeiro que responder, então o rápido vai na frente. Uma rodada isolada oscila — a decisão
vem do histórico (`reports/kilo-latencia-historico.json`), não de um pico.

- última rodada: 2026-09-18T10:41:18Z
- rodadas no histórico: 11

## Agregado (todas as rodadas do histórico)

| modelo | resposta com conteúdo | mediana | amostras |
|---|---|---:|---:|
| `nex-agi/nex-n2.5-pro:free` | 100% (11/11) | 0.79s | 11 com conteúdo |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 100% (11/11) | 1.30s | 11 com conteúdo |
| `nvidia/nemotron-3.5-lightning:free` | 100% (11/11) | 2.48s | 11 com conteúdo |
| `nvidia/nemotron-3-super-120b-a12b:free` | 91% (10/11) | 0.84s | 10 com conteúdo |
| `dots-studio/dots-3-note-preview:free` | 91% (10/11) | 1.45s | 10 com conteúdo |
| `liquid/lfm-2.5-2.6b:free` | 82% (9/11) | 0.80s | 9 com conteúdo |
| `stepfun/step-3.7-flash:free` | 82% (9/11) | 2.21s | 9 com conteúdo |
| `cohere/north-mini-code:free` | 73% (8/11) | 0.96s | 8 com conteúdo |
| `kilo-auto/free` | 55% (6/11) | 1.23s | 6 com conteúdo |
| `qwen/qwen3.8-27b:free` | 18% (2/11) | 1.06s | 2 com conteúdo |
| `thinkingmachines/inkling-small:free` | 0% (0/11) | - | 0 com conteúdo |
| `poolside/laguna-s-2.1:free` | 0% (0/11) | - | 0 com conteúdo |

## Última rodada (2026-09-18T10:41:18Z)

| modelo | resultado | latência (mediana de 3 amostras) |
|---|---|---:|
| `thinkingmachines/inkling-small:free` | HTTP 429 | 0.41s |
| `liquid/lfm-2.5-2.6b:free` | 200 | 0.61s |
| `nex-agi/nex-n2.5-pro:free` | 200 | 0.76s |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 200 | 0.90s |
| `kilo-auto/free` | 200 | 1.18s |
| `dots-studio/dots-3-note-preview:free` | 200 | 1.56s |
| `nvidia/nemotron-3-super-120b-a12b:free` | 200 | 1.58s |
| `cohere/north-mini-code:free` | 200 | 2.15s |
| `nvidia/nemotron-3.5-lightning:free` | 200 | 2.21s |
| `stepfun/step-3.7-flash:free` | 200 | 2.24s |
| `poolside/laguna-s-2.1:free` | 200 vazio | 3.76s |
| `qwen/qwen3.8-27b:free` | 200 vazio | 5.01s |

_Mediana com contagem par fica com a amostra mais lenta de propósito: melhor ordenar por
pessimismo do que por sorte._
