\set ON_ERROR_STOP on

-- The lease/draft boundary is server-only and deliberately separate from the
-- published layout snapshot. This suite runs after world_layout_snapshot_atomic.sql.
do $$
begin
  if not exists (
    select 1
    from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public'
      and c.relname = 'world_edit_leases'
      and c.relrowsecurity
  ) then
    raise exception 'world edit lease table must have RLS enabled';
  end if;

  if exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'world_edit_leases'
  ) then
    raise exception 'world edit lease table must remain deny-by-default with no browser policy';
  end if;

  if not exists (
    select 1
    from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public'
      and c.relname = 'world_edit_drafts'
      and c.relrowsecurity
  ) or exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'world_edit_drafts'
  ) then
    raise exception 'durable World drafts must be RLS deny-by-default';
  end if;

  if has_table_privilege('anon', 'public.world_edit_drafts', 'SELECT')
     or has_table_privilege('authenticated', 'public.world_edit_drafts', 'SELECT')
     or not has_table_privilege('service_role', 'public.world_edit_drafts', 'SELECT')
     or not has_table_privilege('service_role', 'public.world_edit_drafts', 'INSERT')
     or not has_table_privilege('service_role', 'public.world_edit_drafts', 'UPDATE')
     or has_table_privilege('service_role', 'public.world_edit_drafts', 'DELETE') then
    raise exception 'durable World draft grants must stay server-only and append/update oriented';
  end if;

  if has_table_privilege('anon', 'public.world_edit_leases', 'SELECT')
     or has_table_privilege('authenticated', 'public.world_edit_leases', 'SELECT') then
    raise exception 'browser roles must not read world edit leases';
  end if;

  if not has_table_privilege('service_role', 'public.world_edit_leases', 'SELECT')
     or not has_table_privilege('service_role', 'public.world_edit_leases', 'INSERT')
     or not has_table_privilege('service_role', 'public.world_edit_leases', 'UPDATE')
     or not has_table_privilege('service_role', 'public.world_edit_leases', 'DELETE') then
    raise exception 'service_role must have the four lease table privileges it needs';
  end if;

  if has_table_privilege('service_role', 'public.world_edit_leases', 'TRUNCATE')
     or has_table_privilege('service_role', 'public.world_edit_leases', 'REFERENCES')
     or has_table_privilege('service_role', 'public.world_edit_leases', 'TRIGGER') then
    raise exception 'service_role must not inherit broad default privileges on world edit leases';
  end if;

  if has_function_privilege('anon', 'public.acquire_world_edit_lease_atomic(uuid,uuid,text,uuid)', 'EXECUTE')
     or has_function_privilege('authenticated', 'public.acquire_world_edit_lease_atomic(uuid,uuid,text,uuid)', 'EXECUTE')
     or has_function_privilege('anon', 'public.renew_world_edit_lease_atomic(uuid,uuid,text,uuid)', 'EXECUTE')
     or has_function_privilege('authenticated', 'public.renew_world_edit_lease_atomic(uuid,uuid,text,uuid)', 'EXECUTE')
     or has_function_privilege('anon', 'public.save_world_edit_layout_draft_atomic(uuid,uuid,text,uuid,jsonb)', 'EXECUTE')
     or has_function_privilege('authenticated', 'public.save_world_edit_layout_draft_atomic(uuid,uuid,text,uuid,jsonb)', 'EXECUTE')
     or has_function_privilege('anon', 'public.publish_world_edit_layout_atomic(uuid,uuid,text,uuid)', 'EXECUTE')
     or has_function_privilege('authenticated', 'public.publish_world_edit_layout_atomic(uuid,uuid,text,uuid)', 'EXECUTE')
     or has_function_privilege('anon', 'public.release_world_edit_lease_atomic(uuid,uuid,text,uuid)', 'EXECUTE')
     or has_function_privilege('authenticated', 'public.release_world_edit_lease_atomic(uuid,uuid,text,uuid)', 'EXECUTE')
     or has_function_privilege('anon', 'public.discard_world_edit_lease_atomic(uuid,uuid,text,uuid)', 'EXECUTE')
     or has_function_privilege('authenticated', 'public.discard_world_edit_lease_atomic(uuid,uuid,text,uuid)', 'EXECUTE') then
    raise exception 'browser roles must not execute world edit lease RPCs';
  end if;

  if not has_function_privilege('service_role', 'public.acquire_world_edit_lease_atomic(uuid,uuid,text,uuid)', 'EXECUTE')
     or not has_function_privilege('service_role', 'public.renew_world_edit_lease_atomic(uuid,uuid,text,uuid)', 'EXECUTE')
     or not has_function_privilege('service_role', 'public.save_world_edit_layout_draft_atomic(uuid,uuid,text,uuid,jsonb)', 'EXECUTE')
     or not has_function_privilege('service_role', 'public.publish_world_edit_layout_atomic(uuid,uuid,text,uuid)', 'EXECUTE')
     or not has_function_privilege('service_role', 'public.release_world_edit_lease_atomic(uuid,uuid,text,uuid)', 'EXECUTE')
     or not has_function_privilege('service_role', 'public.discard_world_edit_lease_atomic(uuid,uuid,text,uuid)', 'EXECUTE') then
    raise exception 'service_role must execute every world edit lease RPC';
  end if;
