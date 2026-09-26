-- Synthetic-only contract for immutable cloud transcript revisions.
-- Never executed against the connected Supabase project.

create function public.synthetic_publication_input(
  p_operation_id uuid,
  p_run_id text,
  p_text text
)
returns jsonb
language plpgsql
as $$
declare
  v_payload jsonb;
  v_payload_json text;
  v_payload_sha text;
  v_word_count integer;
begin
  v_word_count := cardinality(regexp_split_to_array(btrim(p_text), E'\\s+'));
  v_payload := jsonb_build_object(
    'schema_version', 'tda_transcript_publication_v1',
    'source_id', 'craig-' || repeat('a', 64),
    'run_id', p_run_id,
    'base_transcript_sha256', repeat('b', 64),
    'draft_sha256', repeat('d', 64),
    'lineage', jsonb_build_object(
      'profile_id', 'whisper-detailed',
      'engine', 'faster-whisper',
      'model', 'large-v3',
      'model_revision', 'test-revision',
      'device', 'cuda',
      'compute_type', 'float16',
      'alignment', 'native',
      'completed_at', '2026-09-21T00:00:00Z'
    ),
    'review', jsonb_build_object(
      'status', 'approved_local',
      'draft_revision', 3,
      'reviewed_segments', 1,
      'total_segments', 1,
      'warning_count', 0,
      'word_count', v_word_count
    ),
    'segments', jsonb_build_array(
      jsonb_build_object(
        'track_number', 1,
        'segment_id', '1-0',
        'start', 0.0,
        'end', 1.0,
        'text', p_text,
        'speaker', 'Alice',
        'reviewed', true
      )
    )
  );
  v_payload_json := v_payload::text;
  v_payload_sha := encode(
    extensions.digest(convert_to(v_payload_json, 'UTF8'), 'sha256'),
    'hex'
  );

  return jsonb_build_object(
    'campaignId', '11111111-1111-4111-8111-111111111111',
    'sessionId', '22222222-2222-4222-8222-222222222222',
    'operationId', p_operation_id,
    'expectedCurrentRevisionId', (select current_transcript_revision_id from public.sessions where id = '22222222-2222-4222-8222-222222222222'),
    'sourceSystem', 'local_companion',
    'sourceSessionId', 'fixture-source',
    'sourceId', 'craig-' || repeat('a', 64),
    'runId', p_run_id,
    'baseTranscriptSha256', repeat('b', 64),
    'draftSha256', repeat('d', 64),
    'payloadSha256', v_payload_sha,
    'payloadJson', v_payload_json,
    'segmentCount', 1
  );
end;
$$;

do $hardening$
declare
  v_table text;
  v_index text;
begin
  foreach v_table in array array[
    'transcript_revisions',
    'transcript_publication_receipts',
    'transcript_publication_events'
  ] loop
    if not has_table_privilege('service_role', format('public.%I', v_table), 'SELECT')
       or not has_table_privilege('service_role', format('public.%I', v_table), 'INSERT')
       or has_table_privilege('service_role', format('public.%I', v_table), 'UPDATE')
       or has_table_privilege('service_role', format('public.%I', v_table), 'DELETE') then
      raise exception 'PUBLICATION_SERVICE_ROLE_PRIVILEGES_NOT_MINIMAL:%', v_table;
    end if;
  end loop;

  foreach v_index in array array[
    'sessions_current_transcript_revision_id_idx',
    'transcript_revisions_campaign_id_idx',
    'transcript_revisions_actor_profile_id_idx',
    'transcript_publication_receipts_campaign_id_idx',
    'transcript_publication_receipts_actor_profile_id_idx',
    'transcript_publication_events_campaign_id_idx',
    'transcript_publication_events_revision_id_idx',
    'transcript_publication_events_previous_revision_id_idx',
    'transcript_publication_events_actor_profile_id_idx'
  ] loop
    if to_regclass('public.' || v_index) is null then
      raise exception 'PUBLICATION_FK_INDEX_MISSING:%', v_index;
    end if;
  end loop;
end;
$hardening$;

