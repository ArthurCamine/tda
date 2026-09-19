# Migrations e evolução do schema

> Status: vigente
> Owner: dados/Supabase
> Última revisão: 2026-09-19
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
- `20260910012546 world_graph_provenance_guard` — hardening aplicado remotamente; arquivo local equivalente `20260910005000_world_graph_provenance_guard.sql`. Não reexecutar DDL apenas para alinhar o timestamp.

### 2026-09-15 — contrato editorial da transcrição

- `20260915211245 transcript_review_contract_comments` — migration COMMENT-only aplicada remotamente; arquivo local equivalente `20260915211000_transcript_review_contract_comments.sql`. Não reexecutar DDL nem editar migration history apenas para alinhar o timestamp.

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

### `20260915211000_transcript_review_contract_comments`

**Estado:** aplicada no Supabase canônico em 2026-09-15 sob o migration history remoto `20260915211245 transcript_review_contract_comments`. O arquivo local preserva o ID versionado pela PR #368; a divergência de timestamp é nominal e não autoriza reexecutar DDL nem editar migration history.

Objetivo:

- documentar no próprio schema físico que `review_status` é a fonte canônica do estado editorial para leitura;
- documentar `needs_review` como projeção de compatibilidade para novas escritas (`pending`/`needs_review` => `true`; `approved`/`discarded` => `false`);
- tornar explícito que linhas históricas podem divergir dessa projeção e não devem ser reinterpretadas a partir da flag legada.

Compatibilidade e limites:

- executa somente `COMMENT ON COLUMN`;
- não altera defaults, dados, grants, RLS, funções, constraints ou triggers;
- não executa backfill e preserva deliberadamente os 30.839 registros históricos `pending/false` observados antes da aplicação;
- não ativa o transcript-sync de produção nem muda os writers existentes.

Validação:

- read-back confirmou `review_status DEFAULT 'pending'::text` e `needs_review DEFAULT true`;
- os comentários físicos de `review_status` e `needs_review` correspondem exatamente ao SQL versionado;
- a distribuição permaneceu `30.857` segmentos no total, com `pending/false=30.839`, `pending/true=17`, `needs_review/true=1`, `approved/false=0` e `discarded/false=0`;
- o PostgreSQL sintético aplica a migration e `supabase/tests/transcript_review_default.sql` valida default e comentários;
- `src/features/transcript-sync/database.test.ts` continua provando novos imports como `review_status='pending'` + `needs_review=true`;
- advisors de segurança/performance foram reexecutados após a aplicação sem classe nova atribuível à migration COMMENT-only.

Rollback lógico:

- comentário incorreto pode ser substituído por migration corretiva posterior sem mutação de dados;
- não remover/reclassificar registros históricos para simular rollback documental.

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

## Correção de identidade em profile claims

### `20260915223000_align_profile_claim_discord_identity`

**Estado:** aplicada no Supabase canônico em 2026-09-15 pelo Production CD do commit `1b4931677b7f52f127f508d0c1eae18197d0d848`.

Objetivo:

- substituir a provenance obsoleta `google_claim` na criação de novos perfis aprovados pelo provider oficial Discord;
- resolver o `provider_id` diretamente de `auth.identities`, em vez de usar o UUID interno de `auth.users` como `source_key`;
- persistir novos perfis com `source_system='discord'`, `source_key=<discord provider_id>` e `discord_id=<discord provider_id>`;
- rejeitar aprovação sem identidade Discord vinculada ou quando um `requested_discord_id` divergir da identidade autenticada;
- usar a identidade Discord autenticada também no vínculo de participantes por `discord_id`.

Compatibilidade e limites:

- não executa backfill e não altera os cinco perfis existentes;
- preserva a assinatura, `SECURITY DEFINER`, `search_path`, grants e demais efeitos de `review_profile_claim(...)`;
- não remove `google_claim` do CHECK legado de `profiles.source_system`, evitando contract/drop misturado nesta correção;
- rejeições de claim continuam independentes da existência de identidade Discord; a exigência é aplicada somente na aprovação;
- a inspeção pré-migration confirmou 5/5 perfis canônicos com identidade Discord e correspondência exata entre `source_key`, `discord_id` e `auth.identities.provider_id`, além de zero claims existentes no momento da auditoria.

