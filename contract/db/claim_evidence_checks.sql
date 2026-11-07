-- Run in the SQL editor after the evidence migration. All mock records roll back.
begin;
do $setup$
declare
    test_key text := replace(gen_random_uuid()::text || gen_random_uuid()::text, '-', '');
begin
    if has_table_privilege('anon', 'claim_intake_private.evidence_cases', 'SELECT')
        or has_table_privilege('anon', 'claim_intake_private.evidence_config', 'SELECT')
        or has_schema_privilege('anon', 'claim_intake_private', 'USAGE') then
        raise exception 'The public browser role can access private evidence directly.';
    end if;
    -- This verifier is visible only to this transaction and is always rolled back.
    update claim_intake_private.evidence_config set verifier=sha256(convert_to(test_key,'UTF8'));
    perform set_config('evidence_check.secret',test_key,true);
end $setup$;
set local role anon;
do $test$
declare
    service text := current_setting('evidence_check.secret');
    token text := replace(gen_random_uuid()::text || gen_random_uuid()::text, '-', '');
    ref text := 'CLM-' || gen_random_uuid()::text;
    quote jsonb := jsonb_build_object('kind','itemized_quote','name','sample.pdf','content_base64','JVBERi0=');
    revised jsonb := quote || '{"content_base64":"JVBERi0xLjQ="}'::jsonb;
    packet jsonb := jsonb_build_object('request_id',gen_random_uuid(),'description','Fictional parking incident',
        'incident_date','2025-02-01','location','Test street','policy_number','FAKE','email','demo@example.invalid',
        'injury_status','no','documents',jsonb_build_array(quote));
    initial jsonb := '{"history":[{"quote_version":1}]}'::jsonb;
    updated jsonb := '{"history":[{"quote_version":1},{"quote_version":2}]}'::jsonb;
    appended jsonb := jsonb_build_object('request_id',gen_random_uuid(),'hash',repeat('ab',32),'offset',1,
        'documents',jsonb_build_array(revised),'state',updated);
    out jsonb;
begin
    begin
        perform public.claim_evidence_io('incorrect','staff','',jsonb_build_object('reference',ref));
        raise exception 'Invalid evidence credential accepted.';
    exception when sqlstate 'PT403' then null;
    end;
    out := public.claim_evidence_io(service,'submit',token,jsonb_build_object('payload',packet,'state',initial,
        'hash',repeat('cd',32),'revision',0,'reference',ref));
    if out->'state' is distinct from initial then raise exception 'First evidence record missing.'; end if;
    out := public.claim_evidence_io(service,'append',token,appended);
    if out->'state' is distinct from updated or out#>>'{receipt,document_count}' is distinct from '2'
        or public.claim_evidence_io(service,'append',token,appended) is distinct from out
        or public.claim_evidence_io(service,'open',token,'{}') is distinct from out then
        raise exception 'Updated evidence, count, retry or reopen failed.';
    end if;
    if public.claim_evidence_io(service,'staff','',jsonb_build_object('reference',ref))->'state' is distinct from updated
        or public.claim_evidence_io(service,'file','',jsonb_build_object('reference',ref,'position',0))->>'content_base64' is distinct from quote->>'content_base64'
        or public.claim_evidence_io(service,'file','',jsonb_build_object('reference',ref,'position',1))->>'content_base64' is distinct from revised->>'content_base64' then
        raise exception 'Staff history or original bytes changed.';
    end if;
end $test$;
rollback;
select 'Private evidence, revisions, original files and access checks passed. Test data rolled back.' as result;