end;
$$;

insert into public.profiles(id, auth_user_id, display_name)
values (
  '77777777-7777-4777-8777-777777777777',
  '88888888-8888-4888-8888-888888888888',
  'Editor Dois'
);

insert into public.role_assignments(profile_id, role_id, scope_type, scope_id, status, starts_at)
values (
  '77777777-7777-4777-8777-777777777777',
  '55555555-5555-4555-8555-555555555555',
  'campaign',
  'synthetic-campaign',
  'active',
  now() - interval '1 minute'
);

set role service_role;
do $$
declare
  result jsonb;
  token_a uuid := 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  token_b uuid := 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
begin
  result := public.acquire_world_edit_lease_atomic(
    '99999999-9999-4999-8999-999999999999',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token_a
  );
  if result <> '{"ok":false,"reason":"forbidden"}'::jsonb then
    raise exception 'unbound identity must not acquire a world edit lease: %', result;
  end if;

  result := public.acquire_world_edit_lease_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token_a
  );
  if result->>'ok' <> 'true'
     or result->>'status' <> 'acquired'
     or (result->>'baseRevision')::bigint <> 2
     or result->'draftPositions' <> '{"node-a":{"x":200,"y":-50},"node-b":{"x":-320,"y":75}}'::jsonb
     or result->>'expiresAt' is null then
    raise exception 'initial lease must start from the published revision: %', result;
  end if;

  result := public.acquire_world_edit_lease_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token_a
  );
  if result->>'ok' <> 'true' or result->>'status' <> 'resumed' then
    raise exception 'same tab token must resume its lease: %', result;
  end if;

  result := public.acquire_world_edit_lease_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token_b
  );
  if result->>'ok' <> 'false'
     or result->>'reason' <> 'busy'
     or result->>'sameActor' <> 'true' then
    raise exception 'same actor in a different tab must be busy: %', result;
  end if;

  result := public.acquire_world_edit_lease_atomic(
    '88888888-8888-4888-8888-888888888888',
    '77777777-7777-4777-8777-777777777777',
    'synthetic-campaign',
    token_b
  );
  if result->>'ok' <> 'false'
     or result->>'reason' <> 'busy'
     or result->>'sameActor' <> 'false'
     or result->>'holderLabel' <> 'Editor Um' then
    raise exception 'second editor must see a busy lease without taking it over: %', result;
  end if;

  result := public.renew_world_edit_lease_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token_b
  );
  if result <> '{"ok":false,"reason":"lease_lost"}'::jsonb then
    raise exception 'wrong token must not renew another tab lease: %', result;
  end if;

  result := public.save_world_edit_layout_draft_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token_a,
    '{"node-a":{"x":260,"y":-40},"node-b":{"x":-300,"y":90}}'::jsonb
  );
  if result->>'ok' <> 'true' or result->>'status' <> 'draft_saved' then
    raise exception 'valid private draft must save: %', result;
  end if;
  if (select revision from public.world_layout_snapshots) <> 2
     or (select draft_positions from public.world_edit_leases) <>
        '{"node-a":{"x":260,"y":-40},"node-b":{"x":-300,"y":90}}'::jsonb then
    raise exception 'draft save must not mutate the published snapshot';
  end if;

  result := public.save_world_edit_layout_draft_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token_a,
    '{"node-a":{"x":9000,"y":0}}'::jsonb
  );
  if result <> '{"ok":false,"reason":"invalid_payload"}'::jsonb then
    raise exception 'invalid draft coordinates must fail closed: %', result;
  end if;

  result := public.publish_world_edit_layout_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token_b
  );
  if result <> '{"ok":false,"reason":"lease_lost"}'::jsonb then
    raise exception 'wrong token must not publish another tab draft: %', result;
  end if;

  result := public.publish_world_edit_layout_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token_a
  );
  if result <> '{"ok":true,"status":"saved","revision":3}'::jsonb then
    raise exception 'lease holder must publish through the atomic snapshot boundary: %', result;
  end if;
  if exists (select 1 from public.world_edit_leases)
     or (select revision from public.world_layout_snapshots) <> 3
     or (select positions from public.world_layout_snapshots) <>
        '{"node-a":{"x":260,"y":-40},"node-b":{"x":-300,"y":90}}'::jsonb
     or (select count(*) from public.audit_log where action = 'world_layout.update') <> 3
     or not exists (
       select 1
       from public.world_edit_drafts
       where owner_profile_id = '33333333-3333-4333-8333-333333333333'
         and lease_token = token_a
         and status = 'published'
         and published_layout_revision = 3
         and last_publish_error is null
     ) then
    raise exception 'publish must update snapshot/audit, persist its receipt and release the lease atomically';
  end if;
end;
$$;
reset role;