Rollback lógico:

- se a função precisar ser revertida, criar migration corretiva posterior com a definição anterior revisada; não editar migration history nem reintroduzir `google_claim` silenciosamente;
- nenhum dado existente precisa ser revertido por esta migration porque ela altera somente o comportamento futuro da RPC.

## Hardening de índices esparsos de transcrição

### `20260916001000_add_sparse_transcript_fk_indexes`

**Estado:** aplicada no Supabase canônico em 2026-09-16 pelo Production CD #109 do commit `4da70a9effddb01bb0d4e847b6c4e2baeccf39b2`.

Objetivo:

- cobrir os quatro FKs restantes de `public.transcript_segments` que ainda não possuíam índice iniciando pela coluna referenciada;
- criar índices btree parciais em `participant_id`, `source_chunk_id`, `source_file_id` e `speaker_profile_id`, somente quando o valor não é nulo;
- reduzir custo de verificações de FK e de lookups diretos sem adicionar índices indiscriminadamente às 61 sugestões do advisor.

Medição pré-migration em produção:

- `transcript_segments`: 30.857 linhas, cerca de 17 MB incluindo índices;
- `participant_id`: 2.464 valores não nulos / 18 distintos;
- `source_chunk_id`: 2.464 valores não nulos / 305 distintos;
- `source_file_id`: 2.464 valores não nulos / 18 distintos;
- `speaker_profile_id`: 41 valores não nulos / 5 distintos;
- `entity_relations` possui apenas 4 linhas e `profile_claims` está vazio, portanto esses advisor findings foram deliberadamente deixados sem índice até existir uso que justifique o custo.

Compatibilidade e limites:

- não altera dados, FK, constraints, RLS, grants ou comportamento da aplicação;
- usa `CREATE INDEX IF NOT EXISTS` e predicates `IS NOT NULL`, mantendo footprint e write amplification pequenos para colunas esparsas;
- não tenta otimizar queries de sessão já cobertas pelos índices compostos existentes em `(session_id, ...)`.

Validação pós-migration:

- os quatro índices parciais foram confirmados fisicamente no Supabase canônico;
- não restaram FKs de `transcript_segments` sem índice iniciando pela coluna do FK;
- uma consulta representativa por `source_file_id` passou de `Seq Scan` (~3,83 ms / 1.205 buffers no preflight) para `Index Scan` pelo `idx_transcript_segments_source_file_id_fk` (~1,78 ms / 28 blocos acessados na validação pós-release).

Rollback lógico:

- se algum índice provar custo maior que benefício, remover somente esse índice em migration corretiva posterior;
- não há dado para restaurar, pois a mudança é exclusivamente de estrutura de acesso.

## Hardening de grants autenticados do Ordo

### `20260916002000_harden_ordo_authenticated_grants`

**Estado:** migration versionada na PR #373; **ainda não aplicada no Supabase canônico**.

Objetivo:

- reduzir o grant direto de `authenticated` sobre `public.ordo_access_members` ao contrato realmente usado pela aplicação;
- revogar somente `REFERENCES`, `TRIGGER` e `TRUNCATE`, que não fazem parte do fluxo de acesso do Ordo;
- preservar `SELECT`, `INSERT`, `UPDATE` e `DELETE`, ainda governados pelas policies RLS existentes.

Revisão de segurança:

- a inspeção do schema real confirmou RLS habilitado e policies de acesso self/master já existentes;
- a mudança não altera policies, dados, constraints, funções ou grants de outros roles;
- como `REVOKE` contrai capacidade SQL, a migration contém o marker `TDA:ALLOW_DESTRUCTIVE_MIGRATION` exigido pelo guardrail após revisão explícita do impacto;
- o marker não amplia o escopo: documenta que esta contração específica foi deliberadamente revisada.

Rollback lógico:

- se um consumidor legítimo for identificado, uma migration corretiva posterior pode regrantar somente o privilégio realmente necessário;
- não há dado a restaurar e o CRUD autenticado permanece intacto durante este recorte.

## Mutation atômica de provenance das relações do World Explorer

