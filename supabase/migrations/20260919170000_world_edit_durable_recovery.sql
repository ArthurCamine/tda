-- Durable World edit recovery.
--
-- The exclusive lease serializes writers, but it is intentionally short-lived and may
-- be deleted/reassigned. A long editing session must therefore not depend on the lease
-- row itself for durability. This migration keeps a server-only recovery checkpoint per
-- editing token and teaches lease acquisition to restore the latest compatible draft.
-- Explicit discard is separate from ordinary release and preserves a tombstoned copy.

create table public.world_edit_drafts (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references public.campaigns(id) on delete cascade,
  owner_profile_id uuid not null references public.profiles(id) on delete cascade,
  lease_token uuid not null,
  base_layout_revision bigint not null default 0 check (base_layout_revision >= 0),
  base_graph_revision bigint not null default 0 check (base_graph_revision >= 0),
  draft_positions jsonb not null default '{}'::jsonb check (jsonb_typeof(draft_positions) = 'object'),
  draft_graph jsonb not null default '{}'::jsonb check (jsonb_typeof(draft_graph) = 'object'),
  graph_draft_initialized boolean not null default false,
  status text not null default 'active'
    check (status in ('active','published','discarded','superseded')),
  last_publish_attempt_at timestamptz,
  last_publish_error text,
  published_graph_revision bigint check (published_graph_revision is null or published_graph_revision >= 0),
  published_layout_revision bigint check (published_layout_revision is null or published_layout_revision >= 0),
  created_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp(),
  unique(campaign_id, owner_profile_id, lease_token)
);

create index world_edit_drafts_owner_latest_idx
  on public.world_edit_drafts(campaign_id, owner_profile_id, updated_at desc);

create index world_edit_drafts_active_idx
  on public.world_edit_drafts(campaign_id, owner_profile_id, updated_at desc)
  where status = 'active';

-- Do not create a rollout gap: any lease that already exists when this migration
-- lands may contain the only copy of an editor's saved work. Seed a durable
-- checkpoint before changing acquisition/release behavior.
insert into public.world_edit_drafts(
  campaign_id,
  owner_profile_id,
  lease_token,
  base_layout_revision,
  base_graph_revision,
  draft_positions,
  draft_graph,
  graph_draft_initialized,
  status,
  created_at,
  updated_at
)
select
  lease.campaign_id,
  lease.holder_profile_id,
  lease.lease_token,
  lease.base_layout_revision,
  lease.base_graph_revision,
  lease.draft_positions,
  lease.draft_graph,
  lease.graph_draft_initialized,
  'active',
  lease.acquired_at,
  lease.draft_updated_at
from public.world_edit_leases lease
on conflict (campaign_id, owner_profile_id, lease_token) do update set
  base_layout_revision = excluded.base_layout_revision,
  base_graph_revision = excluded.base_graph_revision,
  draft_positions = excluded.draft_positions,
  draft_graph = excluded.draft_graph,
  graph_draft_initialized = excluded.graph_draft_initialized,
  status = 'active',
  updated_at = excluded.updated_at;

alter table public.world_edit_drafts enable row level security;
revoke all on public.world_edit_drafts from public, anon, authenticated, service_role;
grant select, insert, update on public.world_edit_drafts to service_role;

create or replace function public.checkpoint_world_edit_draft_from_lease()
returns trigger
language plpgsql
security invoker
set search_path = pg_catalog, public
as $$
begin
  -- A new token means the editor deliberately continued from another session.
  -- Preserve older checkpoints as history instead of overwriting or deleting them.
  update public.world_edit_drafts draft
  set status = 'superseded',
      updated_at = clock_timestamp()
  where draft.campaign_id = new.campaign_id
    and draft.owner_profile_id = new.holder_profile_id
    and draft.status = 'active'
    and draft.lease_token <> new.lease_token;

  insert into public.world_edit_drafts(
    campaign_id,
    owner_profile_id,
    lease_token,
    base_layout_revision,
    base_graph_revision,
    draft_positions,
    draft_graph,
    graph_draft_initialized,
    status,
    last_publish_error,
    updated_at
  ) values (
    new.campaign_id,
    new.holder_profile_id,
    new.lease_token,
    new.base_layout_revision,
    new.base_graph_revision,
    new.draft_positions,
    new.draft_graph,
    new.graph_draft_initialized,
    'active',
    null,
    new.draft_updated_at
  )
  on conflict (campaign_id, owner_profile_id, lease_token) do update set
    base_layout_revision = excluded.base_layout_revision,
    base_graph_revision = excluded.base_graph_revision,
    draft_positions = excluded.draft_positions,
    draft_graph = excluded.draft_graph,
    graph_draft_initialized = excluded.graph_draft_initialized,
    status = 'active',
    last_publish_error = null,
    updated_at = excluded.updated_at;

  return new;
