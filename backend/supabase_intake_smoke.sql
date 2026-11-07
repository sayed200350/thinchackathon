-- Run after claim_intake.sql in the SQL Editor. All test packets are rolled back.
begin;
select set_config('intake_test.id', gen_random_uuid()::text, true);
select set_config('intake_test.bad_id', gen_random_uuid()::text, true);

do $permissions$
declare
    role_name text;
    tbl regclass;
begin
    foreach role_name in array array['anon','authenticated'] loop
        if has_schema_privilege(role_name, 'claim_intake_private', 'USAGE,CREATE')
           or not has_function_privilege(role_name, 'public.submit_claim_intake(jsonb)', 'EXECUTE') then
            raise exception 'Unexpected intake privileges for %', role_name;
        end if;
        foreach tbl in array array['claim_intake_private.submissions'::regclass, 'claim_intake_private.documents'::regclass] loop
            if has_table_privilege(role_name, tbl, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
               or has_any_column_privilege(role_name, tbl, 'SELECT,INSERT,UPDATE,REFERENCES') then
                raise exception 'Unexpected table privileges for % on %', role_name, tbl;
            end if;
        end loop;
    end loop;
end;
$permissions$;

set local role anon;
do $claimant$
declare
    packet jsonb := jsonb_build_object(
        'request_id', current_setting('intake_test.id'), 'description', 'A parked car was scraped.',
        'incident_date', '2020-02-29', 'location', 'Example road', 'policy_number', 'DEMO-001',
        'email', 'example@example.test', 'injury_status','unknown',
        'documents', jsonb_build_array(jsonb_build_object('kind','incident_report','name','report.pdf',
                          'content_base64', encode(convert_to('%PDF-1.4 smoke attachment','UTF8'), 'base64')))
    );
    bad_packet jsonb;
    receipt jsonb;
    invalid jsonb;
begin
    receipt := public.submit_claim_intake(packet);
    if receipt <> jsonb_build_object('reference', receipt->>'reference', 'document_count',1,
                                      'missing_documents',jsonb_build_array('itemized_quote'))
       or receipt->>'reference' !~ '^CLM-[0-9a-f-]{36}$'
       or public.submit_claim_intake(packet) <> receipt then
        raise exception 'Unexpected receipt or failed idempotency.';
    end if;
    perform set_config('intake_test.ref', receipt->>'reference', true);
    begin
        perform public.submit_claim_intake(packet || '{"location":"Different city"}'::jsonb);
        raise exception 'Changed retry was accepted.';
    exception when sqlstate 'PT409' then null;
    end;
    bad_packet := packet || jsonb_build_object('request_id',current_setting('intake_test.bad_id'));
    for invalid in select value from jsonb_array_elements(jsonb_build_array(
        bad_packet || '{"extra":"unexpected"}'::jsonb,
        bad_packet || '{"injury_status":null}'::jsonb,
        bad_packet || '{"incident_date":"2025-02-29"}'::jsonb,
        bad_packet || '{"incident_date":"9999-01-01"}'::jsonb,
        bad_packet || '{"documents":null}'::jsonb,
        jsonb_set(bad_packet, '{documents,0,name}', to_jsonb('../report.pdf'::text)),
        jsonb_set(bad_packet, '{documents,0,content_base64}', to_jsonb('**!!'::text)),
        jsonb_set(bad_packet, '{documents,0,name}', to_jsonb('report.png'::text)),
        bad_packet || jsonb_build_object('documents', (packet->'documents') ||
          jsonb_build_array(jsonb_build_object('kind','damage_photo','name','bad.png','content_base64','dGVzdA==')))
    )) loop
        begin
            perform public.submit_claim_intake(invalid);
            raise exception 'Invalid packet accepted.';
        exception when sqlstate 'PT400' then null;
        end;
    end loop;
    begin
        perform content from claim_intake_private.documents limit 1;
        raise exception 'Public document read unexpectedly succeeded.';
    exception when insufficient_privilege then null;
    end;
end;
$claimant$;
reset role;

do $staff$
declare
    key uuid := current_setting('intake_test.id')::uuid;
    ref text := current_setting('intake_test.ref');
begin
    if (select count(*) from claim_intake_private.submissions where request_id = key and reference = ref) <> 1
       or (select count(*) from claim_intake_private.documents where reference = ref) <> 1 then
        raise exception 'Duplicate or missing test submission.';
    end if;
    if not exists (select from claim_intake_private.submissions s join claim_intake_private.documents d using (reference)
                   where s.reference = ref and s.email = 'example@example.test' and s.incident_date = date '2020-02-29'
                     and d.filename = 'report.pdf' and d.media_type = 'application/pdf'
                     and d.content = convert_to('%PDF-1.4 smoke attachment', 'UTF8')) then
        raise exception 'Private packet did not preserve the details and file bytes.';
    end if;
    if exists (select from claim_intake_private.submissions where request_id = current_setting('intake_test.bad_id')::uuid) then
        raise exception 'Invalid submission left a partial packet.';
    end if;
end;
$staff$;
select 'passed' as private_intake_and_attachments_check;
rollback;
