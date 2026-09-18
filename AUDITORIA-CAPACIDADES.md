# Auditoria de capacidades do Farol

Protocolo usado para auditar → testar → encontrar → corrigir → testar de novo → atualizar o bot.
A regra que evita a interpretação preguiçosa de "testar tudo":

> **Testar "tudo" é exercitar todas as CAPACIDADES que cada ferramenta permite — cada parâmetro,
> cada valor (válido e inválido), cada combinação, os limites, a hierarquia e o estado real do
> Discord depois da operação — e não apenas chamar cada ferramenta uma vez. Capacidade que não foi
> testada ao vivo precisa ser declarada como NÃO TESTADA, nunca dada como funcionando.**

## Como está dividido

| Camada | Onde roda | O que cobra |
| --- | --- | --- |
| `tests/test_capacidades.py` | CI, sem rede, objetos falsos | cada parâmetro/valor/combinação chega na API; valores inválidos recusados com mensagem clara; round-trip do export/import; coerência schema ↔ função ↔ executor (nenhum argumento some em silêncio) |
| fase `caps` do E2E | Discord real (`scripts/e2e_live.py`, fase 6 do workflow) | o **estado real** depois de cada operação: cor/hoist/mentionable/permissões/posição do cargo, tipo/tópico/NSFW/slowmode/bitrate/limite/categoria do canal, overwrites, sincronização, clone, export/import, recusas por hierarquia e falta de permissão |
| fase `policy` do E2E | discord.py simulado | quem pode o quê, confirmação destrutiva, `@everyone` e cargo gerenciado |

## Matriz coberta (o que "tudo" significa aqui)

**Cargos** — criar; nome; cor; posição; `hoist`; `mentionable`; permissões; várias permissões
juntas; editar cada propriedade; trocar o conjunto de permissões (substituir, não acumular);
mover posição; excluir; combinações; valores inválidos (cor, posição negativa, permissão
inexistente, edição vazia); hierarquia (cargo acima do bot é recusado com explicação);
`@everyone`; cargo gerenciado por integração; falta de permissão; repetição; comandos em
linguagem natural; estado real conferido na API depois de cada passo.

**Canais** — tipos suportados (texto, voz, categoria, palco, fórum); nome; categoria (entrar e
sair); posição; tópico; NSFW; slowmode; bitrate; limite de usuários; permissões e overwrites;
sincronização com a categoria; mover; editar cada propriedade; clonar; excluir; combinações;
valores inválidos e fora de faixa (nada é criado por engano).

**Mensagens** — limite 1..500 (0, negativo, acima do teto e não numérico são recusados);
apagar de verdade e conferir o canal vazio.

**Estrutura** — export guardando as capacidades (permissões do cargo, tipo, tópico, NSFW,
slowmode, bitrate, limite, posição, canais sem categoria) e import recriando com os **mesmos
campos**; falha de um item não impede os outros e aparece no relatório.

**Servidor** — `server_info`, `list_roles`, `show_permissions`, `export_structure` como leitura
no servidor real; `edit_server`/`set_icon` seguem bloqueados por decisão do dono (identidade).

## Nada disso é "achismo": o que a auditoria já encontrou

1. `set_permissions` repassava o texto do usuário direto para o discord.py — permissão escrita em
   português ("gerenciar mensagens") estourava `TypeError` em vez de funcionar. Agora existe
   tradução PT-BR/EN com erro claro e sugestões, e um teste confere cada bit contra o discord.py.
2. `create_roles` **prometia** permissões na descrição e não aceitava `permissions` — impossível
   criar cargo com permissão pelo bot. Resolvido (inclusive por item do lote) e verificado ao vivo.
3. `create_channels` anunciava `stage` e `forum` no schema e entregava **canal de texto** —
   mentira silenciosa. Agora cada tipo chama o criador correto (ou recusa explicando).
4. `edit_role` chamava a API sem alteração nenhuma quando ninguém pedia nada, e respondia
   "atualizado com sucesso"; `move_channel` fazia igual ("movido com sucesso" sem mover).
