create or replace function public.review_profile_claim(
  claim_id uuid,
  decision text,
  review_note text default null::text
)
returns jsonb
language plpgsql
security definer
set search_path to 'public', 'auth'
as $function$
declare
  reviewer_id uuid := public.current_profile_id();
  claim public.profile_claims%rowtype;
  target_profile uuid;
  character_value text;
  requester_discord_provider_id text;
  requested_discord_id_value text;
begin
  select * into claim
  from public.profile_claims pc
  where pc.id = claim_id
  for update;

  if claim.id is null then
    raise exception 'claim_not_found';
  end if;
  if not public.has_campaign_role(claim.campaign_id, array['owner','master']) then
    raise exception 'dm_or_owner_required' using errcode = '42501';
  end if;
  if claim.status <> 'pending' then
    raise exception 'claim_already_reviewed';
  end if;
  if decision not in ('approved','rejected') then
    raise exception 'invalid_decision';
  end if;

  if decision = 'rejected' then
    update public.profile_claims
    set status = 'rejected', reviewer_profile_id = reviewer_id, reviewed_at = now(), review_note = nullif(trim(review_profile_claim.review_note), ''), updated_at = now()
    where id = claim.id;
    return jsonb_build_object('ok', true, 'status', 'rejected');
  end if;

  select ai.provider_id
    into requester_discord_provider_id
  from auth.identities ai
  where ai.user_id = claim.requester_auth_user_id
    and ai.provider = 'discord'
  order by ai.created_at asc
  limit 1;

  if requester_discord_provider_id is null or btrim(requester_discord_provider_id) = '' then
    raise exception 'discord_identity_required' using errcode = '42501';
  end if;

  requested_discord_id_value := nullif(trim(claim.requested_discord_id), '');
  if requested_discord_id_value is not null
     and requested_discord_id_value <> requester_discord_provider_id then
    raise exception 'discord_identity_mismatch' using errcode = '22023';
  end if;

  target_profile := claim.target_profile_id;
  if target_profile is null then
    insert into public.profiles (
      id, display_name, discord_id, discord_handle, roll20_name, default_character_name,
      source_system, source_key, auth_user_id, email, metadata
    ) values (
      gen_random_uuid(),
      coalesce(nullif(trim(claim.requested_display_name), ''), claim.requester_name, claim.requester_email, 'Novo jogador'),
      requester_discord_provider_id,
      nullif(trim(claim.requested_discord_handle), ''),
      nullif(trim(claim.requested_roll20_name), ''),
      nullif(trim(coalesce(claim.requested_character_names[1], '')), ''),
      'discord',
      requester_discord_provider_id,
      claim.requester_auth_user_id,
      claim.requester_email,
      jsonb_build_object('claimed_at', now(), 'claim_id', claim.id)
    ) returning id into target_profile;
  else
    if exists (
      select 1
      from public.profiles p
      where p.id = target_profile
        and p.discord_id is not null
        and p.discord_id <> requester_discord_provider_id
    ) then
      raise exception 'discord_identity_mismatch' using errcode = '22023';
    end if;

    update public.profiles
    set auth_user_id = coalesce(auth_user_id, claim.requester_auth_user_id),
        email = coalesce(nullif(email, ''), claim.requester_email),
        discord_id = coalesce(discord_id, requester_discord_provider_id),
        discord_handle = coalesce(nullif(trim(claim.requested_discord_handle), ''), discord_handle),
        roll20_name = coalesce(nullif(trim(claim.requested_roll20_name), ''), roll20_name),
        default_character_name = coalesce(nullif(trim(coalesce(claim.requested_character_names[1], '')), ''), default_character_name),
        metadata = coalesce(metadata, '{}'::jsonb) || jsonb_build_object('last_claim_approved_at', now(), 'last_claim_id', claim.id)
    where id = target_profile
      and (auth_user_id is null or auth_user_id = claim.requester_auth_user_id);
  end if;

  insert into public.campaign_members (campaign_id, profile_id, role)
  select claim.campaign_id, target_profile, 'player'
  where not exists (
    select 1 from public.campaign_members cm
    where cm.campaign_id = claim.campaign_id and cm.profile_id = target_profile
  );

  foreach character_value in array coalesce(claim.requested_character_names, '{}'::text[]) loop
    character_value := nullif(trim(character_value), '');
    if character_value is not null then
      insert into public.profile_characters (campaign_id, profile_id, character_name, approved_by, approved_at, player_note, metadata)
      select claim.campaign_id, target_profile, character_value, reviewer_id, now(), claim.player_note,
             jsonb_build_object('source_claim_id', claim.id)
      where not exists (
        select 1 from public.profile_characters pc
        where pc.campaign_id = claim.campaign_id
          and pc.profile_id = target_profile
          and lower(pc.character_name) = lower(character_value)
      );
    end if;
  end loop;

  update public.participants pt
  set profile_id = target_profile,
      needs_review = false,
      metadata = coalesce(pt.metadata, '{}'::jsonb) || jsonb_build_object('profile_claim_id', claim.id, 'linked_at', now())
  from public.sessions s
  where s.id = pt.session_id
    and s.campaign_id = claim.campaign_id
    and (
      (claim.requested_roll20_name is not null and pt.source_track_key = claim.requested_roll20_name)
      or (claim.requested_roll20_name is not null and pt.discord_handle = claim.requested_roll20_name)
      or (requester_discord_provider_id is not null and pt.discord_id = requester_discord_provider_id)
      or (claim.requested_display_name is not null and lower(pt.player_name) = lower(claim.requested_display_name))
    );

  update public.profile_claims
  set status = 'approved', target_profile_id = target_profile, reviewer_profile_id = reviewer_id,
      reviewed_at = now(), review_note = nullif(trim(review_profile_claim.review_note), ''), updated_at = now()
  where id = claim.id;

  return jsonb_build_object('ok', true, 'status', 'approved', 'profileId', target_profile);
end;
$function$;
