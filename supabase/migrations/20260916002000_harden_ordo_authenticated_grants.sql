-- Keep the RLS-governed CRUD contract for authenticated users while removing
-- table-level privileges that are not part of the application access model.

revoke references, trigger, truncate
on table public.ordo_access_members
from authenticated;
