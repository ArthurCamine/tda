\set ON_ERROR_STOP on

-- Synthetic contract for relation provenance. Runs only after World graph
-- authoring has persisted the deterministic review-only relation fixture.
do $$
declare
  secure boolean;
  config text;
begin
  select p.prosecdef, coalesce(array_to_string(p.proconfig, ','), '')
  into secure, config
  from pg_proc p
  join pg_namespace n on n.oid = p.pronamespace
  where n.nspname = 'public'
    and p.oid = 'public.replace_world_relation_sources_atomic(uuid,uuid,text,uuid,uuid[])'::regprocedure;

  if secure is not true then
    raise exception 'relation provenance RPC must be SECURITY DEFINER';
  end if;
  if position('search_path=pg_catalog, public' in config) = 0 then
    raise exception 'relation provenance RPC must pin search_path: %', config;
  end if;
  if has_function_privilege(
       'anon',
       'public.replace_world_relation_sources_atomic(uuid,uuid,text,uuid,uuid[])',
       'EXECUTE'
     )
     or has_function_privilege(
       'authenticated',
       'public.replace_world_relation_sources_atomic(uuid,uuid,text,uuid,uuid[])',
       'EXECUTE'
     ) then
    raise exception 'browser roles must not execute provenance mutation';
  end if;
  if not has_function_privilege(
    'service_role',
    'public.replace_world_relation_sources_atomic(uuid,uuid,text,uuid,uuid[])',
    'EXECUTE'
  ) then
    raise exception 'service_role must execute provenance mutation';
  end if;

  if not has_table_privilege('service_role', 'public.entity_relation_sources', 'SELECT')
     or has_table_privilege('service_role', 'public.entity_relation_sources', 'INSERT')
     or has_table_privilege('service_role', 'public.entity_relation_sources', 'UPDATE')
     or has_table_privilege('service_role', 'public.entity_relation_sources', 'DELETE')
     or has_table_privilege('service_role', 'public.entity_relation_sources', 'TRUNCATE') then
    raise exception 'service_role must keep relation source table read-only';
  end if;
end;
$$;

-- The existing synthetic site_editor has campaign.content.edit but not canon
-- approval yet. The new RPC must therefore fail closed before any write.
set role service_role;
do $$
declare
  result jsonb;
begin
  result := public.replace_world_relation_sources_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    '18181818-1818-4818-8818-181818181818',
    '{}'::uuid[]
  );
  if result <> '{"ok":false,"reason":"forbidden"}'::jsonb then
    raise exception 'content edit without canon approval must be forbidden: %', result;
  end if;
end;
$$;
reset role;

insert into public.permission_catalog(action, plane, description)
values ('narrative.canon.approve', 'narrative', 'Approve reviewed narrative canon.')
on conflict (action) do nothing;

insert into public.role_permissions(role_id, permission_action)
values ('55555555-5555-4555-8555-555555555555', 'narrative.canon.approve')
on conflict do nothing;

insert into public.campaigns(id, slug)
values ('90909090-9090-4090-8090-909090909090', 'other-synthetic-campaign')
on conflict do nothing;

insert into public.canon_entries(id, campaign_id, status) values
  ('30303030-3030-4030-8030-303030303030', '11111111-1111-4111-8111-111111111111', 'active'),
  ('31313131-3131-4131-8131-313131313131', '11111111-1111-4111-8111-111111111111', 'active'),
  ('32323232-3232-4232-8232-323232323232', '11111111-1111-4111-8111-111111111111', 'archived'),
  ('33303030-3030-4030-8030-303030303030', '90909090-9090-4090-8090-909090909090', 'active');

set role service_role;
do $$
declare
  result jsonb;
