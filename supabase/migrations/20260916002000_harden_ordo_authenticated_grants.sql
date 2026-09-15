-- Keep the RLS-governed CRUD contract for authenticated users while removing
-- table-level privileges that are not part of the application access model.
-- TDA:ALLOW_DESTRUCTIVE_MIGRATION: reviewed privilege contraction; removes only REFERENCES, TRIGGER and TRUNCATE while preserving RLS-governed CRUD.

revoke references, trigger, truncate
on table public.ordo_access_members
from authenticated;
