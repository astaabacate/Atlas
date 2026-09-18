# Latência real por modelo do gateway Kilo

Medida pelo CI com chamadas curtas (`max_tokens=64`) e **3 amostras por modelo por rodada**;
a coluna latência é a **mediana**. É o que define a ordem da fila do corredor: o bot usa o
primeiro que responder, então o rápido vai na frente. Uma rodada isolada oscila — a decisão
vem do histórico (`reports/kilo-latencia-historico.json`), não de um pico.

- última rodada: 2026-09-18T03:16:31Z
- rodadas no histórico: 3

## Agregado (todas as rodadas do histórico)

| modelo | resposta com conteúdo | mediana | amostras |
|---|---|---:|---:|
| `nex-agi/nex-n2.5-pro:free` | 100% (3/3) | 0.78s | 3 com conteúdo |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 100% (3/3) | 1.30s | 3 com conteúdo |
| `dots-studio/dots-3-note-preview:free` | 67% (2/3) | 1.81s | 2 com conteúdo |
| `nvidia/nemotron-3-super-120b-a12b:free` | 67% (2/3) | 1.89s | 2 com conteúdo |
| `nvidia/nemotron-3.5-lightning:free` | 100% (3/3) | 2.15s | 3 com conteúdo |
| `liquid/lfm-2.5-2.6b:free` | 33% (1/3) | 0.57s | 1 com conteúdo |
| `kilo-auto/free` | 33% (1/3) | 1.55s | 1 com conteúdo |
| `stepfun/step-3.7-flash:free` | 33% (1/3) | 2.21s | 1 com conteúdo |
| `thinkingmachines/inkling-small:free` | 0% (0/3) | - | 0 com conteúdo |
| `qwen/qwen3.8-27b:free` | 0% (0/3) | - | 0 com conteúdo |
| `poolside/laguna-s-2.1:free` | 0% (0/3) | - | 0 com conteúdo |
| `cohere/north-mini-code:free` | 0% (0/3) | - | 0 com conteúdo |

## Última rodada (2026-09-18T03:16:31Z)

| modelo | resultado | latência (mediana de 3 amostras) |
|---|---|---:|
| `thinkingmachines/inkling-small:free` | HTTP 429 | 0.40s |
| `qwen/qwen3.8-27b:free` | HTTP 429 | 0.41s |
| `liquid/lfm-2.5-2.6b:free` | 200 | 0.57s |
| `nvidia/nemotron-3-super-120b-a12b:free` | 200 | 0.66s |
| `nex-agi/nex-n2.5-pro:free` | 200 | 0.78s |
| `cohere/north-mini-code:free` | 200 vazio | 0.98s |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 200 | 1.30s |
| `kilo-auto/free` | 200 | 1.55s |
| `poolside/laguna-s-2.1:free` | 200 vazio | 1.75s |
| `dots-studio/dots-3-note-preview:free` | 200 | 1.81s |
| `nvidia/nemotron-3.5-lightning:free` | 200 | 2.15s |
| `stepfun/step-3.7-flash:free` | 200 | 2.21s |

_Mediana com contagem par fica com a amostra mais lenta de propósito: melhor ordenar por
pessimismo do que por sorte._
