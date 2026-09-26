-- Candidate for #636; deploy with the fenced Web client. No data rewrite.
-- Retire the unfenced six-argument operational API; consumers must pass CAS.
drop function public.set_current_transcript_revision_atomic(uuid, uuid, uuid, uuid, uuid, uuid);

create or replace function public.publish_transcript_revision_atomic(
  p_auth_user_id uuid,
  p_actor_profile_id uuid,
  p_input jsonb,
  p_lookup_only boolean default false
)
returns jsonb
language plpgsql
security invoker
set search_path = pg_catalog, public
as $$
declare
  v_campaign_id uuid;
  v_session_id uuid;
  v_operation_id uuid;
  v_campaign_slug text;
  v_source_session_id text;
  v_source_id text;
  v_run_id text;
  v_base_transcript_sha256 text;
  v_draft_sha256 text;
  v_payload_sha256 text;
  v_payload_json text;
  v_payload jsonb;
  v_lineage jsonb;
  v_review jsonb;
  v_segments jsonb;
  v_session public.sessions%rowtype;
  v_existing public.transcript_publication_receipts%rowtype;
  v_revision_id uuid;
  v_revision_number bigint;
  v_previous_revision_id uuid;
  v_action text;
  v_segment_count integer;
  v_word_count integer;
  v_reviewed_segments integer;
  v_warning_count integer;
  v_receipt_id uuid;
  v_segment jsonb;
