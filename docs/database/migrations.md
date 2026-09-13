# Migrations e evolução do schema

> Status: vigente
> Owner: dados/Supabase
> Última revisão: 2026-09-10
> Fonte: migration history do Supabase `dmrqnbdvbkfqzctcerbx`

## Princípio

O Supabase existente é produção e possui história anterior ao reboot. O repositório TDA **não deve fingir que criou migrations históricas que nasceram no `dnd-scribe`**.

A estratégia é:

- história remota anterior permanece no Supabase e legado;
- novas mudanças do reboot entram em `Faysk/tda/supabase/migrations`;
- versão/nome remoto e arquivo local devem corresponder após aplicação ou a divergência precisa ficar explicitamente documentada;
- migration candidata pode existir no repo antes da aplicação, mas precisa estar explicitamente marcada como não aplicada;
- migrations de transição preservam consumidores legados enquanto necessários;
- o procedimento operacional obrigatório está em `docs/operations/database-runbook.md`.

## Histórico remoto observado

### 2026-06-26 — canon, IA e áudio

- `20260626211159 canon_entries`
- `20260626211239 ai_cost_cache`
- `20260626214638 audio_speech_slices`
- `20260626215040 audio_work_units_absolute_times`
- `20260626215758 audio_chunks_updated_at`

### 2026-06-27 — processamento e acesso

- `20260627002400 exclude_silent_audio_work_units`
- `20260627125614 access_claims_model`
- `20260627131222 access_role_slug_rpc`
- `20260627133027 discord_notes_interactions`
- `20260627134245 table_notes_review_rpc`
- `20260627140124 harden_access_and_discord_rpc_grants`
- `20260627140209 revoke_direct_access_tables_for_rpc_only`
- `20260627140631 fix_table_notes_directory_source_session_parameter`
- `20260627143105 tighten_access_directory_visibility`

### 2026-06-28 — artifacts, jobs e Craig

- `20260628023337 audio_artifacts_retention`
- `20260628023549 audio_artifact_reclassify`
- `20260628110227 processing_job_steps`
- `20260628110807 craig_manifest_contract`
- `20260628111006 craig_manifest_temporal_quality`
- `20260628112021 craig_track_extraction_steps`
- `20260628112729 audio_cleanup_readiness`
- `20260628113102 audio_cleanup_success_policy`

### 2026-07-26 — API pública e permissões de site

- `20260726211900 secure_public_data_api`
- `20260726222922 site_feature_permissions`
- `20260726224036 seed_site_feature_access`

### 2026-08-01 — companion

- `20260801143158 companion_distribution_permissions`
- `20260801150510 remove_local_publisher_permission`

### 2026-08-13 — Ordo

- `20260813160644 ordo_access_control`
- `20260813160736 optimize_ordo_access_rls`

### 2026-08-16 — summary API

- `20260816200927 summary_api_v1`

### 2026-09-06 — transcript permission e início das migrations do reboot

- `20260906000203 transcript_view_permission`
- `20260906210333 align_tda_domain_identity`
- `20260906210427 backfill_narrative_entity_links`
- `20260906211040 relax_reboot_entity_name_lookup`

### 2026-09-07/08 — concorrência otimista do Edit e review de transcrição

- `20260907084234 add_transcript_segment_revision`
- `20260908064257 edit_transcript_segment_atomic`
- `20260908144711 transcript_review_default`

### 2026-09-08 — persistência editorial do World Explorer

- `20260908203249 world_layout_capability`
- `20260908203331 world_layout_snapshot_atomic`
- `20260908203441 world_layout_service_role_privileges`
- `20260908203642 world_layout_site_editor_grant`

### 2026-09-09 — lease exclusivo do World Explorer

- `20260909205836 world_edit_lease` — migration aplicada remotamente; arquivo local equivalente preservado como `20260909173000_world_edit_lease.sql` até reconciliação nominal deliberada.

### 2026-09-10 — autoria factual do World Explorer

- `20260910002529 world_graph_authoring` — migration aplicada remotamente; arquivo local equivalente permanece `20260909215000_world_graph_authoring.sql`. Não reexecutar DDL para alinhar somente o número.
- `20260910012546 world_graph_provenance_guard` — hardening aplicado remotamente; arquivo local equivalente `20260910005000_world_graph_provenance_guard.sql`. Não reexecutar DDL para alinhar somente o timestamp.

