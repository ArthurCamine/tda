\set ON_ERROR_STOP on

-- Synthetic contract for canonical World graph authoring. No production data.
do $$
begin
  if not exists (
    select 1 from pg_class c join pg_namespace n on n.oid=c.relnamespace
    where n.nspname='public' and c.relname='entity_relations' and c.relrowsecurity
  ) or not exists (
    select 1 from pg_class c join pg_namespace n on n.oid=c.relnamespace
    where n.nspname='public' and c.relname='relation_types' and c.relrowsecurity
  ) then
    raise exception 'world graph tables must have RLS enabled';
  end if;

  if exists (
    select 1 from pg_policies
    where schemaname='public' and tablename in (
      'relation_types','world_relation_styles','entity_relations',
      'entity_relation_sources','world_graph_heads','world_graph_revisions'
    )
  ) then
    raise exception 'world graph tables must remain deny-by-default for browser roles';
  end if;

  if has_table_privilege('anon','public.entity_relations','SELECT')
     or has_table_privilege('authenticated','public.entity_relations','SELECT')
     or has_table_privilege('anon','public.relation_types','SELECT')
     or has_table_privilege('authenticated','public.relation_types','SELECT') then
    raise exception 'browser roles must not read canonical graph tables directly';
  end if;

  if has_function_privilege('anon','public.acquire_world_graph_draft_atomic(uuid,uuid,text,uuid)','EXECUTE')
     or has_function_privilege('authenticated','public.acquire_world_graph_draft_atomic(uuid,uuid,text,uuid)','EXECUTE')
     or has_function_privilege('anon','public.save_world_graph_draft_atomic(uuid,uuid,text,uuid,jsonb)','EXECUTE')
     or has_function_privilege('authenticated','public.save_world_graph_draft_atomic(uuid,uuid,text,uuid,jsonb)','EXECUTE')
     or has_function_privilege('anon','public.publish_world_edit_state_atomic(uuid,uuid,text,uuid)','EXECUTE')
     or has_function_privilege('authenticated','public.publish_world_edit_state_atomic(uuid,uuid,text,uuid)','EXECUTE') then
    raise exception 'browser roles must not execute world graph authoring RPCs';
  end if;
end;
$$;

-- Leave the previous layout/lease suite behind and start a deterministic factual graph.
reset role;
delete from public.world_edit_leases;
delete from public.entity_relation_sources;
delete from public.entity_relations;
delete from public.world_relation_styles;
delete from public.relation_types;
delete from public.world_graph_revisions;
delete from public.world_graph_heads;
delete from public.world_layout_snapshots;
delete from public.entities;
delete from public.audit_log where action in ('world_layout.update','world_graph.publish');

insert into public.entities(
  id, campaign_id, name, slug, entity_type, status, visibility, summary, aliases
) values (
  '10101010-1010-4010-8010-101010101010',
  '11111111-1111-4111-8111-111111111111',
  'Herói Um',
  'heroi-um',
  'pc',
  'active',
  'public_web',
  'Identidade estrutural sintética.',
  array['Primeiro Herói']
);

-- A profile with layout capability only proves factual authoring does not inherit
-- from campaign.world.layout.edit.
insert into public.profiles(id, auth_user_id, display_name)
values (
  '12121212-1212-4212-8212-121212121212',
  '13131313-1313-4313-8313-131313131313',
  'Layout Apenas'
);
insert into public.role_definitions(id, slug, plane)
values (
  '14141414-1414-4414-8414-141414141414',
  'layout_only',
  'narrative'
);
insert into public.role_permissions(role_id, permission_action)
values (
  '14141414-1414-4414-8414-141414141414',
  'campaign.world.layout.edit'
);
insert into public.role_assignments(profile_id, role_id, scope_type, scope_id, status, starts_at)
values (
  '12121212-1212-4212-8212-121212121212',
  '14141414-1414-4414-8414-141414141414',
  'campaign',
  'synthetic-campaign',
  'active',
  now() - interval '1 minute'
);

set role service_role;
do $$
declare
  result jsonb;
  token uuid := '15151515-1515-4515-8515-151515151515';
