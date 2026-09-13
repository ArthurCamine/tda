-- CANDIDATE ONLY — not authorized for Production.
-- World entity media foundation v2.
-- Binary bytes live in Cloudflare R2. PostgreSQL owns stable identity,
-- verification/provenance and the semantic entity -> media binding.
-- Browser roles receive no table or RPC grants.

-- A composite entity key lets the media binding enforce campaign scope in the
-- database instead of trusting an application-side UUID lookup alone. `id` is
-- already globally unique; this redundant unique constraint exists solely as a
-- referenced key for the campaign-scoped FK below.
alter table public.entities
  add constraint entities_campaign_id_id_key unique (campaign_id, id);

create table public.media_assets (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references public.campaigns(id) on delete cascade,
  media_kind text not null default 'image' check (media_kind = 'image'),
  role_hint text not null default 'portrait' check (role_hint in ('portrait', 'artwork', 'gallery')),
  status text not null default 'staged' check (status in ('staged', 'verified_public', 'retired')),
  staged_bucket text not null check (staged_bucket in ('tda-media-preview', 'tda-media-private')),
  object_key text not null,
  sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  mime_type text not null check (mime_type in ('image/png', 'image/webp')),
  byte_size bigint not null check (byte_size between 24 and 8388608),
  width integer not null check (width between 1 and 16384),
  height integer not null check (height between 1 and 16384),
  read_back_verified boolean not null default false,
  public_bucket text check (public_bucket is null or public_bucket = 'tda-media-public'),
  public_object_key text,
  public_delivery_verified boolean not null default false,
  public_verified_at timestamptz,
  created_by uuid references public.profiles(id) on delete set null,
  created_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp(),
  unique (campaign_id, id),
  unique (campaign_id, staged_bucket, object_key),
  check (
    object_key ~ '^campaigns/[a-z0-9][a-z0-9-]{0,95}/entities/[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/(portrait|artwork|gallery)/[0-9a-f]{64}[.](png|webp)$'
  ),
  check (
    (status = 'verified_public'
      and read_back_verified
      and public_bucket = 'tda-media-public'
      and public_object_key is not null
      and public_delivery_verified
      and public_verified_at is not null)
    or status <> 'verified_public'
  ),
  check (public_object_key is null or public_object_key = object_key)
);

create index media_assets_campaign_status_idx
  on public.media_assets(campaign_id, status, created_at desc);

create table public.entity_media_bindings (
  campaign_id uuid not null references public.campaigns(id) on delete cascade,
  entity_id uuid not null,
  role text not null default 'portrait' check (role = 'portrait'),
  asset_id uuid not null,
  focal_x numeric(5,4) not null default 0.5 check (focal_x between 0 and 1),
  focal_y numeric(5,4) not null default 0.5 check (focal_y between 0 and 1),
  updated_by uuid references public.profiles(id) on delete set null,
  created_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp(),
  primary key (campaign_id, entity_id, role),
  foreign key (campaign_id, entity_id)
    references public.entities(campaign_id, id) on delete cascade,
  foreign key (campaign_id, asset_id)
    references public.media_assets(campaign_id, id) on delete restrict
);

create index entity_media_bindings_asset_idx
  on public.entity_media_bindings(campaign_id, asset_id);

alter table public.media_assets enable row level security;
alter table public.entity_media_bindings enable row level security;

revoke all on public.media_assets from public, anon, authenticated, service_role;
revoke all on public.entity_media_bindings from public, anon, authenticated, service_role;

grant select, insert, update on public.media_assets to service_role;
grant select, insert, update, delete on public.entity_media_bindings to service_role;

