# 🏮 Farol — relatório de teste E2E

- **Resumo:** ✅ 97 · ❌ 5 · ⚠️ 6 · ⏭️ 1
- **python:** 3.11.16
- **runner:** Linux
- **commit:** 5a71fdc
- **execução:** 35305579300
- **discord.py:** 2.7.1
- **fases:** static, spy, policy, connect, audit, tools, agent, mutate, caps, botloop, sweep
- **mutações reais:** sim

## Anotações
- conectado como Atlas#1985 em 1 servidor(es)

## Checagens estáticas (schemas ↔ executores)
`static` — ✅ 6 · ❌ 0 · ⚠️ 0 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `27 ferramentas ↔ 27 executores` | 28 ferramentas e 28 executores casados |
| PASS | `assinaturas ↔ schemas` | 28 assinaturas conferem com os schemas |
| PASS | `toda ferramenta tem política` | as 28 ferramentas têm política declarada |
| PASS | `qualidade dos schemas enviados ao LLM` | descrições e schemas bem formados para function calling |
| PASS | `prompt de sistema completo` | prompt com os 7 blocos obrigatórios (regra de confirmação dinâmica) |
| PASS | `tamanho do payload enviado ao LLM` | schema com 13677 chars + prompt de 2038 chars |

## Duplos de teste: a ferramenta promete, a ferramenta faz?
`spy` — ✅ 22 · ❌ 0 · ⚠️ 0 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `create_channels cria na raiz de verdade` | chamou create_() e respondeu 'Pronto! Criei 3 canal(is): <#1009> <#1010> <#1011> 🎉 (✅ 3/3 ' |
| PASS | `create_channels cria DENTRO de categoria` | chamou create_() e respondeu 'Pronto! Criei 2 canal(is): <#1012> <#1013> 🎉 (✅ 2/2 concluíd' |
| PASS | `edit_channel edita de verdade` | chamou edit() e respondeu 'Canal <#1008> atualizado com sucesso (name, nsfw, slowmode_d' |
| PASS | `move_channel move de verdade` | chamou edit() e respondeu 'Canal <#1008> movido com sucesso (categoria: sem categoria, ' |
| PASS | `clone_channel clona de verdade` | chamou clone() e respondeu 'Canal clonado com sucesso: <#1014> 🎉' |
| PASS | `delete_channels apaga de verdade (1 canal)` | chamou delete() e respondeu '🗑️ Exclusão concluída: #canal-renomeado (✅ 1/1 concluídos co' |
| PASS | `delete_channels em lote: modo direto apaga na hora` | 2 canais apagados direto, com o resultado na resposta |
| PASS | `delete_channels em lote: modo cauteloso pede confirmação` | 2 canais: exige confirmação e só apaga com confirmed=true |
| PASS | `edit_server altera de verdade` | chamou edit() e respondeu 'Informações do servidor atualizadas com sucesso!' |
| PASS | `set_icon altera de verdade (baixa a URL e envia os bytes)` | baixou a URL, mandou os bytes em guild.edit(icon=...) e aceitou data URI |
| PASS | `set_icon com estilo gera imagem sem rede` | gerou um PNG 256x256 sem tocar a rede |
| PASS | `set_icon NÃO mente quando o download falha` | erro honesto: 'Falha ao baixar a imagem: https://exemplo.invalido/nao-existe.png' |
| PASS | `apply_template cria de verdade` | 5 cargos, 3 categorias e 11 canais dentro delas |
| PASS | `import_structure cria de verdade` | chamou create_() e respondeu '✅ Estrutura importada: 1 cargo(s) e 1 canal(is) recriados co' |
| PASS | `cargos: criar/editar/dar/tirar/apagar de verdade` | criou/editou/deu/tirou/apagou: todas as chamadas de API aconteceram |
| PASS | `permissões: set/clear/sync tocam a API` | set/clear/sync chamaram a API e show leu as permissões |
| PASS | `somente-leitura não muta nada` | 8 ferramentas de leitura rodaram sem mutar nada |
| PASS | `conversation_clear limpa a memória` | histórico do canal apagado de verdade |
| PASS | `conversa isolada por servidor (multi-servidor)` | conversa, contexto e pendência de confirmação separados por servidor (mesmo id de canal) |
| PASS | `clear_messages apaga o chat de vero (bulk delete)` | chat apagado com bulk delete e memória limpa sem mentir |
| PASS | `textão em inglês do modelo nunca chega ao usuário` | rascunho em inglês barrado (2 chamadas) e resposta curta em PT-BR |
| PASS | `agente não se auto-confirma (offline)` | sem confirmação do usuário nada é apagado; a pergunta sempre aparece; com o 'sim', apaga |