## Boundary do reboot aplicado

As migrations abaixo são mudanças explicitamente assumidas, versionadas e observadas no histórico remoto do novo repositório TDA.

### `20260906210333_align_tda_domain_identity`

Objetivos:

- introduzir `project/tda` como scope técnico canônico;
- preservar `project/dnd-scribe` como compatibilidade;
- ligar `profile_characters` a `entities`;
- criar entities PC a partir dos três PCs conhecidos sem inventar canon.

### `20260906210427_backfill_narrative_entity_links`

Objetivos:

- ligar participações históricas de Astel, Dandelion e Screacky às entities canônicas;
- preservar `profile_id` nulo quando o dado humano histórico não existe;
- adicionar índices para os caminhos narrativos novos.

Resultado validado: 12/12 participações desses PCs ligadas à entity correta.

### `20260906211040_relax_reboot_entity_name_lookup`

Objetivo:

- remover uma restrição adicional case-insensitive introduzida no reboot;
- preservar a constraint histórica `(campaign_id, name)` porque o consolidator legado usa `ON CONFLICT (campaign_id, name)`;
- manter índice de busca por lower(name) sem tornar a situação mais restritiva.

### `20260907084234_add_transcript_segment_revision`

Objetivo:

- adicionar `transcript_segments.revision bigint not null default 0`;
- criar o contador monotônico necessário para optimistic concurrency do Edit sem alterar o comportamento dos consumidores atuais;
- preparar, sem ainda introduzir RPC/grants, o boundary transacional de update + audit da issue #32.

Validação pós-migration registrada: 30.857 segmentos preservados, zero `revision` nula e intervalo inicial `0..0`.

## Migration history reconciliado em 2026-09-08

A reconciliação de `transcript_review_default` alinhou o arquivo local ao ID remoto `20260908144711`. A persistência do World Explorer foi reconciliada com os quatro IDs efetivamente registrados no remoto. Nesta rodada, `edit_transcript_segment_atomic` também foi alinhada ao ID remoto `20260908064257` após comparação read-only do `statements` preservado em `supabase_migrations.schema_migrations` com o SQL local. Nenhum DDL foi reexecutado e nenhuma linha do migration history foi editada.

## Mutation atômica do Edit aplicada e reconciliada

### `20260908064257_edit_transcript_segment_atomic`

**Estado:** aplicada no Supabase canônico e reconciliada com o migration history remoto. O SQL versionado permanece equivalente ao changeset originalmente mantido localmente como `20260907115300_edit_transcript_segment_atomic.sql`; a mudança deste recorte alinha somente o filename/ID local, sem reexecutar DDL.

Objetivo:

- criar `public.edit_transcript_segment_atomic(...)` como boundary server-only `SECURITY INVOKER`;
- revalidar `segment -> session -> campaign` pelo slug antes de qualquer write;
- fazer optimistic concurrency por `expectedRevision` com lock da linha e incremento exato `+1`;
- persistir estado editorial e um único evento `audit_log` na mesma transação;
- preservar `character_name` quando o speaker não muda e invalidá-lo apenas quando o speaker muda;
- retornar `updated`, `conflict` ou `not_found` sem revelar recurso cross-campaign;
- manter `EXECUTE` somente para `service_role`, sem abrir `anon`/`authenticated`.

Compatibilidade:

- nenhuma coluna existente é removida/renomeada;
- nenhuma das 8 funções `SECURITY DEFINER` existentes é alterada neste slice;
- o adapter temporário do Edit permanece independente até o binding canônico;
- a função nova não substitui Auth/RBAC: actor/capability continuam resolvidos no boundary autorizado da aplicação.

Validação isolada concluída em 2026-09-07:

- SHA validado: `f44a74c653d416a614bb3468ffc112d741bc4893`;
- PostgreSQL 16.14 real em cluster descartável novo, sem TCP nem conexão remota;
- migration de `revision` + migration candidata originais aplicadas sobre schema mínimo sintético;
- `supabase/tests/edit_transcript_segment_atomic.sql` integral passou e terminou em `ROLLBACK`;
- concorrência real com duas conexões `service_role` passou 3/3 sob `READ COMMITTED`: uma conexão ficou bloqueada no lock da outra, depois houve exatamente `updated/1` + `conflict/NULL`, revision final `1` e um único audit `0 -> 1`;
- `anon`, `authenticated` e role sem acesso tiveram chamada direta negada;
- cross-campaign retornou `not_found` sem audit;
- identidade foi preservada quando speaker não mudou e `character_name` foi limpo quando mudou;
- falha de audit por trigger e por FK de ator inválido reverteu a linha inteira;
- nenhum bug SQL foi reproduzido; a branch/migration não foi alterada durante o ensaio.

Limites da validação isolada:

- schema de teste mínimo, não dump completo do Supabase;
- sem Auth/PostgREST real;
- sem advisors do projeto canônico;
- somente `READ COMMITTED`.

Ainda pendente:

- registrar smoke real do caminho canônico do Edit em release deliberada;
- remover `unsafe-mutation.ts` e `TDA_EDIT_UNSAFE` somente após esse smoke, em recorte separado.

Rollback lógico:

- se ainda sem consumidor, remover/revogar a função em migration corretiva é reversível;
- se já houver consumidor, primeiro desligar o adapter canônico e restaurar o caminho anterior;
- não remover `transcript_segments.revision` e não apagar eventos de audit para simular rollback de edição.

### `20260908144711_transcript_review_default`

**Estado:** aplicada no Supabase canônico em 2026-09-08. O SQL é idêntico ao da candidata originalmente versionada como `20260908134500_transcript_review_default.sql`; esta reconciliação alinha somente o ID local ao migration history remoto, sem reexecutar DDL.

Objetivo:

- alinhar o default físico de `public.transcript_segments.needs_review` para `true`;
- manter coerência com o default existente `review_status = 'pending'` e com o invariante atual do Edit/import;
- impedir que novos writers que omitam `needs_review` fabriquem novos registros `pending/false`.

Compatibilidade e limites:

- não altera linhas históricas;
- não executa backfill;
- não adiciona CHECK constraint enquanto a massa histórica inconsistente não for reconciliada;
- writers que persistem `needs_review` explicitamente continuam com o mesmo comportamento.

Validação:

- o PostgreSQL sintético do job `transcript-import-postgres` aplica a migration e executa `supabase/tests/transcript_review_default.sql`;
- o assert falha se `information_schema.columns.column_default` para `needs_review` não for `true`;
- no Supabase canônico, o default foi confirmado como `true` e as contagens históricas permaneceram `pending/false=30.839`, `pending/true=17`, `needs_review/true=1` após a aplicação.

Rollback lógico:

- antes de qualquer dependência nova do default, uma migration corretiva pode restaurar o default anterior;
- não apagar nem reclassificar linhas históricas como forma de rollback.

## Persistência editorial aplicada do World Explorer

A aplicação remota ocorreu em quatro recortes e foi reconciliada com os arquivos locais sem reexecutar DDL. O migration history remoto preserva o SQL integral de cada entrada, o que permitiu comparar os statements efetivamente executados com os candidatos versionados.

### `20260908203249_world_layout_capability`

**Estado:** aplicada no Supabase canônico. O statement remoto é equivalente ao candidato originalmente versionado como `20260908192500_world_layout_capability.sql`.

Objetivo:

- definir `campaign.world.layout.edit` no `permission_catalog` com plane `narrative`;
- não criar assignment de usuário/perfil;
- preparar uma autorização separada de `campaign.content.edit` para a mutation física de layout.

### `20260908203331_world_layout_snapshot_atomic`

**Estado:** aplicada no Supabase canônico. O statement remoto é equivalente ao candidato originalmente versionado como `20260908192600_world_layout_snapshot_atomic.sql`.

Objetivo:

- criar `world_layout_snapshots`, separado de entities/relations/canon;
- manter um snapshot `overview` por campaign com `schema_version`, `revision`, `positions`, actor e timestamps;
- habilitar RLS sem policy de browser;
- criar `save_world_layout_snapshot_atomic(...)` como `SECURITY INVOKER` server-only;
- revalidar identidade, capability, assignment ativo e scope;
- validar payload/limites defensivos;
- aplicar optimistic concurrency por `expected_revision`;
- registrar `world_layout.update` no `audit_log` na mesma transação;
- retornar `unchanged` sem bump de revision/audit quando o snapshot não muda.