begin
  result := public.replace_world_relation_sources_atomic(
    '66666666-6666-4666-8666-666666666666',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    '18181818-1818-4818-8818-181818181818',
    array['30303030-3030-4030-8030-303030303030'::uuid]
  );
  if result <> '{"ok":false,"reason":"forbidden"}'::jsonb then
    raise exception 'unbound auth identity must be forbidden: %', result;
  end if;

  result := public.replace_world_relation_sources_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    '34343434-3434-4434-8434-343434343434',
    array['30303030-3030-4030-8030-303030303030'::uuid]
  );
  if result <> '{"ok":false,"reason":"not_found"}'::jsonb then
    raise exception 'unknown same-campaign relation must stay undisclosed: %', result;
  end if;

  result := public.replace_world_relation_sources_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    '18181818-1818-4818-8818-181818181818',
    array['32323232-3232-4232-8232-323232323232'::uuid]
  );
  if result <> '{"ok":false,"reason":"invalid_payload"}'::jsonb then
    raise exception 'inactive canon must not become provenance: %', result;
  end if;

  result := public.replace_world_relation_sources_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    '18181818-1818-4818-8818-181818181818',
    array['33303030-3030-4030-8030-303030303030'::uuid]
  );
  if result <> '{"ok":false,"reason":"invalid_payload"}'::jsonb then
    raise exception 'cross-campaign canon must not become provenance: %', result;
  end if;

  if exists (select 1 from public.entity_relation_sources)
     or exists (select 1 from public.audit_log where action='world_relation.provenance.replace') then
    raise exception 'rejected provenance mutations must be side-effect free';
  end if;

  result := public.replace_world_relation_sources_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    '18181818-1818-4818-8818-181818181818',
    array[
      '30303030-3030-4030-8030-303030303030'::uuid,
      '30303030-3030-4030-8030-303030303030'::uuid
    ]
  );
  if result <> '{"ok":true,"status":"saved","sourceCount":1}'::jsonb then
    raise exception 'valid active canon source must save and deduplicate: %', result;
  end if;
  if (select count(*) from public.entity_relation_sources) <> 1
     or (select canon_entry_id from public.entity_relation_sources limit 1)
          <> '30303030-3030-4030-8030-303030303030'::uuid
     or (select count(*) from public.audit_log where action='world_relation.provenance.replace') <> 1 then
    raise exception 'saved provenance must persist one source and one audit event';
  end if;

  result := public.replace_world_relation_sources_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    '18181818-1818-4818-8818-181818181818',
    array['30303030-3030-4030-8030-303030303030'::uuid]
  );
  if result <> '{"ok":true,"status":"unchanged","sourceCount":1}'::jsonb then
    raise exception 'identical source set must be a no-op: %', result;
  end if;
  if (select count(*) from public.audit_log where action='world_relation.provenance.replace') <> 1 then
    raise exception 'unchanged provenance must not duplicate audit';
  end if;

  result := public.replace_world_relation_sources_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    '18181818-1818-4818-8818-181818181818',
    array['31313131-3131-4131-8131-313131313131'::uuid]
  );
  if result <> '{"ok":true,"status":"saved","sourceCount":1}'::jsonb then
    raise exception 'replacing provenance must save atomically: %', result;
  end if;
end;
$$;
reset role;

update public.entity_relations
set visibility = 'public_web'
where id = '18181818-1818-4818-8818-181818181818';

set role service_role;
do $$
declare
  result jsonb;
begin
  result := public.replace_world_relation_sources_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    '18181818-1818-4818-8818-181818181818',
    '{}'::uuid[]
  );
  if result <> '{"ok":false,"reason":"review_required"}'::jsonb then
    raise exception 'public active relation must not lose its final source: %', result;
  end if;
end;
$$;
reset role;

do $$
begin
  if (select count(*) from public.entity_relation_sources) <> 1
     or (select canon_entry_id from public.entity_relation_sources limit 1)
          <> '31313131-3131-4131-8131-313131313131'::uuid
     or (select count(*) from public.audit_log where action='world_relation.provenance.replace') <> 2 then
    raise exception 'review_required must preserve previous provenance and audit count';
  end if;
end;
$$;

-- Force the audit insert to fail and prove DELETE+INSERT is rolled back with it.
create function public.fail_world_relation_provenance_audit()
returns trigger
language plpgsql
as $function$
begin
  if new.action = 'world_relation.provenance.replace' then
    raise exception 'synthetic provenance audit failure';
  end if;
  return new;
end;
$function$;

create trigger fail_world_relation_provenance_audit
before insert on public.audit_log
for each row execute function public.fail_world_relation_provenance_audit();

update public.entity_relations
set visibility = 'review_only'
where id = '18181818-1818-4818-8818-181818181818';

set role service_role;
do $$
declare
  failed boolean := false;
begin
  begin
    perform public.replace_world_relation_sources_atomic(
      '44444444-4444-4444-8444-444444444444',
      '33333333-3333-4333-8333-333333333333',
      'synthetic-campaign',
      '18181818-1818-4818-8818-181818181818',
      array['30303030-3030-4030-8030-303030303030'::uuid]
    );
  exception when others then
    failed := true;
  end;
  if not failed then
    raise exception 'synthetic audit failure must abort provenance replacement';
  end if;
end;
$$;
reset role;

drop trigger fail_world_relation_provenance_audit on public.audit_log;
drop function public.fail_world_relation_provenance_audit();

do $$
begin
  if (select count(*) from public.entity_relation_sources) <> 1
     or (select canon_entry_id from public.entity_relation_sources limit 1)
          <> '31313131-3131-4131-8131-313131313131'::uuid
     or (select count(*) from public.audit_log where action='world_relation.provenance.replace') <> 2 then
    raise exception 'failed audit must roll back relation source replacement';
  end if;
end;
$$;

set role service_role;
do $$
declare
  result jsonb;
begin
  result := public.replace_world_relation_sources_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    '18181818-1818-4818-8818-181818181818',
    '{}'::uuid[]
  );
  if result <> '{"ok":true,"status":"saved","sourceCount":0}'::jsonb then
    raise exception 'review-only relation may intentionally clear provenance: %', result;
  end if;
end;
$$;
reset role;

do $$
begin
  if exists (select 1 from public.entity_relation_sources)
     or (select count(*) from public.audit_log where action='world_relation.provenance.replace') <> 3 then
    raise exception 'final review-only clear must be persisted and audited once';
  end if;
end;
$$;