-- Reload/recovery keeps the private draft, while a stale published revision is
-- surfaced as conflict without destroying that draft.
set role service_role;
do $$
declare
  result jsonb;
  token_a uuid := 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  token_b uuid := 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
begin
  result := public.acquire_world_edit_lease_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token_a
  );
  if result->>'status' <> 'acquired'
     or (result->>'baseRevision')::bigint <> 3
     or result->>'previousPublishConfirmed' <> 'true'
     or (result->>'previousPublishedLayoutRevision')::bigint <> 3 then
    raise exception 'fresh lease must observe revision 3 and reconcile the previous publish receipt: %', result;
  end if;

  result := public.save_world_edit_layout_draft_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token_a,
    '{"node-a":{"x":310,"y":-10}}'::jsonb
  );
  if result->>'status' <> 'draft_saved' then
    raise exception 'draft must save before recovery test: %', result;
  end if;
end;
$$;
reset role;

-- Simulate wall-clock expiry while keeping the row internally valid: a real lease
-- naturally expires after acquisition, it does not move expires_at before acquired_at.
update public.world_edit_leases
set acquired_at = acquired_at - interval '2 minutes',
    heartbeat_at = heartbeat_at - interval '2 minutes',
    draft_updated_at = draft_updated_at - interval '2 minutes',
    expires_at = clock_timestamp() - interval '1 second';

set role service_role;
do $$
declare
  result jsonb;
  token_a uuid := 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  token_b uuid := 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
begin
  result := public.acquire_world_edit_lease_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token_b
  );
  if result->>'ok' <> 'true'
     or result->>'status' <> 'recovered'
     or result->'draftPositions' <> '{"node-a":{"x":310,"y":-10}}'::jsonb then
    raise exception 'same editor must recover its expired private draft: %', result;
  end if;

  result := public.release_world_edit_lease_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token_b
  );
  if result <> '{"ok":true,"status":"released"}'::jsonb
     or exists (select 1 from public.world_edit_leases)
     or not exists (
       select 1 from public.world_edit_drafts
       where owner_profile_id = '33333333-3333-4333-8333-333333333333'
         and status = 'active'
         and draft_positions = '{"node-a":{"x":310,"y":-10}}'::jsonb
     ) then
    raise exception 'ordinary release must preserve the durable draft: %', result;
  end if;

  result := public.acquire_world_edit_lease_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token_a
  );
  if result->>'ok' <> 'true'
     or result->>'status' <> 'recovered'
     or result->>'recoverySource' <> 'durable'
     or result->'draftPositions' <> '{"node-a":{"x":310,"y":-10}}'::jsonb then
    raise exception 'same editor must recover a durable draft after the lease row is gone: %', result;
  end if;

  result := public.discard_world_edit_lease_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token_a
  );
  if result <> '{"ok":true,"status":"discarded"}'::jsonb
     or exists (select 1 from public.world_edit_leases)
     or exists (
       select 1 from public.world_edit_drafts
       where owner_profile_id = '33333333-3333-4333-8333-333333333333'
         and status = 'active'
     )
     or not exists (
       select 1 from public.world_edit_drafts
       where owner_profile_id = '33333333-3333-4333-8333-333333333333'
         and status = 'discarded'
     ) then
    raise exception 'explicit discard must tombstone the draft and release the lease: %', result;
  end if;
end;
$$;
reset role;

set role service_role;
do $$
declare
  result jsonb;
  token_a uuid := 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
begin
  result := public.acquire_world_edit_lease_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token_a
  );
  if result->>'status' <> 'acquired' or (result->>'baseRevision')::bigint <> 3 then
    raise exception 'conflict lease must start from revision 3: %', result;
  end if;

  result := public.save_world_layout_snapshot_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    3,
    '{"node-a":{"x":400,"y":20}}'::jsonb
  );
  if result <> '{"ok":true,"status":"saved","revision":4}'::jsonb then
    raise exception 'synthetic external publish must advance revision: %', result;
  end if;

  result := public.save_world_edit_layout_draft_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token_a,
    '{"node-a":{"x":500,"y":30}}'::jsonb
  );
  if result <> '{"ok":false,"reason":"conflict","revision":4}'::jsonb
     or (select base_layout_revision from public.world_edit_leases) <> 3
     or (select draft_positions from public.world_edit_leases) <>
        '{"node-a":{"x":500,"y":30}}'::jsonb then
    raise exception 'stale editor must keep its draft and report the current revision: %', result;
  end if;

  result := public.publish_world_edit_layout_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token_a
  );
  if result <> '{"ok":false,"reason":"conflict","revision":4}'::jsonb
     or not exists (select 1 from public.world_edit_leases)
     or (select revision from public.world_layout_snapshots) <> 4 then
    raise exception 'conflicted publish must preserve lease/draft and published winner: %', result;
  end if;

  result := public.release_world_edit_lease_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token_a
  );
  if result->>'status' <> 'released' or exists (select 1 from public.world_edit_leases) then
    raise exception 'conflicted editor must be able to discard its preserved draft: %', result;
  end if;
end;
$$;
reset role;