begin
  result := public.acquire_world_edit_lease_atomic(
    '13131313-1313-4313-8313-131313131313',
    '12121212-1212-4212-8212-121212121212',
    'synthetic-campaign',
    token
  );
  if result->>'ok' <> 'true' then
    raise exception 'layout-only editor should acquire layout lease: %', result;
  end if;

  result := public.acquire_world_graph_draft_atomic(
    '13131313-1313-4313-8313-131313131313',
    '12121212-1212-4212-8212-121212121212',
    'synthetic-campaign',
    token
  );
  if result <> '{"ok":false,"reason":"forbidden"}'::jsonb then
    raise exception 'layout-only editor must not gain factual authoring: %', result;
  end if;

  result := public.release_world_edit_lease_atomic(
    '13131313-1313-4313-8313-131313131313',
    '12121212-1212-4212-8212-121212121212',
    'synthetic-campaign',
    token
  );
  if result->>'ok' <> 'true' then
    raise exception 'layout-only lease cleanup failed: %', result;
  end if;
end;
$$;
reset role;

-- A direct service-role RPC call must not bypass canon/review provenance.
-- The rejection happens before graph/layout/audit writes and leaves the private
-- draft recoverable until the caller explicitly releases/discards the lease.
set role service_role;
do $$
declare
  result jsonb;
  token uuid := '15161616-1516-4516-8516-151616161616';
  draft jsonb;
begin
  result := public.acquire_world_edit_lease_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token
  );
  if result->>'status' <> 'acquired' then
    raise exception 'provenance guard fixture must acquire lease: %', result;
  end if;

  result := public.acquire_world_graph_draft_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token
  );
  if result->>'ok' <> 'true' or (result->>'baseRevision')::bigint <> 0 then
    raise exception 'provenance guard fixture must acquire factual draft: %', result;
  end if;

  draft := jsonb_build_object(
    'schemaVersion', 1,
    'revision', 0,
    'nodes', jsonb_build_array(
      jsonb_build_object(
        'id','10101010-1010-4010-8010-101010101010',
        'name','Herói Um',
        'slug','heroi-um',
        'entityType','pc',
        'status','active',
        'visibility','public_web',
        'summary','Identidade estrutural sintética.',
        'aliases',jsonb_build_array('Primeiro Herói')
      ),
      jsonb_build_object(
        'id','21212121-2121-4121-8121-212121212121',
        'name','NPC Sem Fonte',
        'slug','npc-sem-fonte',
        'entityType','npc',
        'status','active',
        'visibility','public_web',
        'summary','Somente rascunho para o teste de provenance.',
        'aliases','[]'::jsonb
      )
    ),
    'relationTypes', jsonb_build_array(
      jsonb_build_object(
        'slug','rival_of',
        'label','Rivalidade',
        'direction','symmetric',
        'family','conflict',
        'description','Relação sintética sem fonte.',
        'isActive',true,
        'color','#aa6655',
        'lineStyle','dashed',
        'lineWidth',3
      )
    ),
    'edges', jsonb_build_array(
      jsonb_build_object(
        'id','22222222-2222-4222-8222-222222222222',
        'source','10101010-1010-4010-8010-101010101010',
        'target','21212121-2121-4121-8121-212121212121',
        'relationType','rival_of',
        'labelOverride','Rivais sem fonte',
        'status','active',
        'visibility','public_web',
        'colorOverride',null,
        'lineStyleOverride',null,
        'lineWidthOverride',null
      )
    )
  );

  result := public.save_world_graph_draft_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token,
    draft
  );
  if result->>'status' <> 'draft_saved' then
    raise exception 'provenance guard fixture draft must save privately: %', result;
  end if;

  result := public.publish_world_edit_state_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token
  );
  if result <> '{"ok":false,"reason":"review_required"}'::jsonb then
    raise exception 'direct unsourced public publish must fail review gate: %', result;
  end if;

  if (select count(*) from public.entities) <> 1
     or exists (select 1 from public.entity_relations)
     or exists (select 1 from public.relation_types)
     or exists (select 1 from public.world_layout_snapshots)
     or exists (select 1 from public.world_graph_revisions)
     or coalesce((select revision from public.world_graph_heads where campaign_id='11111111-1111-4111-8111-111111111111'), 0) <> 0
     or exists (select 1 from public.audit_log where action in ('world_layout.update','world_graph.publish')) then
    raise exception 'review_required must leave canonical graph/layout/audit unchanged';
  end if;

  result := public.release_world_edit_lease_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token
  );
  if result->>'ok' <> 'true' then
    raise exception 'provenance guard fixture cleanup failed: %', result;
  end if;
end;
$$;
reset role;

set role service_role;
do $$
declare
  result jsonb;
  token uuid := '16161616-1616-4616-8616-161616161616';
  draft jsonb;