### `20260916113000_world_relation_provenance_atomic`

**Estado:** aplicada no Supabase canônico em 2026-09-16 pelo Production CD #116 do commit `77aad98a0eeca402411e88fa4ddb82a4c6eed326`; migration history, definição física/grants da RPC e `/api/version` canônico foram verificados por read-back independente.

Objetivo:

- criar `replace_world_relation_sources_atomic(...)` como boundary server-only para substituir fontes canônicas de uma relação em uma única transação;
- manter provenance fora do JSON editorial do World e persistida exclusivamente em `entity_relation_sources`;
- exigir que a relation já exista fisicamente em `entity_relations`, evitando fabricar provenance para uma edge que existe apenas no draft;
- aceitar somente `canon_entries` com `status='active'` e pertencentes à mesma campaign da relation;
- preservar o invariante de que relation `active` em `public_campaign`/`public_web` não pode terminar sem ao menos uma fonte canônica válida;
- registrar `world_relation.provenance.replace` no `audit_log` com conjunto anterior e novo de canon IDs.

Segurança e autorização:

- a função é `SECURITY DEFINER` com `search_path = pg_catalog, public`;
- exige identidade/profile válidos e, cumulativamente, `campaign.content.edit` + `narrative.canon.approve` no scope efetivo da campaign ou do projeto `tda`;
- `EXECUTE` fica revogado de `public`, `anon` e `authenticated` e concedido apenas a `service_role`;
- `service_role` continua sem `INSERT/DELETE` direto em `entity_relation_sources`; o RPC é o único boundary de escrita proposto por este recorte;
- o payload é limitado a 50 canon IDs, rejeita nulos/cross-campaign/inativos e deduplica IDs antes da troca.

Compatibilidade e rollout:

- não altera relations, canon entries, visibilities ou source rows durante a aplicação da migration;
- não cria canon automaticamente nem amplia `campaign.content.edit` para permitir aprovação canônica;
- `TDA_WORLD_CANONICAL_ENABLED` permanece desligado;
- o consumidor de UI será integrado em recorte separado após a função estar validada/aplicada;
- relações novas continuam seguindo `draft -> persistir privado/review -> anexar canon revisado -> promover público` enquanto provenance não fizer parte de um publish atômico futuro.

Validação pós-release:

- migration history contém `20260916113000 world_relation_provenance_atomic`;
- `replace_world_relation_sources_atomic(...)` está `SECURITY DEFINER`, owner `postgres`, com `search_path=pg_catalog, public`;
- somente `postgres` e `service_role` possuem `EXECUTE` entre os roles relevantes;
- `service_role` permaneceu apenas com `SELECT` em `entity_relation_sources`;
- aplicação da migration não criou source ou audit de provenance e o domínio canônico respondeu o merge commit esperado.

Rollback lógico:

- antes de existir consumidor, uma migration corretiva pode revogar/remover a função sem tocar em facts ou source rows;
- após ativação de consumidor, primeiro retirar o server action/UI e só depois remover o RPC em migration corretiva;
- nunca apagar `entity_relation_sources`, `canon_entries` ou `audit_log` para simular rollback.

## Invalidação semântica de provenance das relações do World Explorer

### `20260916120000_world_graph_provenance_semantic_invalidation`

**Estado:** migration versionada na PR #381; **ainda não aplicada no Supabase canônico**.

Objetivo:

- impedir que uma fonte canônica aprovada para um fato continue validando silenciosamente outro fato editado sob o mesmo UUID de relation;
- tratar mudança de `source_entity_id`, `target_entity_id`, `relation_type_slug`, `label_override` ou `status` como mudança semântica;
- manter `visibility` e overrides visuais fora da identidade semântica da provenance;
- invalidar atomicamente `entity_relation_sources` quando uma relation privada/review muda de semântica e registrar `world_relation.provenance.invalidate` no `audit_log`;
- impedir INSERT de relation já `active/public_*`, promoção sem source ativa da mesma campaign e mudança semântica direta enquanto a relation permanece pública;
- exigir o fluxo explícito `review/private -> revisar/anexar canon -> promover público`.

Boundary e segurança:

- `enforce_world_relation_provenance_on_write()` é trigger `SECURITY DEFINER` com `search_path = pg_catalog, public` e sem `EXECUTE` direto para `public`, `anon`, `authenticated` ou `service_role`;
- o trigger `entity_relations_provenance_write_guard` roda `BEFORE INSERT OR UPDATE` em `entity_relations`, portanto também cobre callers internos que tentem contornar o server action;
- a invalidação de sources e o audit acontecem na mesma transação da alteração semântica; falha do audit reverte a mudança inteira;
- `publish_world_edit_state_atomic(...)` recebe um guard forward-only adicional para retornar `review_required` antes de qualquer write quando um draft público tenta alterar a semântica de relation já persistida;
- o guard de publish respeita inversão de endpoints quando o tipo de relation do draft é simétrico.

Preflight e validação:

- produção possuía 4 `entity_relations`, 0 relations ativas públicas e 0 `entity_relation_sources`, portanto não existe evidence atual para backfill/invalidação durante a migration;
- PostgreSQL 16 descartável aplicou a candidata e passou o contrato de World, incluindo direct bypass, invalidação automática, audit, promoção bloqueada sem evidence, re-review, promoção por visibility e bloqueio de semantic edit pública;
- migration safety policy passou; o primeiro CI vermelho foi exclusivamente o guardrail documental por ausência deste registro.

Compatibilidade e rollback lógico:

- não cria nem altera lore/canon durante a aplicação e não faz backfill;
- `TDA_WORLD_CANONICAL_ENABLED` permanece desligado;
- para rollback, retirar primeiro consumidores que dependam do novo invariante e usar migration corretiva explícita para remover trigger/restaurar a definição revisada do publish RPC;
- não restaurar automaticamente sources invalidadas: elas foram evidência de uma semântica anterior e exigem nova revisão para voltar a existir.


## Reconciliação autoritativa de relações no publish do World

### `20260919162000_world_graph_authoritative_relation_reconcile`

**Estado:** aplicada no Supabase canônico em 2026-09-19 pelo Production CD da PR #401, merge `b5a72440b08d666b8df915acdd86265699bb3d32`; migration history, definição/grants da RPC e `/api/version` canônico foram verificados por read-back pós-release.

Objetivo:

- alinhar o publish ao contrato já existente de lease exclusivo + `world_graph_heads.revision`: depois que ambos são validados, o draft salvo é a intenção editorial autoritativa daquela sessão;
- impedir que uma relação antiga ainda `active` bloqueie uma substituição legítima apenas por ordem de UUID/JSON;
- aplicar relações não ativas primeiro, relações ativas inalteradas em seguida e relações novas/semanticamente alteradas por último;
- quando a relação autoritativa colidir semanticamente com uma row ativa anterior, preservar a anterior como `superseded` e publicar a nova, sem hard delete;
- manter no máximo uma relação ativa por identidade semântica ao final da transação;
- preservar os gates existentes de capability, lease, optimistic concurrency, provenance pública, layout atômico, snapshots e audit.

Motivação observada:

- produção registrou repetidamente `duplicate active relation` em `/mundo` durante uma publicação válida de um editor que já possuía o lease exclusivo;
- o publisher anterior resolvia conflito olhando o estado físico intermediário linha a linha, então uma relação antiga podia ser encontrada ainda ativa antes que o próprio draft a arquivasse/substituísse;
- esse comportamento contradizia a serialização já fornecida pelo lease e fazia a transação inteira falhar embora não existisse editor concorrente.

Compatibilidade e recuperação:

- nenhuma tabela, coluna, RLS, policy ou capability é criada/alterada;
- a assinatura, `SECURITY INVOKER`, `search_path` e grants de `publish_world_edit_state_atomic(...)` permanecem os mesmos;
- relações históricas não são apagadas; substituições usam lifecycle `superseded`;
- rollback deve ser feito por migration corretiva posterior restaurando a definição anterior da RPC, sem apagar revisions/audit/relations históricas;
- o teste sintético cobre explicitamente uma edge nova ativa aparecendo antes da predecessora arquivada no JSON, provando que a publicação não depende mais dessa ordem.