end;
$$;

drop trigger if exists world_edit_lease_durable_checkpoint on public.world_edit_leases;
create trigger world_edit_lease_durable_checkpoint
after update on public.world_edit_leases
for each row
when (
  old.holder_profile_id = new.holder_profile_id
  and old.draft_updated_at is distinct from new.draft_updated_at
)
execute function public.checkpoint_world_edit_draft_from_lease();

revoke all on function public.checkpoint_world_edit_draft_from_lease()
  from public, anon, authenticated;
grant execute on function public.checkpoint_world_edit_draft_from_lease()
  to service_role;

-- Graph-only autosaves historically refreshed the lease heartbeat without moving
-- draft_updated_at, which meant a durability trigger could not distinguish them.
-- Preserve the current RPC definition and add the missing draft timestamp update.
do $migration$
declare
  v_definition text;
  v_old text := E'set draft_graph = p_draft,\n      heartbeat_at = v_now,';
  v_new text := E'set draft_graph = p_draft,\n      draft_updated_at = v_now,\n      heartbeat_at = v_now,';
begin
  select pg_get_functiondef(
    'public.save_world_graph_draft_atomic(uuid,uuid,text,uuid,jsonb)'::regprocedure
  ) into v_definition;

  if v_definition is null then
    raise exception 'save_world_graph_draft_atomic is missing';
  end if;

  if strpos(v_definition, 'draft_updated_at = v_now') = 0 then
    if strpos(v_definition, v_old) = 0 then
      raise exception 'unexpected World graph draft save definition';
    end if;
    v_definition := replace(v_definition, v_old, v_new);
    execute v_definition;
  end if;
end;
$migration$;

create or replace function public.acquire_world_edit_lease_atomic(
  p_auth_user_id uuid,
  p_actor_profile_id uuid,
  p_campaign_slug text,
  p_lease_token uuid
)
returns jsonb
language plpgsql
security invoker
set search_path = pg_catalog, public
as $$
declare
  v_campaign_id uuid;
  v_existing public.world_edit_leases%rowtype;
  v_recovery public.world_edit_drafts%rowtype;
  v_previous_receipt public.world_edit_drafts%rowtype;
  v_layout_revision bigint := 0;
  v_layout_positions jsonb := '{}'::jsonb;
  v_graph_revision bigint := 0;
  v_current_graph jsonb := '{}'::jsonb;
  v_now timestamptz := clock_timestamp();
  v_holder_label text;
  v_recovered boolean := false;
  v_stale_recovery boolean := false;
  v_same_as_published boolean := false;
