# Segurança do banco: Auth, RLS, RBAC, RPCs e grants

> Status: implementado + transição em andamento
> Owner: segurança/dados
> Última revisão: 2026-09-19
> Fonte: schema/advisors do Supabase `dmrqnbdvbkfqzctcerbx`

## Modelo mental

Segurança do TDA possui camadas diferentes e elas não devem ser confundidas:

```text
identidade Auth
   ↓
profiles
   ↓
membership / role assignment
   ↓
capabilities + scope
   ↓
RLS/RPC/server boundary
   ↓
dado permitido
```

O fato de o servidor possuir uma chave poderosa **não transforma toda consulta server-side em segura automaticamente**. Cada integração deve selecionar campos e aplicar fronteira de domínio deliberada.

## Auth

`profiles.auth_user_id` pode apontar para `auth.users.id`.

Direção do reboot:

- OAuth/Auth identifica usuário;
- profile resolve identidade humana interna;
- capabilities resolvem ações permitidas;
- conteúdo sensível só é retornado depois da autorização.

Não usar email, Discord handle ou character name como substituto permanente do `auth_user_id/profile_id`.

## Modelo legado: `campaign_members`

Possui roles `owner`, `master`, `player`, `reviewer`, `viewer` e ainda é usado por funções/RPCs legadas.

**Política:** manter compatibilidade durante transição, mas não expandir esse modelo para novas features quando RBAC resolve o caso.

## RBAC extensível

### `permission_catalog`

Capabilities/ações, classificadas por plane `technical | narrative | mixed`.

### `role_definitions`

Agrupamentos nomeados de capabilities.

### `role_permissions`

Mapeia role para capability.

### `role_assignments`

Mapeia profile + role para scope:

- `project`;
- `campaign`;
- `session`;
- `resource`;
- `integration`.

O scope canônico do reboot é `project/tda`. `project/dnd-scribe` permanece temporariamente porque consumidores legados ainda o utilizam.

### Regra da UI/API nova

Perguntar:

```text
usuário possui capability X no scope Y?
```

Evitar:

```text
role_slug == "master"
```

A primeira forma permite alterar composição de roles sem reescrever UI e regras de negócio.

## RLS

Na revisão de 2026-09-06, RLS estava habilitado em todas as 43 tabelas públicas observadas.

Muitas tabelas não possuem policy explícita. O Database Linter reporta `rls_enabled_no_policy`, mas nesse caso o efeito é **deny-by-default** para roles sujeitas ao RLS.

### Regra

Não adicionar uma policy ampla apenas para remover warning/info do linter.

Uma policy nova precisa responder:

1. quem lê/escreve?
2. por qual identity/capability?
3. qual campaign/scope?
4. quais colunas/dados podem chegar ao client?
5. a mesma policy vaza informação por join/RPC?
6. existe superfície server-side mais adequada?

## Fronteira pública atual

O site público usa consultas server-side estreitas para conteúdo publicado da campanha principal. A chave server-side possui poder elevado e **não é tecnicamente read-only**.

Mitigações atuais:

- secret não vai ao browser;
- seleção explícita de campos;
- filtro de campanha/estado publicado;
- catálogo não carrega transcrições completas nem dados de usuário;
- conteúdo Markdown não aceita HTML bruto arbitrário;
- mídia passa por allowlist/contrato de origem.

### Dívida futura

Uma role/view/endpoint tecnicamente read-only e de menor privilégio é desejável antes de ampliar a superfície pública, desde que introduzida com migration revisada e sem quebrar o legado.

## `SECURITY DEFINER`

A inspeção revalidada em 2026-09-10 confirmou **8 funções `SECURITY DEFINER` em `public`**:

- `access_directory(campaign_slug text)`;
- `current_profile_id()`;
- `has_campaign_role(target_campaign_id uuid, allowed_roles text[])`;
- `has_campaign_role_slug(campaign_slug text, allowed_roles text[])`;
- `review_profile_claim(...)`;
- `review_table_note(...)`;
- `submit_profile_claim(...)`;
- `table_notes_directory(...)`.