-- Combined publication wrapper. Public media promotion/read-back happens before
-- this RPC. The wrapper validates desired media against the same live lease and
-- draft that the factual/layout publish will consume, then calls the existing
-- atomic publisher and applies bindings in the SAME PostgreSQL transaction.
-- If any later media DML raises, graph/layout publication is rolled back too.
create function public.publish_world_edit_state_with_media_atomic(
  p_auth_user_id uuid,
  p_actor_profile_id uuid,
  p_campaign_slug text,
  p_lease_token uuid,
  p_bindings jsonb
)
returns jsonb
language plpgsql
security invoker
set search_path = pg_catalog, public
as $$
declare
  v_campaign_id uuid;
  v_now timestamptz := clock_timestamp();
  v_draft jsonb;
  v_binding jsonb;
  v_draft_node jsonb;
  v_entity_id uuid;
  v_entity_visibility text;
  v_asset_id uuid;
  v_draft_asset_id uuid;
  v_focal_x numeric(5,4);
  v_focal_y numeric(5,4);
  v_draft_focal_x numeric(5,4);
  v_draft_focal_y numeric(5,4);
  v_expected_key text;
  v_result jsonb;
  v_count integer := 0;
  v_draft_media_count integer := 0;
begin
  if p_auth_user_id is null
     or p_actor_profile_id is null
     or p_campaign_slug is null
     or p_lease_token is null
     or p_bindings is null
     or jsonb_typeof(p_bindings) <> 'array'
     or jsonb_array_length(p_bindings) > 1000
     or not exists (
       select 1 from public.profiles p
       where p.id = p_actor_profile_id and p.auth_user_id = p_auth_user_id
     ) then
    return jsonb_build_object('ok', false, 'reason', 'invalid_payload');
  end if;

  select c.id into v_campaign_id
  from public.campaigns c
  where c.slug = p_campaign_slug
    and exists (
      select 1
      from public.role_assignments a
      join public.role_permissions rp on rp.role_id = a.role_id
      where a.profile_id = p_actor_profile_id
        and a.status = 'active'
        and a.starts_at <= v_now
        and (a.ends_at is null or a.ends_at > v_now)
        and rp.permission_action = 'campaign.content.edit'
        and ((a.scope_type = 'campaign' and a.scope_id = c.slug)
          or (a.scope_type = 'project' and a.scope_id = 'tda'))
    );
  if not found then
    return jsonb_build_object('ok', false, 'reason', 'forbidden');
  end if;

  select lease.draft_graph into v_draft
  from public.world_edit_leases lease
  where lease.campaign_id = v_campaign_id
    and lease.holder_profile_id = p_actor_profile_id
    and lease.lease_token = p_lease_token
    and lease.expires_at > v_now
    and lease.graph_draft_initialized
  for update;
  if not found then
    return jsonb_build_object('ok', false, 'reason', 'lease_lost');
  end if;

  if jsonb_typeof(v_draft) <> 'object'
     or jsonb_typeof(v_draft->'nodes') <> 'array' then
    return jsonb_build_object('ok', false, 'reason', 'invalid_payload');
  end if;

  if exists (
    select 1
    from (
      select value->>'entityId' entity_id, count(*) n
      from jsonb_array_elements(p_bindings)
      group by value->>'entityId'
    ) d
    where d.n > 1
  ) then
    return jsonb_build_object('ok', false, 'reason', 'duplicate');
  end if;

  -- Every explicit media field in the lease draft must have exactly one binding
  -- argument and vice versa. This prevents an internal/service-role caller from
  -- publishing the factual graph while silently dropping or replacing the media
  -- intent that the editor actually saved in the same lease.
  select count(*)::integer into v_draft_media_count
  from jsonb_array_elements(v_draft->'nodes') n(value)
  where n.value ? 'primaryMediaAssetId';
  if jsonb_array_length(p_bindings) <> v_draft_media_count then
    return jsonb_build_object('ok', false, 'reason', 'media_invalid');
  end if;

  -- Validate ALL media intent before the existing publisher mutates or deletes
  -- the lease. Visibility is read from the draft, not the old entity row, so a
  -- private -> public_web transition cannot bind a merely staged asset.
  for v_binding in select value from jsonb_array_elements(p_bindings)
  loop
    if jsonb_typeof(v_binding) <> 'object' then
      return jsonb_build_object('ok', false, 'reason', 'invalid_payload');
    end if;

    begin
      v_entity_id := (v_binding->>'entityId')::uuid;
      v_asset_id := case
        when v_binding->>'assetId' is null or v_binding->>'assetId' = '' then null
        else (v_binding->>'assetId')::uuid
      end;
      v_focal_x := coalesce((v_binding->>'focalX')::numeric, 0.5);
      v_focal_y := coalesce((v_binding->>'focalY')::numeric, 0.5);
    exception when others then
      return jsonb_build_object('ok', false, 'reason', 'invalid_payload');
    end;

    if v_focal_x < 0 or v_focal_x > 1 or v_focal_y < 0 or v_focal_y > 1 then
      return jsonb_build_object('ok', false, 'reason', 'invalid_payload');
    end if;

    select n.value into v_draft_node
    from jsonb_array_elements(v_draft->'nodes') n(value)
    where n.value->>'id' = v_entity_id::text
    limit 1;
    if not found or not (v_draft_node ? 'primaryMediaAssetId') then
      return jsonb_build_object('ok', false, 'reason', 'media_invalid');
    end if;

    begin
      if v_draft_node->'primaryMediaAssetId' = 'null'::jsonb then
        v_draft_asset_id := null;
      elsif jsonb_typeof(v_draft_node->'primaryMediaAssetId') = 'string' then
        v_draft_asset_id := (v_draft_node->>'primaryMediaAssetId')::uuid;
      else
        return jsonb_build_object('ok', false, 'reason', 'invalid_payload');
      end if;

      if v_draft_asset_id is null then
        if v_draft_node ? 'primaryMediaFocalPoint'
           and v_draft_node->'primaryMediaFocalPoint' <> 'null'::jsonb then
          return jsonb_build_object('ok', false, 'reason', 'invalid_payload');
        end if;
        v_draft_focal_x := 0.5;
        v_draft_focal_y := 0.5;
      elsif not (v_draft_node ? 'primaryMediaFocalPoint')
            or v_draft_node->'primaryMediaFocalPoint' = 'null'::jsonb then
        v_draft_focal_x := 0.5;
        v_draft_focal_y := 0.5;
      elsif jsonb_typeof(v_draft_node->'primaryMediaFocalPoint') = 'object'
            and jsonb_typeof(v_draft_node->'primaryMediaFocalPoint'->'x') = 'number'
            and jsonb_typeof(v_draft_node->'primaryMediaFocalPoint'->'y') = 'number' then
        v_draft_focal_x := (v_draft_node->'primaryMediaFocalPoint'->>'x')::numeric;
        v_draft_focal_y := (v_draft_node->'primaryMediaFocalPoint'->>'y')::numeric;
      else
        return jsonb_build_object('ok', false, 'reason', 'invalid_payload');
      end if;
    exception when others then
      return jsonb_build_object('ok', false, 'reason', 'invalid_payload');
    end;

    if v_draft_focal_x < 0 or v_draft_focal_x > 1
       or v_draft_focal_y < 0 or v_draft_focal_y > 1
       or v_asset_id is distinct from v_draft_asset_id
       or v_focal_x is distinct from v_draft_focal_x
       or v_focal_y is distinct from v_draft_focal_y then
      return jsonb_build_object('ok', false, 'reason', 'media_invalid');
    end if;

    v_entity_visibility := v_draft_node->>'visibility';
    if v_entity_visibility not in (
      'private_master','private_players','review_only','public_campaign','public_web'
    ) then
      return jsonb_build_object('ok', false, 'reason', 'invalid_payload');
    end if;

    if v_asset_id is not null then
      select 'campaigns/' || p_campaign_slug || '/entities/' || v_entity_id::text ||
             '/portrait/' || a.sha256 ||
             case when a.mime_type = 'image/png' then '.png' else '.webp' end
      into v_expected_key
      from public.media_assets a
      where a.id = v_asset_id
        and a.campaign_id = v_campaign_id
        and a.role_hint = 'portrait'
        and a.status <> 'retired'
        and a.read_back_verified
        and a.mime_type in ('image/png','image/webp');
      if not found then
        return jsonb_build_object('ok', false, 'reason', 'media_invalid');
      end if;

      if not exists (
        select 1
        from public.media_assets a
        where a.id = v_asset_id
          and a.campaign_id = v_campaign_id
          and a.object_key = v_expected_key
          and (
            v_entity_visibility <> 'public_web'
            or (
              a.status = 'verified_public'
              and a.public_bucket = 'tda-media-public'
              and a.public_object_key = a.object_key
              and a.public_delivery_verified
              and a.public_verified_at is not null
            )
          )
      ) then
        return jsonb_build_object(
          'ok', false,
          'reason', case when v_entity_visibility = 'public_web'
            then 'media_not_verified'
            else 'media_invalid'
          end
        );
      end if;
    end if;
  end loop;

  -- Existing graph/layout/canon/revision guard remains the authority for the
  -- factual publish. It deletes the lease only on success, still inside this
  -- transaction. We deliberately apply bindings only after that success.
  v_result := public.publish_world_edit_state_atomic(
    p_auth_user_id,
    p_actor_profile_id,
    p_campaign_slug,
    p_lease_token
  );
  if coalesce((v_result->>'ok')::boolean, false) is not true then
    return v_result;
  end if;

  for v_binding in select value from jsonb_array_elements(p_bindings)
  loop
    v_entity_id := (v_binding->>'entityId')::uuid;
    v_asset_id := case
      when v_binding->>'assetId' is null or v_binding->>'assetId' = '' then null
      else (v_binding->>'assetId')::uuid
    end;
    v_focal_x := coalesce((v_binding->>'focalX')::numeric, 0.5);
    v_focal_y := coalesce((v_binding->>'focalY')::numeric, 0.5);

    if v_asset_id is null then
      delete from public.entity_media_bindings b
      where b.campaign_id = v_campaign_id
        and b.entity_id = v_entity_id
        and b.role = 'portrait';
    else
      insert into public.entity_media_bindings(
        campaign_id, entity_id, role, asset_id, focal_x, focal_y, updated_by, updated_at
      ) values (
        v_campaign_id, v_entity_id, 'portrait', v_asset_id, v_focal_x, v_focal_y,
        p_actor_profile_id, v_now
      )
      on conflict (campaign_id, entity_id, role) do update set
        asset_id = excluded.asset_id,
        focal_x = excluded.focal_x,
        focal_y = excluded.focal_y,
        updated_by = p_actor_profile_id,
        updated_at = v_now;
    end if;
    v_count := v_count + 1;
  end loop;

  if v_count > 0 then
    insert into public.audit_log(campaign_id, actor_id, action, table_name, old_value, new_value)
    values (
      v_campaign_id,
      p_actor_profile_id,
      'world_entity_media.publish',
      'entity_media_bindings',
      null,
      jsonb_build_object('bindingCount', v_count)
    );
  end if;

  return v_result || jsonb_build_object(
    'mediaStatus', case when v_count > 0 then 'saved' else 'unchanged' end,
    'mediaBindingCount', v_count
  );
end;
$$;

comment on table public.media_assets is
  'Stable media identity and verified R2 object metadata. Binary bytes are not stored in PostgreSQL.';
comment on table public.entity_media_bindings is
  'First-class entity-to-media relation. Private entity portraits may remain staged; public_web portraits require verified public delivery.';

revoke all on function public.publish_world_edit_state_with_media_atomic(uuid,uuid,text,uuid,jsonb)
  from public, anon, authenticated;
grant execute on function public.publish_world_edit_state_with_media_atomic(uuid,uuid,text,uuid,jsonb)
  to service_role;