begin
  result := public.acquire_world_edit_lease_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token
  );
  if result->>'status' <> 'acquired' or (result->>'baseRevision')::bigint <> 0 then
    raise exception 'content editor must start with layout revision 0: %', result;
  end if;

  result := public.acquire_world_graph_draft_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token
  );
  if result->>'ok' <> 'true'
     or (result->>'baseRevision')::bigint <> 0
     or jsonb_array_length(result->'draftGraph'->'nodes') <> 1
     or result->'draftGraph'->'nodes'->0->>'name' <> 'Herói Um' then
    raise exception 'graph draft must start from canonical entities: %', result;
  end if;

  draft := jsonb_build_object(
    'schemaVersion', 1,
    'revision', 0,
    'nodes', jsonb_build_array(
      jsonb_build_object(
        'id','10101010-1010-4010-8010-101010101010',
        'name','Herói Um',
        'slug','heroi-um',
        'entityType','pc',
        'status','active',
        'visibility','public_web',
        'summary','Identidade estrutural sintética atualizada.',
        'aliases',jsonb_build_array('Primeiro Herói')
      ),
      jsonb_build_object(
        'id','17171717-1717-4717-8717-171717171717',
        'name','NPC Novo',
        'slug','npc-novo',
        'entityType','npc',
        'status','active',
        'visibility','public_web',
        'summary','Criado manualmente no editor.',
        'aliases','[]'::jsonb
      )
    ),
    'relationTypes', jsonb_build_array(
      jsonb_build_object(
        'slug','friend_of',
        'label','Amizade',
        'direction','symmetric',
        'family','affinity',
        'description','Laço de amizade explícito.',
        'isActive',true,
        'color','#55aa77',
        'lineStyle','solid',
        'lineWidth',3
      )
    ),
    'edges', jsonb_build_array(
      jsonb_build_object(
        'id','18181818-1818-4818-8818-181818181818',
        'source','17171717-1717-4717-8717-171717171717',
        'target','10101010-1010-4010-8010-101010101010',
        'relationType','friend_of',
        'labelOverride','Amigos de viagem',
        'status','active',
        'visibility','review_only',
        'colorOverride','#66bb88',
        'lineStyleOverride','dashed',
        'lineWidthOverride',4
      )
    )
  );

  result := public.save_world_graph_draft_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token,
    draft
  );
  if result->>'status' <> 'draft_saved' then
    raise exception 'canonical graph draft must save privately: %', result;
  end if;

  result := public.save_world_edit_layout_draft_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token,
    '{"10101010-1010-4010-8010-101010101010":{"x":100,"y":20},"17171717-1717-4717-8717-171717171717":{"x":-120,"y":80}}'::jsonb
  );
  if result->>'status' <> 'draft_saved' then
    raise exception 'combined publish fixture layout draft failed: %', result;
  end if;

  -- Draft must not leak into canonical tables before explicit publish.
  if (select count(*) from public.entities) <> 1
     or exists (select 1 from public.entity_relations)
     or exists (select 1 from public.relation_types) then
    raise exception 'private graph draft mutated canonical state before publish';
  end if;

  result := public.publish_world_edit_state_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token
  );
  if result->>'ok' <> 'true'
     or result->>'status' <> 'saved'
     or (result->>'graphRevision')::bigint <> 1
     or (result->>'layoutRevision')::bigint <> 1
     or result->>'graphChanged' <> 'true'
     or result->>'layoutChanged' <> 'true' then
    raise exception 'combined World publication failed: %', result;
  end if;

  if exists (select 1 from public.world_edit_leases)
     or (select revision from public.world_graph_heads) <> 1
     or (select count(*) from public.world_graph_revisions) <> 1
     or (select count(*) from public.entities) <> 2
     or (select count(*) from public.relation_types) <> 1
     or (select count(*) from public.entity_relations) <> 1
     or (select count(*) from public.audit_log where action='world_graph.publish') <> 1
     or (select count(*) from public.audit_log where action='world_layout.update') <> 1 then
    raise exception 'combined publish did not leave expected canonical/audit state';
  end if;

  if (select source_entity_id::text from public.entity_relations limit 1)
       <> least('10101010-1010-4010-8010-101010101010','17171717-1717-4717-8717-171717171717')
     or (select color from public.world_relation_styles where relation_type_slug='friend_of') <> '#55aa77'
     or (select color_override from public.entity_relations limit 1) <> '#66bb88' then
    raise exception 'symmetric normalization or visual style persistence failed';
  end if;
end;
$$;
reset role;

