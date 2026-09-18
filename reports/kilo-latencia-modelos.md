# Latência real por modelo do gateway Kilo

Medida pelo CI com chamadas curtas (`max_tokens=64`) e **3 amostras por modelo por rodada**;
a coluna latência é a **mediana**. É o que define a ordem da fila do corredor: o bot usa o
primeiro que responder, então o rápido vai na frente. Uma rodada isolada oscila — a decisão
vem do histórico (`reports/kilo-latencia-historico.json`), não de um pico.

- última rodada: 2026-09-18T03:28:36Z
- rodadas no histórico: 5

## Agregado (todas as rodadas do histórico)

| modelo | resposta com conteúdo | mediana | amostras |
|---|---|---:|---:|
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 100% (5/5) | 1.30s | 5 com conteúdo |
| `nex-agi/nex-n2.5-pro:free` | 100% (5/5) | 1.56s | 5 com conteúdo |
| `nvidia/nemotron-3.5-lightning:free` | 100% (5/5) | 2.20s | 5 com conteúdo |
| `nvidia/nemotron-3-super-120b-a12b:free` | 80% (4/5) | 0.97s | 4 com conteúdo |
| `dots-studio/dots-3-note-preview:free` | 80% (4/5) | 1.45s | 4 com conteúdo |
| `liquid/lfm-2.5-2.6b:free` | 60% (3/5) | 1.50s | 3 com conteúdo |
| `stepfun/step-3.7-flash:free` | 60% (3/5) | 2.21s | 3 com conteúdo |
| `cohere/north-mini-code:free` | 40% (2/5) | 0.96s | 2 com conteúdo |
| `kilo-auto/free` | 40% (2/5) | 1.55s | 2 com conteúdo |
| `thinkingmachines/inkling-small:free` | 0% (0/5) | - | 0 com conteúdo |
| `qwen/qwen3.8-27b:free` | 0% (0/5) | - | 0 com conteúdo |
| `poolside/laguna-s-2.1:free` | 0% (0/5) | - | 0 com conteúdo |

## Última rodada (2026-09-18T03:28:36Z)

| modelo | resultado | latência (mediana de 3 amostras) |
|---|---|---:|
| `thinkingmachines/inkling-small:free` | HTTP 429 | 0.41s |
| `qwen/qwen3.8-27b:free` | HTTP 429 | 0.48s |
| `cohere/north-mini-code:free` | 200 | 0.96s |
| `nvidia/nemotron-3-super-120b-a12b:free` | 200 | 0.97s |
| `dots-studio/dots-3-note-preview:free` | 200 | 1.45s |
| `liquid/lfm-2.5-2.6b:free` | 200 | 1.50s |
| `nex-agi/nex-n2.5-pro:free` | 200 | 1.56s |
| `stepfun/step-3.7-flash:free` | 200 | 2.18s |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 200 | 2.32s |
| `poolside/laguna-s-2.1:free` | 200 vazio | 4.05s |
| `nvidia/nemotron-3.5-lightning:free` | 200 | 4.61s |
| `kilo-auto/free` | 200 vazio | 5.97s |

_Mediana com contagem par fica com a amostra mais lenta de propósito: melhor ordenar por
pessimismo do que por sorte._
