# 🤖 Pedido de pesquisa: LLMs grátis com contexto gigante para o bot **Farol**

> **Para quem receber este documento (outra IA):** este é o contexto completo de um bot de Discord
> em produção, hospedado de graça no GitHub Actions, que hoje usa apenas APIs de LLM **gratuitas
> (sem cartão de crédito)**. Quero que você encontre **provedores de LLM gratuitos com contexto
> muito grande (quanto maior, melhor) e cota generosa** que possam substituir ou reforçar a corrida
> atual. Responda no formato pedido na seção 6. Hoje é **2026-09-17** — priorize informação recente
> e diga a data em que cada fonte foi conferida.

---

## 1. O que é o bot (contexto mínimo)

- **Nome:** Farol (`farol`) — bot de Discord em **Python 3.11 + discord.py 2.7.1**.
- **Propósito:** montar, organizar, auditar e consertar servidores Discord (27 ferramentas reais:
  criar/editar/mover/clonar/apagar canais, categorias, cargos, permissões, templates, ícone etc.).
- **Hospedagem:** 100% gratuita no **GitHub Actions**, com encadeamento de execuções de ~5h35m para
  ficar **24/7** (sem servidor próprio). O tráfego de saída vem de **IPs de datacenter do Azure
  (runners do GitHub Actions)**.
- **Produto:** o bot **será vendido** para vários servidores e roda **um único processo** atendendo
  todos ao mesmo tempo (memória isolada por `servidor:canal`).
- **Uso de LLM:** cada mensagem de usuário gera **1 a 4 chamadas** ao LLM (o agente pode rodar até 3
  rodadas de ferramentas + 1 resumo final).
- **Custo aceitável:** **zero**. Nada de cartão de crédito, nada de trial que expira.

### Tamanho real de uma chamada (para dimensionar contexto)

| Componente | Tamanho medido |
| --- | --- |
| Prompt de sistema | ~1.900 caracteres |
| Esquema das 27 ferramentas (`tools`) | **11.386 caracteres** |
| Snapshot do servidor (canais, cargos, permissões) | varia com o servidor (pode ser grande) |
| Histórico da conversa | até ~30 mensagens por canal (limite de memória) |
| `max_tokens` de saída | 1.024 (padrão do bot) |
| Timeout por chamada | 60 s (configurável) |

Na prática: **~8k a 25k tokens de entrada por chamada**, com picos maiores em servidores cheios de
canais/cargos. Contexto maior = mais histórico de conversa e snapshots mais completos sem cortes.

---

## 2. Como a camada de LLM funciona hoje (arquitetura que o provedor precisa encaixar)

1. **Corrida (`AutoProvider`)** — todos os provedores configurados são chamados **em paralelo** com o
   mesmo timeout; o **primeiro que responde algo válido vence** e os demais são cancelados.
2. **Resiliência embutida:**
   - `HTTP 429` ("fila cheia") → uma segunda tentativa rápida, respeitando o header `Retry-After`, e o
     provedor fica **de castigo ~30 s** (não é martelado a cada mensagem);
   - modelo aposentado (`400/404 "model unavailable"`) → o bot **redescobre o catálogo** no
     `/v1/models` do provedor (cache de 30 min) e recomeça a varredura;
   - se a corrida inteira falhar, tenta **uma segunda onda** antes de desistir.
3. **Ferramentas:** function calling **nativo** é preferido; se o provedor não suportar (ou recusar o
   schema), o bot **degrada sozinho** para um protocolo de texto (```tool {"name": ..., "args": {...}}```)
   e continua funcionando.
4. **Formato exigido:** API **compatível com OpenAI** — `POST {base}/chat/completions`, header
   `Authorization: Bearer <chave>`, corpo com `model`, `messages`, opcionalmente `tools`/`tool_choice`
   e `max_tokens`.
5. **Onde os provedores são plugados no código** (para quem quiser sugerir patch):
   `llm/free_providers.py` (`KNOWN_GATEWAYS` + corredores anônimos), `llm/auto.py` (a corrida),
   `scripts/smoke_llm.py` (sonda ao vivo), `scripts/e2e_live.py` (teste de ponta a ponta).

### Variáveis de ambiente aceitas hoje