### `20260908203441_world_layout_service_role_privileges`

**Estado:** aplicada no Supabase canônico e agora versionada no repo.

Objetivo:

- neutralizar default privileges mais amplos observados no ambiente Supabase;
- revogar todos os privilégios de tabela de `service_role` e reabrir somente `SELECT`, `INSERT` e `UPDATE`;
- manter `DELETE` indisponível para o boundary de snapshot.

### `20260908203642_world_layout_site_editor_grant`

**Estado:** aplicada no Supabase canônico e agora versionada no repo.

Objetivo:

- conceder `campaign.world.layout.edit` ao role narrativo existente `site_editor`;
- preservar assignments existentes;
- não criar grant direto para usuário/profile e não ampliar `campaign.content.edit`.

Validação reconciliada:

- `world_layout_snapshots` existe e permaneceu com `0` snapshots durante a auditoria;
- RLS está habilitado e não há policy de browser;
- `service_role` possui `SELECT/INSERT/UPDATE`, sem `DELETE`;
- `save_world_layout_snapshot_atomic(...)` permanece `SECURITY INVOKER`, com `EXECUTE` apenas para `postgres` e `service_role` entre os roles relevantes;
- a capability existe em `permission_catalog` e está ligada ao `site_editor`;
- `tools/world-layout-db.py` aplica os quatro arquivos reconciliados em PostgreSQL 16 sintético e testa grant, ausência de assignment automático, autorização/scope, payload, revision/conflict/no-op e rollback em falha do audit.

Contrato arquitetural: [ADR-0011](../adr/0011-world-explorer-layout-physical-persistence.md).

## Regras para migration nova

### Deve

- possuir objetivo único ou coeso;
- existir como arquivo versionado antes da aplicação deliberada em produção;
- ser idempotente quando razoável, especialmente backfills/índices condicionais;
- preservar produção;
- ter nome descritivo em snake_case;
- evitar dependência de UUID gerado em outro ambiente;
- explicar compatibilidade e rollback lógico;
- ser adicionada a este documento quando passa a fazer parte do reboot;
- atualizar documentação de contrato quando altera schema, autorização ou comportamento.

### Não deve

- resetar produção;
- apagar dados narrativos para "limpar" ambiente;
- promover candidato para canon sem revisão;
- renomear provenance só por branding;
- derrubar scope/grant/tabela legado sem consumidor mapeado;
- embutir secret;
- fazer grande refactor de schema + grande backfill + mudança de auth numa migration opaca.

## Processo recomendado

```text
1. documentar contrato/feature e invariantes
2. inspecionar schema real + consumidores
3. criar migration pequena e versionada
4. revisar impacto de RLS/grants/indexes e recuperação
5. validar o repositório/CI
6. aplicar de forma controlada no projeto correto
7. validar invariantes com SQL read-only
8. confirmar migration history remoto
9. rodar advisors quando aplicável
10. atualizar catálogo/auditoria/docs
11. registrar a verificação em verification-log.md
```

## Guardrail automático

`pnpm check` executa `pnpm db:docs:check`, implementado em `tools/check-database-governance.mjs`.

O check garante pelo menos que:

- os documentos obrigatórios de governança do banco existem;
- o índice do banco aponta para runbook, inventário de RPCs e log de verificações;
- os documentos centrais identificam o project ref canônico;
- `AGENTS.md` exige consulta ao runbook antes de mudanças de banco;
- **todo arquivo `.sql` em `supabase/migrations` aparece neste documento**.

Assim, uma migration nova do reboot sem registro documental quebra o CI em vez de virar dívida silenciosa.

O check é guardrail de documentação; ele **não substitui** inspeção do migration history remoto, advisors ou validação do schema real.

## Validação pós-migration

Dependendo da mudança:

