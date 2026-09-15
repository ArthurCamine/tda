do $$
declare
  actual_default text;
  review_status_comment text;
  needs_review_comment text;
begin
  select column_default
    into actual_default
  from information_schema.columns
  where table_schema = 'public'
    and table_name = 'transcript_segments'
    and column_name = 'needs_review';

  if actual_default is distinct from 'true' then
    raise exception 'expected transcript_segments.needs_review default true, got %', actual_default;
  end if;

  select col_description('public.transcript_segments'::regclass, a.attnum)
    into review_status_comment
  from pg_attribute a
  where a.attrelid = 'public.transcript_segments'::regclass
    and a.attname = 'review_status'
    and not a.attisdropped;

  if review_status_comment is distinct from 'Canonical editorial review state and application source of truth. Historical needs_review values may not match it.' then
    raise exception 'unexpected transcript_segments.review_status comment: %', review_status_comment;
  end if;

  select col_description('public.transcript_segments'::regclass, a.attnum)
    into needs_review_comment
  from pg_attribute a
  where a.attrelid = 'public.transcript_segments'::regclass
    and a.attname = 'needs_review'
    and not a.attisdropped;

  if needs_review_comment is distinct from 'Legacy compatibility projection for new writes: true for review_status pending/needs_review and false for approved/discarded. Historical rows are preserved and may differ; do not use as canonical read state.' then
    raise exception 'unexpected transcript_segments.needs_review comment: %', needs_review_comment;
  end if;
end
$$;
