-- review_status is the canonical editorial state read by the application.
-- needs_review remains a compatibility projection for new writes only.
-- Historical rows are intentionally preserved and may not satisfy that projection.
comment on column public.transcript_segments.review_status is
  'Canonical editorial review state and application source of truth. Historical needs_review values may not match it.';

comment on column public.transcript_segments.needs_review is
  'Legacy compatibility projection for new writes: true for review_status pending/needs_review and false for approved/discarded. Historical rows are preserved and may differ; do not use as canonical read state.';
