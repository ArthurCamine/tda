# Inventário de RPCs privilegiadas do Supabase

> Status: vigente / revisão de hardening em andamento
> Owner: segurança/dados
> Última verificação: 2026-09-10
> Projeto: `dmrqnbdvbkfqzctcerbx`

Este documento classifica funções privilegiadas/expostas relevantes do schema `public`. `SECURITY DEFINER` merece atenção especial porque executa com privilégios do owner; funções `SECURITY INVOKER` server-only também são registradas quando representam um boundary de write sensível.

## Estado verificado

Na inspeção de produção revalidada em 2026-09-10 foram encontradas **8 funções `SECURITY DEFINER` em `public`**.

Para as oito:

- owner: `postgres`;
- `anon`: **sem EXECUTE**;
- `authenticated`: **com EXECUTE**;
- `service_role`: com EXECUTE;
- nenhuma das oito está aberta a chamadas anônimas pela grant atual.

Todas as definições observadas usam `SET search_path TO pg_catalog, public`, reduzindo risco clássico de search-path hijacking.

## Classificação

| Função | Classe | Auth interna | Estado de grant | Decisão atual |
| --- | --- | --- | --- | --- |
| `current_profile_id()` | helper interno | resolve `auth.uid()` para `profiles.id` | authenticated pode executar diretamente | candidato a `REVOKE EXECUTE` de authenticated após prova final de consumidores |
| `has_campaign_role(uuid,text[])` | helper interno | resolve profile atual e membership ativo | authenticated pode executar diretamente | candidato a `REVOKE EXECUTE` após prova final de consumidores |
| `has_campaign_role_slug(text,text[])` | helper interno | resolve profile atual, campaign e membership ativo | authenticated pode executar diretamente | candidato a `REVOKE EXECUTE` após prova final de consumidores |
| `access_directory(text)` | endpoint autenticado de onboarding/claims | exige usuário autenticado; admin recebe visão ampliada | authenticated | manter por enquanto; revisar escopo multi-campaign antes do Edit público |
| `submit_profile_claim(...)` | endpoint autenticado de onboarding | exige requester ligado e valida target/claim | authenticated | manter enquanto fluxo de claim existir |
| `review_profile_claim(...)` | endpoint admin | usa autorização admin interna antes de aprovar/rejeitar | authenticated + autorização interna | manter enquanto fluxo legado existir |
| `table_notes_directory(text,text)` | endpoint autenticado de campanha | exige profile e membership ativo; filtra visibilidade | authenticated | manter enquanto fluxo legado existir |
| `review_table_note(...)` | endpoint admin | exige role admin interna antes do update | authenticated + autorização interna | manter enquanto fluxo legado existir |

## Helpers internos

### `current_profile_id()`

Função pequena e estável que traduz `auth.uid()` para o `profile_id` interno.

Ela é útil como building block dentro de políticas/RPCs, mas não há benefício óbvio em expô-la como endpoint REST direto para todo usuário autenticado.

**Hardening proposto:** retirar `EXECUTE` direto de `authenticated` quando a ausência de consumidores externos estiver comprovada e houver teste de regressão dos RPCs que dependem do helper.

### `has_campaign_role(...)`

Verifica membership ativo do profile atual em uma campanha por UUID e compara com roles permitidas.

É helper de autorização. Expor seu booleano diretamente não é equivalente a dar acesso ao dado protegido, mas aumenta superfície desnecessária.

**Hardening proposto:** mesma política de `current_profile_id()`.

### `has_campaign_role_slug(...)`

Versão de lookup por slug. Mesma classificação e decisão do helper anterior.

## Endpoints intencionais

### `access_directory(campaign_slug text)`

Objetivo observado: fornecer diretório para fluxo de associação/claim de perfil.

Comportamento observado:

- rejeita usuário sem Auth;
- detecta se o profile atual é admin da campanha;
- admin recebe visão de diretório mais ampla;
- não-admin recebe somente profiles ainda não ligados a Auth e campos Discord são mascarados.

### Ponto de atenção

No caminho não-admin, a função não exige explicitamente membership do caller na campanha solicitada antes de retornar profiles não vinculados daquele `campaign_slug`.

No estado atual existe somente a campanha principal conhecida, então isso não representa hoje um vazamento cross-campaign observado. Porém a regra fica perigosa quando houver múltiplas campanhas ou onboarding mais aberto.

**Decisão:** não alterar agora para não quebrar onboarding/claim legado. Antes do Edit público ou segunda campanha, decidir explicitamente uma destas regras:

