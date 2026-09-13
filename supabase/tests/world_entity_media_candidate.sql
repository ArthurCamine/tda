\set ON_ERROR_STOP on

-- Synthetic-only contract for the World entity media candidate. This test is
-- executed in the disposable PostgreSQL cluster created by tools/world-layout-db.py;
-- it never connects to Supabase or R2.
do $$
begin
  if not exists (
    select 1 from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relname = 'media_assets' and c.relrowsecurity
  ) or not exists (
    select 1 from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relname = 'entity_media_bindings' and c.relrowsecurity
  ) then
    raise exception 'world media tables must have RLS enabled';
  end if;

  if exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename in ('media_assets', 'entity_media_bindings')
  ) then
    raise exception 'world media tables must remain deny-by-default for browser roles';
  end if;

  if has_table_privilege('anon', 'public.media_assets', 'SELECT')
     or has_table_privilege('authenticated', 'public.media_assets', 'SELECT')
     or has_table_privilege('anon', 'public.entity_media_bindings', 'SELECT')
     or has_table_privilege('authenticated', 'public.entity_media_bindings', 'SELECT') then
    raise exception 'browser roles must not read world media tables directly';
  end if;

  if has_function_privilege(
       'anon',
       'public.publish_world_edit_state_with_media_atomic(uuid,uuid,text,uuid,jsonb)',
       'EXECUTE'
     ) or has_function_privilege(
       'authenticated',
       'public.publish_world_edit_state_with_media_atomic(uuid,uuid,text,uuid,jsonb)',
       'EXECUTE'
     ) then
    raise exception 'browser roles must not execute world media publication';
  end if;
end;
$$;

reset role;
delete from public.entity_media_bindings;
delete from public.media_assets;

insert into public.media_assets(
  id, campaign_id, media_kind, role_hint, status, staged_bucket, object_key,
  sha256, mime_type, byte_size, width, height, read_back_verified
) values (
  '31313131-3131-4313-8313-313131313131',
  '11111111-1111-4111-8111-111111111111',
  'image',
  'portrait',
  'staged',
  'tda-media-preview',
  'campaigns/synthetic-campaign/entities/10101010-1010-4010-8010-101010101010/portrait/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.webp',
  'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
  'image/webp',
  1024,
  512,
  512,
  true
);

-- The binding itself must be campaign-scoped at FK level. An entity from
-- another campaign cannot be paired with this campaign even when its UUID is a
-- perfectly valid canonical entity id.
insert into public.campaigns(id, slug)
values ('51515151-5151-4515-8515-515151515151', 'other-synthetic-campaign');
insert into public.entities(
  id, campaign_id, name, slug, entity_type, status, visibility, summary, aliases
) values (
  '41414141-4141-4414-8414-414141414141',
  '51515151-5151-4515-8515-515151515151',
  'Entidade de outra campanha',
  'entidade-outra-campanha',
  'npc',
  'active',
  'private_master',
  'Fixture de isolamento.',
  '{}'::text[]
);

do $$
begin
  begin
    insert into public.entity_media_bindings(
      campaign_id, entity_id, role, asset_id, focal_x, focal_y
    ) values (
      '11111111-1111-4111-8111-111111111111',
      '41414141-4141-4414-8414-414141414141',
      'portrait',
      '31313131-3131-4313-8313-313131313131',
      0.5,
      0.5
    );
    raise exception 'cross-campaign entity binding unexpectedly succeeded';
  exception when foreign_key_violation then
    null;
  end;
end;
$$;

delete from public.entities where id = '41414141-4141-4414-8414-414141414141';
delete from public.campaigns where id = '51515151-5151-4515-8515-515151515151';

-- A public_web draft cannot consume a merely staged portrait. Rejection must
-- happen before the existing graph publisher consumes the lease.
set role service_role;
do $$
declare
  result jsonb;
  draft jsonb;
  token uuid := '61616161-6161-4616-8616-616161616161';
  asset uuid := '31313131-3131-4313-8313-313131313131';
  hero uuid := '10101010-1010-4010-8010-101010101010';
  bindings jsonb;