do $$
declare
  v_existing jsonb;
  v_missing jsonb;
begin
  if has_function_privilege(
    'anon',
    'public.publish_transcript_revision_atomic(uuid,uuid,jsonb,boolean)',
    'EXECUTE'
  ) or has_function_privilege(
    'authenticated',
    'public.publish_transcript_revision_atomic(uuid,uuid,jsonb,boolean)',
    'EXECUTE'
  ) then
    raise exception 'PUBLICATION_FUNCTION_EXPOSED_TO_BROWSER_ROLE';
  end if;

  set local role service_role;

  select public.publish_transcript_revision_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    public.synthetic_publication_input(
      '90000000-0000-4000-8000-000000000001',
      'run-first',
      'Texto publicado inicial'
    ),
    false
  ) into v_existing;

  select public.publish_transcript_revision_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    jsonb_set(
      public.synthetic_publication_input(
        '90000000-0000-4000-8000-000000000001',
        'run-first',
        'Texto publicado inicial'
      ),
      '{sessionId}',
      '"99999999-9999-4999-8999-999999999999"'::jsonb
    ),
    false
  ) into v_missing;

  if v_existing <> '{"ok":false,"reason":"forbidden"}'::jsonb
     or v_missing <> '{"ok":false,"reason":"forbidden"}'::jsonb then
    raise exception 'TARGET_EXISTENCE_ORACLE_BEFORE_GRANT: % %', v_existing, v_missing;
  end if;
end;
$$;

do $grant$
begin
  if not exists (
    select 1
    from public.role_permissions rp
    join public.role_definitions rd on rd.id = rp.role_id
    where rd.slug = 'site_editor'
      and rd.plane = 'narrative'
      and rp.permission_action = 'campaign.transcript.publish'
  ) then
    raise exception 'PUBLICATION_SITE_EDITOR_GRANT_MISSING';
  end if;

  if exists (
    select 1
    from public.role_assignments ra
    where ra.role_id = '66666666-6666-4666-8666-666666666666'::uuid
  ) then
    raise exception 'PUBLICATION_ROLLOUT_CREATED_USER_ASSIGNMENT';
  end if;
end;
$grant$;

insert into public.role_permissions(role_id, permission_action)
values (
  '55555555-5555-4555-8555-555555555555',
  'campaign.transcript.publish'
);

insert into public.role_assignments(
  profile_id,
  role_id,
  scope_type,
  scope_id,
  status,
  starts_at
) values (
  '33333333-3333-4333-8333-333333333333',
  '55555555-5555-4555-8555-555555555555',
  'campaign',
  'synthetic-campaign',
  'active',
  now()
);

-- Install the synthetic rollback probe as the scratch-cluster owner before the
-- test switches to service_role. The trigger is selective so normal publication,
-- restore and unpublish operations still exercise the least-privileged boundary.
create function public.fail_publication_event_on_probe() returns trigger
language plpgsql as $probe$
begin
  if new.operation_id = '90000000-0000-4000-8000-000000000003'::uuid then
    raise exception 'synthetic publication event failure';
  end if;
  return new;
end;
$probe$;

create trigger fail_publication_event
before insert on public.transcript_publication_events
for each row execute function public.fail_publication_event_on_probe();

do $main$
declare
  v_first jsonb;
  v_replay jsonb;
  v_lookup jsonb;
  v_conflict jsonb;
  v_second jsonb;
  v_failed boolean := false;
  v_revision_1 uuid;
  v_revision_2 uuid;
  v_current uuid;
  v_restore jsonb;
  v_restore_replay jsonb;
  v_unpublish jsonb;
  v_receipts bigint;
  v_revisions bigint;
  v_events bigint;
  v_audits bigint;