- contagem antes/depois;
- valores nulos inesperados;
- FK/constraint/index existentes;
- duplicatas;
- RLS/policies/grants;
- advisors de segurança/performance;
- consumidores legados ainda funcionam;
- nenhum dado canônico foi criado sem aprovação;
- migration history remoto corresponde ao arquivo ou a divergência nominal está documentada sem reexecutar DDL.

## Rollback

Preferir migrations reversíveis conceitualmente, mas produção com dados reais nem sempre pode simplesmente executar `DOWN`.

Classificar rollback:

- **DDL reversível**: remover índice/coluna nova ainda não usada;
- **compatibilidade**: manter coluna/alias antigo enquanto novo caminho estabiliza;
- **data backfill**: registrar como identificar linhas alteradas antes de desfazer;
- **irreversível por perda de dado**: evitar; exige estratégia real de backup/restore e aceite explícito antes da aplicação.

## Drift

Há drift quando:

- Supabase possui DDL que o repo não conhece;
- repo possui migration que produção não aplicou;
- versão/nome não corresponde e a divergência não está registrada;
- documentação descreve constraint/coluna inexistente.

Uma migration explicitamente marcada como **candidata/não aplicada** não é drift por si só. Uma mudança aplicada com ID remoto diferente do filename local deve ser registrada como equivalência operacional e não ser reexecutada apenas para satisfazer nomenclatura.

Antes de qualquer grande etapa de banco, verificar migration history + schema real. O `database-audit.md` serve como fotografia datada, não como substituto dessa verificação.

## Candidatos de importação de transcrição

- `20260907193704_transcript_import_capability`: define campaign.transcript.import (mixed), sem grants de roles/operadores.
- `20260907193705_transcript_import_atomic`: recibo durável e consumer transacional service-only; revisado pelo owner SQL e validado em PostgreSQL scratch com concorrência real, **não aplicado em produção**.

Contrato, testes sintéticos e rollback: [importação local](../integrations/transcript-import.md).

## Sessão exclusiva de edição do World Explorer

### `20260909173000_world_edit_lease`

**Estado:** aplicada no Supabase canônico em 2026-09-09 sob o migration history remoto `20260909205836 world_edit_lease`. O arquivo local mantém o ID candidato original até uma reconciliação nominal deliberada; não reexecutar DDL para alinhar nomes.

Objetivo:

- permitir que o mesmo `/mundo` alterne entre exploração e edição editorial de layout sem criar um segundo editor concorrente;
- garantir no banco apenas uma sessão ativa de edição de layout por campanha;
- manter posições em rascunho server-side e invisíveis à projection pública até publicação explícita;
- renovar a sessão por lease com expiração, evitando lock permanente quando aba, navegador ou conexão desaparecem;
- publicar chamando o boundary já aplicado `save_world_layout_snapshot_atomic(...)`, preservando optimistic concurrency e `audit_log` existentes;
- permitir descarte do rascunho sem tocar no snapshot publicado.

Segurança e compatibilidade:

- reutiliza exclusivamente `campaign.world.layout.edit`; não amplia `campaign.content.edit` e não autoriza CRUD factual de entities/relations;
- tabela `world_edit_leases` fica com RLS habilitado, sem grants para `anon`/`authenticated`;
- RPCs são `SECURITY INVOKER` e executáveis por `service_role`, com revalidação interna de identidade, capability, assignment ativo e scope;
- token de lease identifica a sessão/aba editorial, não usuário nem segredo de autorização;
- draft contém somente coordenadas de nodes já autorizados pelo contrato do layout; canon, relations, visibility e conhecimento não entram no payload;
- nenhuma alteração de relations, entities, canon ou publication é feita por esta migration.

Concorrência e recuperação:

- lease ativo de outra sessão retorna `busy` em vez de roubar o lock;
- lease expirado pode ser recuperado pelo mesmo editor com o draft preservado;
- novo editor após expiração inicia do snapshot publicado vigente;
- conflito de `revision` preserva o draft e bloqueia publicação silenciosa sobre versão mais nova.

Validação observada antes/após a aplicação:

- `pnpm check`, build e Playwright passaram no SHA de integração da #117;
- PostgreSQL 16 descartável validou os RPCs, incluindo duas sessões concorrentes, expiração/recovery, payload inválido, capability/scope e rollback de publish;
- a migration foi aplicada de forma deliberada ao Supabase canônico e o deployment correspondente ficou READY;
- smoke público confirmou `/`, `/sessoes`, `/mundo` e `/conta`; fluxo autenticado completo de edição continua sendo um gate separado quando houver fixture/credencial apropriada.