begin
  if p_auth_user_id is null
     or p_actor_profile_id is null
     or p_lease_token is null
     or p_campaign_slug is null
     or p_campaign_slug !~ '^[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?$'
     or not exists (
       select 1
       from public.profiles p
       where p.id = p_actor_profile_id
         and p.auth_user_id = p_auth_user_id
     ) then
    return jsonb_build_object('ok', false, 'reason', 'forbidden');
  end if;

  select c.id
  into v_campaign_id
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
        and rp.permission_action = 'campaign.world.layout.edit'
        and (
          (a.scope_type = 'campaign' and a.scope_id = c.slug)
          or (a.scope_type = 'project' and a.scope_id = 'tda')
        )
    );

  if not found then
    return jsonb_build_object('ok', false, 'reason', 'forbidden');
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(v_campaign_id::text, 0)
  );
  v_now := clock_timestamp();

  select snapshot.revision, snapshot.positions
  into v_layout_revision, v_layout_positions
  from public.world_layout_snapshots snapshot
  where snapshot.campaign_id = v_campaign_id
    and snapshot.view_name = 'overview';

  if not found then
    v_layout_revision := 0;
    v_layout_positions := '{}'::jsonb;
  end if;

  select h.revision
  into v_graph_revision
  from public.world_graph_heads h
  where h.campaign_id = v_campaign_id;

  if not found then
    v_graph_revision := 0;
  end if;

  v_current_graph := public.world_graph_snapshot_json(v_campaign_id);

  select lease.*
  into v_existing
  from public.world_edit_leases lease
  where lease.campaign_id = v_campaign_id
  for update;

  if found then
    if v_existing.expires_at > v_now then
      if v_existing.holder_profile_id = p_actor_profile_id
         and v_existing.lease_token = p_lease_token then
        update public.world_edit_leases lease
        set heartbeat_at = v_now,
            expires_at = v_now + interval '60 seconds'
        where lease.campaign_id = v_campaign_id
        returning * into v_existing;

        return jsonb_build_object(
          'ok', true,
          'status', 'resumed',
          'baseRevision', v_existing.base_layout_revision,
          'draftPositions', v_existing.draft_positions,
          'expiresAt', v_existing.expires_at,
          'staleRecovery', (
            v_existing.base_layout_revision <> v_layout_revision
            or (
              v_existing.graph_draft_initialized
              and v_existing.base_graph_revision <> v_graph_revision
            )
          )
        );
      end if;

      select p.display_name
      into v_holder_label
      from public.profiles p
      where p.id = v_existing.holder_profile_id;

      return jsonb_build_object(
        'ok', false,
        'reason', 'busy',
        'holderLabel', coalesce(v_holder_label, 'Outra pessoa'),
        'sameActor', v_existing.holder_profile_id = p_actor_profile_id,
        'expiresAt', v_existing.expires_at
      );
    end if;

    if v_existing.holder_profile_id = p_actor_profile_id then
      update public.world_edit_leases lease
      set lease_token = p_lease_token,
          heartbeat_at = v_now,
          expires_at = v_now + interval '60 seconds'
      where lease.campaign_id = v_campaign_id
      returning * into v_existing;

      return jsonb_build_object(
        'ok', true,
        'status', 'recovered',
        'baseRevision', v_existing.base_layout_revision,
        'draftPositions', v_existing.draft_positions,
        'expiresAt', v_existing.expires_at,
        'recoverySource', 'lease',
        'staleRecovery', (
          v_existing.base_layout_revision <> v_layout_revision
          or (
            v_existing.graph_draft_initialized
            and v_existing.base_graph_revision <> v_graph_revision
          )
        )
      );
    end if;

    update public.world_edit_leases lease
    set holder_profile_id = p_actor_profile_id,
        lease_token = p_lease_token,
        base_layout_revision = v_layout_revision,
        draft_positions = v_layout_positions,
        acquired_at = v_now,
        heartbeat_at = v_now,
        draft_updated_at = v_now,
        expires_at = v_now + interval '60 seconds'
    where lease.campaign_id = v_campaign_id
    returning * into v_existing;
  else
    insert into public.world_edit_leases(
      campaign_id,
      holder_profile_id,
      lease_token,
      base_layout_revision,
      draft_positions,
      acquired_at,
      heartbeat_at,
      draft_updated_at,
      expires_at
    )
    values (
      v_campaign_id,
      p_actor_profile_id,
      p_lease_token,
      v_layout_revision,
      v_layout_positions,
      v_now,
      v_now,
      v_now,
      v_now + interval '60 seconds'
    )
    returning * into v_existing;
  end if;

  -- If this exact client token already committed successfully, that receipt
  -- outranks any older active checkpoint. This is the lost-response case: the
  -- client did not hear "success", but the database can prove the commit.
  select draft.*
  into v_previous_receipt
  from public.world_edit_drafts draft
  where draft.campaign_id = v_campaign_id
    and draft.owner_profile_id = p_actor_profile_id
    and draft.lease_token = p_lease_token
    and draft.status = 'published'
  order by draft.updated_at desc
  limit 1;

  if found then
    update public.world_edit_drafts draft
    set status = 'superseded',
        updated_at = v_now
    where draft.campaign_id = v_campaign_id
      and draft.owner_profile_id = p_actor_profile_id
      and draft.status = 'active';

    return jsonb_build_object(
      'ok', true,
      'status', 'acquired',
      'baseRevision', v_existing.base_layout_revision,
      'draftPositions', v_existing.draft_positions,
      'expiresAt', v_existing.expires_at,
      'recoverySource', null,
      'staleRecovery', false,
      'previousPublishConfirmed', true,
      'previousPublishedGraphRevision', v_previous_receipt.published_graph_revision,
      'previousPublishedLayoutRevision', v_previous_receipt.published_layout_revision
    );
  end if;

  select draft.*
  into v_recovery
  from public.world_edit_drafts draft
  where draft.campaign_id = v_campaign_id
    and draft.owner_profile_id = p_actor_profile_id
    and draft.status = 'active'
  order by draft.updated_at desc
  limit 1;

  if found then
    v_same_as_published :=
      v_recovery.draft_positions = v_layout_positions
      and (
        not v_recovery.graph_draft_initialized
        or (v_recovery.draft_graph - 'revision') = (v_current_graph - 'revision')
      );

    if v_same_as_published then
      update public.world_edit_drafts draft
      set status = 'published',
          published_graph_revision = v_graph_revision,
          published_layout_revision = v_layout_revision,
          last_publish_error = null,
          updated_at = v_now
      where draft.id = v_recovery.id;
    elsif v_recovery.base_layout_revision = v_layout_revision
       and (
         not v_recovery.graph_draft_initialized
         or v_recovery.base_graph_revision = v_graph_revision
       ) then
      update public.world_edit_leases lease
      set base_layout_revision = v_recovery.base_layout_revision,
          draft_positions = v_recovery.draft_positions,
          base_graph_revision = v_recovery.base_graph_revision,
          draft_graph = v_recovery.draft_graph,
          graph_draft_initialized = v_recovery.graph_draft_initialized,
          draft_updated_at = v_recovery.updated_at,
          heartbeat_at = v_now,
          expires_at = v_now + interval '60 seconds'
      where lease.campaign_id = v_campaign_id
      returning * into v_existing;
      v_recovered := true;
    else
      v_stale_recovery := true;
    end if;
  end if;

  return jsonb_build_object(
    'ok', true,
    'status', case when v_recovered then 'recovered' else 'acquired' end,
    'baseRevision', v_existing.base_layout_revision,
    'draftPositions', v_existing.draft_positions,
    'expiresAt', v_existing.expires_at,
    'recoverySource', case when v_recovered then 'durable' else null end,
    'staleRecovery', v_stale_recovery,
    'previousPublishConfirmed', false,
    'previousPublishedGraphRevision', null,
    'previousPublishedLayoutRevision', null
  );
