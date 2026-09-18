# 🏮 Farol — relatório de teste E2E

- **Resumo:** ✅ 45 · ❌ 9 · ⚠️ 0 · ⏭️ 7
- **python:** 3.11.16
- **runner:** Linux
- **commit:** 5d8469f
- **execução:** 35341439906
- **discord.py:** 2.7.1
- **fases:** static, spy, policy, connect, audit, tools, agent, mutate, caps, botloop, sweep
- **mutações reais:** sim

## Checagens estáticas (schemas ↔ executores)
`static` — ✅ 6 · ❌ 0 · ⚠️ 0 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `27 ferramentas ↔ 27 executores` | 31 ferramentas e 31 executores casados |
| PASS | `assinaturas ↔ schemas` | 31 assinaturas conferem com os schemas |
| PASS | `toda ferramenta tem política` | as 31 ferramentas têm política declarada |
| PASS | `qualidade dos schemas enviados ao LLM` | descrições e schemas bem formados para function calling |
| PASS | `prompt de sistema completo` | prompt com os 7 blocos obrigatórios (regra de confirmação dinâmica) |
| PASS | `tamanho do payload enviado ao LLM` | schema com 15015 chars + prompt de 2038 chars |

## Duplos de teste: a ferramenta promete, a ferramenta faz?
`spy` — ✅ 22 · ❌ 0 · ⚠️ 0 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `create_channels cria na raiz de verdade` | chamou create_() e respondeu 'Pronto! Criei 3 canal(is): <#1009> <#1010> <#1011> 🎉 (✅ 3/3 ' |
| PASS | `create_channels cria DENTRO de categoria` | chamou create_() e respondeu 'Pronto! Criei 2 canal(is): <#1012> <#1013> 🎉 (✅ 2/2 concluíd' |
| PASS | `edit_channel edita de verdade` | chamou edit() e respondeu 'Canal <#1008> atualizado com sucesso (name, nsfw, slowmode_d' |
| PASS | `move_channel move de verdade` | chamou edit() e respondeu 'Canal <#1008> movido com sucesso (categoria: sem categoria, ' |
| PASS | `clone_channel clona de verdade` | chamou clone() e respondeu 'Canal clonado: <#1014> 🎉 (copiei tópico, NSFW, modo lento, c' |
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
| PASS | `cargo acima do bot é protegido` | cargo acima do bot protegido: O cargo 'CargoDoDono' (posição 6) está acima ou na mesma posição do meu cargo mais alto (posição 5). Suba o cargo do farol nas configurações de cargos do servidor. |
| PASS | `autor não edita cargo no próprio nível` | cargo no nível do autor protegido: O cargo 'CargoDoAutor' (posição 9) está acima ou na mesma posição do meu cargo mais alto (posição 5). Suba o cargo do farol nas configurações de cargos do servidor. |
| PASS | `exclusão em lote exige confirmação (modo cauteloso)` | 2 canais: pede confirmação e não apaga nada antes |
| PASS | `exclusão em lote executa direto no padrão` | 2 canais: modo direto apaga e informa, sem perguntar |
| PASS | `canal único apaga sem confirmação` | canal único nominal executa sem travar o fluxo |
| PASS | `exclusão de cargo exige confirmação (modo cauteloso)` | cargo: exige confirmação e apaga com confirmed=true |
| PASS | `exclusão de cargo executa direto no padrão` | cargo: modo direto apaga o que foi pedido, sem perguntar |
| PASS | `ferramenta inexistente é rejeitada` | ferramenta desconhecida rejeitada: A ferramenta 'ferramenta_inexistente' não foi encontrada. |
| PASS | `argumentos inválidos são rejeitados` | lista vazia rejeitada com ToolError: Nenhum canal foi informado para exclusão. |

## Conexão ao gateway do Discord
`connect` — ✅ 3 · ❌ 2 · ⚠️ 0 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `corredores de LLM na corrida` | kilo/tools |
| PASS | `configuração carregada` | token no formato correto (72 chars) · provider=auto · intents: members=False, message_content=False |
| PASS | `corrida de LLMs responde` | vencedor kilo (tools nativas: True) → 'pong' |
| FAIL | `login e gateway` | LoginFailure: Improper token has been passed. |
| FAIL | `servidor e autor do teste` | sem servidor para escolher autor |

## Diagnóstico de permissões e hierarquia no servidor
`audit` — ✅ 0 · ❌ 1 · ⚠️ 0 · ⏭️ 1

| Status | Verificação | Detalhe |
| --- | --- | --- |
| FAIL | `conexão` | LoginFailure: Improper token has been passed. |
| SKIP | `diagnóstico` | sem conexão ao Discord |

## Ferramentas somente-leitura em servidor real
`tools` — ✅ 0 · ❌ 1 · ⚠️ 0 · ⏭️ 1

| Status | Verificação | Detalhe |
| --- | --- | --- |
| FAIL | `conexão` | LoginFailure: Improper token has been passed. |
| SKIP | `ferramentas de leitura` | sem conexão ao Discord |

## Agente + LLM ao vivo (prompt → ferramenta → resposta)
`agent` — ✅ 0 · ❌ 1 · ⚠️ 0 · ⏭️ 1

| Status | Verificação | Detalhe |
| --- | --- | --- |
| FAIL | `conexão` | LoginFailure: Improper token has been passed. |
| SKIP | `agente` | sem conexão ao Discord |

## Mutações reais em objetos de teste (com limpeza)
`mutate` — ✅ 0 · ❌ 1 · ⚠️ 0 · ⏭️ 1

| Status | Verificação | Detalhe |
| --- | --- | --- |
| FAIL | `conexão` | LoginFailure: Improper token has been passed. |
| SKIP | `mutações reais` | sem conexão ao Discord |

## Matriz de capacidades: cada parâmetro, valor e combinação no Discord real
`caps` — ✅ 0 · ❌ 1 · ⚠️ 0 · ⏭️ 1

| Status | Verificação | Detalhe |
| --- | --- | --- |
| FAIL | `conexão` | LoginFailure: Improper token has been passed. |
| SKIP | `matriz de capacidades` | sem conexão ao Discord |

## core.bot.FarolBot: on_message → resposta real no Discord
`botloop` — ✅ 0 · ❌ 1 · ⚠️ 0 · ⏭️ 1

| Status | Verificação | Detalhe |
| --- | --- | --- |
| FAIL | `conexão` | LoginFailure: Improper token has been passed. |
| SKIP | `loop do bot` | sem conexão ao Discord |

## Varredura de sobras de teste
`sweep` — ✅ 0 · ❌ 1 · ⚠️ 0 · ⏭️ 1

| Status | Verificação | Detalhe |
| --- | --- | --- |
| FAIL | `conexão` | LoginFailure: Improper token has been passed. |
| SKIP | `varredura` | sem conexão ao Discord |