| Variável | Função |
| --- | --- |
| `LLM_PROVIDER` | Nome do gateway (`groq`, `gemini`, `openrouter`, `deepseek`, `cerebras`, `mistral`, `openai`, `anthropic`, `opencode-zen` ou um nome livre com `LLM_BASE_URL`) |
| `LLM_API_KEY` | Chave genérica (guardada como **secret do GitHub Actions**) |
| `<PROVEDOR>_API_KEY` | Chave específica (ex.: `GROQ_API_KEY`) |
| `LLM_BASE_URL` | Base de **qualquer** endpoint OpenAI-compatível |
| `LLM_MODEL` / `LLM_MODELS` | Modelo principal / cadeia de fallback (`a,b,c`) |
| `DISABLE_FREE_LLMS` | `true` desliga os gratuitos |
| `LLM_RACE_WAVES` / `LLM_RACE_DELAY` | Quantas ondas de corrida (padrão 2) e pausa entre elas |
| `LLM_TIMEOUT` | Timeout por chamada (padrão 60 s) |

---

## 3. Requisitos que um provedor candidato precisa cumprir

### Obrigatório

- [ ] **Grátis de verdade**: sem cartão de crédito, sem trial que expira, sem "créditos que acabam
      em 30 dias". Cadastro com e-mail + chave de API é aceitável.
- [ ] **Endpoint OpenAI-compatível** (`/chat/completions`) — ou informe o formato alternativo e o
      adaptador necessário.
- [ ] **Aceita tráfego automatizado de IP de datacenter** (runner do GitHub Actions/Azure). APIs que
      exigem proxy residencial, CAPTCHA por requisição ou bloqueiam datacenter não servem.
- [ ] **Cota suficiente para um bot**: pelo menos algumas centenas de requisições por dia, ou limite
      por minuto que aguente uso contínuo leve.
- [ ] **Contexto grande**: **≥ 128k tokens** (ideal ≥ 200k; "quase infinito" = 1M+ é o sonho).
- [ ] **Bom em português do Brasil** e capaz de seguir instruções com rigor (é um bot que executa
      ações destrutivas no servidor — alucinação custa caro).

### Desejável (não elimina o candidato)

- [ ] **Function calling nativo** (sem ele o bot usa o protocolo de texto, funciona, mas é menos preciso).
- [ ] **Lista de modelos em `/v1/models`** (permite a auto-descoberta quando o catálogo muda).
- [ ] Latência de primeira resposta ≤ 30 s.
- [ ] Modelos com nomes estáveis (ou catálogo que avise quando um modelo for aposentado).
- [ ] Chave por conta (melhor que anônimo por IP, porque o bot compartilha o IP do runner).

---

## 4. O que já está rodando (não precisa indicar de novo, mas ajuda se tiver alternativa melhor)

| Corredor | Autenticação | Contexto | Situação real em produção |
| --- | --- | --- | --- |
| **llm7.io** (`api.llm7.io/v1`) | anônimo ou chave `LLM7_API_KEY` | — | Funciona, function calling nativo, mas o catálogo muda sem aviso (o `qwen2.5-coder-32b` foi aposentado e derrubava a corrida) |
| **OVHcloud AI Endpoints** (`oai.endpoints.kepler.ai.cloud.ovh.net/v1`) | anônimo | gpt-oss-20b 128k | Funciona, mas devolve `HTTP 429 API rate limit exceeded` com frequência (limite baixo por IP) |
| **Pollinations** (`text.pollinations.ai/openai`) | anônimo ou token `POLLINATIONS_TOKEN` | — | Funciona, mas devolve `429 Queue full for IP` nos horários de pico |

> Os três falharem **ao mesmo tempo** foi exatamente o bug que acabamos de corrigir: o cliente via uma
> parede de erro técnico. Agora a corrida repete em ondas e o cliente lê só "tente de novo em
> segundos" — mas o objetivo é **depender menos de sortudos por IP**.

---

## 5. Já testado e descartado (não sugerir de novo sem evidência nova)

| Provedor | Por que saiu |
| --- | --- |
| **GitHub Models** (Azure `models.inference.ai.azure.com`) | Serviço **aposentado em 30/07/2026**; o endpoint foi desligado |
| **OpenCode Zen** (anônimo) | Passou a exigir login/cartão; o anônimo devolve `401 Invalid API key` (segue como pago) |
| **Kilo** (`api.kilo.ai/v1/...`) e **Blackbox** (`api.blackbox.ai/...`) | Devolveram **HTTP 404 em HTML** (caminho inexistente) quando testamos — se você confirmar que voltaram, traga a URL exata e a data |
| **Cerebras** (free tier) | Passou a exigir cartão de crédito (virou trial pago) |
| **llm7 `qwen2.5-coder-32b`** | Modelo **removido** do catálogo (não é o provedor inteiro, só o slug) |

---

## 6. O que eu preciso que você me devolva (formato exato)

### 6.1 Tabela ranqueada (markdown)