1. usuário autenticado pode consultar diretório de onboarding de uma campanha conhecida; ou
2. consulta exige convite/claim token/membership prévia/capability específica.

A decisão deve virar contrato e teste negativo.

### `submit_profile_claim(...)`

Endpoint de onboarding. A definição observada:

- exige profile do requester;
- impede claim de target já vinculado;
- resolve campanha pelo slug;
- evita claim pendente duplicado;
- grava solicitação pendente em `profile_claims`.

**Decisão:** manter até o fluxo TDA substituir ou formalizar esse contrato.

### `review_profile_claim(...)`

Endpoint de revisão. A definição observada:

- carrega claim existente;
- resolve reviewer atual;
- exige autorização admin da campanha;
- valida decisão;
- quando aprovado, atualiza identidade/profile e associações necessárias;
- finaliza estado do claim.

**Decisão:** manter durante transição; o novo Edit deve migrar autorização para capabilities/RBAC sem quebrar o fluxo existente.

### `table_notes_directory(...)`

Endpoint de leitura autenticada de notas.

A definição observada exige profile e membership ativo e aplica regras diferentes para admin/player, incluindo máscara de reviewer para quem não é admin.

**Decisão:** manter durante transição e cobrir com testes de audience/visibilidade antes de reutilizar no TDA.

### `review_table_note(...)`

Endpoint de update/revisão administrativa.

A definição observada resolve a campanha da nota, exige autorização admin e valida os valores antes do update.

**Decisão:** manter durante transição; migrar para capability explícita quando a superfície Edit for implementada.

## RPC server-only do Edit — estado remoto revalidado

### `edit_transcript_segment_atomic(...)`

A inspeção read-only de 2026-09-08 confirmou a função física no Supabase canônico sob migration history remoto `20260908064257 edit_transcript_segment_atomic`.

A definição física observada corresponde ao contrato versionado quanto a assinatura, corpo da função, `SECURITY INVOKER`, `search_path`, comentário e grants efetivos:

- `anon`: sem `EXECUTE`;
- `authenticated`: sem `EXECUTE`;
- `service_role`: com `EXECUTE`;
- `search_path = pg_catalog, public`;
- comentário server-only esperado presente.

Boundary físico observado/local:

- actor/profile é resolvido pelo contexto autorizado da aplicação;
- `segment -> session -> campaign` é revalidado pelo slug;
- `expectedRevision` controla concorrência otimista;
- update e `audit_log` fazem parte da mesma chamada/transação;
- falha de audit aborta o update;
- cross-campaign retorna `not_found`;
- nenhuma das 8 funções `SECURITY DEFINER` legadas é modificada por esse slice.

## RPCs server-only do World layout — estado remoto

### `save_world_layout_snapshot_atomic(...)` e sessão exclusiva

A persistência editorial do World layout está aplicada no Supabase canônico. O migration history remoto contém `20260908203249 world_layout_capability`, `20260908203331 world_layout_snapshot_atomic`, `20260908203441 world_layout_service_role_privileges`, `20260908203642 world_layout_site_editor_grant` e `20260909205836 world_edit_lease`.

RPCs observadas deste boundary:

- `save_world_layout_snapshot_atomic(uuid,uuid,text,bigint,jsonb)`;
- `acquire_world_edit_lease_atomic(uuid,uuid,text,uuid)`;
- `renew_world_edit_lease_atomic(uuid,uuid,text,uuid)`;
- `save_world_edit_layout_draft_atomic(uuid,uuid,text,uuid,jsonb)`;
- `publish_world_edit_layout_atomic(uuid,uuid,text,uuid)`;
- `release_world_edit_lease_atomic(uuid,uuid,text,uuid)`;
- `discard_world_edit_lease_atomic(uuid,uuid,text,uuid)` (candidate `20260919170000`).

Classificação observada:

- `SECURITY INVOKER`;
- `search_path = pg_catalog, public`;
- `PUBLIC`, `anon` e `authenticated`: sem `EXECUTE`;
- `service_role`: caller SQL autorizado;
- storages do World layout/lease com RLS habilitado e sem policy de browser.

Boundary:

- valida vínculo `auth_user_id -> profile_id`;
- exige capability `campaign.world.layout.edit` e assignment ativo no scope da campaign ou `project/tda`;
- lease exclusivo protege **concorrência** da sessão editorial; durabilidade do trabalho não depende mais da row temporária do lease;
- `world_edit_drafts` mantém checkpoints server-only por campaign/editor/token, inclusive depois de release/expiração;
- acquire restaura somente checkpoint compatível do mesmo editor; recovery stale é preservado, mas não aplicado cegamente;
- release encerra o lock sem apagar checkpoint; discard explícito tombstona a cópia antes de encerrar;
- publish bem-sucedido grava receipt de revision no checkpoint na mesma transação e só então remove o lease;
- `expected_revision`/`base_layout_revision` controlam concorrência otimista;
- payload de positions é limitado a IDs/coords válidos;
- dragging público não recebe permissão para persistir por inferência.

A leitura pública continua intersectando positions apenas com IDs já autorizados; chaves do JSONB de layout nunca decidem audience.

## RPCs server-only do World graph — estado remoto #119

A migration local `20260909215000_world_graph_authoring.sql` foi aplicada deliberadamente em 2026-09-10 e registrada remotamente como `20260910002529 world_graph_authoring`. O ID local/remoto divergente fica documentado; não reexecutar DDL para alinhar nomes.

### `world_graph_snapshot_json(uuid)`

Helper server-only que monta o snapshot factual mínimo da campanha para inicialização/revisão do draft.

Estado observado:

- `SECURITY INVOKER`;
- `search_path = pg_catalog, public`;
- sem `EXECUTE` para `anon/authenticated`;
- `service_role` com `EXECUTE`;
- no pós-migration da campanha principal retornou `3` nodes, `0` edges e `0` relation types; nenhum dado factual novo foi criado pela aplicação do schema.

### `acquire_world_graph_draft_atomic(uuid,uuid,text,uuid)`

Boundary de aquisição/inicialização do draft factual dentro do lease de layout já existente.

Revalida:

- `auth_user_id -> profile_id`;
- `campaign.content.edit` no scope correto;
- campaign;
- holder/token/expiração do lease;
- base revision factual.

O draft publicado é inicializado somente dentro do lease autorizado; o trigger `world_edit_lease_graph_handoff` zera o draft factual se o holder mudar, preservando recovery apenas para o mesmo editor.

### `save_world_graph_draft_atomic(uuid,uuid,text,uuid,jsonb)`

Boundary de autosave privado do draft factual.

Revalida identity, capability/scope, lease, shape/limites de payload e `base_graph_revision`. Conflito de revision retorna erro recuperável e não promove rascunho para estado publicado.

### `publish_world_edit_state_atomic(uuid,uuid,text,uuid)`

Boundary atômico de publicação conjunta de layout + grafo factual.

Invariantes versionadas:

- exige `campaign.content.edit` + lease vigente de `campaign.world.layout.edit`;
- valida relation types, entities e relations antes do write factual;
- rejeita IDs cross-campaign, self-edge, tipo ausente e payload inválido;
- depois de validar lease exclusivo + graph revision, trata o draft salvo como intenção editorial autoritativa;
- relações anteriores semanticamente equivalentes são preservadas como histórico não ativo (`superseded`) quando uma edição explícita as substitui, em vez de abortar a publicação por ordem intermediária de escrita;
- normaliza endpoints de relation simétrica antes de persistir e converge o estado final para uma única relação ativa por identidade semântica;
- usa `world_graph_heads.revision` para optimistic concurrency;
- publica layout pela RPC de snapshot na mesma transação;
- grava snapshot append-only em `world_graph_revisions` e `world_graph.publish` no audit apenas quando o conteúdo factual muda;
- persiste receipt positivo com graph/layout revisions em `world_edit_drafts` no mesmo commit da publicação;
- remove o lease somente após receipt/publish bem-sucedidos;
- conflito/falha mantém checkpoint recuperável e retorna sem declarar publicação concluída.

Estado físico observado para as RPCs novas:

- `SECURITY INVOKER`;
- `search_path = pg_catalog, public`;
- `anon`: sem `EXECUTE`;
- `authenticated`: sem `EXECUTE`;
- `service_role`: com `EXECUTE`.

Chamadas de acquire/publish com identity/profile inexistentes foram executadas como teste negativo pós-migration e retornaram `forbidden`, sem criar lease, revision, relation ou audit.

### Provenance e ativação pública

`entity_relation_sources` foi criada com RLS e `service_role` **somente com SELECT**. A #119 não oferece mutation genérica para anexar `canon_entry`; portanto relação nova não deve sair de `private_*`/`review_only` até o fluxo de review/provenance existir.

