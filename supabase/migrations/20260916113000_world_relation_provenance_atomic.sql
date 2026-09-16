-- Server-only atomic mutation for World relation provenance.
--
-- Provenance is intentionally kept outside the editable graph JSON. A relation
-- must already exist in entity_relations before canonical evidence can be
-- attached, and public active relations may never be left without at least one
-- active same-campaign canon entry.

create or replace function public.replace_world_relation_sources_atomic(
  p_auth_user_id uuid,
  p_actor_profile_id uuid,
  p_campaign_slug text,
  p_relation_id uuid,
  p_canon_entry_ids uuid[]
)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $function$
declare
  v_campaign_id uuid;
  v_relation public.entity_relations%rowtype;
  v_now timestamptz := clock_timestamp();
  v_requested uuid[] := '{}'::uuid[];
  v_previous uuid[] := '{}'::uuid[];
begin
  if p_auth_user_id is null
     or p_actor_profile_id is null
     or p_relation_id is null
     or nullif(btrim(coalesce(p_campaign_slug, '')), '') is null
     or coalesce(cardinality(p_canon_entry_ids), 0) > 50
     or exists (
       select 1
       from unnest(coalesce(p_canon_entry_ids, '{}'::uuid[])) requested(candidate_id)
       where requested.candidate_id is null
     )
     or not exists (
       select 1
       from public.profiles profile
       where profile.id = p_actor_profile_id
         and profile.auth_user_id = p_auth_user_id
     ) then
    return jsonb_build_object('ok', false, 'reason', 'invalid_payload');
  end if;

  select campaign.id
  into v_campaign_id
  from public.campaigns campaign
  where campaign.slug = p_campaign_slug;

  if not found then
    return jsonb_build_object('ok', false, 'reason', 'not_found');
  end if;

  -- Attaching reviewed canon can make a relation eligible for publication.
  -- Require both factual editing and explicit canon approval capability.
  if not exists (
       select 1
       from public.role_assignments assignment
       join public.role_permissions permission on permission.role_id = assignment.role_id
       where assignment.profile_id = p_actor_profile_id
         and assignment.status = 'active'
         and assignment.starts_at <= v_now
         and (assignment.ends_at is null or assignment.ends_at > v_now)
         and permission.permission_action = 'campaign.content.edit'
         and (
           (assignment.scope_type = 'campaign' and assignment.scope_id = p_campaign_slug)
           or (assignment.scope_type = 'project' and assignment.scope_id = 'tda')
         )
     )
     or not exists (
       select 1
       from public.role_assignments assignment
       join public.role_permissions permission on permission.role_id = assignment.role_id
       where assignment.profile_id = p_actor_profile_id
         and assignment.status = 'active'
         and assignment.starts_at <= v_now
         and (assignment.ends_at is null or assignment.ends_at > v_now)
         and permission.permission_action = 'narrative.canon.approve'
         and (
           (assignment.scope_type = 'campaign' and assignment.scope_id = p_campaign_slug)
           or (assignment.scope_type = 'project' and assignment.scope_id = 'tda')
         )
     ) then
    return jsonb_build_object('ok', false, 'reason', 'forbidden');
  end if;

  select relation.*
  into v_relation
  from public.entity_relations relation
  where relation.id = p_relation_id
    and relation.campaign_id = v_campaign_id
  for update;

  if not found then
    return jsonb_build_object('ok', false, 'reason', 'not_found');
  end if;

  select coalesce(array_agg(deduped.candidate_id order by deduped.candidate_id), '{}'::uuid[])
  into v_requested
  from (
    select distinct requested.candidate_id
    from unnest(coalesce(p_canon_entry_ids, '{}'::uuid[])) requested(candidate_id)
  ) deduped;

  -- This workflow attaches only currently active canon from the same campaign.
  -- Historical/superseded evidence remains readable if already stored, but it
  -- cannot be newly selected as publication evidence through this boundary.
  if exists (
    select 1
    from unnest(v_requested) requested(candidate_id)
    where not exists (
      select 1
      from public.canon_entries canon
      where canon.id = requested.candidate_id
        and canon.campaign_id = v_campaign_id
        and canon.status = 'active'
    )
  ) then
    return jsonb_build_object('ok', false, 'reason', 'invalid_payload');
  end if;

  if v_relation.status = 'active'
     and v_relation.visibility in ('public_campaign', 'public_web')
     and cardinality(v_requested) = 0 then
    return jsonb_build_object('ok', false, 'reason', 'review_required');
  end if;

  select coalesce(array_agg(source.canon_entry_id order by source.canon_entry_id), '{}'::uuid[])
  into v_previous
  from public.entity_relation_sources source
  where source.relation_id = p_relation_id;

  if v_previous = v_requested then
    return jsonb_build_object(
      'ok', true,
      'status', 'unchanged',
      'sourceCount', cardinality(v_requested)
    );
  end if;

  delete from public.entity_relation_sources source
  where source.relation_id = p_relation_id;

  insert into public.entity_relation_sources(relation_id, canon_entry_id)
  select p_relation_id, requested.candidate_id
  from unnest(v_requested) requested(candidate_id);

  insert into public.audit_log(
    campaign_id,
    actor_id,
    action,
    table_name,
    record_id,
    old_value,
    new_value
  ) values (
    v_campaign_id,
    p_actor_profile_id,
    'world_relation.provenance.replace',
    'entity_relation_sources',
    p_relation_id,
    jsonb_build_object('canonEntryIds', to_jsonb(v_previous)),
    jsonb_build_object('canonEntryIds', to_jsonb(v_requested))
  );

  return jsonb_build_object(
    'ok', true,
    'status', 'saved',
    'sourceCount', cardinality(v_requested)
  );
end;
$function$;

comment on function public.replace_world_relation_sources_atomic(uuid,uuid,text,uuid,uuid[]) is
  'Server-only atomic replacement of World relation canon sources. Requires campaign.content.edit plus narrative.canon.approve; accepts only active same-campaign canon and preserves the public provenance invariant.';

revoke all on function public.replace_world_relation_sources_atomic(uuid,uuid,text,uuid,uuid[])
  from public, anon, authenticated;
grant execute on function public.replace_world_relation_sources_atomic(uuid,uuid,text,uuid,uuid[])
  to service_role;
