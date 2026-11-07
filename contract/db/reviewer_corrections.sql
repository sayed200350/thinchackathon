-- Apply after schema.sql. Keep the original decision and all existing reviewer entries.
begin;

alter table public.overrides add column if not exists revision bigint;
with ordered as (
    select id, row_number() over (
        partition by case_id, policy_version order by created_at, id
    ) as revision
    from public.overrides
)
update public.overrides o set revision = ordered.revision
from ordered where ordered.id = o.id and o.revision is null;

alter table public.overrides alter column revision set not null;
create unique index if not exists overrides_case_version_revision_idx
    on public.overrides (case_id, policy_version, revision);

-- The existing Lovable direct insert and the API both pass through this trigger.
-- Assign the revision *after* taking the same case lock as the RPC. Identity
-- values and transaction timestamps alone are allocated before that lock.
create or replace function public.reviewer_stamp_correction()
returns trigger language plpgsql security invoker set search_path = '' as $stamp$
begin
    perform pg_advisory_xact_lock(hashtextextended('policy_replay.override:' || new.case_id, 0));
    select coalesce(max(o.revision) filter (where o.policy_version = new.policy_version), 0) + 1,
           greatest(clock_timestamp(), max(o.created_at) + interval '1 microsecond')
      into new.revision, new.created_at
      from public.overrides o where o.case_id = new.case_id;
    return new;
end;
$stamp$;

create or replace trigger reviewer_stamp_correction before insert on public.overrides
    for each row execute function public.reviewer_stamp_correction();
revoke all on function public.reviewer_stamp_correction() from public, anon, authenticated;

create or replace function public.reviewer_save_correction(
    p_case_id text, p_policy_version text, p_recommendation text, p_reason text,
    p_reviewer text, p_request_id text, p_expected_revision bigint
) returns text language plpgsql security invoker set search_path = '' as $save$
declare
    original_route text;
    case_state text;
    current_revision bigint;
    current_route text;
    prior public.overrides%rowtype;
begin
    p_request_id := btrim(p_request_id);
    p_reviewer := btrim(p_reviewer);
    p_reason := btrim(p_reason);
    p_policy_version := btrim(p_policy_version);
    p_recommendation := btrim(p_recommendation);
    if nullif(p_request_id, '') is null or nullif(p_reviewer, '') is null
       or nullif(p_reason, '') is null or nullif(p_policy_version, '') is null
       or p_recommendation is null or p_recommendation not in ('routine_processing', 'request_information', 'human_review')
       or p_expected_revision is null or p_expected_revision < 0 then
        raise sqlstate 'PT400' using message = 'A correction needs a route, reviewer, reason, policy version, request ID and nonnegative expected revision.';
    end if;
    if not exists (select 1 from public.claims c where c.case_id = p_case_id) then
        raise sqlstate 'PT404' using message = 'Unknown case_id.';
    end if;

    perform pg_advisory_xact_lock(hashtextextended('policy_replay.override:' || p_case_id, 0));
    -- Identical retries succeed even after another reviewer has appended an entry.
    select * into prior from public.overrides where request_id = p_request_id;
    if found then
        if prior.case_id = p_case_id and prior.policy_version = p_policy_version
           and prior.revision - 1 = p_expected_revision and prior.reviewer = p_reviewer
           and prior.reason = p_reason and prior.corrected_recommendation = p_recommendation then
            return 'replayed';
        end if;
        raise sqlstate 'PT409' using message = 'request_id already belongs to a different correction.';
    end if;

    select d.recommendation, d.case_status into original_route, case_state from public.decisions d
        where d.case_id = p_case_id and d.policy_version = p_policy_version;
    if not found then
        raise sqlstate 'PT409' using message = 'Policy version mismatch. Reload this claim.';
    end if;
    if case_state = 'closed' then
        raise sqlstate 'PT409' using message = 'Closed claims retain their original decision.';
    end if;
    select o.revision, o.corrected_recommendation into current_revision, current_route
        from public.overrides o where o.case_id = p_case_id and o.policy_version = p_policy_version
        order by o.revision desc limit 1;
    if coalesce(current_revision, 0) <> p_expected_revision then
        raise sqlstate 'PT409' using message = 'Another reviewer updated this claim. Reload before saving.';
    end if;
    if coalesce(current_route, original_route) = p_recommendation then
        raise sqlstate 'PT400' using message = 'Choose a different recommendation for a correction.';
    end if;
    insert into public.overrides (
        case_id, policy_version, original_recommendation, corrected_recommendation, reason, reviewer, request_id
    ) values (p_case_id, p_policy_version, original_route, p_recommendation, p_reason, p_reviewer, p_request_id);
    return 'created';
exception when unique_violation then
    -- Request IDs are unique across claims. Simultaneous reuse on different cases must conflict.
    raise sqlstate 'PT409' using message = 'A correction conflicts with an existing entry. Reload this claim.';
end;
$save$;

revoke all on function public.reviewer_save_correction(text,text,text,text,text,text,bigint) from public;
grant execute on function public.reviewer_save_correction(text,text,text,text,text,text,bigint) to anon, authenticated;
notify pgrst, 'reload schema';
commit;
