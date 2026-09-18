# 🏮 Farol — Chatbot Discord de Estruturação e Organização

> **O bot de Discord que conversa e EXECUTA.**
> 100% gratuito, sem chave de IA obrigatória, sem comandos slash para decorar e online 24/7 hospedado no GitHub Actions.

---

## 📖 1. Visão Geral

O **Farol** é um bot de Discord em Python (`discord.py` 2.x) projetado para **ouvir em linguagem natural e alterar o servidor na prática**. Em vez de obrigar o usuário a decorar dezenas de comandos de barra (`/`), você simplesmente marca `@farol` e pede o que precisa. O Farol interpreta via Inteligência Artificial, aciona ferramentas reais no servidor e responde com os links dos recursos criados (`<#canal>`, `<@&cargo>`).

```
você:  @farol cria 3 canais de voz: Lobby 1, 2 e 3
farol: Pronto! Criei #🔊-lobby-1 #🔊-lobby-2 #🔊-lobby-3 🎉

você:  @farol monta um servidor gamer completo
farol: ✅ Modelo gamer aplicado: 5 cargos, 3 categorias, 11 canais.

você:  @farol apaga tudo da categoria antiga
farol: Isso apaga 8 canais de **antiga** — posso confirmar? 👀
```

### 🎯 Três Princípios Inegociáveis
1. **Sem comandos para decorar:** Apenas menção `@farol` e texto livre.
2. **Sem chave de IA obrigatória:** O cérebro padrão corre sobre provedores gratuitos e anônimos. Chaves (OpenAI, Anthropic, Gemini) são opcionais.
3. **Online 24/7 sem servidor pago:** Hospedado continuamente no GitHub Actions com auto-encadeamento infinito.

### 🚫 Fora de Escopo por Design
O Farol não faz moderação (kick/ban/mute), punições, sorteios, enquetes, matchmaking ou jogos. Quando solicitado, o bot esclarece gentilmente que sua especialidade exclusiva é **estruturar e organizar servidores**.

---

## 🛠️ 2. Guia Definitivo: Como Configurar as Permissões do Bot para Fazer Tudo

Para que o bot consiga criar, renomear, mover e deletar canais, gerenciar cargos e sincronizar categorias sem esbarrar em erros de permissão (`403 Forbidden` / `Missing Permissions`), siga rigorosamente estes 4 passos:

### Passo 1: Configurar as Intents no Discord Developer Portal
1. Acesse o [Discord Developer Portal](https://discord.com/developers/applications).
2. Selecione a sua aplicação e vá na aba **Bot** no menu lateral esquerdo.
3. Role até a seção **Privileged Gateway Intents**:
   - O Farol foi desenvolvido para funcionar com menção direta **sem necessidade de intents privilegiadas**.
   - Contudo, se desejar que o bot leia mensagens sem ser explicitamente mencionado ou responda a mensagens em reply com contexto estendido, ative **MESSAGE CONTENT INTENT** e defina a variável `MESSAGE_CONTENT_INTENT=true`.
   - Se desejar que o bot liste membros offline com alta precisão, ative **SERVER MEMBERS INTENT** e defina `MEMBERS_INTENT=true`.
4. Em **Token**, clique em **Reset Token**, copie o token e guarde-o (será o seu `DISCORD_TOKEN`).

### Passo 2: Gerar o Link de Convite com as Permissões Corretas
1. No menu lateral, acesse **OAuth2** → **URL Generator**.
2. Na caixa **SCOPES**, marque:
   - `bot`
3. Na caixa **BOT PERMISSIONS**, escolha uma das duas abordagens:
   - **Opção A (Recomendada / Mais simples):** Marque **Administrator** (Permissão inteira `8`). Isso concede acesso geral para executar qualquer operação administrativa no servidor.
   - **Opção B (Granular / Estrita):** Se preferir permissões pontuais, marque obrigatoriamente:
     * `Manage Channels` (Gerenciar Canais)
     * `Manage Roles` (Gerenciar Cargos)
     * `Manage Server` (Gerenciar Servidor)
     * `View Channels` (Ver Canais)
     * `Send Messages` (Enviar Mensagens)
     * `Read Message History` (Ver Histórico de Mensagens)
     * `Add Reactions` (Adicionar Reações)
     * `Attach Files` (Anexar Arquivos — para exportar e importar backups)
     * `Embed Links` (Inserir Links)
     * `Use External Emojis` (Usar Emojis Externos)
4. Copie a URL gerada no rodapé da página, abra no navegador e adicione o bot ao seu servidor Discord.

---

### Passo 3: ⚠️ A REGRA DE OURO — A Hierarquia de Cargos no Servidor Discord

> **A armadilha mais comum:** Mesmo que o bot tenha a permissão de "Administrador" ou "Gerenciar Cargos", a API do Discord **impede** qualquer usuário ou bot de modificar, atribuir ou excluir um cargo que esteja **acima ou na mesma posição** do cargo mais alto do bot.

**Como arrumar:**
1. No seu servidor Discord, clique com o botão direito no ícone do servidor → **Configurações do Servidor** → **Cargos**.
2. Encontre o cargo do **farol** (geralmente criado com o mesmo nome do bot).
3. **Clique e arraste o cargo do farol para o topo da lista de cargos**, deixando-o abaixo apenas do cargo pessoal do Dono do Servidor.
4. Salve as alterações.
5. Agora o Farol conseguirá criar, colorir, dar, tirar e organizar todos os cargos abaixo dele sem nenhuma restrição!

---

### Passo 4: Permissões do Usuário (Quem pode dar comandos)
O Farol possui uma **política de segurança de mão dupla** (`brain/policy.py`). Antes de executar qualquer ação, ele valida:
1. Se o **bot** tem permissão técnica no servidor.
2. Se o **usuário que chamou o bot** tem legitimidade para pedir aquilo.

| Tipo de Ferramenta | Permissão Exigida do Usuário e do Bot |
|---|---|
| Canais (criar, editar, excluir, mover, clonar) | `Gerenciar canais` (`manage_channels`) |
| Cargos (criar, editar, excluir, dar, tirar, permissões) | `Gerenciar cargos` (`manage_roles`) |
| Servidor (editar nome, alterar ícone, exportar estrutura) | `Gerenciar servidor` (`manage_guild`) |
| Modelos (`apply_template`) e Backups (`import_structure`) | `Gerenciar canais` + `Gerenciar cargos` |
| Consultas públicas (listar cargos, ver permissões, info, cores, emojis, tradução) | *Nenhuma (Livre para todos os membros)* |

*Nota:* Administradores do servidor possuem bypass natural em suas próprias checagens, mas o Farol **sempre** confere se o seu próprio cargo possui as permissões necessárias antes de agir.

---

## ⚡ 3. As 27 Ferramentas do Farol

O Farol inclui 27 ferramentas com validação estrita de schemas e executores:

- **Canais (5):** `create_channels`, `edit_channel`, `delete_channels`, `move_channel`, `clone_channel`
- **Cargos (6):** `create_roles`, `edit_role`, `delete_role`, `give_role`, `take_role`, `list_roles`
- **Permissões (4):** `set_permissions`, `clear_permissions`, `sync_permissions`, `show_permissions`
- **Servidor (3):** `edit_server`, `server_info`, `set_icon`
- **Modelos Prontos (1):** `apply_template` (opções: `gamer`, `estudos`, `comunidade`)
- **Backups (2):** `export_structure` (exporta JSON estruturado), `import_structure` (lê de texto ou anexo de arquivo)
- **Utilidades Externas (5):** `color_palette`, `color_name`, `emoji_search`, `topic_suggest`, `translate_text`
- **Sessão (1):** `conversation_clear` (limpa o histórico da memória deste canal)

### Confirmação Inteligente de Ações Destrutivas
- **Exclusão de 1 canal nominal:** O usuário disse explicitamente `@farol apaga o canal #teste` → **Executa imediatamente** sem travar o fluxo.
- **Exclusão em massa (2+ canais ou categoria inteira):** O bot calcula o dano, interrompe e avisa: *"Isso apaga 8 canais de **antiga** — posso confirmar?"*. Ao receber "sim" ou "confirmo", executa na mesma rodada.
- **Exclusão de cargo:** Sempre solicita confirmação prévia para evitar perda acidental de permissões.

---

## 🧠 4. O Cérebro: Corrida de LLMs

O Farol utiliza uma arquitetura de **corrida concorrente** (`AutoProvider`):
1. Cada mensagem do usuário dispara chamadas simultâneas para todos os corredores configurados, com o mesmo timeout.
2. A primeira resposta válida vence a rodada e as requisições restantes são **canceladas imediatamente**.
3. Se um provedor cair, limitar (`429`) ou recusar o modelo (`400/404`), ele perde a corrida — e cada corredor ainda tenta o próximo modelo da sua lista antes de desistir.
4. No fim, se ninguém respondeu, o bot tenta **uma segunda onda** de corrida (os gratuitos oscilam muito) antes de desistir.
5. Se **todos** falharem de verdade, o cliente recebe uma frase curta e útil ("os modelos gratuitos estão com a fila cheia, tente de novo") — o relatório técnico completo (uma linha por corredor, sem HTML) fica no log da run.

### Pool de capacidade gratuita (`FREE_PROVIDERS`)

O pool é o único caminho sem chave paga. Cada ficha carrega base, modelos, contexto, cota e se já
foi validada ao vivo. **Só entra corredor que responde de verdade** — e o que ainda não tem
credencial cadastrada fica fora da corrida (o log diz exatamente qual secret falta).

| Corredor | Como entra | Contexto | Cota gratuita | Tools |
| --- | --- | --- | --- | --- |
| `kilo` | **anônimo** (sem cadastro) | **1M** (vários) · 512K · 262K | 200 req/h por IP | nativo |
| `gemini` | secret `GEMINI_API_KEY` | **1M** | 10–15 RPM · 250–1.500 req/dia (por projeto) | nativo |
| `groq` | secret `GROQ_API_KEY` | 128K | 30 RPM · 1.000 req/dia · 200K tokens/dia (por organização) | nativo |
| `mistral` | secret `MISTRAL_API_KEY` | 256K | ~1 bilhão de tokens/mês (~2 RPM) | nativo |
| `nvidia` | secret `NVIDIA_API_KEY` | 128K–262K | 1.000–5.000 créditos · 40 RPM | nativo |
| `zai` | secret `ZAI_API_KEY` | 131K | ~1.000 req/dia (GLM Flash custa US$0/token) | nativo |
| `cloudflare` | `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` | 256K–1.3M | 10.000 neurônios/dia | protocolo de texto |
| `ollama` | secret `OLLAMA_API_KEY` | 128K–1M | créditos mensais, 1 requisição concorrente | nativo |
| `openrouter` | secret `OPENROUTER_API_KEY` | até 1M | 20 RPM · **50 req/dia** (variantes `:free`) | nativo |
| `modelscope` | secret `MODELSCOPE_API_KEY` | 131K–1M | 2.000 req/dia (cadastro pede telefone) | nativo |
| `siliconflow` | secret `SILICONFLOW_API_KEY` | 131K | modelos a US$0 (~1.000 RPM) | nativo |
| `cohere` | secret `COHERE_API_KEY` | 128K | 1.000 chamadas/mês (**só uso não comercial**) | nativo |

Desligue o pool inteiro com `DISABLE_FREE_LLMS=true`.

**Confirmação de ação destrutiva (`CONFIRM_DESTRUCTIVE`)** — padrão **desligada** (modo direto):
*"apague todos os canais e deixe só esse"* executa na hora e responde o que apagou. Ligue com
`CONFIRM_DESTRUCTIVE=true` para o modo cauteloso (2+ canais, categoria ou cargo pedem um "sim" antes).

**Nunca vaza raciocínio nem responde em inglês:** modelos grátis às vezes devolvem o rascunho
interno ("Here's a thinking process…") dentro do `content`. O provedor corta o rascunho e mantém só o
que vier após o `final answer:`; se sobrar apenas rascunho, a resposta conta como vazia e o corredor
passa para o próximo modelo. No agente há a última barreira (`MAX_RESPOSTA_CHARS`, heurística de
idioma): resposta com mais de 1.000 caracteres, em inglês ou com cara de rascunho é **reescrita uma
vez** em PT-BR curto; se o modelo insistir, o bot entrega o resultado real da ferramenta (já em PT-BR)
ou um "Feito! ✅" honesto — nunca o texto ruim.

**Limpar conversa ≠ apagar mensagens:** `conversation_clear` limpa só a memória do bot (o histórico
interno), `clear_messages` apaga as mensagens do canal de verdade (exige "Gerenciar mensagens" e relata
quantas apagou). Pedido do tipo *"exclua esse chat"* cai em `clear_messages`; *"esqueça o que eu falei"*
cai em `conversation_clear`. O bot nunca responde ter feito o que a ferramenta não confirmou.

**Resposta pronta não passa pelo LLM de novo (`DIRECT_TOOL_REPLY`, padrão ligado):** quando o turno
tem **uma** ferramenta terminal (excluir canal/cargo, limpar conversa) e ela deu certo, o bot responde
com o próprio resultado em vez de pedir um resumo ao modelo — isso corta quase metade do tempo até a
mensagem aparecer. Desligue com `DIRECT_TOOL_REPLY=false`.

**Ordem da fila por latência:** o primeiro modelo do corredor é o que responde primeiro no Discord.
A ordem vem da medição real do CI, não de chute: o smoke mede **3 amostras por modelo por rodada**,
guarda tudo em `reports/kilo-latencia-historico.json` e a fila sai da **mediana acumulada** +
**taxa de resposta com conteúdo** (`reports/kilo-latencia-modelos.md`). Uma rodada isolada oscila
(um modelo que respondeu em 0,66 s volta vazio na seguinte), então a decisão nunca é de uma amostra
só. Critério (confiabilidade antes de velocidade): maior **taxa de rodadas com conteúdo** primeiro,
mediana de latência como desempate, reservas que nunca responderam no fim e o roteador `kilo-auto`
(o que mais devolve vazio) sempre por último. Ranquear só por mediana era enganoso — um modelo que
acertou 1 de 4 rodadas aparecia em 1º. Agregado de 18/09 (4 rodadas × 3 amostras):
`nemotron-3-ultra-550b` (100% · 1,30 s) → `nex-n2.5-pro` (100% · 2,13 s) →
`nemotron-3.5-lightning` (100% · 2,20 s) → `nemotron-3-super-120b` (75% · 0,84 s) →
`dots-3-note-preview` (75% · 1,43 s) → metade/metade (`lfm-2.5`, `step-3.7-flash`) →
`north-mini-code` (25%) → reservas.

**Lista de modelos conferida ao vivo:** a ficha do `kilo` não é chute — cada id sai do catálogo real
(`GET /api/gateway/models`, 380 modelos, 21 marcados `:free`), publicado pelo CI em
[`reports/kilo-modelos-free.md`](reports/kilo-modelos-free.md). Modelo que sai do catálogo é
descartado sozinho pela descoberta automática.

**Como saber quem está realmente respondendo:** a sonda ao vivo roda no CI a cada push em
`llm/**` (workflow *Smoke LLM Providers*) e grava o resultado em
[`reports/smoke-llm.md`](reports/smoke-llm.md) — tabela por corredor com `GET /models`,
`POST /chat/completions` em português, tool call nativo, chamadas consecutivas (429/Retry-After)
e fallback textual. Rode local com `python scripts/smoke_llm.py --timeout 30 --out /tmp/sonda.md`
(requer rede; no sandbox fechado o GET volta `-`).

**Cadastro de secrets (sem cartão):** `gh secret set GEMINI_API_KEY` · `GROQ_API_KEY` ·
`MISTRAL_API_KEY` · `NVIDIA_API_KEY` · `ZAI_API_KEY` · `CLOUDFLARE_API_TOKEN` (+ variável
`CLOUDFLARE_ACCOUNT_ID`: `gh variable set CLOUDFLARE_ACCOUNT_ID`) · `OLLAMA_API_KEY` ·
`OPENROUTER_API_KEY` · `MODELSCOPE_API_KEY` · `SILICONFLOW_API_KEY` · `COHERE_API_KEY`.
Cada secret cadastrado entra na corrida no próximo ciclo, sem mudar código.

> 🧹 **Corredores removidos (17/09/2026):** `llm7`, `ovh` e `pollinations` **saíram do código** —
> não são mais classe, corredor, fallback, segunda/terceira onda nem config. Eles falhavam juntos
> (HTTP 429 "queue full/rate limit" e modelo aposentado) e derrubavam a corrida inteira.
> Também continuam fora: GitHub Models (aposentado), OpenCode Zen (pago) e Cerebras (exige cartão).

> ⚠️ **Cadastre as chaves gratuitas para o pool crescer:** o bot ativa automaticamente todo corredor
> cuja chave existir. Sem nenhuma chave, sobra só o `kilo` (anônimo, 200 req/h por IP). O log da run
> mostra a linha `Pool gratuito ativo: ...` e, logo abaixo,
> `Fora do pool por falta de credencial: ...`.
> Chaves: `aistudio.google.com/apikey` (Gemini) · `console.groq.com/keys` (Groq) ·
> `console.mistral.ai` (Mistral) · `build.nvidia.com` (NVIDIA) · `docs.z.ai` (GLM).

### Corredores com chave (recomendado para uso contínuo)

Defina a variável `LLM_PROVIDER` e cadastre **um** segredo no GitHub Actions
(Settings → Secrets and variables → Actions):

| `LLM_PROVIDER` | Segredo | Modelo padrão |
| --- | --- | --- |
| `groq` | `GROQ_API_KEY` | `llama-3.3-70b-versatile` |
| `gemini` | `GEMINI_API_KEY` | `gemini-2.5-flash` |
| `openrouter` | `OPENROUTER_API_KEY` | `openai/gpt-4o-mini` |
| `deepseek` | `DEEPSEEK_API_KEY` | `deepseek-chat` |
| `cerebras` | `CEREBRAS_API_KEY` | `llama-3.3-70b` |
| `mistral` | `MISTRAL_API_KEY` | `mistral-small-latest` |
| `openai` | `OPENAI_API_KEY` | `gpt-4o-mini` |
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-3-5-haiku-20241022` |
| `opencode-zen` | `OPENCODE_API_KEY` | `deepseek-v4-flash` |

Variáveis de ajuste:

| Variável | Função |
| --- | --- |
| `LLM_MODEL` | Modelo principal do provedor escolhido |
| `LLM_MODELS` | Cadeia de fallback separada por vírgula (`a,b,c`) |
| `LLM_BASE_URL` | Base de **qualquer** gateway OpenAI-compatível (use com `LLM_PROVIDER=meu-nome`) |
| `LLM_API_KEY` | Chave genérica — tem prioridade sobre o segredo específico do provedor |
| `DISABLE_FREE_LLMS` | `true` para correr apenas com o provedor pago |
| `LLM_RACE_WAVES` | Quantas ondas de corrida tentar antes de desistir (padrão `2`, máximo `5`) |
| `LLM_RACE_DELAY` | Pausa em segundos entre as ondas (padrão `0,8`) |

O provedor com chave **não desliga** os gratuitos: ele entra na corrida como mais um
corredor e, por responder com function calling nativo, costuma vencer.

### Provedores removidos (e o porquê)

| Removido | Motivo |
| --- | --- |
| `github_models` | O endpoint Azure (`models.inference.ai.azure.com`) foi desligado em 17/10/2025 e o serviço **GitHub Models foi aposentado em 30/07/2026** — daí o `Name or service not known`. `GITHUB_TOKEN` não gera mais corredor de LLM. |
| `zen` | OpenCode Zen passou a exigir login, cartão e chave paga (o anônimo devolve `401 Invalid API key`). Continua disponível como pago: `LLM_PROVIDER=opencode-zen`. |
| `kilo` | `api.kilo.ai/v1/chat/completions` devolve 404 em HTML (caminho inexistente). |
| `blackbox` | `api.blackbox.ai/chat/completions` devolve 404 (caminho inexistente). |

### Fallback inteligente de ferramentas

Quando o corredor vencedor não suporta function calling nativo, o adaptador injeta um
protocolo de texto no prompt (` ```tool {"name": ..., "args": {...}}``` `) e o agente lê
esses blocos. O histórico também é convertido: mensagens `role=tool` e
`assistant.tool_calls` viram texto puro, porque provedores sem function calling rejeitam
esses papéis. Se o provedor aceitar o schema na teoria e recusá-lo na prática, o adaptador
detecta o erro, degrada para o protocolo de texto e repete a chamada sozinho.

### ❌ "Nenhum dos N provedores de LLM respondeu"

1. Confira o log da run: a linha `Corredores de LLM na corrida: ...` mostra quem entrou na disputa.
2. Se só houver corredores gratuitos, eles provavelmente caíram ou mudaram de modelo — cadastre uma chave (`GROQ_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`…) e defina `LLM_PROVIDER`.
3. Se a mensagem trouxer `HTTP 401`, a chave está errada; `HTTP 404` em HTML indica `LLM_BASE_URL` errado.
4. Provedor gratuito de castigo (`HTTP 429`, "queue full") é passageiro: o bot já repete a onda sozinho e o cliente vê apenas um pedido para tentar de novo em segundos.
5. Depois de mudar segredos/variáveis, rode **Actions → Farol Bot 24/7 → Run workflow** para reiniciar o processo.

---

## ♾️ 5. Hospedagem 24/7 no GitHub Actions

O Farol mantém-se online gratuitamente no GitHub Actions através de um loop auto-sustentável:
1. Cada execução roda por até **~5 horas e 35 minutos** (`timeout 20100s bash run.sh`).
2. O script `run.sh` mantém o processo vivo e aplica backoff exponencial se houver quedas transitórias de conexão.
3. Ao término do tempo limite, o job finaliza com sucesso (`exit 124` mapeado para sucesso) e aciona a etapa **Encadear**, que agenda a próxima execução via `gh workflow run`.
4. Um gatilho de cron agendado (`cron: '25 */5 * * *'`) serve como redundância de segurança.

### 🛡️ Guarda de Obsolescência (`freshness.py`)
No primeiro passo da esteira (antes mesmo do checkout), o Farol verifica a ponta do repositório remoto (`git ls-remote --heads origin`). Se um novo commit tiver sido enviado enquanto uma run estava na fila, o commit desatualizado **aborta imediatamente com `sys.exit(1)`**, impedindo que código antigo desfaça correções recentes.

### 🔌 Ligar / reiniciar / parar o bot

| Quero | Como fazer |
| --- | --- |
| **Ligar ou reiniciar** | Toque no arquivo `.github/bot-24x7-enabled` (qualquer alteração) ou faça um merge na `main`. O workflow *Farol Bot 24/7* dispara na hora. |
| **Conferir se está no ar** | Aba **Actions** → *Farol Bot 24/7*: deve existir uma execução *In progress*. O workflow *Farol Vigia 24/7* também avisa nas anotações a cada 30 min. |
| **Parar só agora** | Cancele a execução em andamento. O vigia reergue em até 30 minutos. |
| **Parar de vez** | Crie o arquivo `.github/bot-disabled` (o bot não sobe e o vigia não o reergue) ou desative o workflow na aba Actions. |

### 🐕 O vigia (`bot-watchdog.yml`)

A corrente sozinha já mantém o bot no ar, mas ela pode romper (erro, runner perdido, cancelamento
acidental, push no meio da run). O *Farol Vigia 24/7* fecha essas brechas:

1. confere a cada **30 minutos** se existe execução do bot ativa/na fila — se não existir, sobe uma;
2. se a ponta do ramo estiver parada há **mais de 45 dias**, grava um batimento (commit trivial) para
   o GitHub não suspender os agendamentos por inatividade — é o que evita o bot morrer no 60º dia;
3. respeita o `.github/bot-disabled` para não lutar contra uma parada proposital.

O passo de frescor do bot também mudou: em vez de abortar quando o checkout está obsoleto (o que
matava a corrente), ele **agenda uma run nova** — que já roda o código atualizado. Na prática, um
push na `main` faz o bot se atualizar sozinho no fim da fatia de 5h35m.

### 🧩 Vários servidores ao mesmo tempo (isolamento)

O Farol é feito para ser vendido e usado em muitos servidores por UM processo só. Tudo que é
por conversa usa a chave `servidor:canal` (`brain/memory.py`):

- **histórico da conversa** — o que foi dito no servidor A nunca entra no prompt do servidor B;
- **pendência de confirmação** — o "sim" de um servidor não autoriza exclusão em outro;
- **lock de processamento** — duas mensagens do mesmo canal entram em fila, canais de outros
  servidores nem se enxergam;
- **memória limitada** — as conversas mais antigas saem por LRU (`max_conversations`, 400 por
  padrão) e o histórico por canal tem teto, então o bot pode ficar meses no ar sem crescer.

Cobertura: `tests/test_isolation.py` (12 testes, incluindo dois servidores com o MESMO id de canal)
e a checagem *conversa isolada por servidor* na fase `spy` do E2E.

### ⏰ Como Reativar o Schedule Após 60 Dias
O GitHub suspende cron schedules automaticamente em repositórios sem atividade após 60 dias. Para manter ou reativar:
1. Acesse a aba **Actions** no seu repositório GitHub.
2. No menu esquerdo, clique no workflow **Farol Bot 24/7**.
3. Se houver um banner amarelo avisando da suspensão, clique em **Enable workflow** ou dispare manualmente via **Run workflow**.
4. Qualquer push para o repositório reinicia o contador de 60 dias do GitHub.

---

## ⚙️ 6. Variáveis de Ambiente

O único segredo obrigatório é o `DISCORD_TOKEN`.

| Variável | Padrão | Descrição |
|---|---|---|
| `DISCORD_TOKEN` | *Obrigatório* | Token de autenticação do Bot do Discord. |
| `LLM_PROVIDER` | `auto` | Provedor de LLM (`auto`, `openai`, `anthropic`, `gemini`). |
| `LLM_MODEL` | `""` | Modelo específico (opcional). |
| `LLM_API_KEY` | `""` | Chave de API caso utilize um provedor proprietário. |
| `LLM_TIMEOUT` | `60` | Timeout em segundos para cada chamada LLM. |
| `LLM_MAX_TOKENS` | `1024` | Máximo de tokens na resposta gerada. |
| `MAX_TOOL_ROUNDS`| `3` | Rodadas máximas de ferramentas por turno de mensagem. |
| `HISTORY_LEN` | `10` | Quantidade de turnos mantidos na memória por canal. |
| `BULK_CONCURRENCY`| `3` | Semáforo de concorrência em operações em lote. |
| `API_TIMEOUT` | `10` | Timeout em segundos para utilitários externos. |
| `LOG_LEVEL` | `INFO` | Nível de log (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `HEALTH_PORT` | `""` | Porta para subir servidor HTTP `/health` (opcional). |
| `DISABLED_APIS` | `""` | Nomes de APIs externas para desativar (separadas por vírgula). |
| `ALLOWED_CHANNEL_IDS` | `""` | IDs de canais permitidos (vazio = atende em todos os canais). |
| `MEMBERS_INTENT` | `false` | Ativa a intent privilegiada de membros. |
| `MESSAGE_CONTENT_INTENT` | `false` | Ativa a intent privilegiada de conteúdo de mensagem. |
| `GITHUB_TOKEN` | *(Automático)* | Token do GitHub Actions para o GitHub Models. |

---

## 🧪 7. Testes e Validação Local

A suíte de testes do Farol foi desenvolvida sem dependência de tokens de rede ou instâncias reais do Discord:
- Toda a lógica de `brain/` é duck-typed.
- Cobertura completa de intents, policy, hierarquia de cargos, confirmação destrutiva, loop do agente com mock LLM, isolamento do bulk, resolução de queries e guarda de frescor.
- Verificação estrita contra `ResourceWarning` ou skips.

Para executar os testes localmente:
```bash
pip install -r requirements.txt
python -W error::ResourceWarning -m unittest discover -s tests -v
```

### 🛰️ Teste E2E ao vivo (`scripts/e2e_live.py`)

Os testes acima são offline (duplos de teste fiéis ao `discord.py`). Para provar que o bot
**faz de verdade** no servidor, existe a suíte E2E ao vivo, que roda no GitHub Actions
(workflow **E2E ao vivo do Farol**) porque o runner tem acesso a `discord.com`:

| Fase | O que verifica |
| --- | --- |
| `static` | 27 ferramentas ↔ 27 executores ↔ 27 políticas, schemas e prompt de sistema |
| `spy` | cada ferramenta "promete e cumpre": duplos que imitam o discord.py 2.7.1 |
| `policy` | permissões do autor/bot, `@everyone`, cargos gerenciados, hierarquia, confirmação |
| `connect` / `audit` | login no gateway, corrida de LLMs, permissões e cache vs API |
| `tools` | ferramentas de leitura no servidor real |
| `agent` | prompt → ferramenta → resposta com o modelo real |
| `mutate` | cria/edita/apaga objetos 🧪 **no servidor** e confere pela API (limpeza garantida) |
| `botloop` | `core.bot.FarolBot` recebendo mensagem real (menção, DM, reações, ferramenta) |
| `sweep` | varredura de sobras 🧪 no fim |

O relatório consolidado é publicado no branch em `reports/e2e-latest.{json,md}` e comentado no PR.

As fases destrutivas só rodam com autorização explícita — qualquer um destes interruptores liga:
variável de repositório `E2E_MUTATIONS=true`, disparo manual com `mutate=true`, ou o arquivo
`.github/e2e-mutations-enabled` presente no branch. Tudo que o teste cria fica marcado com 🧪,
é registrado por diferença de estado na API e removido no fim (a fase `sweep` limpa o que sobrar).
`edit_server` e `set_icon` **não** são executados no servidor real (mudariam nome/ícone).

---

## 📄 Licença
Distribuído sob licença MIT. Sinta-se livre para usar, estudar e adaptar para o seu servidor!