## Política de permissões e confirmação destrutiva
`policy` — ✅ 14 · ❌ 0 · ⚠️ 0 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `membro comum é bloqueado` | membro comum bloqueado: Você precisa da permissão 'Gerenciar canais' para usar a ferramenta 'create_channels'. |
| PASS | `apagar mensagens exige permissão` | apagar mensagens exige 'Gerenciar mensagens': Você precisa da permissão 'Gerenciar mensagens' para usar a ferramenta 'clear_messages'. |
| PASS | `bot sem permissão é bloqueado` | bot sem permissão bloqueado: Eu preciso da permissão 'Gerenciar canais' no meu cargo para executar 'create_channels'. Ajuste meu cargo e tente de novo. |
| PASS | `@everyone é intocável` | @everyone protegido: Não é possível alterar ou excluir o cargo @everyone. |
| PASS | `cargo de integração é intocável` | cargo de integração protegido: O cargo 'CargoDeBot' é gerenciado por uma integração ou aplicativo e não pode ser modificado. |
| PASS | `cargo acima do bot é protegido` | cargo acima do bot protegido: O cargo 'CargoDoDono' está acima ou na mesma posição do meu cargo mais alto. Suba o cargo do farol nas configurações de cargos do servidor. |
| PASS | `autor não edita cargo no próprio nível` | cargo no nível do autor protegido: O cargo 'CargoDoAutor' está acima ou na mesma posição do meu cargo mais alto. Suba o cargo do farol nas configurações de cargos do servidor. |
| PASS | `exclusão em lote exige confirmação (modo cauteloso)` | 2 canais: pede confirmação e não apaga nada antes |
| PASS | `exclusão em lote executa direto no padrão` | 2 canais: modo direto apaga e informa, sem perguntar |
| PASS | `canal único apaga sem confirmação` | canal único nominal executa sem travar o fluxo |
| PASS | `exclusão de cargo exige confirmação (modo cauteloso)` | cargo: exige confirmação e apaga com confirmed=true |
| PASS | `exclusão de cargo executa direto no padrão` | cargo: modo direto apaga o que foi pedido, sem perguntar |
| PASS | `ferramenta inexistente é rejeitada` | ferramenta desconhecida rejeitada: A ferramenta 'ferramenta_inexistente' não foi encontrada. |
| PASS | `argumentos inválidos são rejeitados` | lista vazia rejeitada com ToolError: Nenhum canal foi informado para exclusão. |

## Conexão ao gateway do Discord
`connect` — ✅ 6 · ❌ 0 · ⚠️ 0 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `corredores de LLM na corrida` | kilo/tools |
| PASS | `configuração carregada` | token no formato correto (72 chars) · provider=auto · intents: members=False, message_content=False |
| PASS | `corrida de LLMs responde` | vencedor kilo (tools nativas: True) → 'pong' |
| PASS | `servidores do bot` | 1: Pinguim (1546763083005825084) |
| PASS | `login e gateway` | conectado como Atlas#1985 · gateway em 16ms |
| PASS | `servidor e autor do teste` | servidor de teste: Pinguim (1546763083005825084) · autor: ek8a (administrador) |