begin
  result := public.acquire_world_edit_lease_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token
  );
  if result->>'status' <> 'acquired' then
    raise exception 'media fixture must acquire world lease: %', result;
  end if;

  result := public.acquire_world_graph_draft_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token
  );
  if result->>'ok' <> 'true' then
    raise exception 'media fixture must acquire graph draft: %', result;
  end if;
  draft := result->'draftGraph';

  select jsonb_set(
    draft,
    '{nodes}',
    jsonb_agg(
      case
        when n.value->>'id' = hero::text then
          n.value || jsonb_build_object(
            'primaryMediaAssetId', asset::text,
            'primaryMediaFocalPoint', jsonb_build_object('x', 0.25, 'y', 0.75)
          )
        else n.value
      end
      order by n.ordinality
    ),
    true
  ) into draft
  from jsonb_array_elements(draft->'nodes') with ordinality n(value, ordinality);

  result := public.save_world_graph_draft_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token,
    draft
  );
  if result->>'status' <> 'draft_saved' then
    raise exception 'media fixture draft save failed: %', result;
  end if;

  bindings := jsonb_build_array(jsonb_build_object(
    'entityId', hero::text,
    'assetId', asset::text,
    'focalX', 0.25,
    'focalY', 0.75
  ));

  result := public.publish_world_edit_state_with_media_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token,
    bindings
  );
  if result <> '{"ok":false,"reason":"media_not_verified"}'::jsonb then
    raise exception 'staged public portrait must fail closed: %', result;
  end if;
  if not exists (
    select 1 from public.world_edit_leases
    where campaign_id = '11111111-1111-4111-8111-111111111111'
      and holder_profile_id = '33333333-3333-4333-8333-333333333333'
      and lease_token = token
  ) then
    raise exception 'media_not_verified must preserve the live draft lease';
  end if;
  if exists (select 1 from public.entity_media_bindings) then
    raise exception 'failed media publication must not mutate bindings';
  end if;

  update public.media_assets
  set status = 'verified_public',
      public_bucket = 'tda-media-public',
      public_object_key = object_key,
      public_delivery_verified = true,
      public_verified_at = clock_timestamp(),
      updated_at = clock_timestamp()
  where id = asset;

  result := public.publish_world_edit_state_with_media_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token,
    bindings
  );
  if result->>'ok' <> 'true'
     or result->>'mediaStatus' <> 'saved'
     or (result->>'mediaBindingCount')::integer <> 1 then
    raise exception 'verified media-only publication failed: %', result;
  end if;

  if exists (
    select 1 from public.world_edit_leases
    where campaign_id = '11111111-1111-4111-8111-111111111111'
  ) then
    raise exception 'successful media publication must consume the lease';
  end if;
  if not exists (
    select 1 from public.entity_media_bindings b
    where b.campaign_id = '11111111-1111-4111-8111-111111111111'
      and b.entity_id = hero
      and b.asset_id = asset
      and b.role = 'portrait'
      and b.focal_x = 0.25
      and b.focal_y = 0.75
  ) then
    raise exception 'verified media publication did not persist exact binding/focal point';
  end if;
end;
$$;
reset role;

-- The wrapper must not be a generic service-role media mutation endpoint. Its
-- p_bindings argument has to match explicit media intent saved in that lease.
set role service_role;
do $$
declare
  result jsonb;
  token uuid := '71717171-7171-4717-8717-717171717171';
  asset uuid := '31313131-3131-4313-8313-313131313131';
  hero uuid := '10101010-1010-4010-8010-101010101010';
begin
  result := public.acquire_world_edit_lease_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token
  );
  if result->>'status' <> 'acquired' then
    raise exception 'binding-scope fixture must acquire lease: %', result;
  end if;

  result := public.acquire_world_graph_draft_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token
  );
  if result->>'ok' <> 'true' then
    raise exception 'binding-scope fixture must initialize draft: %', result;
  end if;

  result := public.publish_world_edit_state_with_media_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token,
    jsonb_build_array(jsonb_build_object(
      'entityId', hero::text,
      'assetId', asset::text,
      'focalX', 0.25,
      'focalY', 0.75
    ))
  );
  if result <> '{"ok":false,"reason":"media_invalid"}'::jsonb then
    raise exception 'bindings absent from lease draft must be rejected: %', result;
  end if;

  if not exists (
    select 1 from public.world_edit_leases
    where campaign_id = '11111111-1111-4111-8111-111111111111'
      and lease_token = token
  ) then
    raise exception 'media_invalid must preserve the draft lease';
  end if;

  result := public.release_world_edit_lease_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'synthetic-campaign',
    token
  );
  if result->>'ok' <> 'true' then
    raise exception 'binding-scope fixture cleanup failed: %', result;
  end if;
end;
$$;
reset role;

-- Keep subsequent World concurrency checks isolated from this candidate suite.
delete from public.entity_media_bindings;
delete from public.media_assets;
delete from public.audit_log where action = 'world_entity_media.publish';

select 'WORLD_ENTITY_MEDIA_DATABASE_OK synthetic=true rls=true campaign_scope=true draft_binding=true fail_closed=true';