end;
$$;

create or replace function public.discard_world_edit_lease_atomic(
  p_auth_user_id uuid,
  p_actor_profile_id uuid,
  p_campaign_slug text,
  p_lease_token uuid
)
returns jsonb
language plpgsql
security invoker
set search_path = pg_catalog, public
as $$
declare
  v_campaign_id uuid;
  v_lease public.world_edit_leases%rowtype;
  v_now timestamptz := clock_timestamp();
begin
  if p_auth_user_id is null
     or p_actor_profile_id is null
     or p_lease_token is null
     or not exists (
       select 1
       from public.profiles p
       where p.id = p_actor_profile_id
         and p.auth_user_id = p_auth_user_id
     ) then
    return jsonb_build_object('ok', false, 'reason', 'forbidden');
  end if;

  select c.id
  into v_campaign_id
  from public.campaigns c
  where c.slug = p_campaign_slug;

  if not found then
    return jsonb_build_object('ok', false, 'reason', 'not_found');
  end if;

  select lease.*
  into v_lease
  from public.world_edit_leases lease
  where lease.campaign_id = v_campaign_id
    and lease.holder_profile_id = p_actor_profile_id
    and lease.lease_token = p_lease_token
  for update;

  if not found then
    return jsonb_build_object('ok', false, 'reason', 'lease_lost');
  end if;

  update public.world_edit_drafts draft
  set status = 'discarded',
      updated_at = v_now
  where draft.campaign_id = v_campaign_id
    and draft.owner_profile_id = p_actor_profile_id
    and draft.status = 'active';

  insert into public.world_edit_drafts(
    campaign_id,
    owner_profile_id,
    lease_token,
    base_layout_revision,
    base_graph_revision,
    draft_positions,
    draft_graph,
    graph_draft_initialized,
    status,
    updated_at
  ) values (
    v_campaign_id,
    p_actor_profile_id,
    p_lease_token,
    v_lease.base_layout_revision,
    v_lease.base_graph_revision,
    v_lease.draft_positions,
    v_lease.draft_graph,
    v_lease.graph_draft_initialized,
    'discarded',
    v_now
  )
  on conflict (campaign_id, owner_profile_id, lease_token) do update set
    base_layout_revision = excluded.base_layout_revision,
    base_graph_revision = excluded.base_graph_revision,
    draft_positions = excluded.draft_positions,
    draft_graph = excluded.draft_graph,
    graph_draft_initialized = excluded.graph_draft_initialized,
    status = 'discarded',
    updated_at = excluded.updated_at;

  delete from public.world_edit_leases lease
  where lease.campaign_id = v_campaign_id
    and lease.holder_profile_id = p_actor_profile_id
    and lease.lease_token = p_lease_token;

  return jsonb_build_object('ok', true, 'status', 'discarded');
