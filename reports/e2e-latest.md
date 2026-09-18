# 🏮 Farol — relatório de teste E2E

- **Resumo:** ✅ 67 · ❌ 0 · ⚠️ 7 · ⏭️ 6
- **python:** 3.11.16
- **runner:** Linux
- **commit:** 3ae66cc
- **execução:** 35391125443
- **discord.py:** 2.7.1
- **fases:** static, spy, policy, connect, audit, tools, agent, mutate, caps, botloop, sweep
- **mutações reais:** sim

## Anotações
- conectado como Atlas#1985 em 1 servidor(es)

## Checagens estáticas (schemas ↔ executores)
`static` — ✅ 6 · ❌ 0 · ⚠️ 0 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `31 ferramentas ↔ 31 executores` | 31 ferramentas e 31 executores casados |
| PASS | `assinaturas ↔ schemas` | 31 assinaturas conferem com os schemas |
| PASS | `toda ferramenta tem política` | as 31 ferramentas têm política declarada |
| PASS | `qualidade dos schemas enviados ao LLM` | descrições e schemas bem formados para function calling |
| PASS | `prompt de sistema completo` | prompt com os 7 blocos obrigatórios (regra de confirmação dinâmica) |
| PASS | `tamanho do payload enviado ao LLM` | schema com 15123 chars + prompt de 2322 chars |

## Duplos de teste: a ferramenta promete, a ferramenta faz?
`spy` — ✅ 23 · ❌ 0 · ⚠️ 0 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `create_channels cria na raiz de verdade` | chamou create_() e respondeu 'Pronto! Criei 3 canal(is): <#1010> <#1011> <#1012> 🎉 (✅ 3/3 ' |
| PASS | `create_channels cria DENTRO de categoria` | chamou create_() e respondeu 'Pronto! Criei 2 canal(is): <#1013> <#1014> 🎉 (✅ 2/2 concluíd' |
| PASS | `edit_channel edita de verdade` | chamou edit() e respondeu 'Canal <#1008> atualizado com sucesso (name, nsfw, slowmode_d' |
| PASS | `move_channel move de verdade` | chamou edit() e respondeu 'Canal <#1008> movido com sucesso (categoria: sem categoria, ' |
| PASS | `clone_channel clona de verdade` | chamou clone() e respondeu 'Canal clonado: <#1015> 🎉 (copiei tópico, NSFW, modo lento, c' |
| PASS | `delete_channels apaga de verdade (1 canal)` | chamou delete() e respondeu '🗑️ Exclusão concluída: #descartavel-spy (✅ 1/1 concluídos co' |
| PASS | `delete_channels NUNCA apaga o canal da conversa` | canal da conversa preservado no lote, com aviso na resposta; pedido só dele é recusado explicando o caminho (clear_messages) |
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
`connect` — ✅ 6 · ❌ 0 · ⚠️ 0 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `corredores de LLM na corrida` | kilo/tools |
| PASS | `configuração carregada` | token no formato correto (72 chars) · provider=auto · intents: members=False, message_content=False |
| PASS | `corrida de LLMs responde` | vencedor kilo (tools nativas: True) → 'pong' |
| PASS | `servidores do bot` | 1: Pinguim (1546763083005825084) |
| PASS | `login e gateway` | conectado como Atlas#1985 · gateway em 45ms |
| PASS | `servidor e autor do teste` | servidor de teste: Pinguim (1546763083005825084) · autor: ek8a (administrador) |

## Diagnóstico de permissões e hierarquia no servidor
`audit` — ✅ 5 · ❌ 0 · ⚠️ 1 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `permissões do bot no servidor` | OK: ['manage_channels', 'manage_roles', 'manage_guild', 'administrator', 'send_messages'] |
| WARN | `cargos que o bot não consegue gerenciar` | 1 cargo(s) no nível ou acima do bot (Atlas): ele não conseguirá editar/apagar esses cargos. Suba o cargo do farol (README Passo 3). |
| PASS | `hierarquia de cargos` | cargo do bot na posição 27 |
| PASS | `estrutura do servidor` | 5 categorias · 0 texto · 0 voz · 27 cargos · 4 membros |
| PASS | `snapshot do servidor` | snapshot com 35 linhas alimenta o prompt |
| PASS | `estado local bate com a API` | cache local bate com a API REST (5 canais, 27 cargos) |

## Ferramentas somente-leitura em servidor real
`tools` — ✅ 7 · ❌ 0 · ⚠️ 0 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `server_info` | 📊 **Informações de Pinguim:** · • **ID:** `1546763083005825084` · • **Dono:** <@1521612392105250836> · • **Membros:** 4 · • **Canais:** 5 · • **Cargos:** 27 · • **Criado em:** 2026-09-08 06:04:16.4570 |
| PASS | `performance_report (tempo das respostas)` | Ainda não respondi nada nesta sessão do bot (nenhuma medida de tempo disponível). Me peça de novo depois de algumas tarefas. |
| PASS | `list_roles` | listou os 27 cargos reais com menção e posição |
| PASS | `export_structure (JSON válido e completo)` | servidor grande: JSON completo com 2366 chars no recorte AVISADO (aviso + balanço de canais/categorias/cargos exportados) |
| PASS | `show_permissions` | O canal <#1550466167800598580> não possui permissões personalizadas configuradas. |
| PASS | `resolve por ID e por menção` | 5 canais e 6 cargos resolvidos por ID e por menção |
| PASS | `APIs externas (cores/emojis/tópicos/tradução)` | 5 APIs externas responderam |

