-- Cover the remaining transcript_segments foreign keys with compact partial indexes.
-- These columns are sparse in production, so indexing only non-null rows keeps
-- write/storage overhead low while avoiding full-table scans during FK checks
-- and direct lookups by participant/source/profile.

create index if not exists idx_transcript_segments_participant_id_fk
  on public.transcript_segments (participant_id)
  where participant_id is not null;

create index if not exists idx_transcript_segments_source_chunk_id_fk
  on public.transcript_segments (source_chunk_id)
  where source_chunk_id is not null;

create index if not exists idx_transcript_segments_source_file_id_fk
  on public.transcript_segments (source_file_id)
  where source_file_id is not null;

create index if not exists idx_transcript_segments_speaker_profile_id_fk
  on public.transcript_segments (speaker_profile_id)
  where speaker_profile_id is not null;
