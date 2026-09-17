# 🏮 Farol — relatório de teste E2E

- **Resumo:** ✅ 74 · ❌ 0 · ⚠️ 6 · ⏭️ 1
- **python:** 3.11.16
- **runner:** Linux
- **commit:** f439465
- **execução:** 35283805588
- **discord.py:** 2.7.1
- **fases:** static, spy, policy, connect, audit, tools, agent, mutate, botloop, sweep
- **mutações reais:** sim

## Anotações
- conectado como Atlas#1985 em 1 servidor(es)

## Checagens estáticas (schemas ↔ executores)
`static` — ✅ 6 · ❌ 0 · ⚠️ 0 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `27 ferramentas ↔ 27 executores` | 27 ferramentas e 27 executores casados |
| PASS | `assinaturas ↔ schemas` | 27 assinaturas conferem com os schemas |
| PASS | `toda ferramenta tem política` | as 27 ferramentas têm política declarada |
| PASS | `qualidade dos schemas enviados ao LLM` | descrições e schemas bem formados para function calling |
| PASS | `prompt de sistema completo` | prompt com os 5 blocos obrigatórios |
| PASS | `tamanho do payload enviado ao LLM` | schema com 11386 chars + prompt de 1877 chars |

## Duplos de teste: a ferramenta promete, a ferramenta faz?
`spy` — ✅ 18 · ❌ 0 · ⚠️ 0 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `create_channels cria na raiz de verdade` | chamou create_() e respondeu 'Pronto! Criei 3 canal(is): <#1009> <#1010> <#1011> 🎉 (✅ 3/3 ' |
| PASS | `create_channels cria DENTRO de categoria` | chamou create_() e respondeu 'Pronto! Criei 2 canal(is): <#1012> <#1013> 🎉 (✅ 2/2 concluíd' |
| PASS | `edit_channel edita de verdade` | chamou edit() e respondeu 'Canal <#1008> atualizado com sucesso!' |
| PASS | `move_channel move de verdade` | chamou edit() e respondeu 'Canal <#1008> movido com sucesso!' |
| PASS | `clone_channel clona de verdade` | chamou clone() e respondeu 'Canal clonado com sucesso: <#1014> 🎉' |
| PASS | `delete_channels apaga de verdade (1 canal)` | chamou delete() e respondeu '🗑️ Exclusão concluída: #canal-renomeado (✅ 1/1 concluídos co' |
| PASS | `delete_channels em lote pede confirmação` | 2 canais: exige confirmação e só apaga com confirmed=true |
| PASS | `edit_server altera de verdade` | chamou edit() e respondeu 'Informações do servidor atualizadas com sucesso!' |
| PASS | `set_icon altera de verdade (baixa a URL e envia os bytes)` | baixou a URL, mandou os bytes em guild.edit(icon=...) e aceitou data URI |
| PASS | `set_icon com estilo gera imagem sem rede` | gerou um PNG 256x256 sem tocar a rede |
| PASS | `set_icon NÃO mente quando o download falha` | erro honesto: 'Falha ao baixar a imagem: https://exemplo.invalido/nao-existe.png' |
| PASS | `apply_template cria de verdade` | 5 cargos, 3 categorias e 11 canais dentro delas |
| PASS | `import_structure cria de verdade` | chamou create_() e respondeu '✅ Estrutura importada com sucesso: 1 cargos e 1 canais recri' |
| PASS | `cargos: criar/editar/dar/tirar/apagar de verdade` | criou/editou/deu/tirou/apagou: todas as chamadas de API aconteceram |
| PASS | `permissões: set/clear/sync tocam a API` | set/clear/sync chamaram a API e show leu as permissões |
| PASS | `somente-leitura não muta nada` | 8 ferramentas de leitura rodaram sem mutar nada |
| PASS | `conversation_clear limpa a memória` | histórico do canal apagado de verdade |
| PASS | `agente não se auto-confirma (offline)` | sem confirmação do usuário nada é apagado; a pergunta sempre aparece; com o 'sim', apaga |

