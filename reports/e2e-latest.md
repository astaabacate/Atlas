# 🏮 Farol — relatório de teste E2E

- **Resumo:** ✅ 49 · ❌ 4 · ⚠️ 2 · ⏭️ 0
- **fases:** agent
- **mutações reais:** não
- **python:** 3.11.16
- **runner:** Linux
- **commit:** 62fcfed
- **execução:** 35277780929
- **discord.py:** 2.7.1

## Anotações
- conectado como Atlas#1985 em 1 servidor(es)

## Checagens estáticas (schemas ↔ executores)
`static` — ✅ 6 · ❌ 0 · ⚠️ 1 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `27 ferramentas ↔ 27 executores` | 27 ferramentas e 27 executores casados |
| WARN | `parâmetros declarados e nunca usados` | o LLM pode preencher e o executor ignorar: show_permissions.target, set_icon.style |
| PASS | `assinaturas ↔ schemas` | 27 assinaturas conferem com os schemas |
| PASS | `toda ferramenta tem política` | as 27 ferramentas têm política declarada |
| PASS | `qualidade dos schemas enviados ao LLM` | descrições e schemas bem formados para function calling |
| PASS | `prompt de sistema completo` | prompt com os 5 blocos obrigatórios |
| PASS | `tamanho do payload enviado ao LLM` | schema com 11386 chars + prompt de 1585 chars |

## Duplos de teste: a ferramenta promete, a ferramenta faz?
`spy` — ✅ 12 · ❌ 3 · ⚠️ 0 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `create_channels cria na raiz de verdade` | chamou create_() e respondeu 'Pronto! Criei 3 canal(is): <#1009> <#1010> <#1011> 🎉 (✅ 3/3 ' |
| FAIL | `create_channels cria DENTRO de categoria` | ToolError: Falha ao criar canais: __main__.SpyGuild.create_text_channel() got multiple values for keyword argument 'category' |
| PASS | `edit_channel edita de verdade` | chamou edit() e respondeu 'Canal <#1008> atualizado com sucesso!' |
| PASS | `move_channel move de verdade` | chamou edit() e respondeu 'Canal <#1008> movido com sucesso!' |
| PASS | `clone_channel clona de verdade` | chamou clone() e respondeu 'Canal clonado com sucesso: <#1012> 🎉' |
| PASS | `delete_channels apaga de verdade (1 canal)` | chamou delete() e respondeu '🗑️ Exclusão concluída: #canal-renomeado (✅ 1/1 concluídos co' |
| PASS | `delete_channels em lote pede confirmação` | 2 canais: exige confirmação e só apaga com confirmed=true |
| PASS | `edit_server altera de verdade` | chamou edit() e respondeu 'Informações do servidor atualizadas com sucesso!' |
| FAIL | `set_icon altera de verdade` | respondeu 'Ícone do servidor atualizado com sucesso a partir de https://example.c' mas NÃO chamou edit() — chamadas vistas: nenhuma |
| FAIL | `apply_template cria de verdade` | ToolError: Erro ao executar 'apply_template': __main__.SpyGuild.create_text_channel() got multiple values for keyword argument 'category' |
| PASS | `import_structure cria de verdade` | chamou create_() e respondeu '✅ Estrutura importada com sucesso: 1 cargos e 1 canais recri' |
| PASS | `cargos: criar/editar/dar/tirar/apagar de verdade` | criou/editou/deu/tirou/apagou: todas as chamadas de API aconteceram |
| PASS | `permissões: set/clear/sync tocam a API` | set/clear/sync chamaram a API e show leu as permissões |
| PASS | `somente-leitura não muta nada` | 8 ferramentas de leitura rodaram sem mutar nada |
| PASS | `conversation_clear limpa a memória` | histórico do canal apagado de verdade |

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
| PASS | `login e gateway` | conectado como Atlas#1985 · gateway em 85ms |
| PASS | `servidor e autor do teste` | servidor de teste: asta (1546763083005825084) · autor: ek8a (administrador) |

## Diagnóstico de permissões e hierarquia no servidor
`audit` — ✅ 5 · ❌ 0 · ⚠️ 1 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `permissões do bot no servidor` | OK: ['manage_channels', 'manage_roles', 'manage_guild', 'administrator', 'send_messages'] |
| WARN | `hierarquia de cargos` | 3 cargo(s) no nível ou acima do bot (Atlas, iTinder, Cupido): ele não conseguirá editar/apagar esses cargos. Suba o cargo do farol (README Passo 3). |
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
`agent` — ✅ 3 · ❌ 1 · ⚠️ 0 · ⏭️ 0

| Status | Verificação | Detalhe |
| --- | --- | --- |
| PASS | `prompt → ferramenta → resposta coerente` | ferramentas ['tool_list_roles', 'tool_list_roles'] · vencedor pollinations · citou ['Atlas', 'iTinder', 'Cupido'] |
| PASS | `fora de escopo é recusado sem executar` | recusou moderação sem chamar ferramentas: 'Desculpe, mas não posso ajudar com banimentos ou outras ações de moderação. Meu foco é org' |
| FAIL | `agente conhece a estrutura real` | não citou nada real do servidor (nem nome nem menção): '**Resumo do que foi feito até agora**\n\n1. **Cargos listados** – Apresentei os cargos existentes no servidor:\u202fCupido, Atlas, iTinder e everyone.  \n2. **Solicitaç' |
| PASS | `memória do canal entre turnos` | histórico do canal lembrado entre turnos |