5. `clear_messages` transformava limite inválido em 50 calado; agora recusa e explica a faixa.
6. `export_structure` → `import_structure` degradava a estrutura (perdia NSFW, slowmode, bitrate,
   limite, posição, permissões do cargo e os canais sem categoria). Round-trip testado offline e
   ao vivo.
7. Faltavam `bitrate`, `user_limit` e `position` em `edit_channel`, e `permissions`/`position` em
   `edit_role` — capacidades que o Discord tem e o bot não expunha.

8. `export_structure` cortava o JSON `indent=2` no meio **sem aviso** (o recorte não podia ser
   importado de volta). Agora sai compacto e, quando não cabe numa mensagem, avisa em letras
   garrafas que **este recorte NÃO serve para importar**, com o tamanho real.
9. `move_channel`/`edit_channel` relatavam a posição **pedida** como se fosse a real — o Discord
   reordena junto com os vizinhos. Agora releem o canal e respondem "pedida X, real Y".
10. Bitrate acima do teto do servidor devolvia `400 Invalid Form Body` cru. Agora compara com
    `Guild.bitrate_limit` (96 kbps sem boost; 128/256/384 com boosts) e explica o número.
11. Palco/estágio sem o recurso **Comunidade** devolvia `50024` cru. Agora explica da onde vem o
    erro (e a matriz registra ⚠️, porque não é defeito do bot).
12. Dar/tirar cargo de membro REAL falhava com "não foi encontrado no servidor" quando o cache de
    membros está vazio (intent de membros desligada no portal). Agora cai na API antes de desistir.
13. 5xx do Discord (ex.: `503 Service error -27`) matava a criação de cargo/canal e derrubava tudo
    depois. Agora uma segunda tentativa única em erro de infraestrutura (400/403 seguem sem
    repetição) — e a matriz trata 5xx como ⚠️, nunca ✅ nem cascata de ❌.
14. `server_info` respondia "Membros: None" e "Dono: None" quando o Discord não manda a contagem
    ou o dono não está no cache. Agora usa `owner_id` (menção) e o tamanho do cache (ou "?").
15. `color_name` inventava nome para qualquer coisa ("zzzz" → "Cor #ZZZZ"); `translate_text`
    devolvia o texto original como se fosse tradução quando o tradutor não respondia;
    `emoji_search` respondia "encontrados:" com a lista vazia; `topic_suggest` usava o tom geral
    calado para categoria inventada. Todos passaram a admitir o que não fizeram.
16. Nos provedores sem function calling nativo, a lista de ferramentas do protocolo de texto
    truncava em 40: a ferramenta 41 seria **inalcançável por linguagem natural**. Agora a lista
    é completa e há teste cobrando isso.

Cada achado virou teste (offline e/ou na matriz ao vivo) — regressão permanente, não relatório.

## Causa-raiz da recusa de cargos: cache de cargos do discord.py