Rollback lógico:

- antes de consumidores dependerem do lease, remover os RPCs e `world_edit_leases` em migration corretiva é reversível;
- após ativação, primeiro desligar o toggle/boundary no app, deixar leases expirarem e então remover a infraestrutura em migration corretiva;
- nunca apagar `world_layout_snapshots` ou `audit_log` para desfazer esta feature.

## Autoria canônica do World Explorer — infraestrutura aplicada

### `20260909215000_world_graph_authoring`

**Estado:** aplicada no Supabase canônico em 2026-09-10 sob o migration history remoto `20260910002529 world_graph_authoring`. O arquivo local preserva o ID original da PR #119; não reexecutar DDL apenas para alinhar o timestamp.

Objetivo:

- introduzir `relation_types`, `world_relation_styles`, `entity_relations`, `entity_relation_sources`, `world_graph_heads` e `world_graph_revisions` sem acoplar o schema ao React Flow;
- estender o lease exclusivo existente com revision e rascunho factual privado;
- permitir criação/edição/arquivamento manual de entities, relações e tipos por um editor autorizado;
- persistir estilo editorial de relação em tabela separada da semântica (`world_relation_styles`), mantendo cor/traço/espessura como apresentação;
- publicar conteúdo factual e layout na mesma transação SQL, com revisions separadas e `audit_log` de publicação do grafo;
- manter IA/candidatos fora do caminho de promoção automática.

Segurança e autorização:

- autoria factual exige `campaign.content.edit` e uma sessão exclusiva válida de `campaign.world.layout.edit`;
- o browser não recebe grants diretos das tabelas ou RPCs editoriais;
- RLS está habilitado nas seis novas tabelas sem policy pública;
- `service_role` recebe somente os privilégios versionados; não possui `DELETE` nas tabelas factuais, recebe apenas `SELECT` em `entity_relation_sources` e não recebe `UPDATE` em `world_graph_revisions`;
- RPCs de acquire/save/publish são `SECURITY INVOKER`, usam `search_path = pg_catalog, public`, não são executáveis por `anon/authenticated` e revalidam identidade/profile/campaign/scope/lease/revision;
- a projection pública continua filtrada no servidor e não usa o rascunho privado como fonte de autorização.

Concorrência e integridade:

- `world_graph_heads.revision` protege publicação factual por optimistic concurrency;
- o rascunho preserva `base_graph_revision` e sobrevive à recuperação do mesmo editor, mas é zerado na transferência do lease para outro editor;
- relações simétricas são normalizadas antes de persistir e duplicatas ativas são rejeitadas;
- IDs cross-campaign, endpoints ausentes, tipos inexistentes, self-edge e colisões de nome/slug são rejeitados;
- exclusão editorial normal é arquivamento; publicação cria snapshot append-only em `world_graph_revisions` quando o conteúdo factual muda.

Validação observada:

- o SHA candidato anterior à rodada documental passou `pnpm check`, build, Playwright/E2E, processamento e PostgreSQL sintético com `tools/world-layout-db.py`;
- preflight remoto confirmou 0 leases ativos, 0 snapshots, 3 entities, 0 canon entries e ausência das seis tabelas antes do DDL;
- pós-migration: `entities=3`, `canon_entries=0`, `world_layout_snapshots=0`, `world_edit_leases=0` e todas as seis tabelas factuais novas permaneceram vazias;
- RLS/grants/RPC signatures/security/search_path foram revalidados fisicamente;
- `world_graph_snapshot_json` projetou 3 nodes, 0 edges e 0 relation types;
- chamadas negativas de acquire/publish com identity inexistente retornaram `forbidden` sem criar lease/revision/relation/audit;
- nenhum `world_graph.publish` foi produzido pela aplicação da infraestrutura.

Advisors pós-aplicação:

- security: 46 `rls_enabled_no_policy` informativos, incluindo deliberadamente as seis tabelas novas deny-by-default; mesmas 8 funções `SECURITY DEFINER` legadas executáveis por `authenticated`; Leaked Password Protection desabilitada;
- performance: 59 FKs sem covering index e 30 índices sem uso registrado.