Estado de grants observado nas oito:

- `anon`: sem `EXECUTE`;
- `authenticated`: com `EXECUTE`;
- `service_role`: com `EXECUTE`;
- owner: `postgres`.

Todas as definições observadas fixam `search_path` em `pg_catalog, public`.

O warning do advisor **não significa automaticamente vulnerabilidade**, porque várias dessas RPCs são endpoints autenticados deliberados. Porém `SECURITY DEFINER` executa com privilégios do owner e precisa ser tratado como boundary de segurança.

O inventário função a função, incluindo classificação, autorização interna, risco e decisão atual de grant, está em [`rpc-inventory.md`](rpc-inventory.md).

### Classificação atual

Helpers internos candidatos a perder `EXECUTE` direto de `authenticated` depois da prova final de consumidores:

- `current_profile_id()`;
- `has_campaign_role(...)`;
- `has_campaign_role_slug(...)`.

Endpoints autenticados/administrativos mantidos durante a transição:

- `access_directory(...)`;
- `submit_profile_claim(...)`;
- `review_profile_claim(...)`;
- `table_notes_directory(...)`;
- `review_table_note(...)`.

### Atenção especial: `access_directory`

O caminho não-admin mascara dados Discord e retorna apenas profiles ainda não ligados a Auth, mas não exige explicitamente membership prévia na campanha solicitada. Com uma única campanha conhecida isso não criou um vazamento cross-campaign observado; antes de multi-campaign ou Edit público, o contrato de onboarding precisa decidir se a consulta exige convite/membership/capability ou se diretório autenticado por slug é comportamento intencional.

Não alterar essa semântica silenciosamente: é regra de produto/autorização e precisa de teste negativo.

### Checklist para cada RPC

- `search_path` seguro/qualificado;
- validação interna de auth/profile;
- validação de campaign/scope/capability;
- inputs não permitem acessar outro usuário/campanha;
- retorno não contém campos privados desnecessários;
- `EXECUTE` concedido somente a roles que realmente precisam;
- helper interno não exposto por acidente via `/rest/v1/rpc`;
- comportamento coberto por teste negativo, não só happy path.

### Ação antes do Edit público

- cobrir os cinco endpoints intencionais com testes positivos/negativos;
- decidir contrato multi-campaign de `access_directory`;
- comprovar ausência de consumidores externos dos três helpers;
- quando seguro, versionar migration que revogue `EXECUTE` direto de `authenticated` dos helpers;
- rodar advisors e smoke tests depois da mudança;
- convergir autorização nova para capabilities/RBAC.

Não revogar em massa sem mapear consumidores.

## Durabilidade server-only do World

A migration candidata `20260919170000_world_edit_durable_recovery` separa o lock temporário da persistência do trabalho editorial:

- `world_edit_leases` continua responsável por exclusividade e expiração curta;
- `world_edit_drafts` guarda checkpoints privados por campaign/profile/token com RLS habilitado e nenhuma policy/grant de browser;
- `anon` e `authenticated` não leem nem escrevem checkpoints;
- `service_role` recebe somente `SELECT/INSERT/UPDATE` no arquivo durável, sem `DELETE`;
- troca de holder não transfere o conteúdo privado do editor anterior;
- recovery automático exige o mesmo editor e revisions compatíveis;
- checkpoint stale é preservado, mas não é aplicado sobre um estado publicado diferente;
- release comum não equivale a descarte;
- discard explícito possui RPC própria e mantém tombstone;
- receipt positivo de publicação é persistido no mesmo commit canônico antes de consumir o lease, permitindo reconciliar perda da resposta HTTP sem confiar no cliente.

Esse boundary não amplia capabilities: autoria factual continua exigindo `campaign.content.edit` e a sessão exclusiva continua exigindo `campaign.world.layout.edit`.

## `SECURITY INVOKER` server-only do Edit