end;
$$;


-- Publish confirmation must be part of the same transaction as canonical state.
-- A lost HTTP response can then be reconciled by lease token without guessing
-- whether the commit happened.
do $migration$
declare
  v_definition text;
  v_old text := $needle$
  if coalesce((v_result->>'ok')::boolean, false) then
    delete from public.world_edit_leases lease
    where lease.campaign_id = v_campaign_id
      and lease.holder_profile_id = p_actor_profile_id
      and lease.lease_token = p_lease_token;
  end if;
$needle$;
  v_new text := $replacement$
  if coalesce((v_result->>'ok')::boolean, false) then
    insert into public.world_edit_drafts(
      campaign_id,
      owner_profile_id,
      lease_token,
      base_layout_revision,
      base_graph_revision,
      draft_positions,
      draft_graph,
      graph_draft_initialized,
      status,
      last_publish_attempt_at,
      last_publish_error,
      published_layout_revision,
      updated_at
    ) values (
      v_campaign_id,
      p_actor_profile_id,
      p_lease_token,
      v_existing.base_layout_revision,
      v_existing.base_graph_revision,
      v_existing.draft_positions,
      v_existing.draft_graph,
      v_existing.graph_draft_initialized,
      'published',
      v_now,
      null,
      (v_result->>'revision')::bigint,
      v_now
    )
    on conflict (campaign_id, owner_profile_id, lease_token) do update set
      base_layout_revision = excluded.base_layout_revision,
      base_graph_revision = excluded.base_graph_revision,
      draft_positions = excluded.draft_positions,
      draft_graph = excluded.draft_graph,
      graph_draft_initialized = excluded.graph_draft_initialized,
      status = 'published',
      last_publish_attempt_at = excluded.last_publish_attempt_at,
      last_publish_error = null,
      published_layout_revision = excluded.published_layout_revision,
      updated_at = excluded.updated_at;

    delete from public.world_edit_leases lease
    where lease.campaign_id = v_campaign_id
      and lease.holder_profile_id = p_actor_profile_id
      and lease.lease_token = p_lease_token;
  end if;
