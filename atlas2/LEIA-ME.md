# Atlas 2 — o bot feito do zero (19/09/2026)

Código novo, sem nada do bot antigo. A ideia é simples:

> **Comando reconhecido não passa por IA.**

Era isso que causava a demora (e o erro de responder a ficha do servidor quando o pedido era
apagar canais): o pedido ia para um modelo, o modelo pensava 2–4s e às vezes respondia outra
coisa. Aqui o pedido é lido no próprio processo — custa menos de 1 milissegundo — e a ação roda
direto na API do Discord.

## Como funciona cada mensagem

1. **👀 na hora** — a pessoa vê que o bot ouviu antes de qualquer coisa.
2. **Parser local** (`atlas2/parse.py`): entende o pedido em PT-BR e executa (`atlas2/actions.py`).
   Nada de rede, nada de espera. É aqui que vive o "zero delay".
3. **Se não for reconhecido**, aí sim vai para o OmniRoute (`atlas2/llm.py`) — com **streaming**:
   o texto aparece na tela conforme o modelo escreve, em vez de só no fim. O modelo pode chamar
   as mesmas ações do caminho rápido, então ele nunca fica sem poder fazer nada.

## O que ele entende sem IA (exemplos)

| Pedido | O que faz |
| --- | --- |
| `apague todos os canais e deixe apenas esse` | apaga todos menos o canal da conversa, confere na API e diz o que sobrou, se sobrar |
| `apague os canais caps-voz, caps-texto` | apaga exatamente esses |
| `crie 5 canais` / `crie um canal de voz chamado sala-1` | cria (nome ou quantidade) |
| `crie a categoria Testes com os canais um e dois` | cria a categoria e os canais dentro |
| `renomeie o canal geral para bate-papo` | renomeia |
| `mova o canal regras para a categoria Informações` | move |
| `recrie o canal caps-voz` | apaga e devolve igual (nunca duplica) |
| `crie o cargo Moderador vermelho` / `apague o cargo VIP` | cargos (cor por nome ou `#RRGGBB`) |
| `apague as mensagens desse canal` | limpa o chat (não apaga o canal) |
| `liste os canais` / `liste os cargos` / `informações do servidor` | mostra |
| `tempo` | quantos segundos o bot está levando |

Qualquer outra coisa vai para o OmniRoute com essa mesma caixa de ferramentas.

## Ligar / desligar

- `.github/atlas2-on` presente no ramo = **ligado** (workflow `Atlas 2 (novo)`).
- Sem o arquivo = desligado (o workflow passa reto).

⚠️ **Um bot por token.** Se o bot antigo (`Atlas Bot 24/7`) estiver ligado, o novo não pode
entrar ao mesmo tempo: os dois respondem a mesma mensagem. Para trocar, num MESMO commit:
cria `.github/atlas2-on` (liga o novo) **e** cria `.github/bot-disabled` (interruptor do antigo).

## Configuração (Settings → Secrets and variables → Actions)

| Nome | Tipo | Para quê |
| --- | --- | --- |
| `DISCORD_TOKEN` | segredo | já existe — é o mesmo bot |
| `OMNIROUTE_URL` | variável | endereço do gateway, terminando em `/v1` |
| `OMNIROUTE_KEY` | segredo | chave do gateway (gere uma nova; nunca no código) |
| `OMNIROUTE_MODEL` | variável | opcional, padrão `auto` |
| `CANAIS_PERMITIDOS` | variável | opcional: ids de canais onde o bot responde sem ser marcado |

Sem `OMNIROUTE_URL`/`OMNIROUTE_KEY` o bot funciona nos comandos reconhecidos e avisa, num pedido
livre, que a IA não está configurada.

## Rodar na sua máquina

```bash
pip install -r requirements.txt
DISCORD_TOKEN=... OMNIROUTE_URL=https://SEU-ENDEREÇO/v1 OMNIROUTE_KEY=... python -m atlas2.run
```