## Diagnóstico de permissões e hierarquia no servidor
`audit` — ✅ 5 · ❌ 0 · ⚠️ 1 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `permissões do bot no servidor` | OK: ['manage_channels', 'manage_roles', 'manage_guild', 'administrator', 'send_messages'] |
| WARN | `cargos que o bot não consegue gerenciar` | 13 cargo(s) no nível ou acima do bot (asta, asta, asta, asta, asta): ele não conseguirá editar/apagar esses cargos. Suba o cargo do farol (README Passo 3). |
| PASS | `hierarquia de cargos` | cargo do bot na posição 1 |
| PASS | `estrutura do servidor` | 0 categorias · 0 texto · 0 voz · 14 cargos · 4 membros |
| PASS | `snapshot do servidor` | snapshot com 17 linhas alimenta o prompt |
| PASS | `estado local bate com a API` | cache local bate com a API REST (0 canais, 14 cargos) |

## Ferramentas somente-leitura em servidor real
`tools` — ✅ 6 · ❌ 0 · ⚠️ 0 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `server_info` | 📊 **Informações de Pinguim:** · • **ID:** `1546763083005825084` · • **Dono:** None · • **Membros:** 4 · • **Canais:** 0 · • **Cargos:** 14 · • **Criado em:** 2026-09-08 06:04:16.457000+00:00 |
| PASS | `list_roles` | listou os 14 cargos reais com menção e posição |
| PASS | `export_structure (JSON válido e completo)` | 0 categorias, 0 canais e 13 cargos exportados em JSON válido |
| PASS | `show_permissions` | O canal <#1550356982870052974> não possui permissões personalizadas configuradas. |
| PASS | `resolve por ID e por menção` | 0 canais e 6 cargos resolvidos por ID e por menção |
| PASS | `APIs externas (cores/emojis/tópicos/tradução)` | 5 APIs externas responderam |

