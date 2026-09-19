-- Make the lease draft authoritative for relation replacement.
--
-- The World authoring contract already serializes editors with one exclusive lease
-- and rejects a publish when the graph head moved since that lease was acquired.
-- Under that invariant, a relation explicitly replaced by the current draft must
-- supersede the previously active row instead of failing because write ordering
-- happens to encounter the old row first.
--
-- This is forward-only hardening of the applied publisher. Historical rows are
-- preserved with lifecycle status; no relation is hard-deleted.

do $migration$
declare
  v_definition text;
  v_write_loop text := $needle$
  for v_edge in select value from jsonb_array_elements(v_lease.draft_graph->'edges')
  loop
    v_edge_id := (v_edge->>'id')::uuid;
    v_source := (v_edge->>'source')::uuid;
    v_target := (v_edge->>'target')::uuid;
    v_type_slug := v_edge->>'relationType';
$needle$;
  v_ordered_write_loop text := $replacement$
  -- A valid exclusive lease + matching head revision makes this saved draft the
  -- authoritative editor intent. Relations omitted from the full draft snapshot
  -- are historical, not current, so preserve them as superseded rather than
  -- letting an old active row block the accepted editor.
  update public.entity_relations relation
  set status = 'superseded',
      revision = relation.revision + 1,
      updated_by = p_actor_profile_id,
      updated_at = v_now
  where relation.campaign_id = v_campaign_id
    and relation.status = 'active'
    and not exists (
      select 1
      from jsonb_array_elements(v_lease.draft_graph->'edges') draft_edge(value)
      where draft_edge.value->>'id' = relation.id::text
    );

  -- Apply non-active rows first, unchanged active rows next, and newly-created or
  -- semantically-changed active rows last. This makes an explicit replacement win
  -- independently of UUID/JSON ordering while retaining all history.
  for v_edge in
    select draft_edge.value
    from jsonb_array_elements(v_lease.draft_graph->'edges')
      with ordinality draft_edge(value, ordinal)
    left join public.entity_relations persisted
      on persisted.campaign_id = v_campaign_id
     and persisted.id::text = draft_edge.value->>'id'
    left join lateral (
      select relation_type.value->>'direction' as direction
      from jsonb_array_elements(v_lease.draft_graph->'relationTypes') relation_type(value)
      where relation_type.value->>'slug' = draft_edge.value->>'relationType'
      limit 1
    ) desired_type on true
    order by
      case
        when draft_edge.value->>'status' <> 'active' then 0
        when persisted.id is null then 2
        when persisted.relation_type_slug is distinct from draft_edge.value->>'relationType' then 2
        when desired_type.direction = 'symmetric' and (
          least(persisted.source_entity_id::text, persisted.target_entity_id::text)
            is distinct from least(draft_edge.value->>'source', draft_edge.value->>'target')
          or greatest(persisted.source_entity_id::text, persisted.target_entity_id::text)
            is distinct from greatest(draft_edge.value->>'source', draft_edge.value->>'target')
        ) then 2
        when desired_type.direction = 'directed' and (
          persisted.source_entity_id::text is distinct from draft_edge.value->>'source'
          or persisted.target_entity_id::text is distinct from draft_edge.value->>'target'
        ) then 2
        else 1
      end,
      draft_edge.ordinal
  loop
    v_edge_id := (v_edge->>'id')::uuid;
    v_source := (v_edge->>'source')::uuid;
    v_target := (v_edge->>'target')::uuid;
    v_type_slug := v_edge->>'relationType';
$replacement$;
  v_duplicate_guard text := $needle$
    if exists (
      select 1 from public.entity_relations r
      where r.campaign_id = v_campaign_id
        and r.id <> v_edge_id
        and r.relation_type_slug = v_type_slug
        and r.status = 'active'
        and (
          (v_direction = 'symmetric' and least(r.source_entity_id::text, r.target_entity_id::text) = least(v_source::text, v_target::text)
            and greatest(r.source_entity_id::text, r.target_entity_id::text) = greatest(v_source::text, v_target::text))
          or (v_direction = 'directed' and r.source_entity_id = v_source and r.target_entity_id = v_target)
        )
    ) then
      raise exception using errcode = '23505', message = 'duplicate active relation';
    end if;
$needle$;
  v_authoritative_replace text := $replacement$
    if v_edge->>'status' = 'active' then
      -- The currently-applied draft edge wins over an older active semantic
      -- equivalent. Preserve the previous row as historical instead of aborting
      -- the whole publication.
      update public.entity_relations relation
      set status = 'superseded',
          revision = relation.revision + 1,
          updated_by = p_actor_profile_id,
          updated_at = v_now
      where relation.campaign_id = v_campaign_id
        and relation.id <> v_edge_id
        and relation.relation_type_slug = v_type_slug
        and relation.status = 'active'
        and (
          (
            v_direction = 'symmetric'
            and least(relation.source_entity_id::text, relation.target_entity_id::text)
              = least(v_source::text, v_target::text)
            and greatest(relation.source_entity_id::text, relation.target_entity_id::text)
              = greatest(v_source::text, v_target::text)
          )
          or (
            v_direction = 'directed'
            and relation.source_entity_id = v_source
            and relation.target_entity_id = v_target
          )
        );
    end if;
$replacement$;
begin
  select pg_get_functiondef(
    'public.publish_world_edit_state_atomic(uuid,uuid,text,uuid)'::regprocedure
  ) into v_definition;

  if v_definition is null then
    raise exception 'publish_world_edit_state_atomic is missing';
  end if;

  if strpos(v_definition, 'authoritative editor intent') > 0 then
    return;
  end if;

  if strpos(v_definition, v_write_loop) = 0 then
    raise exception 'unexpected World publisher write loop; authoritative reconciliation not applied';
  end if;
  if strpos(v_definition, v_duplicate_guard) = 0 then
    raise exception 'unexpected World duplicate guard; authoritative reconciliation not applied';
  end if;

  v_definition := replace(v_definition, v_write_loop, v_ordered_write_loop);
  v_definition := replace(v_definition, v_duplicate_guard, v_authoritative_replace);
  execute v_definition;
end;
$migration$;

comment on function public.publish_world_edit_state_atomic(uuid,uuid,text,uuid) is
  'Server-only atomic World publish. Exclusive lease + matching graph revision makes the saved draft authoritative; replaced active relations are preserved as superseded history. Public active relations still require reviewed same-campaign canon provenance.';

revoke all on function public.publish_world_edit_state_atomic(uuid,uuid,text,uuid)
  from public, anon, authenticated;
grant execute on function public.publish_world_edit_state_atomic(uuid,uuid,text,uuid)
  to service_role;
