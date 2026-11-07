-- Exercise direct Lovable and backend writes against an isolated synthetic case.
-- Run through an admin connection after schema.sql and reviewer_corrections.sql.
begin;
select set_config('policy_replay.test_case', 'SMOKE-' || gen_random_uuid()::text, true);
insert into public.claims (case_id, case_status, claim_summary, source_fields)
    values (current_setting('policy_replay.test_case'), 'open', 'Temporary reviewer test', '{}');
insert into public.decisions (case_id, policy_version, case_status, recommendation, matched_rule, explanation)
    values (current_setting('policy_replay.test_case'), 'v1', 'open', 'routine_processing', 'v1.3', 'Temporary reviewer test');

set local role anon;
do $checks$
declare
    test_id text := current_setting('policy_replay.test_case');
    request_a text := gen_random_uuid()::text;
    request_b text := gen_random_uuid()::text;
begin
    if public.reviewer_save_correction(test_id, 'v1', 'human_review', 'Conflicting evidence', 'Reviewer A', request_a, 0) <> 'created' then
        raise exception 'Expected new correction.';
    end if;
    insert into public.overrides (case_id, policy_version, original_recommendation, corrected_recommendation, reason, reviewer, request_id)
        values (test_id, 'v1', 'routine_processing', 'request_information', 'Missing report', 'Reviewer B', request_b);
    if public.reviewer_save_correction(test_id, 'v1', 'human_review', 'Conflicting evidence', 'Reviewer A', request_a, 0) <> 'replayed' then
        raise exception 'Expected earlier request replay.';
    end if;
    begin
        perform public.reviewer_save_correction(test_id, 'v1', 'routine_processing', 'Reason', 'Reviewer A', gen_random_uuid()::text, 1);
        raise exception 'An out-of-date correction was accepted.';
    exception when sqlstate 'PT409' then null;
    end;
    begin
        perform public.reviewer_save_correction(test_id, 'v1', 'human_review', 'Different reason', 'Reviewer A', request_a, 0);
        raise exception 'A conflicting retry was accepted.';
    exception when sqlstate 'PT409' then null;
    end;
    begin
        perform public.reviewer_save_correction(test_id, 'v1', 'request_information', 'Repeat', 'Reviewer A', gen_random_uuid()::text, 2);
        raise exception 'An unchanged route was accepted.';
    exception when sqlstate 'PT400' then null;
    end;
    perform public.reviewer_save_correction(test_id, 'v1', 'routine_processing', 'Evidence complete', 'Reviewer A', gen_random_uuid()::text, 2);
    if (select array_agg(o.revision order by o.created_at, o.id) from public.overrides o where o.case_id = test_id)
       is distinct from array[1,2,3]::bigint[] then
        raise exception 'Audit sequence does not match database append order.';
    end if;
    if not exists (select 1 from public.v_compare v where v.case_id = test_id and v.override_count = 3
                    and v.latest_correction = 'routine_processing' and v.recommendation_v1 = 'routine_processing') then
        raise exception 'The queue disagrees with audit history.';
    end if;
end;
$checks$;
select 'passed' as reviewer_correction_check;
rollback;