O INFO de `entity_relation_sources(canon_entry_id)` vira candidato de índice quando o fluxo de provenance realmente consultar por fonte. Nenhum índice/policy foi adicionado apenas para silenciar advisor.

Limites de produto após a aplicação:

- a #119 **não** cria mutation de anexação de `canon_entry` a uma relation; `service_role` possui somente leitura de `entity_relation_sources`;
- relações novas devem permanecer `private_*`/`review_only` até a fatia de provenance/review;
- o server action impede publicação de relation ativa `public_campaign/public_web` sem source já existente;
- `TDA_WORLD_CANONICAL_ENABLED` continua desligado por padrão; com apenas 1 entity `public_web` e 0 canon entries, ativação pública agora seria prematura.

Rollback lógico:

- se o consumidor precisar ser retirado, desligá-lo primeiro e deixar o schema aditivo inerte enquanto a correção é preparada;
- uma eventual migration corretiva deve preservar facts/revisions/audit já existentes e remover objetos somente quando comprovadamente sem consumidor;
- não apagar relações, snapshots ou audit para simular rollback.

## Hardening do provenance no publish do World graph

### `20260910005000_world_graph_provenance_guard`

**Estado:** aplicada no Supabase canônico em 2026-09-10 sob o migration history remoto `20260910012546 world_graph_provenance_guard`.

Objetivo:

- fechar o bypass em que um caller interno com `service_role` podia chamar `publish_world_edit_state_atomic(...)` diretamente e contornar o precheck de provenance feito pelo server action;
- exigir, dentro da própria RPC e antes de qualquer write de graph/layout/audit, que toda relation `active` com visibility `public_campaign` ou `public_web` possua `entity_relation_sources` apontando para `canon_entries` da mesma campaign com `status='active'`;
- retornar `review_required` sem consumir o lease nem publicar qualquer estado quando o gate não estiver satisfeito;
- preservar o boundary como `SECURITY INVOKER`, `search_path = pg_catalog, public`, sem `EXECUTE` para `anon/authenticated` e com `service_role` como caller SQL esperado.

Estratégia forward-only:

- a migration histórica `20260909215000_world_graph_authoring.sql` já havia sido aplicada remotamente e não foi reescrita;
- a correção usa `pg_get_functiondef(...)` para localizar a definição física conhecida e injeta o guard imediatamente antes do primeiro write da RPC;
- a migration falha fechada se o marcador esperado da função não existir, evitando aplicar uma transformação silenciosa sobre uma definição divergente;
- a execução é idempotente para ambientes scratch em que o mesmo guard já esteja materializado.

Validação observada:

- PostgreSQL 16 descartável executou a migration corretiva e `supabase/tests/world_graph_authoring_atomic.sql` passou no job `transcript-import-postgres` da CI #551;
- o teste chama a RPC diretamente com relation `active/public_web` sem source e exige `review_required`, com zero mutation em entities, relations, relation types, layout snapshots, graph revisions/head revision e audit;
- o happy path factual permanece permitido com relation `review_only`;
- pós-aplicação remota, `pg_get_functiondef` confirmou o guard na função física; `prosecdef=false`; `search_path=pg_catalog, public`; `anon/authenticated` sem `EXECUTE`; `service_role` com `EXECUTE`;
- antes do hardening havia 0 leases ativos, 0 relations, 0 graph revisions e 0 `world_graph.publish`; a aplicação não criou fatos canônicos.

Rollback lógico:

- se houver necessidade real de desfazer o hardening, criar migration corretiva explícita que substitua a função por uma definição revisada; não editar migration history nem remover provenance para forçar publicação;
- enquanto não houver fluxo de source/review, relações novas permanecem privadas/review e `TDA_WORLD_CANONICAL_ENABLED` continua desligado.

## Candidato de estabilização de aliases narrativos

### `20260908231000_backfill_screacky_historical_alias`

**Estado:** migration candidata versionada; **não aplicada no Supabase canônico**.

Objetivo:

- preservar `Screacky` como `name`/slug vigente da entity PC existente;
- adicionar `Screaky` somente como alias histórico para resolução/busca;
- não alterar `entity_type`, visibility, canon, relações ou qualquer conteúdo narrativo.

Matching e segurança:

- restringe o alvo à campanha `yuhara-main`, `slug='screacky'` e `entity_type='pc'`;
- falha se o alvo não resolver para exatamente uma entity;
- só faz `array_append` quando o alias ainda não existe, tornando o backfill idempotente;
- não contém UUID de produção nem texto de transcrição.

Validação pré-aplicação:

- inspeção read-only confirmou exatamente um alvo, `name=Screacky`, `visibility=private_players` e aliases vazio;
- a expressão candidata projeta somente a adição de um alias, sem mudança de audience;
- nenhuma escrita foi executada no Supabase durante a estabilização #102.

Rollback lógico:

- antes de existir consumidor dependente do alias, uma migration corretiva pode remover apenas o valor `Screaky` do array dessa entity;
- não renomear `name`/slug nem apagar a entity para simular rollback.

## Candidato de mídia de entidades do World Explorer

### `20260912214500_world_entity_media_foundation_v2`

**Estado:** SQL candidato versionado em `supabase/candidates/`; **não aplicado no Supabase canônico** e sem autorização de aplicação remota.

Objetivo:

- criar identidade first-class de mídia sem armazenar URL arbitrária em `entities`;
- manter bytes em Cloudflare R2 e identidade/metadados/verificação em PostgreSQL;
- introduzir `media_assets` e `entity_media_bindings`, com `portrait` como primeiro role;
- persistir focal point normalizado junto ao binding;
- usar object keys imutáveis por campaign/entity/hash em vez de tratar URL de entrega como identidade;
- compor a publicação de graph/layout e bindings de mídia no mesmo boundary transacional do banco.

Segurança e autorização candidatas:

- RLS habilitado em `media_assets` e `entity_media_bindings`, sem policy de browser;
- `anon`/`authenticated` não recebem grants diretos; `service_role` recebe somente o conjunto necessário;
- o wrapper `publish_world_edit_state_with_media_atomic(...)` permanece `SECURITY INVOKER`, revalida identidade, `campaign.content.edit`, scope e a lease exclusiva vigente;
- media intent é validada contra o `draft_graph` bloqueado pela mesma lease, inclusive a visibility que será publicada;
- entity que sai do draft como `public_web` só pode receber asset já `verified_public`, com read-back e delivery público verificados;
- campaign/entity/object key/sha/MIME precisam corresponder antes do binding;
- o wrapper chama `publish_world_edit_state_atomic(...)` dentro da mesma transação e só aplica `entity_media_bindings` após sucesso factual/layout; erro SQL posterior reverte o conjunto inteiro.

Compatibilidade e lifecycle:

- `TDA_WORLD_ENTITY_MEDIA_ENABLED` permanece desligado por padrão enquanto o schema candidato não existe;
- upload para `tda-media-preview`/`tda-media-private` não equivale a publicação;
- promoção pública externa ao banco deve terminar e ser verificada antes de consumir a lease de publicação; falha de promoção preserva draft/lease para retry;
- URLs públicas são projeções derivadas de asset verificado, não dados canônicos persistidos no draft;
- a arquitetura de upload direto por presigned PUT continua como próximo recorte; o boundary de finalização/read-back já é desenhado para revalidar os bytes no servidor.

Validação antes de qualquer promoção:

- o candidato deve permanecer fora de `supabase/migrations` até revisão explícita contra o schema vigente;
- CI deve manter migration safety, documentação de governança e testes de contrato verdes;
- qualquer ensaio SQL do candidato deve ocorrer somente em PostgreSQL scratch preparado deliberadamente para ele, sem tocar Production.

Rollback lógico:

- enquanto candidato, pode ser revisado ou descartado sem efeito remoto;
- se futuramente autorizado/aplicado, desligar primeiro `TDA_WORLD_ENTITY_MEDIA_ENABLED` e retirar consumidores antes de migration corretiva;
- não apagar assets, bindings ou `audit_log` para simular rollback; preservar evidência e identidade já usadas.

Contrato detalhado: [World entity media foundation](../features/world-entity-media-foundation.md).