O arquivo local `20260907115300_edit_transcript_segment_atomic` descreve `public.edit_transcript_segment_atomic(...)`. Em 2026-09-08 a função física foi confirmada no Supabase canônico sob migration history remoto `20260908064257 edit_transcript_segment_atomic`.

A definição física observada corresponde ao contrato local quanto a assinatura/corpo, `SECURITY INVOKER`, `search_path`, comentário e grants efetivos. Existe drift de **ID de migration**, registrado em `migrations.md`; equivalência funcional não autoriza reescrever migration history.

Decisões de segurança observadas/esperadas:

- `SECURITY INVOKER`, não eleva para owner;
- `search_path = pg_catalog, public`;
- `PUBLIC`, `anon` e `authenticated` sem `EXECUTE`;
- `service_role` com `EXECUTE`;
- chamada exclusivamente server-side;
- usuário/profile/capability `campaign.content.edit` resolvidos antes da persistence;
- actor vem do contexto autorizado da aplicação, não de escolha livre do browser;
- `segment -> session -> campaign` é revalidado dentro da função;
- recurso de outra campaign retorna `not_found`;
- update otimista e `audit_log` são atômicos;
- nenhuma das 8 funções `SECURITY DEFINER` legadas é alterada por esse boundary.

### Por que `SECURITY INVOKER`

`anon` e `authenticated` não possuem os grants diretos necessários ao write, enquanto `service_role` possui o privilégio server-side. A função pode herdar o privilégio do caller sem elevação para owner.

O uso de `service_role` continua sendo boundary poderoso: a aplicação não pode oferecer a função como CRUD genérico nem confiar no segredo server-side como substituto de autorização.

### Concorrência e audience

O SQL:

- bloqueia a linha do segmento antes da decisão de revision;
- exige igualdade com `expectedRevision`;
- incrementa revision exatamente em 1 apenas no update válido;
- não cria audit em conflito;
- não revela a existência de segmento cross-campaign;
- preserva `character_name` quando o speaker não muda e invalida essa identidade quando o speaker textual muda.

## `SECURITY INVOKER` server-only do World layout — aplicado

As migrations de persistência editorial do World layout e lease exclusivo estão aplicadas no Supabase canônico. O migration history remoto inclui `20260908203249 world_layout_capability`, `20260908203331 world_layout_snapshot_atomic`, `20260908203441 world_layout_service_role_privileges`, `20260908203642 world_layout_site_editor_grant` e `20260909205836 world_edit_lease`.

Capability:

```text
campaign.world.layout.edit
```

- plane `narrative`;
- o catálogo/role foi versionado sem criar assignment de usuário por inferência;
- assignments ativos são avaliados por scope no boundary.

Storage `world_layout_snapshots` e `world_edit_leases`:

- RLS habilitado;
- nenhuma policy de browser;
- `PUBLIC`, `anon` e `authenticated` sem acesso;
- grants server-side mínimos conforme contrato de cada tabela.

RPCs do boundary:

- `save_world_layout_snapshot_atomic(...)`;
- `acquire_world_edit_lease_atomic(...)`;
- `renew_world_edit_lease_atomic(...)`;
- `save_world_edit_layout_draft_atomic(...)`;
- `publish_world_edit_layout_atomic(...)`;
- `release_world_edit_lease_atomic(...)`.

As funções observadas são `SECURITY INVOKER`, usam `search_path = pg_catalog, public`, não são executáveis por `anon/authenticated` e revalidam identity/profile, capability, assignment ativo, campaign/scope, lease e revision conforme o caso.

### Audience na leitura

A tabela não ganhou policy pública como atalho. O fluxo server-side continua:

```text
request + identidade/audience
  -> projection autorizada de nodes/edges
  -> carregar snapshot aplicável
  -> intersectar positions com IDs já autorizados
  -> sanitizar contrato
  -> browser
```

Chaves presentes no JSONB jamais podem ser usadas para decidir quais nodes existem/ficam visíveis.

### Validação observada