A matriz recusava editar o cargo que ela mesma tinha acabado de criar ("acima ou na mesma posição
do meu cargo mais alto"). Não era configuração do servidor: `Member.top_role` é montado com
`guild.get_role(id)` — **se o cache de cargos do servidor estiver vazio, os cargos do membro são
descartados e `top_role` cai no @everyone (posição 0)**. Com isso QUALQUER cargo de posição ≥ 0 era
recusado: o bot se autobloqueava.

- `_posicao_do_topo()` confere a posição do cargo mais alto **na API** quando o cache não resolve os
  cargos do membro (casando os IDs do membro com `fetch_roles()`); `_cargos_do_membro()` recupera os
  IDs crus quando `Member.roles` vem vazio.
- `require()` aceita `bot_top_position`/`actor_top_position` já conferidos.
- as mensagens de recusa mostram **as duas posições** — recusa de verdade fica distinguível de
  cache ruim, e o dono sabe exatamente o que subir.
- a matriz mede a posição do bot na API (`topo_do_bot()`), nunca pelo cache.

## Rodada 4 (run 35310362333, commit 3809884): ✅ 104 · ❌ 0 · ⚠️ 8 · ⏭️ 1

Primeira rodada SEM nenhuma falha. O que sobrou são avisos com causa medida, não defeito
escondido:

| ⚠️ | Causa | Dono |
| --- | --- | --- |
| `cargos que o bot não consegue gerenciar` | 13 cargos (Cupido, iTinder, Atlas, asta…) **no nível ou acima** do cargo do farol, que está na posição 1 | dono do servidor: arrastar o cargo do farol para cima |
| `cargo do farol no chão do servidor` | o mesmo: o Discord recusa gerenciar cargo no nível do topo do bot | dono do servidor |
| 3 × `cargos: gerenciar o cargo criado` | consequência direta: a matriz confere a RECUSA (clara, sem alterar nada) e registra que **não pôde** provar edição/inválidos/dar-tirar ao vivo — essas validações seguem cobertas offline | dono do servidor |
| `canais: tipo stage` | o servidor não tem o recurso **Comunidade**; a mensagem traduzida foi conferida | opcional: ativar Comunidade |
| `prompt → ferramenta → resposta coerente` | o modelo grátis não chamou ferramenta nesta rodada (a rede oscila; tratado como aviso, nunca como ✅ falso) | aceito pelo dono |
| `modo cauteloso pergunta e apaga após 'sim'` | o provedor grátis não cooperou na resposta ao "sim" | aceito pelo dono |

Nesta rodada o `clear_messages` (que havia falhado com 503 do Discord) passou com a segunda
tentativa, e `export_structure`/`import_structure` fecharam o round-trip completo.

**Sobre os avisos de cargo**: a recusa é conferida de verdade (mensagem clara + nada alterado), por
isso eles não são ❌. Para virarem ✅ de execução, basta o dono subir o cargo do farol acima dos
cargos de teste — não há correção de código pendente ali.


## Respostas do bot: por que "oi" virou textão e por que falhava "em tarefas específicas"

Dois relatos do dono do servidor, duas causas distintas:

### 1. O textão em inglês (o bot respondeu "oi" com o planejamento)

O bot ONLINE estava na fatia antiga (código `6685b71`, iniciada 02:12Z — antes da barreira de
resposta). O texto recebido era o modelo **regurgitando o contexto**: começava com
`[Ação solicitada: edit_channel(...)]`, que é a marca que o bot usa ao converter uma chamada de
ferramenta para o protocolo de texto dos provedores sem function calling nativo.

Além da barreira que já existia (sem rascunho, sem inglês, ≤ ~1000 chars), `resposta_ruim` agora
reconhece **eco do contexto interno** por essas marcas (`[Ação solicitada`, bloco ```tool,
"PROTOCOLO DE FERRAMENTAS", "ferramentas disponíveis", `"tool_calls"`, `"system prompt"`) e manda
a resposta para a mesma correção: reescrita curta em PT-BR e, se falhar, o resultado real da
ferramenta.

### 2. "Não consegui falar com nenhum modelo de linguagem" em tarefas específicas

Três causas, medidas:

| Causa | Correção |
| --- | --- |
| **O CI tem UM corredor só.** O relatório do E2E registra `corredores de LLM na corrida: kilo/tools` — nenhuma das 11 chaves gratuitas está cadastrada como secret no repositório (os workflows já passam todas). Qualquer soluço do kilo derruba o turno | estrutural: cadastrar as chaves gratuitas (`GEMINI_API_KEY`, `GROQ_API_KEY`, `MISTRAL_API_KEY`, `NVIDIA_API_KEY`, `OPENROUTER_API_KEY`, `COHERE_API_KEY`, …) nos secrets do repositório → a corrida passa a ter 10+ corredores |
| **O pedido não cabia no modelo** (HTTP 400/413 de contexto/tamanho) era tratado como erro definitivo | `ProviderError.is_context_problem` reconhece o caso e a corrida repete com o histórico CORTADO de forma progressiva (12 → 6 → 3 → 2 mensagens, mantendo o system) sem gastar onda; se ainda não couber, o cliente lê o motivo certo ("a conversa ficou comprida demais… use `limpar conversa`") |
| **O LLM caía DEPOIS de a ferramenta já ter rodado** — a ação estava feita e o cliente achava que não | o agente responde com o RESULTADO REAL da ferramenta em português (antes isso só valia para a última rodada) |

Também: as ondas da corrida subiram de 2 para 3 (com o mesmo teto de tempo total).

## Rodada 5 (18/09): os 3 bugs que o dono viu usando o bot

Relato ao vivo: (a) "recrie o canal" devolvia o canal como estava; (b) cargos duplicados;
(c) o lote (ex.: 5 canais) só agia depois de um tempo. Os três tinham causa no agente, não no
Discord — e cada um virou teste de regressão.

| Bug | Causa-raiz (medida) | Correção | Regressão |
| --- | --- | --- | --- |
| **(a) recriar não recria** | "recrie o canal X" chega ao agente como `delete_channels` + `clone_channel`, e a ordem crua do modelo era executada como veio. Com o delete primeiro, qualquer falha na criação deixava o canal APAGADO e sem substituto (inclusive o retry de 5xx podia duplicar a criação) | `_ordenar_por_seguranca` executa quem CRIA antes de quem APAGA, mantendo a ordem dentro de cada grupo; e `TOOLS_QUE_CRIAM_DE_VERDADE` (criar/copiar) que falhou **bloqueia** as exclusões da MESMA mensagem — melhor não mexer do que ficar sem o substituto. A retentativa de 5xx agora só repete com **5xx confirmado** (o casamento por texto podia repetir um timeout ambíguo e duplicar) | `TestOrdemSeguraEDedupe` (clone-antes-de-apagar; criação que falha não deixa apagar; mesmo com `create_channels`) |
| **(b) duplicados** | o modelo repetia a MESMA chamada (mesmo nome + mesmos args) e o agente executava de novo — cada repetição criava mais um cargo/canal. Repetir a mesma ordem em outra mensagem também criava de novo | dedupe por assinatura (`nome + args`) dentro da mensagem, devolvendo o primeiro resultado com o aviso "(já executei esta mesma chamada…)" — aviso que nunca vai para o cliente; e `create_roles`/`create_channels` não criam o que já existe com o mesmo nome (mesmo lugar, no caso de canal): respondem "(já existia — não dupliquei)". **Exceção**: o que a MESMA mensagem vai apagar pode ser recriado (`ctx.alvos_apagados`) — se não fosse assim, "apague e crie de novo o canal X" pularia a criação e o canal sumiria | `test_repeticao_de_criacao_nao_duplica_cargo`, `test_lote_com_o_mesmo_nome_nao_duplica*`, `test_recriacao_*_nao_e_pulada_como_duplicata`, `test_mesmo_nome_em_categoria_diferente_cria`, e no E2E a fase de repetição agora exige **1** canal, não 3 |
| **(c) delay no lote** | o atalho de resposta direta (o resultado da ferramenta já é a resposta em PT-BR) só valia para `TERMINAL_TOOLS`; qualquer outra ferramenta — `create_channels`, `edit_channel`… — obrigava uma SEGUNDA ida ao modelo só para "resumir" o que já estava pronto. Com o pool gratuito, isso é o delay que o dono sentiu | o atalho vale para **qualquer ferramenta única** que deu certo (respeitando o pedido extra na frase: "crie X **e** me diga Y" ainda passa pelo modelo) | simulação com espião de LLM: lote de 5 canais = **1** chamada ao modelo; `TestOrdemSeguraEDedupe`, `test_ferramenta_unica_responde_direto_*` |

Além disso, `clone_channel` passou a **copiar a posição** do original (o `clone()` do discord.py
copia nome/tópico/NSFW/modo lento/categoria/permissões, mas não a posição — o canal recriado caía
no fim da lista) e a resposta agora diz exatamente o que foi copiado e que o original continua no ar.

Evidência desta rodada: `python -m unittest discover -s tests` → **294 testes OK**;
`e2e_live.py --phases static,spy,policy` → **✅ 42 · ❌ 0**; simulação dos 5 cenários do dono
(recriar por clone, recriar por create+delete, cargo repetido, lote de 5 canais, ferramenta única).

### Rodada 5: o FAIL que sobrou no relatório ao vivo (`export_structure` numa mensagem só)

O relatório da execução `35317479297` (commit `12b3960`) fechou em ✅ 104 · ❌ 1 · ⚠️ 7 · ⏭️ 1. O
único ❌ era `caps/estrutura: export guarda as capacidades reais` → *"export não guardou o campo
permissions"*. **O export guarda** (o caminho de servidor pequeno confere a lista de permissões do
cargo); o que faltava era o HARNESS: em servidor grande o JSON não cabe numa mensagem e o bot
devolve um **recorte avisado** com os primeiros 1800 caracteres — e os cargos (com
`permissions`/`hoist`/`mentionable`) vêm DEPOIS dos canais no JSON, ou seja, caem fora do pedaço.
O teste cobrava as chaves de cargo de um texto que, por construção, não as contém.

Correções: (1) o aviso do recorte agora diz **o que ficou fora dele** ("guardou N canal(is) em X
categoria(s) e K cargo(s) — cada cargo com as permissões, hoist e mentionable dele"), então o dono
sabe que o export pegou os cargos mesmo sem vê-los no pedaço; (2) o harness cobra, no caminho do
recorte, o aviso e o balanço (não as chaves que não cabem — o round-trip completo é verificado na
fase de import e nos testes offline); (3) teste offline novo `test_export_avisa_quando_o_json_nao_cabe_na_mensagem`
agora exige o balanço.

Limitação conhecida e documentada: o export/import cobre estrutura + capacidades de canal
(tipo, tópico, NSFW, modo lento, bitrate, limite, categoria) e de cargo (cor, hoist, mentionable,
permissões, posição) — **overwrites de canal não entram no JSON**; para isso existe `set_permissions`
(capacidade verificada ao vivo na fase `caps`). Num servidor grande o backup "de uma vez" não cabe
numa mensagem do Discord por limite da própria plataforma.

### Rodada 5: o E2E ao vivo pegou uma duplicata que o teste offline não pegava

A execução `35327334718` (commit `c4d151e`, já com o dedupe por assinatura) fechou em
✅ 103 · ❌ 2 · ⚠️ 7 · ⏭️ 1, e o segundo ❌ foi **novo e real**: `caps/repetição` →
*"o lote com o mesmo nome criou 2 canais (esperado 1)"*.

Causa: o lote (`create_channels`/`create_roles`) roda com **concorrência 3** (`run_bulk`). A
conferência de "esse nome já existe?" era feita antes do `await` da criação, mas o NOME só era
marcado como usado DEPOIS que a criação voltava. Dois itens iguais na mesma chamada passavam
juntos pela conferência e os dois criavam — a duplicata que o dono viu nascer com uma ordem só.
Nos testes offline isso não aparecia porque os objetos falsos criam sem esperar pela rede (sem
ponto de suspensão, os itens rodavam praticamente em sequência).

Correção: o nome é **reservado antes do `await`** (`_NomeReservado`) e a reserva vira o objeto
criado quando ele nasce (ou é liberada se a criação falhar). Regressão nova:
`ServidorRedeLenta` (cada criação espera como na rede) + `test_lote_repetido_com_rede_lenta_cria_um_canal_so`
e `test_lote_repetido_de_cargos_com_rede_lenta_cria_um_cargo_so` — **provado que falham sem a
correção** (3 canais em vez de 1) e passam com ela.

O outro ❌ (`tools/export_structure`) era o harness cobrando as chaves `"permissions"`/`"channels"`
de um **recorte** do JSON: num servidor sem categorias os canais aparecem depois do corte. O
harness passou a cobrar o aviso e o balanço do que foi exportado (as chaves do pedaço cortado não
podem ser exigidas; o JSON completo continua validado quando ele cabe na mensagem).

### Rodada 6 (18/09): "tive que pedir várias vezes" e "demora para agir"

Relato do dono depois de usar o bot no Discord. Duas queixas, duas causas diferentes — e uma
descoberta que explica as duas.

**1. Tive que pedir várias vezes.** Com os modelos gratuitos, a resposta mais comum a um pedido de
ação não é o erro: é o **plano**. O modelo escreve *"Vou criar o canal agora mesmo! Deixa comigo"*
(or *"Primeiro eu verifico…"*) e **não chama ferramenta nenhuma**. O bot mandava esse texto para o
Discord como se fosse a resposta e nada acontecia — o cliente lia a promessa, esperava, e tinha de
pedir de novo. Correção: quando o pedido é de AÇÃO e a resposta é promessa/plano (sem pergunta de
esclarecimento e sem recusa legítima), o agente **cobra a ferramenta uma vez** ("você não chamou
nenhuma ferramenta; chame AGORA") antes de responder. Também entrou no protocolo de texto dos
provedores sem function calling: JSON solto no meio da frase (sem cerca de código) e a forma nativa
`{"tool_calls": …}` agora são reconhecidos — recortando o objeto por contagem de chaves, porque
recorte por regex cortava no primeiro `}`, perdendo os argumentos aninhados. Regressões:
`test_promessa_sem_acao_cobra_a_ferramenta`, `test_pergunta_de_esclarecimento_nao_vira_cobranca`,
`test_recusa_de_escopo_nao_vira_cobranca`, `test_apos_executar_nao_gasta_cobranca` e os testes do
parser.

**2. "Devia ser instantâneo" — e por que não era.** Ações de uma ferramenta só já respondem sem
segunda ida ao modelo (`direct_tool_reply`), então o que sobra é a corrida de LLM. Medido: a fila
do kilo responde em ~1–2,5 s. O problema é a **cota do acesso anônimo** (o kilo limita ~200 req/h) e
o fato de o bot ter **um corredor só**: qualquer 429 dele é falha ou espera para o cliente — foi
assim que apareceu "os modelos gratuitos estão com a fila cheia agora", tanto no bot quanto no CI.
Observação honesta: o limite do acesso anônimo é por IP/janela, e o CI roda em outra máquina — não
dá para afirmar daqui que o CI "rouba" a cota do bot; o que se pode afirmar é que **o projeto testa
e roda no mesmo provedor gratuito**, então a disputa existe e o risco de 429 é maior enquanto
existe só ele. Mitigação nesta rodada: `concurrency` nos workflows (só a execução mais nova fica na
fila, nada de run velha consumindo cota) e a orientação de cadastrar as **12 chaves gratuitas** —
cada chave nova é um corredor a mais na corrida paralela, e o primeiro que responde vence. Com um
corredor, o pool de castigo também faz o bot ESPERAR (até 10 s) quando o único modelo acabou de
estourar limite: é melhor que falhar na hora, mas é tempo que o cliente sente.

**3. Medir em vez de adivinhar.** O agente agora mede o próprio tempo por etapa (LLM × execução das
ações) e loga uma linha por resposta (`turno: 4,1s no total (LLM 3,2s em 2 chamadas…)`) — **sem
nenhum conteúdo de conversa** (o log do Actions é público, o chat do dono não). E existe uma
ferramenta nova, `performance_report`: o dono pode perguntar no Discord *"quanto tempo o bot está
levando?"* e receber mediana/pior/melhor com o que pesou. Isso também é o que permite diagnosticar
"demora" sem ler o chat de ninguém.

### Nota honesta sobre "entrar no bot e ler o chat"

O `DISCORD_TOKEN` só existe como *secret* do repositório (visível apenas dentro das execuções do
Actions) e o repositório é **público**: despejar a conversa em log/artefato de CI publicaria o chat
do dono para qualquer pessoa. Por isso a leitura da conversa real precisa vir do dono (copiar e
colar aqui) — o que dá para fazer daqui, e foi feito, é medir o tempo e a sequência de ferramentas
sem o texto, e cobrir cada comportamento com regressão.

### Rodada 7 (18/09): "continua demorando" — onde o tempo era perdido (e o que mudou)

O dono insistiu: segue lento. Três causas reais encontradas lendo o caminho da requisição:

| Onde | Causa | Correção |
| --- | --- | --- |
| **Fila de modelos do provedor era sequencial** | com um corredor só (kilo), a lista de modelos era percorrida **um por vez**: o modelo da frente tinha o tempo INTEIRO dele (até o teto do turno) antes de o próximo ser tentado. Um modelo congelado custava 20 s e o cliente só esperava | **hedge**: se o modelo da frente não responde em 1,6 s, o próximo entra em paralelo (no máximo 2 em voo). O primeiro que responder vence e o outro é cancelado; o 429 continua respeitado (castigo + retry curto, agora sem travar os demais) |
| **A chamada podia ser escrita no RASCUNHO** | o provedor corta o rascunho interno do `content`; se o modelo escrevia a chamada de ferramenta **dentro** desse rascunho, ela era jogada fora: a ação não acontecia, o cliente pedia de novo e o bot "demorava" (era o mesmo caso do "tive que pedir várias vezes") | o provedor **recupera** a chamada do texto original (antes do corte) — parser único em `llm/base.py`, com filtro de nomes de ferramenta conhecidos para não executar JSON por engano. Sem chamada, o comportamento segue o de antes (resposta vazia → próximo modelo) |
| **Ninguém medía** | não havia número nenhum de quanto o cliente esperava, e o log do Actions é público (ler a conversa ali não é opção) | o loop de produção agora mede **mensagem → resposta** na fase `botloop` do E2E (mediana de 3 pedidos simples, WARN acima de 6 s) e o agente loga o tempo por etapa **sem nenhum conteúdo de conversa** |

E, para o dono, duas ferramentas novas no Discord:

- **`performance_report`** — "quanto tempo o bot está levando?" → mediana/pior/melhor + o que pesou
  (modelo × ações no Discord).
- **`diagnostic_report`** — entrega por **mensagem direta** (só para quem pediu) um arquivo `.txt`
  com a conversa recente do canal e os tempos. É o caminho para o dono repassar a conversa real a
  quem dá suporte **sem** publicar o chat em log público de CI.

### Rodada 8 (18/09): "pedi pra apagar todos os cargos e ele diz que não consegue"

Relato do dono. A regra do Discord é real e estrita — "um bot só gerencia cargos **estritamente
ABAIXO** do cargo mais alto dele" (empate não vale; o cargo de bot nasce no **chão** da hierarquia) —
e no servidor do dono o cargo **farol** está na **posição 1**, com tudo acima dele.

**Mas o relatório ao vivo não provava nada disso** e a Rodada 9 corrigiu isso: o harness chamava a
ferramenta do produto, o NOSSO gate de hierarquia recusava por posição e o relatório anotava
"o Discord recusa" — o Discord nunca foi perguntado. Era o produto recusando por conta própria, e era
esse texto que o dono lia como "ele diz que não consegue".

O que estava **mal no produto** (e foi corrigido agora):

| Problema | Antes | Agora |
| --- | --- | --- |
| Não existia exclusão de cargo EM LOTE | "apague todos os cargos" virava uma tentativa por cargo: erro atrás de erro, sem resumo e sem dizer o que fazer | ferramenta nova **`delete_roles`**: apaga o que pode, informa quantos saíram, quantos ficaram e **por quê**, com o caminho exato (Configurações do Servidor → Cargos → arrastar o **farol** para cima) |
| A recusa era seca | "Suba o cargo do farol nas configurações de cargos do servidor." (sem dizer onde nem o que acontece) | mensagem completa: posição do cargo × posição do bot + o passo a passo no Discord + "me peça de novo que eu apago de uma vez" |
| Posição empatada era recusada de chute | o cache do discord.py pode estar velho (já mentiu antes) e o cargo podia ser apagável | quando a posição empata, o bot **tenta de verdade** e relata o que o Discord respondeu |
| Pior de tudo: **mentira** | quando TODAS as execuções falhavam e o modelo devolvia texto vazio, o bot respondia **"Feito! ✅ Confira no servidor"** | agora responde o motivo real ("❌ Não deu para concluir: …") — nunca mais finge que fez |

Regressões: `TestExclusaoEmLoteDeCargos` (8 testes: chão do servidor, apaga-o-que-pode, cargo
inexistente no meio do lote, lista vazia, modo cauteloso, empate que funciona, empate recusado com
instrução, cargo individual) e `test_falha_em_tudo_nao_vira_feito` no agente.

**Ação do dono (30 segundos, e vale para tudo):** Configurações do Servidor → **Cargos** → arraste o
cargo do **farol** para cima dos cargos que ele deve gerenciar. Depois disso, "apague todos os
cargos" funciona de uma vez — e o cargo do bot passa a conseguir editar/apagar cargos em geral.

## O que ainda precisa do dono para ser verificado de verdade

- **Cargo do bot**: ele só gerencia cargos **abaixo** do próprio cargo. O E2E registra ⚠️ e diz o
  motivo quando o servidor de teste tem cargos no nível ou acima do bot (hoje há 13). Para a
  auditoria de hierarquia ficar 100% verde, suba o cargo do bot acima dos cargos de teste.
  (O cache do discord.py já foi corrigido: recusas que vinham dele não acontecem mais — quando a
  matriz registrar ⚠️ de novo, a mensagem agora traz as duas posições medidas na API.)
- **Servidor de teste**: a matriz cria e apaga objetos marcados com 🧪. Sem um servidor onde o bot
  tenha "Gerenciar canais/cargos/mensagens", a fase fica em ⚠️ "não verificável" em vez de ✅.

### Rodada 9 (18/09): "essa de posição tá errada" — o gate recusava sem perguntar ao Discord

O dono desconfiou do diagnóstico ("como assim um bot não apaga um cargo que ele mesmo criou?") e
mandou o token para eu testar por conta própria. A desconfiança estava certa **em parte**, e o que
saiu desta rodada:

| Achado | Consequência |
| --- | --- |
| O relatório ao vivo dizia "o Discord recusa a edição" **sem nunca ter perguntado ao Discord** | corrigido: em **empate de posição** a ferramenta agora **tenta de verdade** e traduz a resposta real da API (`O Discord recusou editar … (403 …): Missing Permissions`). Em posição rigorosamente acima, a recusa continua na hora — com o passo a passo |
| O empate só tentava em `delete_role`/`delete_roles`; `edit_role`, `give_role` e `take_role` recusavam de chute | todas passam pelo mesmo gate (`_exige_cargo_gerenciavel`) e tentam no empate |
| Não existia prova CRUA da regra de hierarquia no servidor do dono | nova sonda `scripts/sonda_hierarquia.py` + workflow **`sonda-hierarquia.yml`**: fala direto com a API do Discord (sem `brain/`, sem cache, sem LLM), cria UM cargo 🧪, tenta renomear, apagar e mover, e publica a resposta crua em `reports/sonda-hierarquia.md` |

Regressões novas: `tests/test_hierarquia_empate.py` (10 testes — empate tenta e funciona; empate
recusado traduz a resposta real; acima do bot **não gasta chamada**; lote; dar/tirar cargo; posição
medida na API com cache vazio) e `tests/test_sonda_hierarquia.py` (13 testes — visão de posições,
permissão, e que a sonda sempre deixa rastro, inclusive quando o token falha).

**Bloqueio honesto:** o segredo `DISCORD_TOKEN` do repositório está respondendo **401 Unauthorized**
(o token do bot foi resetado) — a sonda roda e publica o motivo, mas a prova crua ao vivo só sai
quando o dono atualizar o segredo em Settings → Secrets and variables → Actions → `DISCORD_TOKEN`.
O bot 24/7 também não sobe no próximo reinício enquanto o segredo estiver assim.