$replacement$;
begin
  select pg_get_functiondef(
    'public.publish_world_edit_layout_atomic(uuid,uuid,text,uuid)'::regprocedure
  ) into v_definition;

  if v_definition is null then
    raise exception 'publish_world_edit_layout_atomic is missing';
  end if;

  if strpos(v_definition, 'published_layout_revision = excluded.published_layout_revision') = 0 then
    if strpos(v_definition, v_old) = 0 then
      raise exception 'unexpected layout publisher definition for durable receipt';
    end if;
    v_definition := replace(v_definition, v_old, v_new);
    execute v_definition;
  end if;
end;
$migration$;

do $migration$
declare
  v_definition text;
  v_old text := $needle$
  delete from public.world_edit_leases
  where campaign_id = v_campaign_id
    and holder_profile_id = p_actor_profile_id
    and lease_token = p_lease_token;

  return jsonb_build_object(
$needle$;
  v_new text := $replacement$
  insert into public.world_edit_drafts(
    campaign_id,
    owner_profile_id,
    lease_token,
    base_layout_revision,
    base_graph_revision,
    draft_positions,
    draft_graph,
    graph_draft_initialized,
    status,
    last_publish_attempt_at,
    last_publish_error,
    published_graph_revision,
    published_layout_revision,
    updated_at
  ) values (
    v_campaign_id,
    p_actor_profile_id,
    p_lease_token,
    v_lease.base_layout_revision,
    v_lease.base_graph_revision,
    v_lease.draft_positions,
    v_lease.draft_graph,
    v_lease.graph_draft_initialized,
    'published',
    v_now,
    null,
    v_next_revision,
    (v_layout_result->>'revision')::bigint,
    v_now
  )
  on conflict (campaign_id, owner_profile_id, lease_token) do update set
    base_layout_revision = excluded.base_layout_revision,
    base_graph_revision = excluded.base_graph_revision,
    draft_positions = excluded.draft_positions,
    draft_graph = excluded.draft_graph,
    graph_draft_initialized = excluded.graph_draft_initialized,
    status = 'published',
    last_publish_attempt_at = excluded.last_publish_attempt_at,
    last_publish_error = null,
    published_graph_revision = excluded.published_graph_revision,
    published_layout_revision = excluded.published_layout_revision,
    updated_at = excluded.updated_at;

  delete from public.world_edit_leases
  where campaign_id = v_campaign_id
    and holder_profile_id = p_actor_profile_id
    and lease_token = p_lease_token;

  return jsonb_build_object(
$replacement$;
begin
  select pg_get_functiondef(
    'public.publish_world_edit_state_atomic(uuid,uuid,text,uuid)'::regprocedure
  ) into v_definition;

  if v_definition is null then
    raise exception 'publish_world_edit_state_atomic is missing';
  end if;

  if strpos(v_definition, 'published_graph_revision = excluded.published_graph_revision') = 0 then
    if strpos(v_definition, v_old) = 0 then
      raise exception 'unexpected graph publisher definition for durable receipt';
    end if;
    v_definition := replace(v_definition, v_old, v_new);
    execute v_definition;
  end if;
end;
$migration$;

comment on table public.world_edit_drafts is
  'Server-only durable checkpoints for World editing sessions. Lease expiry, handoff or release must not erase hours of editorial work.';
comment on function public.acquire_world_edit_lease_atomic(uuid,uuid,text,uuid) is
  'Acquires the exclusive World lease and restores the latest compatible durable checkpoint for the same editor when available.';
comment on function public.discard_world_edit_lease_atomic(uuid,uuid,text,uuid) is
  'Explicitly discards the active World draft while preserving a tombstoned recovery/audit copy.';

revoke all on function public.acquire_world_edit_lease_atomic(uuid,uuid,text,uuid)
  from public, anon, authenticated;
grant execute on function public.acquire_world_edit_lease_atomic(uuid,uuid,text,uuid)
  to service_role;

revoke all on function public.discard_world_edit_lease_atomic(uuid,uuid,text,uuid)
  from public, anon, authenticated;
grant execute on function public.discard_world_edit_lease_atomic(uuid,uuid,text,uuid)
  to service_role;