## Agente + LLM ao vivo (prompt → ferramenta → resposta)
`agent` — ✅ 5 · ❌ 0 · ⚠️ 1 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `prompt → ferramenta → resposta coerente` | ferramentas ['list_roles'] · vencedor kilo · citou ['@everyone', '🧪-caps-import-cargo', '🧪-caps-cargo'] |
| PASS | `tempo de cada ida ao modelo` | 1 chamada(s) ao modelo: mediana **2.6s** (2.6s) · corredores que responderam: kilo |
| PASS | `fora de escopo é recusado sem executar` | recusou moderação sem chamar ferramentas: 'Não posso aplicar banimentos ou punições; meu foco exclusivo é montar e organizar a estrut' |
| WARN | `agente: resposta com dados reais (sem listar nomes)` | o modelo respondeu com o resumo do servidor (dados reais conferidos na API) em vez de listar categorias/canais por nome |
| PASS | `agente conhece a estrutura real` | respondeu com dados reais do servidor (nome do servidor (Pinguim), menção do dono, canais=5, cargos=27) |
| PASS | `memória do canal entre turnos` | histórico do canal lembrado entre turnos |

## Mutações reais em objetos de teste (com limpeza)
`mutate` — ✅ 0 · ❌ 0 · ⚠️ 1 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| WARN | `fase interrompida por tempo` | passou de 900.0s e foi interrompida — o que aparece abaixo é o que terminou; onde estava pendurada: client.py:731:connect, e2e_live.py:3942:run |

## Matriz de capacidades: cada parâmetro, valor e combinação no Discord real
`caps` — ✅ 0 · ❌ 0 · ⚠️ 1 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| WARN | `fase interrompida por tempo` | passou de 900.0s e foi interrompida — o que aparece abaixo é o que terminou; onde estava pendurada: client.py:731:connect, e2e_live.py:3942:run |

## core.bot.FarolBot: on_message → resposta real no Discord
`botloop` — ✅ 0 · ❌ 0 · ⚠️ 1 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| WARN | `fase interrompida por tempo` | passou de 420.0s e foi interrompida — o que aparece abaixo é o que terminou; onde estava pendurada: client.py:731:connect, e2e_live.py:3942:run |

## Varredura de sobras de teste
`sweep` — ✅ 1 · ❌ 0 · ⚠️ 0 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `varredura de sobras` | 7 objeto(s) de teste removidos (#🧪 caps, #🧪-tipo-category, #🧪 caps-destino, #🧪 caps-sync, #🧪 caps-import, @🧪-caps-cargo, @🧪-caps-import-cargo) |

## Cobertura: quais ferramentas foram exercitadas nesta execução
`cobertura` — ✅ 0 · ❌ 0 · ⚠️ 2 · ⏭️ 6

| Status | Verificação | Detalhe |
| --- | --- | --- |
| WARN | `ferramentas exercitadas nesta execução` | 29/31 ferramentas — não exercitadas: delete_roles, diagnostic_report, performance_report (de propósito nesta suíte: set_icon, que mexe na identidade do farol, e diagnostic_report, que manda DM ao dono; qualquer outra que apareça aqui é lacuna a fechar) |
| SKIP | `ferramentas exercitadas nesta execução` | nenhuma fase desta execução chamou ferramenta (rodada só de merge?) |
| WARN | `ferramentas exercitadas nesta execução` | 10/31 ferramentas — não exercitadas: apply_template, clear_messages, clear_permissions, clone_channel, conversation_clear, create_channels, create_roles, delete_channels, delete_role, delete_roles, diagnostic_report, edit_channel, edit_role, edit_server, give_role, import_structure, move_channel, set_icon, set_permissions, sync_permissions, take_role (de propósito nesta suíte: set_icon, que mexe … |
| SKIP | `ferramentas exercitadas nesta execução` | nenhuma fase desta execução chamou ferramenta (rodada só de merge?) |
| SKIP | `ferramentas exercitadas nesta execução` | nenhuma fase desta execução chamou ferramenta (rodada só de merge?) |
| SKIP | `ferramentas exercitadas nesta execução` | nenhuma fase desta execução chamou ferramenta (rodada só de merge?) |
| SKIP | `ferramentas exercitadas nesta execução` | nenhuma fase desta execução chamou ferramenta (rodada só de merge?) |
| SKIP | `ferramentas exercitadas nesta execução` | nenhuma fase desta execução chamou ferramenta (rodada só de merge?) |