O PostgreSQL sintético prova RLS/grants, autorização/scope, payload, revision/conflict/no-op, recovery e rollback. No Supabase canônico, grants e signatures foram revalidados após aplicação; em 2026-09-10 havia `0` snapshots e `0` leases ativos durante o preflight da autoria factual.

## `SECURITY INVOKER` server-only do World graph — aplicado #119

A migration versionada localmente como `20260909215000_world_graph_authoring.sql` foi aplicada deliberadamente em 2026-09-10 e registrada no migration history remoto como `20260910002529 world_graph_authoring`. Não reexecutar o DDL para alinhar apenas o número local/remoto; o drift nominal precisa permanecer documentado até reconciliação deliberada.

Objetos físicos observados após a aplicação:

- `relation_types` para semântica por campanha;
- `world_relation_styles` para apresentação de tipos, separada da semântica;
- `entity_relations` para vínculos first-class entre `entities`;
- `entity_relation_sources` para provenance por `canon_entry`;
- `world_graph_heads` e `world_graph_revisions` para optimistic concurrency + snapshots publicados;
- `world_edit_leases` estendido com `base_graph_revision`, `draft_graph` e `graph_draft_initialized`;
- trigger `world_edit_lease_graph_handoff` para impedir herança de draft factual por outro editor.

Boundary físico revalidado:

- RLS habilitado nas seis tabelas novas e nenhuma policy de browser;
- `PUBLIC`, `anon` e `authenticated` sem acesso direto às tabelas/RPCs editoriais;
- `service_role` recebe apenas os grants versionados: sem `DELETE` nas tabelas factuais, sem write em `entity_relation_sources` e sem `UPDATE` em `world_graph_revisions`;
- `acquire_world_graph_draft_atomic`, `save_world_graph_draft_atomic` e `publish_world_edit_state_atomic` são `SECURITY INVOKER`, usam `search_path = pg_catalog, public`, não são executáveis por `anon/authenticated` e são executáveis por `service_role`;
- autoria factual exige `campaign.content.edit` e um lease vigente de `campaign.world.layout.edit` para a mesma identity/profile/campaign;
- publicação factual e layout compartilham a mesma transação SQL para evitar estado parcialmente publicado;
- conflito de graph revision preserva o rascunho; novo holder não herda draft factual privado do holder anterior;
- depois que lease exclusivo + graph revision são validados, a RPC trata o draft salvo como intenção autoritativa daquela sessão: uma relação ativa anterior semanticamente substituída é preservada como histórico não ativo, sem abrir espaço para um segundo escritor nem relaxar capability/provenance.

### Review/provenance

Relação factual pública não pode ser inventada apenas no editor. O contrato continua sendo `evidence -> candidate -> human review -> canon_entry -> relation -> entity_relation_sources`.

A fatia #119 cria a tabela de provenance e **não** cria ainda o fluxo de anexar uma `canon_entry` nova a uma relação. O boundary da aplicação bloqueia `public_campaign`/`public_web` quando a relação ativa não possui source já existente. Assim, relações novas desta fatia devem permanecer `private_*` ou `review_only` até a fatia de provenance/review.

`service_role` recebe apenas `SELECT` em `entity_relation_sources` nesta fatia; não existe CRUD genérico de source. Isso é limitação deliberada, não permissão implícita para publicar sem prova.

### Ativação pública separada

A existência das tabelas canônicas não ativa automaticamente o dataset real em `/mundo`. A projection pública canônica fica atrás de `TDA_WORLD_CANONICAL_ENABLED=true`; sem essa ativação deliberada, o World público continua no dataset demonstrativo explicitamente não canônico.

A aplicação de schema preservou os dados existentes: `entities=3`, `canon_entries=0`, `world_layout_snapshots=0`, `world_edit_leases=0`; as seis tabelas factuais novas permaneceram vazias e nenhum `world_graph.publish` foi criado durante a validação. O helper de snapshot projetou `3` nodes, `0` edges e `0` relation types, e chamadas de acquire/publish com identidade inexistente falharam fechado com `forbidden`.

