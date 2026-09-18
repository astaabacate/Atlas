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

Cada achado virou teste (offline e/ou na matriz ao vivo) — regressão permanente, não relatório.

## O que ainda precisa do dono para ser verificado de verdade

- **Cargo do bot**: ele só gerencia cargos **abaixo** do próprio cargo. O E2E registra ⚠️ e diz o
  motivo quando o servidor de teste tem cargos no nível ou acima do bot (hoje há 13). Para a
  auditoria de hierarquia ficar 100% verde, suba o cargo do bot acima dos cargos de teste.
- **Servidor de teste**: a matriz cria e apaga objetos marcados com 🧪. Sem um servidor onde o bot
  tenha "Gerenciar canais/cargos/mensagens", a fase fica em ⚠️ "não verificável" em vez de ✅.
