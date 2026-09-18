# Latência real por modelo do gateway Kilo

Medida pelo CI com chamadas curtas (`max_tokens=64`) e **3 amostras por modelo por rodada**;
a coluna latência é a **mediana**. É o que define a ordem da fila do corredor: o bot usa o
primeiro que responder, então o rápido vai na frente. Uma rodada isolada oscila — a decisão
vem do histórico (`reports/kilo-latencia-historico.json`), não de um pico.

- última rodada: 2026-09-18T03:22:59Z
- rodadas no histórico: 4

## Agregado (todas as rodadas do histórico)

| modelo | resposta com conteúdo | mediana | amostras |
|---|---|---:|---:|
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 100% (4/4) | 1.30s | 4 com conteúdo |
| `nex-agi/nex-n2.5-pro:free` | 100% (4/4) | 2.13s | 4 com conteúdo |
| `nvidia/nemotron-3.5-lightning:free` | 100% (4/4) | 2.20s | 4 com conteúdo |
| `nvidia/nemotron-3-super-120b-a12b:free` | 75% (3/4) | 0.84s | 3 com conteúdo |
| `dots-studio/dots-3-note-preview:free` | 75% (3/4) | 1.43s | 3 com conteúdo |
| `kilo-auto/free` | 50% (2/4) | 1.55s | 2 com conteúdo |
| `liquid/lfm-2.5-2.6b:free` | 50% (2/4) | 1.62s | 2 com conteúdo |
| `stepfun/step-3.7-flash:free` | 50% (2/4) | 2.30s | 2 com conteúdo |
| `cohere/north-mini-code:free` | 25% (1/4) | 0.62s | 1 com conteúdo |
| `thinkingmachines/inkling-small:free` | 0% (0/4) | - | 0 com conteúdo |
| `qwen/qwen3.8-27b:free` | 0% (0/4) | - | 0 com conteúdo |
| `poolside/laguna-s-2.1:free` | 0% (0/4) | - | 0 com conteúdo |

## Última rodada (2026-09-18T03:22:59Z)

| modelo | resultado | latência (mediana de 3 amostras) |
|---|---|---:|
| `thinkingmachines/inkling-small:free` | HTTP 429 | 0.34s |
| `qwen/qwen3.8-27b:free` | HTTP 429 | 0.37s |
| `cohere/north-mini-code:free` | 200 | 0.62s |
| `nvidia/nemotron-3-super-120b-a12b:free` | 200 | 0.84s |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 200 | 1.22s |
| `kilo-auto/free` | 200 | 1.23s |
| `dots-studio/dots-3-note-preview:free` | 200 | 1.43s |
| `liquid/lfm-2.5-2.6b:free` | 200 | 1.62s |
| `nex-agi/nex-n2.5-pro:free` | 200 | 2.13s |
| `nvidia/nemotron-3.5-lightning:free` | 200 | 2.20s |
| `stepfun/step-3.7-flash:free` | 200 | 2.30s |
| `poolside/laguna-s-2.1:free` | 200 vazio | 2.36s |

_Mediana com contagem par fica com a amostra mais lenta de propósito: melhor ordenar por
pessimismo do que por sorte._