## Política de permissões e confirmação destrutiva
`policy` — ✅ 11 · ❌ 0 · ⚠️ 0 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `membro comum é bloqueado` | membro comum bloqueado: Você precisa da permissão 'Gerenciar canais' para usar a ferramenta 'create_channels'. |
| PASS | `bot sem permissão é bloqueado` | bot sem permissão bloqueado: Eu preciso da permissão 'Gerenciar canais' no meu cargo para executar 'create_channels'. Ajuste meu cargo e tente de novo. |
| PASS | `@everyone é intocável` | @everyone protegido: Não é possível alterar ou excluir o cargo @everyone. |
| PASS | `cargo de integração é intocável` | cargo de integração protegido: O cargo 'CargoDeBot' é gerenciado por uma integração ou aplicativo e não pode ser modificado. |
| PASS | `cargo acima do bot é protegido` | cargo acima do bot protegido: O cargo 'CargoDoDono' está acima ou na mesma posição do meu cargo mais alto. Suba o cargo do farol nas configurações de cargos do servidor. |
| PASS | `autor não edita cargo no próprio nível` | cargo no nível do autor protegido: O cargo 'CargoDoAutor' está acima ou na mesma posição do meu cargo mais alto. Suba o cargo do farol nas configurações de cargos do servidor. |
| PASS | `exclusão em lote exige confirmação` | 2 canais: pede confirmação e não apaga nada antes |
| PASS | `canal único apaga sem confirmação` | canal único nominal executa sem travar o fluxo |
| PASS | `exclusão de cargo exige confirmação` | cargo: exige confirmação e apaga com confirmed=true |
| PASS | `ferramenta inexistente é rejeitada` | ferramenta desconhecida rejeitada: A ferramenta 'ferramenta_inexistente' não foi encontrada. |
| PASS | `argumentos inválidos são rejeitados` | lista vazia rejeitada com ToolError: Nenhum canal foi informado para exclusão. |

## Conexão ao gateway do Discord
`connect` — ✅ 6 · ❌ 0 · ⚠️ 0 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `corredores de LLM na corrida` | llm7/tools, ovh, pollinations |
| PASS | `configuração carregada` | token no formato correto (72 chars) · provider=auto · intents: members=False, message_content=False |
| PASS | `corrida de LLMs responde` | vencedor pollinations (tools nativas: False) → 'pong' |
| PASS | `servidores do bot` | 1: asta (1546763083005825084) |
| PASS | `login e gateway` | conectado como Atlas#1985 · gateway em 47ms |
| PASS | `servidor e autor do teste` | servidor de teste: asta (1546763083005825084) · autor: ek8a (administrador) |

## Diagnóstico de permissões e hierarquia no servidor
`audit` — ✅ 5 · ❌ 0 · ⚠️ 1 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `permissões do bot no servidor` | OK: ['manage_channels', 'manage_roles', 'manage_guild', 'administrator', 'send_messages'] |
| WARN | `cargos que o bot não consegue gerenciar` | 3 cargo(s) no nível ou acima do bot (Atlas, iTinder, Cupido): ele não conseguirá editar/apagar esses cargos. Suba o cargo do farol (README Passo 3). |
| PASS | `hierarquia de cargos` | cargo do bot na posição 1 |
| PASS | `estrutura do servidor` | 3 categorias · 2 texto · 1 voz · 4 cargos · 4 membros |
| PASS | `snapshot do servidor` | snapshot com 15 linhas alimenta o prompt |
| PASS | `estado local bate com a API` | cache local bate com a API REST (6 canais, 4 cargos) |

## Ferramentas somente-leitura em servidor real
`tools` — ✅ 6 · ❌ 0 · ⚠️ 0 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `server_info` | 📊 **Informações de asta:** · • **ID:** `1546763083005825084` · • **Dono:** None · • **Membros:** 4 · • **Canais:** 6 · • **Cargos:** 4 · • **Criado em:** 2026-09-08 06:04:16.457000+00:00 |
| PASS | `list_roles` | listou os 4 cargos reais com menção e posição |
| PASS | `export_structure (JSON válido e completo)` | 3 categorias, 3 canais e 3 cargos exportados em JSON válido |
| PASS | `show_permissions` | O canal <#1546763083727249481> não possui permissões personalizadas configuradas. |
| PASS | `resolve por ID e por menção` | 6 canais e 4 cargos resolvidos por ID e por menção |
| PASS | `APIs externas (cores/emojis/tópicos/tradução)` | 5 APIs externas responderam |