| # | Provedor | Base URL OpenAI-compatível | Modelo(s) com contexto ≥128k | Autenticação (anônimo / cadastro) | Pede cartão? | Cota grátis (req/min, req/dia, tokens) | Contexto (tokens) | Function calling? | Aceita IP de datacenter? | Verificado em | Fonte (link) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

Ordene do **melhor para o pior** considerando: contexto grande → cota generosa → grátis sem cartão →
aceita datacenter → function calling → qualidade em PT-BR.

### 6.2 Para os **3 melhores**, entregue a configuração pronta

1. **Configuração para o bot** (o que colar nos secrets/variáveis do GitHub Actions):
   ```text
   LLM_PROVIDER=<nome>
   LLM_BASE_URL=<https://.../v1>      # se não for um gateway conhecido
   LLM_MODEL=<modelo-principal>
   LLM_MODELS=<fallback-1>,<fallback-2>   # opcional
   # Secret: LLM_API_KEY=<como obter a chave, passo a passo>
   ```
2. **Comando `curl` de teste** para eu validar em 10 segundos:
   ```bash
   curl -sS https://<base>/chat/completions \
     -H "Authorization: Bearer $CHAVE" -H "Content-Type: application/json" \
     -d '{"model":"<modelo>","messages":[{"role":"user","content":"Responda apenas: ok"}],"max_tokens":16}'
   ```
3. **Teste de function calling** (o bot depende disso ou do protocolo de texto):
   ```bash
   curl -sS https://<base>/chat/completions \
     -H "Authorization: Bearer $CHAVE" -H "Content-Type: application/json" \
     -d '{"model":"<modelo>","messages":[{"role":"user","content":"Chame a ferramenta ping com ok=true."}],"tools":[{"type":"function","function":{"name":"ping","parameters":{"type":"object","properties":{"ok":{"type":"boolean"}},"required":["ok"]}}}]}'
   ```
4. **Letras miúdas (ToS)**: o uso por bot/automação é permitido? Há limite "justo" que derruba conta?
   Existe risco de banir a chave? Precisa de atribuição/citação?

### 6.3 Extras que valem ouro

- Provedores com **contexto ≥ 1M tokens** grátis (mesmo com cota diária baixa — serve como reserva).
- Endpoints que aceitem **streaming desnecessário = false** e devolvam JSON direto (o bot não usa streaming).
- Provedores com **`/v1/models`** público (o bot se auto-conserta quando o catálogo muda).
- Alternativas **não-OpenAI** (ex.: API própria) — diga o formato, que avaliamos escrever um adaptador.
- Se souber de **cotas por conta (chave)** em vez de por IP, destaque: é o mais valioso para nós.

---

## 7. Como validar o que você indicar (faça isso antes de responder, se puder executar código)

1. `GET {base}/models` com a chave → confirma que a chave vale e lista os modelos disponíveis.
2. Uma chamada `chat/completions` curta em português → confirma resposta e latência.
3. Uma chamada com `tools` → confirma function calling nativo (ou ausência dele, o que já sabemos tratar).
4. Repita a chamada ~5× seguidas → sente o limite por minuto na prática.
5. Confirme a **janela de contexto** na documentação oficial (não em blog de terceiros) e cite o link.
6. **Diga a data** de cada verificação e marque com ⚠️ o que for incerto ou baseado em relato de terceiros.

---

## 8. Restrições do projeto (não negociáveis)

- **Sem cartão de crédito.** Nada de "adicione o cartão para liberar".
- **Sem trial de 7/14 dias.** O bot é vendido e precisa durar **meses** sem intervenção.
- **Sem chave paga.** Se o único caminho for pago, diga honestamente e ofereça a alternativa gratuita mais próxima.
- **Aceitamos falhas intermitentes** (já tratadas com corrida + ondas + mensagem amigável), mas cada
  provedor extra com contexto grande **reduz** a chance de o cliente ver "modelos ocupados".
- **Não podemos mostrar erro técnico ao cliente final** — se o candidato tiver modos de falha
  esquisitos (ex.: devolve 200 com corpo vazio), avise, porque isso o bot já detecta mas atrapalha.

---

## 9. Resumo em uma frase

> Ache APIs de LLM **gratuitas e sem cartão**, de preferência **OpenAI-compatíveis**, com **contexto
> gigante (≥128k, ideal 200k–1M+)** e **cota generosa**, que **aceitem IP de datacenter** e
> **function calling** — para um bot de Discord multilíngue (PT-BR) que executa ações reais e hoje
> depende de três corredores gratuitos que estouram limite por IP.