-- The exclusive draft is authoritative when it replaces an existing semantic
-- relation. A new active edge may appear before the archived predecessor in the
-- JSON array; publication must still retire the predecessor first instead of
-- raising "duplicate active relation". Keep the regression isolated so the
-- provenance suite that follows still starts from the canonical revision-1 fixture.
begin;
set role service_role;
do $$
declare
  result jsonb;
  token uuid := '21212121-2121-4212-8212-212121212121';
  draft jsonb;
begin
  result := public.acquire_world_edit_lease_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token
  );
  if result->>'status' <> 'acquired' or (result->>'baseRevision')::bigint <> 1 then
    raise exception 'replacement fixture must acquire layout revision 1: %', result;
  end if;

  result := public.acquire_world_graph_draft_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token
  );
  if result->>'ok' <> 'true' or (result->>'baseRevision')::bigint <> 1 then
    raise exception 'replacement fixture must acquire graph revision 1: %', result;
  end if;

  draft := result->'draftGraph';
  draft := jsonb_set(
    draft,
    '{edges}',
    jsonb_build_array(
      jsonb_build_object(
        'id','17181818-1818-4818-8818-181818181818',
        'source','17171717-1717-4717-8717-171717171717',
        'target','10101010-1010-4010-8010-101010101010',
        'relationType','friend_of',
        'labelOverride','Amizade corrigida',
        'status','active',
        'visibility','review_only',
        'colorOverride',null,
        'lineStyleOverride',null,
        'lineWidthOverride',null
      ),
      jsonb_build_object(
        'id','18181818-1818-4818-8818-181818181818',
        'source','10101010-1010-4010-8010-101010101010',
        'target','17171717-1717-4717-8717-171717171717',
        'relationType','friend_of',
        'labelOverride','Amigos de viagem',
        'status','archived',
        'visibility','review_only',
        'colorOverride','#66bb88',
        'lineStyleOverride','dashed',
        'lineWidthOverride',4
      )
    ),
    true
  );

  result := public.save_world_graph_draft_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token,
    draft
  );
  if result->>'status' <> 'draft_saved' then
    raise exception 'replacement draft must save: %', result;
  end if;

  result := public.publish_world_edit_state_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token
  );
  if result->>'ok' <> 'true'
     or result->>'status' <> 'saved'
     or (result->>'graphRevision')::bigint <> 2
     or (result->>'layoutRevision')::bigint <> 1 then
    raise exception 'authoritative relation replacement failed: %', result;
  end if;

  if (select status from public.entity_relations where id='18181818-1818-4818-8818-181818181818') <> 'archived'
     or (select status from public.entity_relations where id='17181818-1818-4818-8818-181818181818') <> 'active'
     or (select count(*) from public.entity_relations where relation_type_slug='friend_of' and status='active') <> 1 then
    raise exception 'authoritative replacement did not leave exactly one active relation';
  end if;
end;
$$;
reset role;
rollback;

-- Recovery keeps a private factual draft for the same editor after lease expiry.
set role service_role;
do $$
declare
  result jsonb;
  token_a uuid := '19191919-1919-4919-8919-191919191919';
  token_b uuid := '20202020-2020-4020-8020-202020202020';
begin
  result := public.acquire_world_edit_lease_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign', token_a
  );
  result := public.acquire_world_graph_draft_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign', token_a
  );
  if (result->>'baseRevision')::bigint <> 1 then
    raise exception 'fresh factual draft should start at graph revision 1: %', result;
  end if;
end;
$$;
reset role;

update public.world_edit_leases
set acquired_at=acquired_at-interval '2 minutes',
    heartbeat_at=heartbeat_at-interval '2 minutes',
    draft_updated_at=draft_updated_at-interval '2 minutes',
    expires_at=clock_timestamp()-interval '1 second';

set role service_role;
do $$
declare
  result jsonb;
  token_b uuid := '20202020-2020-4020-8020-202020202020';
begin
  result := public.acquire_world_edit_lease_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign', token_b
  );
  if result->>'status' <> 'recovered' then
    raise exception 'same editor lease recovery failed: %', result;
  end if;

  result := public.acquire_world_graph_draft_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign', token_b
  );
  if result->>'ok' <> 'true' or (result->>'baseRevision')::bigint <> 1 then
    raise exception 'same editor graph draft recovery failed: %', result;
  end if;

  result := public.release_world_edit_lease_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign', token_b
  );
  if result->>'ok' <> 'true' then
    raise exception 'recovered graph draft cleanup failed: %', result;
  end if;
end;
$$;
reset role;
