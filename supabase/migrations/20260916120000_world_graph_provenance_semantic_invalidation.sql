-- Forward-only hardening for World relation provenance.
--
-- Canon evidence is attached to a persisted relation fact. If the factual
-- meaning of that relation changes, existing evidence must not silently remain
-- eligible for publication. Presentation and audience changes are deliberately
-- excluded from semantic invalidation.

create or replace function public.enforce_world_relation_provenance_on_write()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog, public
as $function$
declare
  v_semantic_changed boolean := false;
  v_previous_sources uuid[] := '{}'::uuid[];
begin
  if tg_op = 'INSERT' then
    -- A new relation cannot already have a source because the FK target does not
    -- exist until this row is inserted. Force the reviewed/private two-step flow.
    if new.status = 'active'
       and new.visibility in ('public_campaign', 'public_web') then
      raise exception using
        errcode = 'P0001',
        message = 'world_relation_review_required';
    end if;
    return new;
  end if;

  v_semantic_changed :=
    old.source_entity_id is distinct from new.source_entity_id
    or old.target_entity_id is distinct from new.target_entity_id
    or old.relation_type_slug is distinct from new.relation_type_slug
    or old.label_override is distinct from new.label_override
    or old.status is distinct from new.status;

  if v_semantic_changed then
    -- Never mutate the meaning of an already-published relation while reusing
    -- evidence approved for the previous fact. Demote/review it first.
    if new.status = 'active'
       and new.visibility in ('public_campaign', 'public_web') then
      raise exception using
        errcode = 'P0001',
        message = 'world_relation_review_required';
    end if;

    select coalesce(array_agg(source.canon_entry_id order by source.canon_entry_id), '{}'::uuid[])
    into v_previous_sources
    from public.entity_relation_sources source
    where source.relation_id = new.id;

    if cardinality(v_previous_sources) > 0 then
      delete from public.entity_relation_sources source
      where source.relation_id = new.id;

      insert into public.audit_log(
        campaign_id,
        actor_id,
        action,
        table_name,
        record_id,
        old_value,
        new_value
      ) values (
        new.campaign_id,
        new.updated_by,
        'world_relation.provenance.invalidate',
        'entity_relation_sources',
        new.id,
        jsonb_build_object('canonEntryIds', to_jsonb(v_previous_sources)),
        jsonb_build_object('canonEntryIds', '[]'::jsonb)
      );
    end if;

    return new;
  end if;

  -- Visibility-only promotion is valid only after reviewed active canon was
  -- attached to the current persisted semantics.
  if new.status = 'active'
     and new.visibility in ('public_campaign', 'public_web')
     and not exists (
       select 1
       from public.entity_relation_sources source
       join public.canon_entries canon on canon.id = source.canon_entry_id
       where source.relation_id = new.id
         and canon.campaign_id = new.campaign_id
         and canon.status = 'active'
     ) then
    raise exception using
      errcode = 'P0001',
      message = 'world_relation_review_required';
  end if;

  return new;
end;
$function$;

comment on function public.enforce_world_relation_provenance_on_write() is
  'Internal trigger boundary: semantic relation changes atomically invalidate/audit attached canon; active public insert/promotion requires reviewed provenance.';

revoke all on function public.enforce_world_relation_provenance_on_write()
  from public, anon, authenticated, service_role;

create trigger entity_relations_provenance_write_guard
before insert or update on public.entity_relations
for each row execute function public.enforce_world_relation_provenance_on_write();

-- Keep the publish RPC result explicit instead of allowing the trigger to turn a
-- stale-source edit into a generic SQL/dependency failure. This guard runs after
-- the existing source-presence guard and before any graph/layout/audit write.
do $migration$
declare
  v_definition text;
  v_marker text := E'  insert into public.world_graph_heads(campaign_id, revision, updated_by)\n';
  v_guard text := $guard$
  -- Existing canon sources prove the persisted relation, not arbitrary future
  -- semantics under the same UUID. Public semantic edits must return to review.
  if jsonb_typeof(v_lease.draft_graph) = 'object'
     and jsonb_typeof(v_lease.draft_graph->'edges') = 'array'
     and exists (
       select 1
       from jsonb_array_elements(v_lease.draft_graph->'edges') edge(value)
       join public.entity_relations relation
         on relation.campaign_id = v_campaign_id
        and relation.id::text = edge.value->>'id'
       left join lateral (
         select relation_type.value
         from jsonb_array_elements(v_lease.draft_graph->'relationTypes') relation_type(value)
         where relation_type.value->>'slug' = edge.value->>'relationType'
         limit 1
       ) draft_type on true
       where edge.value->>'status' = 'active'
         and edge.value->>'visibility' in ('public_campaign', 'public_web')
         and (
           relation.relation_type_slug is distinct from edge.value->>'relationType'
           or coalesce(relation.label_override, '') is distinct from coalesce(edge.value->>'labelOverride', '')
           or relation.status is distinct from edge.value->>'status'
           or not (
             (
               relation.source_entity_id::text = edge.value->>'source'
               and relation.target_entity_id::text = edge.value->>'target'
             )
             or (
               draft_type.value->>'direction' = 'symmetric'
               and relation.source_entity_id::text = edge.value->>'target'
               and relation.target_entity_id::text = edge.value->>'source'
             )
           )
         )
     ) then
    return jsonb_build_object('ok', false, 'reason', 'review_required');
  end if;

$guard$;
begin
  select pg_get_functiondef(
    'public.publish_world_edit_state_atomic(uuid,uuid,text,uuid)'::regprocedure
  ) into v_definition;

  if v_definition is null then
    raise exception 'publish_world_edit_state_atomic is missing';
  end if;

  if strpos(v_definition, 'Existing canon sources prove the persisted relation') > 0 then
    return;
  end if;

  if strpos(v_definition, v_marker) = 0 then
    raise exception 'unexpected publish_world_edit_state_atomic definition; semantic provenance guard not applied';
  end if;

  execute replace(v_definition, v_marker, v_guard || v_marker);
end;
$migration$;

comment on function public.publish_world_edit_state_atomic(uuid,uuid,text,uuid) is
  'Server-only atomic World publish. Active public relations require active canon provenance for the exact persisted relation semantics; semantic changes must return to review.';

revoke all on function public.publish_world_edit_state_atomic(uuid,uuid,text,uuid)
  from public, anon, authenticated;
grant execute on function public.publish_world_edit_state_atomic(uuid,uuid,text,uuid)
  to service_role;