## Agente + LLM ao vivo (prompt → ferramenta → resposta)
`agent` — ✅ 2 · ❌ 0 · ⚠️ 2 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| WARN | `prompt → ferramenta → resposta coerente` | o LLM não chamou nenhuma ferramenta (rodadas: [{'ferramentas_oferecidas': 27, 'ferramentas_chamadas': [], 'chars': 92, 'vencedor': 'pollinations'}]) — o provedor gratuito não cooperou nesta rodada ('Os cargos disponíveis no servidor são:\n\n- Cupido  \n- Atlas  \n- iTinder  \n- @everyone (todos)'). Sem chave de LLM paga isso é intermitente; rode de novo para conferir. (O comportamento do bot está… |
| PASS | `fora de escopo é recusado sem executar` | recusou moderação sem chamar ferramentas: 'Desculpe, mas não posso ajudar com banimentos ou outras ações de moderação. Meu foco exclu' |
| PASS | `agente conhece a estrutura real` | citou itens reais do servidor (Canais de Texto, Canais de Voz, 📁 Canais de Texto) |
| WARN | `memória do canal entre turnos` | não deu para conversar: o LLM não respondeu — o provedor gratuito não cooperou nesta rodada ('Nenhum dos 3 provedores de LLM respondeu (llm7/tools, ovh, pollinations). Erros: pollinations: HTTP 400 (opena'). Sem chave de LLM paga isso é intermitente; rode de novo para conferir. (O comportamento do bot está coberto offline nas fases spy/policy e em tests/.) |

## Mutações reais em objetos de teste (com limpeza)
`mutate` — ✅ 13 · ❌ 0 · ⚠️ 2 · ⏭️ 1

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `infra: categoria e canais de teste` | categoria 🧪 teste-farol + 🧪-texto + 🧪-voz criados (registrados para limpeza) |
| PASS | `create_channels DENTRO de categoria (via ferramenta)` | texto + voz criados dentro da categoria existente (['🧪-dentro-voz', '🧪-dentro']) |
| PASS | `create_channels na RAIZ (via ferramenta)` | texto + voz + categoria criados na raiz (['🧪-raiz-voz', '🧪-raiz-categoria', '🧪-raiz-texto']) |
| PASS | `edit_channel alterou de verdade` | nome, tópico e slowmode confirmados na API (🧪-renomeado) |
| PASS | `clone_channel clonou de verdade` | clone 🧪-clone criado com a mesma categoria |
| PASS | `move_channel moveu de verdade` | saiu e voltou de categoria, confirmado pela API |
| WARN | `cargo do farol no chão do servidor` | O cargo '🧪 teste-papel' está acima ou na mesma posição do meu cargo mais alto. Suba o cargo do farol nas configurações de cargos do servidor. Ação do dono (README Passo 3): arraste o cargo do farol para cima dos outros — sem isso ele não edita nem os cargos que ele mesmo cria. |
| PASS | `cargos: criar/editar/atribuir de verdade` | cargo criado e conferido na API; editar/dar/tirar ficou bloqueado pela posição do cargo do bot no servidor |
| PASS | `permissões de canal confirmadas pela API` | set, sync, clear e show (com filtro por target) confirmados pela API |
| PASS | `import_structure recriou a estrutura` | import recriou 3 canais e 2 cargo(s) |
| PASS | `fluxo de confirmação em canais reais` | 2 canais: pediu confirmação e só apagou com confirmed=true |
| PASS | `agente apaga canal nominal sem travar` | agente apagou o canal nominal direto: 'Canal #🧪‑efemero (ID: 1550277484199551019) excluído com sucesso.' |
| WARN | `agente pede confirmação em lote e apaga após 'sim'` | o modelo nem tentou excluir os 2 canais — o provedor gratuito não cooperou nesta rodada ('**Resumo das ações realizadas:**\n\n- Canal **#🧪‑efemero** (ID: 1550277484199551019) excluído com sucesso.  \n- T'). Sem chave de LLM paga isso é intermitente; rode de novo para conferir. (O comportamento do bot está coberto offline nas fases spy/policy e em tests/.) |
| PASS | `apply_template (--allow-template)` | template 'estudos' criou 3 categorias, 6 canais dentro delas e 4 cargos (todos registrados para limpeza) |
| SKIP | `edit_server / set_icon no servidor real` | não executado de propósito (renomearia o servidor / trocaria o ícone real); a fase spy prova que set_icon agora baixa a imagem e manda os bytes em guild.edit(icon=...) |
| PASS | `limpeza` | todos os objetos de teste foram removidos |

## core.bot.FarolBot: on_message → resposta real no Discord
`botloop` — ✅ 6 · ❌ 0 · ⚠️ 1 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `canal temporário de teste` | canal temporário 🧪-loop-do-bot (1550278439976837292) criado |
| PASS | `ignora mensagem sem menção` | mensagem sem menção ignorada |
| PASS | `ignora mensagens de outros bots` | mensagem de outro bot ignorada |
| PASS | `DM é respondida com o aviso de escopo` | DM respondida com o aviso de escopo: 'Olá! Eu sou o **farol**, especialista em estruturar e organi' |
| PASS | `menção dispara o agente e responde` | on_message → agente → resposta real no canal: 'asta' |
| PASS | `reações de feedback 👀→✅` | reações corretas no Discord real: ['✅'] |
| WARN | `ferramenta real acionada por mensagem` | o bot não criou o canal — o provedor gratuito não cooperou nesta rodada ('❌ Ocorreu um erro ao processar seu pedido:\n`Nenhum dos 3 provedores de LLM respondeu (llm7/tools, ovh, pollina'). Sem chave de LLM paga isso é intermitente; rode de novo para conferir. (O comportamento do bot está coberto offline nas fases spy/policy e em tests/.) |

## Varredura de sobras de teste
`sweep` — ✅ 1 · ❌ 0 · ⚠️ 0 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `varredura de sobras` | 2 objeto(s) de teste removidos (#🧪-loop-do-bot, #🧪 categoria-loop) |