## Agente + LLM ao vivo (prompt → ferramenta → resposta)
`agent` — ✅ 0 · ❌ 1 · ⚠️ 3 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| WARN | `prompt → ferramenta → resposta coerente` | o LLM não chamou nenhuma ferramenta (rodadas: [{'ferramentas_oferecidas': 28, 'ferramentas_chamadas': [], 'chars': 112, 'vencedor': 'kilo'}]) — o provedor gratuito não cooperou nesta rodada ('Cargos do servidor **Pinguim**:\n\n- @Cupido\n- @asta (10 cargos com o mesmo nome)\n- @Atlas\n- @iTinder\n- @@everyo'). Sem chave de LLM paga isso é intermitente; rode de novo para conferir. (O comportamento… |
| FAIL | `fora de escopo é recusado sem executar` | LLMUnavailableError: Nenhum dos 1 provedores de LLM respondeu (kilo/tools) depois de 2 tentativa(s). Erros: kilo: kilo: falha de rede — TimeoutError: corpo vazio \| kilo: kilo: resposta sem choices (nvidia/nemotron-3-ultra-550b-a55b:free) — {'id': 'gen-1789704391-gAiJMAr18r5SIdz9Z7vh', 'error': {'message': 'Upstream error from Nvidia: Service… Os gratuitos compartilham o IP do servidor e estouram… |
| WARN | `agente conhece a estrutura real` | não deu para perguntar: nenhum corredor grátis atendeu — o provedor gratuito não cooperou nesta rodada ('Nenhum dos 1 provedores de LLM respondeu (kilo/tools) depois de 2 tentativa(s). Os gratuitos compartilham o IP'). Sem chave de LLM paga isso é intermitente; rode de novo para conferir. (O comportamento do bot está coberto offline nas fases spy/policy e em tests/.) |
| WARN | `memória do canal entre turnos` | não deu para conversar: o LLM não respondeu — o provedor gratuito não cooperou nesta rodada ('Nenhum dos 1 provedores de LLM respondeu (kilo/tools) depois de 2 tentativa(s). Os gratuitos compartilham o IP'). Sem chave de LLM paga isso é intermitente; rode de novo para conferir. (O comportamento do bot está coberto offline nas fases spy/policy e em tests/.) |

## Mutações reais em objetos de teste (com limpeza)
`mutate` — ✅ 17 · ❌ 0 · ⚠️ 1 · ⏭️ 1

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `infra: categoria e canais de teste` | categoria 🧪 teste-farol + 🧪-texto + 🧪-voz criados (registrados para limpeza) |
| PASS | `create_channels DENTRO de categoria (via ferramenta)` | texto + voz criados dentro da categoria existente (['🧪-dentro', '🧪-dentro-voz']) |
| PASS | `create_channels na RAIZ (via ferramenta)` | texto + voz + categoria criados na raiz (['🧪-raiz-voz', '🧪-raiz-categoria', '🧪-raiz-texto']) |
| PASS | `edit_channel alterou de verdade` | nome, tópico e slowmode confirmados na API (🧪-renomeado) |
| PASS | `clone_channel clonou de verdade` | clone 🧪-clone criado com a mesma categoria |
| PASS | `move_channel moveu de verdade` | saiu e voltou de categoria, confirmado pela API |
| WARN | `cargo do farol no chão do servidor` | O cargo '🧪 teste-papel' está acima ou na mesma posição do meu cargo mais alto. Suba o cargo do farol nas configurações de cargos do servidor. Ação do dono (README Passo 3): arraste o cargo do farol para cima dos outros — sem isso ele não edita nem os cargos que ele mesmo cria. |
| PASS | `cargos: criar/editar/atribuir de verdade` | cargo criado e conferido na API; editar/dar/tirar ficou bloqueado pela posição do cargo do bot no servidor |
| PASS | `permissões de canal confirmadas pela API` | set, sync, clear e show (com filtro por target) confirmados pela API |
| PASS | `import_structure recriou a estrutura` | import recriou 3 canais e 2 cargo(s) |
| PASS | `fluxo de confirmação em canais reais (modo cauteloso)` | 2 canais: modo cauteloso pediu confirmação e só apagou com confirmed=true |
| PASS | `exclusão em lote direta em canais reais` | 2 canais reais apagados direto, sem perguntar, com o resultado na resposta |
| PASS | `clear_messages apaga mensagens reais do canal` | apagou 3 mensagem(ns) reais e o canal ficou vazio |
| PASS | `agente apaga canal nominal sem travar` | agente apagou o canal nominal direto em 2.1s: '🗑️ Exclusão concluída: #🧪-efemero (✅ 1/1 concluídos com sucesso.)' |
| PASS | `agente apaga lote direto, sem perguntar (padrão)` | apagou os 2 canais direto em 51.8s (1 ida(s) ao LLM): '🗑️ Exclusão concluída: #🧪-lote-1, #🧪-lote-2 (✅ 2/2 concluído' |
| PASS | `modo cauteloso pergunta e apaga após 'sim' (CONFIRM_DESTRUCTIVE)` | pediu confirmação e apagou depois do 'sim' ('Isso vai apagar 2 canais (**🧪-caut-1**, **🧪-caut-2**). Confi') |
| PASS | `apply_template (--allow-template)` | template 'estudos' criou 3 categorias, 6 canais dentro delas e 4 cargos (todos registrados para limpeza) |
| SKIP | `edit_server / set_icon no servidor real` | não executado de propósito (renomearia o servidor / trocaria o ícone real); a fase spy prova que set_icon agora baixa a imagem e manda os bytes em guild.edit(icon=...) |
| PASS | `limpeza` | todos os objetos de teste foram removidos |

## Matriz de capacidades: cada parâmetro, valor e combinação no Discord real
`caps` — ✅ 13 · ❌ 4 · ⚠️ 1 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `infra: categoria e canais da matriz` | categoria 🧪 caps + 🧪-caps-texto + 🧪-caps-voz prontos (tudo registrado para limpeza) |
| PASS | `cargos: criar com nome, cor, hoist, mentionable e permissões` | cargo real com cor 0x5865f2, hoist, mentionable e 3 permissões conferidas na API (posição 1) |
| FAIL | `cargos: editar cada propriedade e ver o efeito real` | ToolError: O cargo '🧪-caps-cargo' está acima ou na mesma posição do meu cargo mais alto. Suba o cargo do farol nas configurações de cargos do servidor. |
| FAIL | `cargos: valores inválidos, @everyone e hierarquia` | erro pouco claro para {'role': '1550358282760364062', 'color': 'roxo-neon'}: O cargo '🧪-caps-cargo' está acima ou na mesma posição do meu cargo mais alto. Suba o cargo do farol nas configurações de cargos do servidor. |
| FAIL | `cargos: dar e tirar de um membro (estado real)` | ToolError: Membro '1521612392105250836' não foi encontrado no servidor. |
| WARN | `canais: tipo stage` | stage: Falha ao criar canais: canal de palco (stage) só existe em servidor com o recurso **Comunidade** ativado — sem isso o Discord recusa a criação. |
| PASS | `canais: todos os tipos suportados (tipo real na API)` | tipos reais conferidos na API: text→text, voice→voice, category→category, forum→forum |
| PASS | `canais: tópico, NSFW, slowmode, bitrate e limite na criação` | texto: tópico, nsfw, slowmode 30s, categoria · voz: bitrate 96000, limite 4 — tudo conferido na API |
| PASS | `canais: editar cada propriedade e ver o efeito real` | nome; tópico; nsfw+slowmode; categoria (sair e voltar); voz: bitrate 96000, limite 7 |
| PASS | `canais: mover, clonar e excluir (estado real)` | mover por categoria e posição, clonar levando tópico+nsfw+slowmode+categoria e apagar só a cópia — tudo conferido na API |
| PASS | `canais: valores inválidos e limites (nada é criado por engano)` | valores inválidos recusados sem criar/alterar nada: não existe, slowmode, bitrate, limite, vazio, slowmode, bitrate, Nenhum parâmetro, negativa |
| PASS | `permissões: allow, deny, conflito, leitura e limpeza` | allow e deny em português viraram permissões reais (view_channel/send_messages/mention_everyone), conflito recusado e limpeza conferida na API |
| PASS | `permissões: sincronizar canal com a categoria` | permissão da categoria copiada para o canal filho (conferido na API) |
| PASS | `permissões: autor sem permissão é barrado antes da API` | 4 ferramentas recusadas ANTES de tocar no Discord (autor sem permissão) e nenhum objeto criado ou apagado |
| FAIL | `estrutura: export guarda as capacidades reais` | JSONDecodeError: Expecting ',' delimiter: line 1 column 1800 (char 1799) |
| PASS | `estrutura: import recria com os mesmos campos (round-trip)` | import recriou cargo (cor, hoist, mentionable, permissões) e canais (tópico, nsfw, slowmode, bitrate, limite, categoria e sem categoria) — conferido na API · '✅ Estrutura importada: 1 cargo(s) e 3 canal(is) recriados com tipo, tópico, nsfw, slowmode, bitrate,' |
| PASS | `repetição: mesma ordem várias vezes não quebra nem duplica efeito` | 3 canais iguais criados e editados em sequência, todos com o estado esperado |
| PASS | `limpeza` | todos os objetos de teste foram removidos |

## core.bot.FarolBot: on_message → resposta real no Discord
`botloop` — ✅ 7 · ❌ 0 · ⚠️ 0 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `canal temporário de teste` | canal temporário 🧪-loop-do-bot (1550358901633851402) criado |
| PASS | `ignora mensagem sem menção` | mensagem sem menção ignorada |
| PASS | `ignora mensagens de outros bots` | mensagem de outro bot ignorada |
| PASS | `DM é respondida com o aviso de escopo` | DM respondida com o aviso de escopo: 'Olá! Eu sou o **farol**, especialista em estruturar e organi' |
| PASS | `menção dispara o agente e responde` | on_message → agente → resposta real no canal: '**Pinguim**' |
| PASS | `reações de feedback 👀→✅` | reações corretas no Discord real: ['✅'] |
| PASS | `ferramenta real acionada por mensagem` | o bot criou de verdade: ['🧪-via-bot'] |

## Varredura de sobras de teste
`sweep` — ✅ 1 · ❌ 0 · ⚠️ 0 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `varredura de sobras` | 4 objeto(s) de teste removidos (#🧪-estrutura, #🧪-loop-do-bot, #🧪 categoria-loop, #🧪-via-bot) |