begin
  set local role service_role;

  -- First publication atomically creates revision 1 and makes it current.
  select public.publish_transcript_revision_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    public.synthetic_publication_input(
      '90000000-0000-4000-8000-000000000001',
      'run-first',
      'Texto publicado inicial'
    ),
    false
  ) into v_first;

  if v_first->>'ok' <> 'true'
     or v_first->'receipt'->>'schemaVersion' <> 'tda_transcript_publication_receipt_v1'
     or (v_first->'receipt'->>'revisionNumber')::bigint <> 1
     or (v_first->'receipt'->>'segmentCount')::integer <> 1 then
    raise exception 'FIRST_PUBLICATION_INVALID: %', v_first;
  end if;

  v_revision_1 := (v_first->'receipt'->>'revisionId')::uuid;

  select current_transcript_revision_id
  into v_current
  from public.sessions
  where id = '22222222-2222-4222-8222-222222222222';

  if v_current <> v_revision_1 then
    raise exception 'FIRST_PUBLICATION_POINTER_INVALID';
  end if;

  -- Retry and readback return exactly the committed receipt with no new evidence.
  select public.publish_transcript_revision_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    public.synthetic_publication_input(
      '90000000-0000-4000-8000-000000000001',
      'run-first',
      'Texto publicado inicial'
    ),
    false
  ) into v_replay;

  select public.publish_transcript_revision_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    public.synthetic_publication_input(
      '90000000-0000-4000-8000-000000000001',
      'run-first',
      'Texto publicado inicial'
    ),
    true
  ) into v_lookup;

  if v_replay->'receipt' <> v_first->'receipt'
     or v_lookup->'receipt' <> v_first->'receipt' then
    raise exception 'PUBLICATION_REPLAY_NOT_EXACT: first=% replay=% lookup=%',
      v_first->'receipt', v_replay->'receipt', v_lookup->'receipt';
  end if;

  select count(*) into v_receipts from public.transcript_publication_receipts;
  select count(*) into v_revisions from public.transcript_revisions;
  select count(*) into v_events from public.transcript_publication_events;
  select count(*) into v_audits
  from public.audit_log
  where action like 'transcript_revision.%';

  if v_receipts <> 1 or v_revisions <> 1 or v_events <> 1 or v_audits <> 1 then
    raise exception 'PUBLICATION_REPLAY_DUPLICATED_EVIDENCE: % % % %',
      v_receipts, v_revisions, v_events, v_audits;
  end if;

  -- Reusing the same operation id with divergent bytes is an explicit conflict.
  select public.publish_transcript_revision_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    public.synthetic_publication_input(
      '90000000-0000-4000-8000-000000000001',
      'run-first',
      'Conteúdo divergente'
    ),
    false
  ) into v_conflict;

  if v_conflict <> '{"ok":false,"reason":"conflict"}'::jsonb then
    raise exception 'DIVERGENT_OPERATION_DID_NOT_CONFLICT: %', v_conflict;
  end if;

  -- A new operation creates revision 2 and preserves revision 1.
  select public.publish_transcript_revision_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    public.synthetic_publication_input(
      '90000000-0000-4000-8000-000000000002',
      'run-second',
      'Texto publicado substituto'
    ),
    false
  ) into v_second;

  if v_second->>'ok' <> 'true'
     or (v_second->'receipt'->>'revisionNumber')::bigint <> 2 then
    raise exception 'REPLACEMENT_PUBLICATION_INVALID: %', v_second;
  end if;
  v_revision_2 := (v_second->'receipt'->>'revisionId')::uuid;

  select current_transcript_revision_id
  into v_current
  from public.sessions
  where id = '22222222-2222-4222-8222-222222222222';

  select count(*) into v_revisions from public.transcript_revisions;
  if v_current <> v_revision_2 or v_revisions <> 2 then
    raise exception 'REPLACEMENT_DID_NOT_PRESERVE_HISTORY';
  end if;

  -- Force a failure after revision/receipt inserts. The scratch-cluster owner
  -- installed a selective trigger before service_role was assumed, so this test
  -- does not need (and must not grant) schema CREATE privileges to service_role.
  begin
    perform public.publish_transcript_revision_atomic(
      '44444444-4444-4444-8444-444444444444',
      '33333333-3333-4333-8333-333333333333',
      public.synthetic_publication_input(
        '90000000-0000-4000-8000-000000000003',
        'run-rollback',
        'Este texto não pode sobreviver'
      ),
      false
    );
  exception
    when others then
      if sqlerrm not like '%synthetic publication event failure%' then
        raise;
      end if;
      v_failed := true;
  end;

  if not v_failed then
    raise exception 'ROLLBACK_PROBE_DID_NOT_FAIL';
  end if;

  select current_transcript_revision_id
  into v_current
  from public.sessions
  where id = '22222222-2222-4222-8222-222222222222';
  select count(*) into v_revisions from public.transcript_revisions;
  select count(*) into v_receipts from public.transcript_publication_receipts;

  if v_current <> v_revision_2 or v_revisions <> 2 or v_receipts <> 2 then
    raise exception 'FAILED_PUBLICATION_LEFT_PARTIAL_STATE: % % %',
      v_current, v_revisions, v_receipts;
  end if;

  -- Restore reactivates revision 1 without duplicating its immutable content.
  select public.set_current_transcript_revision_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    '11111111-1111-4111-8111-111111111111',
    '22222222-2222-4222-8222-222222222222',
    '90000000-0000-4000-8000-000000000004',
    v_revision_1,
    v_revision_2
  ) into v_restore;

  select public.set_current_transcript_revision_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    '11111111-1111-4111-8111-111111111111',
    '22222222-2222-4222-8222-222222222222',
    '90000000-0000-4000-8000-000000000004',
    v_revision_1,
    v_revision_2
  ) into v_restore_replay;

  if v_restore->>'ok' <> 'true'
     or v_restore->'event'->>'action' <> 'restore'
     or v_restore_replay->'event'->>'eventId' <> v_restore->'event'->>'eventId' then
    raise exception 'RESTORE_REPLAY_INVALID: % %', v_restore, v_restore_replay;
  end if;

  select current_transcript_revision_id
  into v_current
  from public.sessions
  where id = '22222222-2222-4222-8222-222222222222';
  if v_current <> v_revision_1 then
    raise exception 'RESTORE_POINTER_INVALID';
  end if;

  -- Unpublish clears only the pointer; immutable revision history remains.
  select public.set_current_transcript_revision_atomic(
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    '11111111-1111-4111-8111-111111111111',
    '22222222-2222-4222-8222-222222222222',
    '90000000-0000-4000-8000-000000000005',
    null,
    v_revision_1
  ) into v_unpublish;

  if v_unpublish->>'ok' <> 'true'
     or v_unpublish->'event'->>'action' <> 'unpublish' then
    raise exception 'UNPUBLISH_INVALID: %', v_unpublish;
  end if;

  select current_transcript_revision_id
  into v_current
  from public.sessions
  where id = '22222222-2222-4222-8222-222222222222';
  select count(*) into v_revisions from public.transcript_revisions;

  if v_current is not null or v_revisions <> 2 then
    raise exception 'UNPUBLISH_DESTROYED_HISTORY';
  end if;

  -- Stale writes, including null expectations, cannot leave partial evidence.
  select count(*) into v_events from public.transcript_publication_events;
  select count(*) into v_audits from public.audit_log;
  select public.publish_transcript_revision_atomic(
    '44444444-4444-4444-8444-444444444444', '33333333-3333-4333-8333-333333333333',
    public.synthetic_publication_input('90000000-0000-4000-8000-000000000010', 'run-stale', 'stale synthetic') || jsonb_build_object('expectedCurrentRevisionId', v_revision_2), false
  ) into v_conflict;
  if v_conflict <> '{"ok":false,"reason":"stale_current"}'::jsonb then raise exception 'STALE_PUBLISH_ACCEPTED:%', v_conflict; end if;
  select public.set_current_transcript_revision_atomic(
    '44444444-4444-4444-8444-444444444444', '33333333-3333-4333-8333-333333333333',
    '11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222',
    '90000000-0000-4000-8000-000000000011', v_revision_1, v_revision_2
  ) into v_conflict;
  if v_conflict <> '{"ok":false,"reason":"stale_current"}'::jsonb then raise exception 'STALE_RESTORE_ACCEPTED'; end if;
  select public.set_current_transcript_revision_atomic(
    '44444444-4444-4444-8444-444444444444', '33333333-3333-4333-8333-333333333333',
    '11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222',
    '90000000-0000-4000-8000-000000000012', null, v_revision_2
  ) into v_conflict;
  if v_conflict <> '{"ok":false,"reason":"stale_current"}'::jsonb then raise exception 'STALE_UNPUBLISH_ACCEPTED'; end if;
  select public.publish_transcript_revision_atomic(
    '44444444-4444-4444-8444-444444444444', '33333333-3333-4333-8333-333333333333',
    public.synthetic_publication_input('90000000-0000-4000-8000-000000000001', 'run-first', 'Texto publicado inicial') || jsonb_build_object('expectedCurrentRevisionId', v_revision_2), false
  ) into v_replay;
  if v_replay->'receipt' <> v_first->'receipt' then raise exception 'REPLAY_LOST_AFTER_CURRENT_CHANGED'; end if;
  if (select count(*) from public.transcript_publication_events) <> v_events
     or (select count(*) from public.audit_log) <> v_audits
     or (select count(*) from public.transcript_revisions) <> 2
     or (select count(*) from public.transcript_publication_receipts) <> 2 then raise exception 'STALE_WRITE_LEFT_EVIDENCE'; end if;
  select public.publish_transcript_revision_atomic(
    '44444444-4444-4444-8444-444444444444', '33333333-3333-4333-8333-333333333333',
    public.synthetic_publication_input('90000000-0000-4000-8000-000000000013', 'run-missing', 'missing expectation') - 'expectedCurrentRevisionId', false
  ) into v_conflict;
  if v_conflict <> '{"ok":false,"reason":"invalid_payload"}'::jsonb then raise exception 'MISSING_EXPECTATION_ACCEPTED'; end if;
  if to_regprocedure('public.set_current_transcript_revision_atomic(uuid,uuid,uuid,uuid,uuid,uuid)') is not null then raise exception 'UNFENCED_RESTORE_STILL_EXISTS'; end if;

  -- Public audit/event evidence must remain metadata-only.
  if exists (
    select 1
    from public.audit_log a
    where a.action like 'transcript_revision.%'
      and (coalesce(a.old_value::text, '') || coalesce(a.new_value::text, ''))
        like '%Texto publicado%'
  ) then
    raise exception 'AUDIT_LEAKED_TRANSCRIPT_CONTENT';
  end if;