begin
  if p_auth_user_id is null
     or p_actor_profile_id is null
     or not exists (
       select 1
       from public.profiles p
       where p.id = p_actor_profile_id
         and p.auth_user_id = p_auth_user_id
     ) then
    return jsonb_build_object('ok', false, 'reason', 'forbidden');
  end if;

  if not exists (
    select 1
    from public.permission_catalog pc
    where pc.action = 'campaign.transcript.publish'
      and pc.plane = 'mixed'
  ) then
    return jsonb_build_object('ok', false, 'reason', 'publish_capability_undefined');
  end if;

  if p_input is null
     or jsonb_typeof(p_input) <> 'object'
     or p_lookup_only is null
     or exists (
       select 1
       from jsonb_object_keys(p_input) as k(key_name)
       where k.key_name not in (
         'campaignId',
         'sessionId',
         'operationId',
         'expectedCurrentRevisionId',
         'sourceSystem',
         'sourceSessionId',
         'sourceId',
         'runId',
         'baseTranscriptSha256',
         'draftSha256',
         'payloadSha256',
         'payloadJson',
         'segmentCount'
       )
     )
     or coalesce(p_input->>'campaignId', '') !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
     or coalesce(p_input->>'sessionId', '') !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
     or coalesce(p_input->>'operationId', '') !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
     or not (p_input ? 'expectedCurrentRevisionId')
     or (p_input->'expectedCurrentRevisionId' <> 'null'::jsonb and (jsonb_typeof(p_input->'expectedCurrentRevisionId') <> 'string' or (p_input->>'expectedCurrentRevisionId') !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'))
     or p_input->>'sourceSystem' is distinct from 'local_companion'
     or coalesce(p_input->>'sourceSessionId', '') !~ '^[A-Za-z0-9_-]{1,160}$'
     or coalesce(p_input->>'sourceId', '') !~ '^craig-[0-9a-f]{64}$'
     or coalesce(p_input->>'runId', '') !~ '^[A-Za-z0-9_-]{1,196}$'
     or coalesce(p_input->>'baseTranscriptSha256', '') !~ '^[0-9a-f]{64}$'
     or coalesce(p_input->>'draftSha256', '') !~ '^[0-9a-f]{64}$'
     or coalesce(p_input->>'payloadSha256', '') !~ '^[0-9a-f]{64}$'
     or coalesce(p_input->>'segmentCount', '') !~ '^[0-9]{1,6}$'
     or (p_input->>'segmentCount')::integer not between 1 and 100000 then
    return jsonb_build_object('ok', false, 'reason', 'invalid_payload');
  end if;

  v_campaign_id := (p_input->>'campaignId')::uuid;
  v_session_id := (p_input->>'sessionId')::uuid;
  v_operation_id := (p_input->>'operationId')::uuid;
  v_source_session_id := p_input->>'sourceSessionId';
  v_source_id := p_input->>'sourceId';
  v_run_id := p_input->>'runId';
  v_base_transcript_sha256 := p_input->>'baseTranscriptSha256';
  v_draft_sha256 := p_input->>'draftSha256';
  v_payload_sha256 := p_input->>'payloadSha256';
  v_segment_count := (p_input->>'segmentCount')::integer;

  -- Authorization is intentionally resolved before target/session existence.
  select c.slug
  into v_campaign_slug
  from public.campaigns c
  where c.id = v_campaign_id
    and exists (
      select 1
      from public.role_assignments a
      join public.role_permissions rp on rp.role_id = a.role_id
      where a.profile_id = p_actor_profile_id
        and a.status = 'active'
        and a.starts_at <= clock_timestamp()
        and (a.ends_at is null or a.ends_at > clock_timestamp())
        and rp.permission_action = 'campaign.transcript.publish'
        and (
          (a.scope_type = 'campaign' and a.scope_id = c.slug)
          or (a.scope_type = 'project' and a.scope_id = 'tda')
        )
    );

  if not found then
    return jsonb_build_object('ok', false, 'reason', 'forbidden');
  end if;

  select s.*
  into v_session
  from public.sessions s
  where s.id = v_session_id
    and s.campaign_id = v_campaign_id
    and s.source_system = 'local_companion'
    and s.source_session_id = v_source_session_id
  for update;

  if not found then
    return jsonb_build_object('ok', false, 'reason', 'not_found');
  end if;

  select *
  into v_existing
  from public.transcript_publication_receipts r
  where r.session_id = v_session.id
    and r.operation_id = v_operation_id;

  if found then
    if v_existing.campaign_id <> v_campaign_id
       or v_existing.source_id <> v_source_id
       or v_existing.run_id <> v_run_id
       or v_existing.base_transcript_sha256 <> v_base_transcript_sha256
       or v_existing.draft_sha256 <> v_draft_sha256
       or v_existing.payload_sha256 <> v_payload_sha256
       or v_existing.segment_count <> v_segment_count then
      return jsonb_build_object('ok', false, 'reason', 'conflict');
    end if;

    select r.revision_number
    into v_revision_number
    from public.transcript_revisions r
    where r.id = v_existing.revision_id
      and r.session_id = v_session.id;

    if not found then
      raise exception 'publication receipt references a missing revision';
    end if;

    return jsonb_build_object(
      'ok', true,
      'receipt', jsonb_build_object(
        'schemaVersion', 'tda_transcript_publication_receipt_v1',
        'status', 'committed',
        'receiptId', v_existing.id,
        'campaignId', v_existing.campaign_id,
        'sessionId', v_existing.session_id,
        'revisionId', v_existing.revision_id,
        'revisionNumber', v_revision_number,
        'operationId', v_existing.operation_id,
        'sourceId', v_existing.source_id,
        'runId', v_existing.run_id,
        'baseTranscriptSha256', v_existing.base_transcript_sha256,
        'draftSha256', v_existing.draft_sha256,
        'payloadSha256', v_existing.payload_sha256,
        'segmentCount', v_existing.segment_count,
        'wordCount', v_existing.word_count,
        'committedAt', v_existing.committed_at
      )
    );
  elsif p_lookup_only then
    return jsonb_build_object('ok', false, 'reason', 'not_found');
  end if;

  -- Replay/readback above precede CAS: a lost response remains recoverable.
  if v_session.current_transcript_revision_id is distinct from (p_input->>'expectedCurrentRevisionId')::uuid then
    return jsonb_build_object('ok', false, 'reason', 'stale_current');
  end if;

  if jsonb_typeof(p_input->'payloadJson') is distinct from 'string' then
    return jsonb_build_object('ok', false, 'reason', 'invalid_payload');
  end if;
  v_payload_json := p_input->>'payloadJson';
  if btrim(v_payload_json) = ''
     or octet_length(v_payload_json) > 33554432
     or encode(
       extensions.digest(convert_to(v_payload_json, 'UTF8'), 'sha256'),
       'hex'
     ) <> v_payload_sha256 then
    return jsonb_build_object('ok', false, 'reason', 'invalid_payload');
  end if;

  begin
    v_payload := v_payload_json::jsonb;
  exception
    when others then
      return jsonb_build_object('ok', false, 'reason', 'invalid_payload');
  end;

  if jsonb_typeof(v_payload) is distinct from 'object'
     or v_payload->>'schema_version' is distinct from 'tda_transcript_publication_v1'
     or exists (
       select 1
       from jsonb_object_keys(v_payload) as k(key_name)
       where k.key_name not in (
         'schema_version',
         'source_id',
         'run_id',
         'base_transcript_sha256',
         'draft_sha256',
         'lineage',
         'review',
         'segments'
       )
     )
     or v_payload->>'source_id' is distinct from v_source_id
     or v_payload->>'run_id' is distinct from v_run_id
     or v_payload->>'base_transcript_sha256' is distinct from v_base_transcript_sha256
     or v_payload->>'draft_sha256' is distinct from v_draft_sha256
     or jsonb_typeof(v_payload->'lineage') is distinct from 'object'
     or jsonb_typeof(v_payload->'review') is distinct from 'object'
     or jsonb_typeof(v_payload->'segments') is distinct from 'array'
     or jsonb_array_length(v_payload->'segments') <> v_segment_count then
    return jsonb_build_object('ok', false, 'reason', 'invalid_payload');
  end if;

  v_lineage := v_payload->'lineage';
  v_review := v_payload->'review';
  v_segments := v_payload->'segments';

  if exists (
       select 1
       from jsonb_object_keys(v_lineage) as k(key_name)
       where k.key_name not in (
         'profile_id',
         'engine',
         'model',
         'model_revision',
         'device',
         'compute_type',
         'alignment',
         'completed_at'
       )
     )
     or jsonb_typeof(v_lineage->'profile_id') is distinct from 'string'
     or char_length(v_lineage->>'profile_id') not between 1 and 64
     or exists (
       select 1
       from jsonb_each(v_lineage) as e(key_name, value)
       where e.key_name <> 'profile_id'
         and jsonb_typeof(e.value) not in ('string', 'null')
     ) then
    return jsonb_build_object('ok', false, 'reason', 'invalid_payload');
  end if;

  if exists (
       select 1
       from jsonb_object_keys(v_review) as k(key_name)
       where k.key_name not in (
         'status',
         'draft_revision',
         'reviewed_segments',
         'total_segments',
         'warning_count',
         'word_count'
       )
     )
     or v_review->>'status' is distinct from 'approved_local'
     or coalesce(v_review->>'draft_revision', '') !~ '^[0-9]{1,12}$'
     or coalesce(v_review->>'reviewed_segments', '') !~ '^[0-9]{1,6}$'
     or coalesce(v_review->>'total_segments', '') !~ '^[0-9]{1,6}$'
     or coalesce(v_review->>'warning_count', '') !~ '^[0-9]{1,9}$'
     or coalesce(v_review->>'word_count', '') !~ '^[0-9]{1,9}$'
     or (v_review->>'total_segments')::integer <> v_segment_count then
    return jsonb_build_object('ok', false, 'reason', 'invalid_payload');
  end if;

  if exists (
    select 1
    from jsonb_array_elements(v_segments) raw(value)
    where jsonb_typeof(raw.value) is distinct from 'object'
       or exists (
         select 1
         from jsonb_object_keys(raw.value) as k(key_name)
         where k.key_name not in (
           'track_number',
           'segment_id',
           'start',
           'end',
           'text',
           'speaker',
           'reviewed'
         )
       )
       or jsonb_typeof(raw.value->'track_number') is distinct from 'number'
       or jsonb_typeof(raw.value->'segment_id') is distinct from 'string'
       or jsonb_typeof(raw.value->'start') is distinct from 'number'
       or jsonb_typeof(raw.value->'end') is distinct from 'number'
       or jsonb_typeof(raw.value->'text') is distinct from 'string'
       or jsonb_typeof(raw.value->'speaker') is distinct from 'string'
       or jsonb_typeof(raw.value->'reviewed') is distinct from 'boolean'
       or coalesce(raw.value->>'track_number', '') !~ '^[0-9]{1,4}$'
       or (raw.value->>'track_number')::integer < 1
       or char_length(raw.value->>'segment_id') not between 1 and 256
       or char_length(btrim(raw.value->>'text')) not between 1 and 100000
       or char_length(btrim(raw.value->>'speaker')) not between 1 and 160
       or (raw.value->>'start')::numeric < 0
       or (raw.value->>'end')::numeric < (raw.value->>'start')::numeric
       or (raw.value->>'end')::numeric > 604800
  ) then
    return jsonb_build_object('ok', false, 'reason', 'invalid_payload');
  end if;

  if (
    select count(*)
    from (
      select
        (value->>'track_number')::integer,
        value->>'segment_id'
      from jsonb_array_elements(v_segments)
      group by 1, 2
    ) unique_segments
  ) <> v_segment_count then
    return jsonb_build_object('ok', false, 'reason', 'invalid_payload');
  end if;

  select
    count(*) filter (where (value->>'reviewed')::boolean),
    coalesce(
      sum(
        cardinality(
          regexp_split_to_array(btrim(value->>'text'), E'\\s+')
        )
      ),
      0
    )
  into v_reviewed_segments, v_word_count
  from jsonb_array_elements(v_segments);

  v_warning_count := (v_review->>'warning_count')::integer;

  if (v_review->>'reviewed_segments')::integer <> v_reviewed_segments
     or (v_review->>'word_count')::integer <> v_word_count then
    return jsonb_build_object('ok', false, 'reason', 'invalid_payload');
  end if;

  select coalesce(max(r.revision_number), 0) + 1
  into v_revision_number
  from public.transcript_revisions r
  where r.session_id = v_session.id;

  v_revision_id := gen_random_uuid();
  v_previous_revision_id := v_session.current_transcript_revision_id;
  v_action := case
    when v_previous_revision_id is null then 'publish'
    else 'replace'
  end;

  insert into public.transcript_revisions (
    id,
    campaign_id,
    session_id,
    revision_number,
    operation_id,
    source_system,
    source_session_id,
    source_id,
    run_id,
    base_transcript_sha256,
    draft_sha256,
    payload_sha256,
    segment_count,
    word_count,
    reviewed_segments,
    warning_count,
    lineage,
    review_summary,
    segments,
    actor_profile_id
  ) values (
    v_revision_id,
    v_campaign_id,
    v_session.id,
    v_revision_number,
    v_operation_id,
    'local_companion',
    v_source_session_id,
    v_source_id,
    v_run_id,
    v_base_transcript_sha256,
    v_draft_sha256,
    v_payload_sha256,
    v_segment_count,
    v_word_count,
    v_reviewed_segments,
    v_warning_count,
    v_lineage,
    v_review,
    v_segments,
    p_actor_profile_id
  );

  v_receipt_id := gen_random_uuid();
  insert into public.transcript_publication_receipts (
    id,
    campaign_id,
    session_id,
    revision_id,
    operation_id,
    source_id,
    run_id,
    base_transcript_sha256,
    draft_sha256,
    payload_sha256,
    segment_count,
    word_count,
    actor_profile_id
  ) values (
    v_receipt_id,
    v_campaign_id,
    v_session.id,
    v_revision_id,
    v_operation_id,
    v_source_id,
    v_run_id,
    v_base_transcript_sha256,
    v_draft_sha256,
    v_payload_sha256,
    v_segment_count,
    v_word_count,
    p_actor_profile_id
  )
  returning * into v_existing;

  update public.sessions
  set current_transcript_revision_id = v_revision_id
  where id = v_session.id;

  insert into public.transcript_publication_events (
    campaign_id,
    session_id,
    operation_id,
    action,
    revision_id,
    previous_revision_id,
    actor_profile_id
  ) values (
    v_campaign_id,
    v_session.id,
    v_operation_id,
    v_action,
    v_revision_id,
    v_previous_revision_id,
    p_actor_profile_id
  );

  insert into public.audit_log (
    campaign_id,
    session_id,
    actor_id,
    action,
    table_name,
    record_id,
    old_value,
    new_value
  ) values (
    v_campaign_id,
    v_session.id,
    p_actor_profile_id,
    'transcript_revision.' || v_action,
    'transcript_revisions',
    v_revision_id,
    jsonb_build_object(
      'current_revision_id',
      v_previous_revision_id
    ),
    jsonb_build_object(
      'current_revision_id',
      v_revision_id,
      'revision_number',
      v_revision_number,
      'source_id',
      v_source_id,
      'run_id',
      v_run_id,
      'payload_sha256',
      v_payload_sha256,
      'segment_count',
      v_segment_count,
      'word_count',
      v_word_count
    )
  );

  return jsonb_build_object(
    'ok', true,
    'receipt', jsonb_build_object(
      'schemaVersion', 'tda_transcript_publication_receipt_v1',
      'status', 'committed',
      'receiptId', v_existing.id,
      'campaignId', v_existing.campaign_id,
      'sessionId', v_existing.session_id,
      'revisionId', v_existing.revision_id,
      'revisionNumber', v_revision_number,
      'operationId', v_existing.operation_id,
      'sourceId', v_existing.source_id,
      'runId', v_existing.run_id,
      'baseTranscriptSha256', v_existing.base_transcript_sha256,
      'draftSha256', v_existing.draft_sha256,
      'payloadSha256', v_existing.payload_sha256,
      'segmentCount', v_existing.segment_count,
      'wordCount', v_existing.word_count,
      'committedAt', v_existing.committed_at
    )
  );
end;
$$;

revoke all on function public.publish_transcript_revision_atomic(uuid, uuid, jsonb, boolean)
from public, anon, authenticated;
grant execute on function public.publish_transcript_revision_atomic(uuid, uuid, jsonb, boolean)
to service_role;

comment on function public.publish_transcript_revision_atomic(uuid, uuid, jsonb, boolean) is
'Candidate-only server boundary for an immutable complete transcript revision. Authorization precedes session lookup. Revision, receipt, current pointer, event and sanitized audit commit atomically; replay of the same operation is idempotent.';

create function public.set_current_transcript_revision_atomic(
  p_auth_user_id uuid,
  p_actor_profile_id uuid,
  p_campaign_id uuid,
  p_session_id uuid,
  p_operation_id uuid,
  p_revision_id uuid,
  p_expected_current_revision_id uuid
)
returns jsonb
language plpgsql
security invoker
set search_path = pg_catalog, public
as $$
declare
  v_campaign_slug text;
  v_session public.sessions%rowtype;
  v_revision public.transcript_revisions%rowtype;
  v_event public.transcript_publication_events%rowtype;
  v_previous_revision_id uuid;
  v_action text;
begin
  if p_auth_user_id is null
     or p_actor_profile_id is null
     or p_campaign_id is null
     or p_session_id is null
     or p_operation_id is null
     or not exists (
       select 1
       from public.profiles p
       where p.id = p_actor_profile_id
         and p.auth_user_id = p_auth_user_id
     ) then
    return jsonb_build_object('ok', false, 'reason', 'forbidden');
  end if;

  if not exists (
    select 1
    from public.permission_catalog pc
    where pc.action = 'campaign.transcript.publish'
      and pc.plane = 'mixed'
  ) then
    return jsonb_build_object('ok', false, 'reason', 'publish_capability_undefined');
  end if;

  select c.slug
  into v_campaign_slug
  from public.campaigns c
  where c.id = p_campaign_id
    and exists (
      select 1
      from public.role_assignments a
      join public.role_permissions rp on rp.role_id = a.role_id
      where a.profile_id = p_actor_profile_id
        and a.status = 'active'
        and a.starts_at <= clock_timestamp()
        and (a.ends_at is null or a.ends_at > clock_timestamp())
        and rp.permission_action = 'campaign.transcript.publish'
        and (
          (a.scope_type = 'campaign' and a.scope_id = c.slug)
          or (a.scope_type = 'project' and a.scope_id = 'tda')
        )
    );

  if not found then
    return jsonb_build_object('ok', false, 'reason', 'forbidden');
  end if;

  select s.*
  into v_session
  from public.sessions s
  where s.id = p_session_id
    and s.campaign_id = p_campaign_id
  for update;

  if not found then
    return jsonb_build_object('ok', false, 'reason', 'not_found');
  end if;

  select *
  into v_event
  from public.transcript_publication_events e
  where e.session_id = v_session.id
    and e.operation_id = p_operation_id;

  if found then
    v_action := case when p_revision_id is null then 'unpublish' else 'restore' end;
    if v_event.action <> v_action
       or v_event.revision_id is distinct from p_revision_id then
      return jsonb_build_object('ok', false, 'reason', 'conflict');
    end if;
    return jsonb_build_object(
      'ok', true,
      'event', jsonb_build_object(
        'schemaVersion', 'tda_transcript_publication_event_v1',
        'eventId', v_event.id,
        'campaignId', v_event.campaign_id,
        'sessionId', v_event.session_id,
        'operationId', v_event.operation_id,
        'action', v_event.action,
        'revisionId', v_event.revision_id,
        'previousRevisionId', v_event.previous_revision_id,
        'committedAt', v_event.created_at
      )
    );
  end if;

  if v_session.current_transcript_revision_id is distinct from p_expected_current_revision_id then
    return jsonb_build_object('ok', false, 'reason', 'stale_current');
  end if;

  if p_revision_id is not null then
    select *
    into v_revision
    from public.transcript_revisions r
    where r.id = p_revision_id
      and r.session_id = v_session.id
      and r.campaign_id = p_campaign_id;

    if not found then
      return jsonb_build_object('ok', false, 'reason', 'not_found');
    end if;
    v_action := 'restore';
  else
    v_action := 'unpublish';
  end if;

  v_previous_revision_id := v_session.current_transcript_revision_id;

  update public.sessions
  set current_transcript_revision_id = p_revision_id
  where id = v_session.id;

  insert into public.transcript_publication_events (
    campaign_id,
    session_id,
    operation_id,
    action,
    revision_id,
    previous_revision_id,
    actor_profile_id
  ) values (
    p_campaign_id,
    v_session.id,
    p_operation_id,
    v_action,
    p_revision_id,
    v_previous_revision_id,
    p_actor_profile_id
  )
  returning * into v_event;

  insert into public.audit_log (
    campaign_id,
    session_id,
    actor_id,
    action,
    table_name,
    record_id,
    old_value,
    new_value
  ) values (
    p_campaign_id,
    v_session.id,
    p_actor_profile_id,
    'transcript_revision.' || v_action,
    'sessions',
    v_session.id,
    jsonb_build_object(
      'current_revision_id',
      v_previous_revision_id
    ),
    jsonb_build_object(
      'current_revision_id',
      p_revision_id
    )
  );

  return jsonb_build_object(
    'ok', true,
    'event', jsonb_build_object(
      'schemaVersion', 'tda_transcript_publication_event_v1',
      'eventId', v_event.id,
      'campaignId', v_event.campaign_id,
      'sessionId', v_event.session_id,
      'operationId', v_event.operation_id,
      'action', v_event.action,
      'revisionId', v_event.revision_id,
      'previousRevisionId', v_event.previous_revision_id,
      'committedAt', v_event.created_at
    )
  );
end;
$$;

revoke all on function public.set_current_transcript_revision_atomic(uuid, uuid, uuid, uuid, uuid, uuid, uuid)
from public, anon, authenticated;
grant execute on function public.set_current_transcript_revision_atomic(uuid, uuid, uuid, uuid, uuid, uuid, uuid)
to service_role;

comment on function public.set_current_transcript_revision_atomic(uuid, uuid, uuid, uuid, uuid, uuid, uuid) is
'Candidate-only restore/unpublish boundary. Existing immutable revisions are reactivated or the current pointer is cleared; history is preserved and each operation is idempotently receipted by publication_events.';