Antes de chamar `publish_world_edit_state_atomic`, o server action da #119 verifica relações ativas `public_campaign`/`public_web` no draft e exige source já existente em `entity_relation_sources`; ausência retorna `review_required` e a RPC de publish não é chamada. Esse gate evita um atalho de publicação, mas **não conclui o fluxo de provenance**.

O app mantém a projection pública canônica atrás de `TDA_WORLD_CANONICAL_ENABLED=true`. A aplicação da infraestrutura não alterou esse gate nem publicou canon: no pós-migration havia `0` relation types, `0` relations, `0` sources, `0` graph heads/revisions e `0` `world_graph.publish` no audit.

O performance advisor sinalizou `entity_relation_sources(canon_entry_id)` sem covering index, além de FKs de actor/audit do novo domínio. Nenhum índice foi adicionado automaticamente apenas para silenciar INFO; o índice de provenance fica candidato quando esse lookup se tornar caminho real do fluxo de review.

## Auditoria de consumidores

### TDA reboot

A integração Supabase do site público permanece server-only e focada em dados autorizados. O World layout integrado pela #117 possui consumidor server-side protegido por capability. A #119 acrescenta consumidores server-side para as três RPCs factuais, também protegidos por capabilities e lease.

O World público permanece demonstrativo por padrão. A projection canônica pública só entra com configuração deliberada posterior, depois de curadoria/provenance/visibility e validação visual.

### `Faysk/dnd-scribe`

O backend principal legado observado em `api/[...path].js` usa conexão PostgreSQL server-side para resolver profile, membership, RBAC e permissions. O web app atual consulta `/api/auth/me`, e esse endpoint delega para o backend legado.

Não foram observadas referências diretas aos três helpers (`current_profile_id`, `has_campaign_role`, `has_campaign_role_slug`) no backend principal inspecionado.

Ainda assim, ausência em código versionado não prova ausência absoluta de consumidor manual, release antigo, script ou cliente externo.

## Observabilidade de chamadas

Na verificação de 2026-09-07, o PostgreSQL retornou `track_functions = none`.

Consequência: `pg_stat_user_functions` não oferece contagem histórica útil dessas RPCs no estado atual. Portanto não é possível usar a estatística nativa de funções como prova de que um helper não possui consumidor em runtime.

**Decisão:** não mudar `track_functions` em produção apenas para essa auditoria e não interpretar ausência de estatística como ausência de uso. A prova para revogar grant deve combinar inventário de código/consumidores, testes da superfície autenticada e janela de transição controlada quando a mudança for planejada.

## Plano de hardening

### Fase 1 — concluída

- inventariar todas as `SECURITY DEFINER`;
- conferir grants por role;
- conferir `search_path`;
- revisar corpo/autorização;
- mapear consumidores principais versionados;
- registrar riscos sem mudar produção às cegas.

### Writes server-only novos

- manter `SECURITY INVOKER` quando elevação não é necessária;
- negar execução direta a `anon/authenticated`;
- revalidar identity/capability/scope dentro do boundary sensível quando aplicável;
- manter audit e mutation atômicos;
- validar em PostgreSQL sintético antes de qualquer aplicação remota;
- revalidar grants/advisors após aplicação real.

### Fase 2 — antes do Edit público

- criar testes positivos/negativos para endpoints autenticados;
- decidir contrato de `access_directory` para cenário multi-campaign;
- provar ausência de consumidores diretos dos helpers;
- criar migration de grant para retirar exposição direta dos helpers quando seguro;
- executar advisors e testes após a migration.

### Fase 3 — convergência TDA

- substituir checks de role legada por capabilities do RBAC onde apropriado;
- reduzir número de `SECURITY DEFINER` públicos ao mínimo necessário;
- preferir fronteira server-side ou funções invoker quando a elevação não for necessária;
- remover endpoints legados somente depois da independência ser comprovada.

## Regra

Não transformar warning do advisor em alteração automática. O objetivo é **reduzir superfície sem quebrar autorização existente**, não deixar o painel verdinho enquanto a aplicação pega fogo.

## Candidato: `import_transcript_bundle_atomic`

`public.import_transcript_bundle_atomic(uuid,uuid,jsonb,boolean)` é candidato service-only `SECURITY INVOKER`, search_path `pg_catalog, public`, sem `EXECUTE` para `PUBLIC`/`anon`/`authenticated`. Revalida operador/profile, action explícita, scope e origem da sessão; grava segmentos/recibo/audit juntos ou consulta recibo. Não aplicado e não selecionado pelo endpoint produtivo. Contrato e rollback em [importação local](../integrations/transcript-import.md).