end;
$main$;

drop trigger fail_publication_event on public.transcript_publication_events;
drop function public.fail_publication_event_on_probe();

-- Keep the shared transcript-import scratch cluster pristine for the existing
-- consumer tests that run after bootstrap. Candidate schema stays loaded, but
-- publication-specific fixture rows and audit evidence are removed.
delete from public.transcript_publication_events
where campaign_id = '11111111-1111-4111-8111-111111111111'::uuid
  and session_id = '22222222-2222-4222-8222-222222222222'::uuid;

delete from public.transcript_publication_receipts
where campaign_id = '11111111-1111-4111-8111-111111111111'::uuid
  and session_id = '22222222-2222-4222-8222-222222222222'::uuid;

delete from public.transcript_revisions
where campaign_id = '11111111-1111-4111-8111-111111111111'::uuid
  and session_id = '22222222-2222-4222-8222-222222222222'::uuid;

delete from public.audit_log
where campaign_id = '11111111-1111-4111-8111-111111111111'::uuid
  and session_id = '22222222-2222-4222-8222-222222222222'::uuid
  and action like 'transcript_revision.%';

delete from public.role_assignments
where profile_id = '33333333-3333-4333-8333-333333333333'::uuid
  and role_id = '55555555-5555-4555-8555-555555555555'::uuid
  and scope_type = 'campaign'
  and scope_id = 'synthetic-campaign';

delete from public.role_permissions
where role_id = '55555555-5555-4555-8555-555555555555'::uuid
  and permission_action = 'campaign.transcript.publish';

-- Helper retained only in this disposable cluster for multi-connection CAS tests.