Ativar a projection pública canônica neste estado continua prematuro: há somente 1 entity `public_web` conhecida e nenhuma `canon_entry` para sustentar relações públicas.

### Advisors pós-aplicação

O security advisor reexecutado em 2026-09-10 reportou:

- 46 ocorrências informativas de `rls_enabled_no_policy`; as seis tabelas novas entram deliberadamente nesse grupo deny-by-default;
- as mesmas 8 funções `SECURITY DEFINER` legadas executáveis por `authenticated` já inventariadas;
- Leaked Password Protection desabilitada.

O performance advisor reportou 59 FKs sem covering index e 30 índices sem uso registrado. Parte do aumento decorre das novas FKs de autoria/audit. O item `entity_relation_sources(canon_entry_id)` foi registrado como candidato de otimização quando o fluxo de provenance passar a consultar por fonte; nenhum índice/policy foi criado automaticamente apenas para silenciar advisor. Os caminhos de exploração já possuem índices `(campaign_id, source_entity_id)` e `(campaign_id, target_entity_id)`.

Nenhum advisor introduziu blocker de segurança para manter a infraestrutura aplicada com a projection pública canônica desativada.

## Secrets e service roles

Nunca versionar:

- Supabase service/secret key;
- JWT secrets;
- OAuth client secrets;
- token R2;
- API keys externas;
- Vercel tokens.

Client/browser recebe apenas identificadores/chaves públicas apropriadas ao SDK quando a arquitetura permitir.

## API externa

`external_api_keys` guarda `key_hash` e `key_prefix`, scopes, expiração/revogação e contadores. O secret completo não deve ser armazenado em claro nem documentado.

Rotação deve criar nova credencial e revogar a anterior de forma explícita.

## Conteúdo narrativo e audience

Visibility existente inclui combinações como:

- `private_master`;
- `private_players`;
- `review_only`;
- `public_campaign`;
- `public_web`.

Outras tabelas legadas possuem vocabulário próprio (`dm_review`, `table_private`, etc.). Antes de construir knowledge/audience avançado, normalizar semântica no domínio, não apenas traduzir strings na UI.

## Segurança de candidatos/outtakes

Outtakes possuem níveis de sensibilidade/aprovação próprios. Conteúdo `private` ou `sensitive` não deve ser exposto porque a session/publication principal é pública.

## Proteção de senha vazada

O advisor revalidado em 2026-09-10 continua sinalizando **Leaked Password Protection desabilitada** no Auth. Como o fluxo vigente é orientado a OAuth, isso não bloqueia a etapa atual. Se login por senha for habilitado, tratar como requisito de hardening e revisar configuração Auth.

## Auditoria

`audit_log` existe, mas sua existência não significa que todo write atual seja auditado. Portanto:

- mapear writes críticos do Edit;
- manter action estável e payload old/new mínimo por mutation;
- não depender do log como mecanismo de autorização;
- não apagar audit para simular rollback de uma edição.

Para transcript, a action é `transcript_segment.update`; old/new registram somente o estado editorial alterável e a revision.

Para o World layout aplicado, a action é `world_layout.update`; old/new registram `schemaVersion`, `view`, `revision` e o snapshot limitado de positions. Para publicação factual do World, a action versionada é `world_graph.publish`; nenhuma dessas actions foi criada artificialmente pela simples aplicação do schema.

## Testes mínimos para autorização

Para cada nova superfície autenticada, testar pelo menos:

- usuário sem login;
- usuário autenticado sem profile resolvido;
- player sem capability;
- player com capability no campaign correto;
- capability em campaign/scope errado;
- DM/operator autorizado;
- ID de recurso de outra campaign;
- tentativa de acessar conteúdo master/private;
- RPC chamada diretamente com parâmetros manipulados.

## Regra de mudança

Qualquer alteração em policy, grant, function security, role/capability ou secret boundary exige:

- migration;
- atualização deste documento e de `rpc-inventory.md` quando houver RPC;
- teste de acesso positivo e negativo;
- registro em `verification-log.md` após aplicação;
- ADR se alterar a estratégia de segurança.