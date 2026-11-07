-- Run after the official v1 fixture is seeded. Use the project's SQL Editor or
-- psql -X -v ON_ERROR_STOP=1 -f backend/supabase_smoke.sql with an admin connection.
-- The reviewer action is rolled back. PostgreSQL may still advance its identity sequence.
begin;

do $grants$
declare
    app_role text;
    relation_name text;
    relation_oid regclass;
    allowed_insert_columns text[] := array[
        'case_id', 'policy_version', 'original_recommendation', 'corrected_recommendation',
        'reason', 'reviewer', 'request_id'
    ];
    unexpected_column text;
begin
    foreach app_role in array array['anon', 'authenticated'] loop
        foreach relation_name in array array[
            'claims', 'decisions', 'validation_results', 'overrides', 'business_metrics',
            'v_compare', 'v_transition', 'v_change_check', 'v_error_rate', 'v_rule_impact', 'v_kpis'
        ] loop
            relation_oid := format('public.%I', relation_name)::regclass;
            if not has_table_privilege(app_role, relation_oid, 'SELECT') then
                raise exception '% needs SELECT on public.%', app_role, relation_name;
            end if;
            if has_table_privilege(app_role, relation_oid, 'DELETE,TRUNCATE,TRIGGER')
                or has_any_column_privilege(app_role, relation_oid, 'UPDATE,REFERENCES') then
                raise exception '% has unplanned write privileges on public.%', app_role, relation_name;
            end if;

            select a.attname into unexpected_column
            from pg_attribute a
            where a.attrelid = relation_oid and a.attnum > 0 and not a.attisdropped
              and has_column_privilege(app_role, relation_oid, a.attnum, 'INSERT')
              and (relation_name <> 'overrides' or a.attname <> all(allowed_insert_columns))
            limit 1;
            if found then
                raise exception '% has unplanned INSERT on public.%.%', app_role, relation_name, unexpected_column;
            end if;
        end loop;
    end loop;
end
$grants$;

set local role anon;

do $checks$
declare
    reason_text constant text := 'Smoke check: workshop requested a second review.';
    audit_id bigint;
begin
    if (select count(*) from public.claims) <> 26
       or (select count(*) from public.claims where case_status = 'closed') <> 2
       or (select count(*) from public.decisions where policy_version = 'v1') <> 26
       or (select count(*) from public.claims c join public.decisions d using (case_id, case_status)
           where d.policy_version = 'v1') <> 26 then
        raise exception 'Expected 26 matching v1 claims and decisions, including two closed cases.';
    end if;
    if (select count(*) from public.validation_results where policy_version = 'v1' and source = 'labelled') <> 14
       or (select count(*) from public.validation_results v join public.decisions d using (case_id, policy_version)
           where v.policy_version = 'v1' and v.source = 'labelled' and d.recommendation = v.expected) <> 14 then
        raise exception 'Expected all 14 official v1 development labels to match.';
    end if;

    insert into public.overrides (case_id, policy_version, original_recommendation,
                                  corrected_recommendation, reason, reviewer, request_id)
    values ('DEV-001', 'v1', 'routine_processing', 'human_review', reason_text,
            'Setup verification', gen_random_uuid()::text)
    returning id into audit_id;

    if not exists (
        select 1 from public.overrides o join public.decisions d using (case_id, policy_version)
        where o.id = audit_id and d.recommendation = 'routine_processing'
          and o.original_recommendation = d.recommendation and o.corrected_recommendation = 'human_review'
          and o.reviewer = 'Setup verification' and o.reason = reason_text
    ) then
        raise exception 'The reviewer could not reload the saved reason and original decision.';
    end if;
end
$checks$;

select 'passed' as v1_fixture_and_reviewer_check, current_user as verified_browser_role,
       (select count(*) from public.decisions where policy_version = 'v1') as v1_decisions,
       (select count(*) from public.validation_results where policy_version = 'v1' and source = 'labelled') as v1_labels,
       (select count(*) from public.claims where case_status = 'closed') as closed_claims;
rollback;
