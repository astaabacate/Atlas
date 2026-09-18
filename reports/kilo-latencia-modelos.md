# Latência real por modelo do gateway Kilo

Medida pelo CI com chamadas curtas (`max_tokens=64`) e **3 amostras por modelo por rodada**;
a coluna latência é a **mediana**. É o que define a ordem da fila do corredor: o bot usa o
primeiro que responder, então o rápido vai na frente. Uma rodada isolada oscila — a decisão
vem do histórico (`reports/kilo-latencia-historico.json`), não de um pico.

- última rodada: 2026-09-18T02:53:24Z
- rodadas no histórico: 2

## Agregado (todas as rodadas do histórico)

| modelo | resposta com conteúdo | mediana | amostras |
|---|---|---:|---:|
| `dots-studio/dots-3-note-preview:free` | 50% (1/2) | 1.18s | 1 com conteúdo |
| `nvidia/nemotron-3-super-120b-a12b:free` | 50% (1/2) | 1.89s | 1 com conteúdo |
| `nex-agi/nex-n2.5-pro:free` | 100% (2/2) | 2.23s | 2 com conteúdo |
| `nvidia/nemotron-3.5-lightning:free` | 100% (2/2) | 3.10s | 2 com conteúdo |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 100% (2/2) | 6.66s | 2 com conteúdo |
| `thinkingmachines/inkling-small:free` | 0% (0/2) | - | 0 com conteúdo |
| `qwen/qwen3.8-27b:free` | 0% (0/2) | - | 0 com conteúdo |
| `poolside/laguna-s-2.1:free` | 0% (0/2) | - | 0 com conteúdo |
| `liquid/lfm-2.5-2.6b:free` | 0% (0/2) | - | 0 com conteúdo |
| `cohere/north-mini-code:free` | 0% (0/2) | - | 0 com conteúdo |
| `kilo-auto/free` | 0% (0/2) | - | 0 com conteúdo |
| `stepfun/step-3.7-flash:free` | 0% (0/2) | - | 0 com conteúdo |

## Última rodada (2026-09-18T02:53:24Z)

| modelo | resultado | latência (mediana de 1 amostras) |
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

_Mediana com contagem par fica com a amostra mais lenta de propósito: melhor ordenar por
pessimismo do que por sorte._
