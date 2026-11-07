-- Run after claim_intake.sql and intake_links.sql. Exercises browser-role RPCs.
-- Only generated fictional packets are touched. All test changes roll back.
begin;

do $access$
declare role_name text;
begin
    foreach role_name in array array['anon','authenticated'] loop
        if has_schema_privilege(role_name, 'claim_intake_private','USAGE,CREATE')
           or has_table_privilege(role_name,'claim_intake_private.links','SELECT,INSERT,UPDATE,DELETE,TRUNCATE')
           or has_table_privilege(role_name,'claim_intake_private.addition_requests','SELECT,INSERT,UPDATE,DELETE,TRUNCATE')
           or not has_function_privilege(role_name,'public.claim_intake_link(text,text,jsonb)','EXECUTE')
        then raise exception 'Incorrect permissions for %',role_name; end if;
    end loop;
end;
$access$;
set local role anon;

do $test$
declare
    token text := replace(gen_random_uuid()::text || gen_random_uuid()::text,'-','');
    stranger text := replace(gen_random_uuid()::text || gen_random_uuid()::text,'-','');
    pdf jsonb := jsonb_build_object('kind','incident_report','name','report.pdf','content_base64',
                                   encode(convert_to('%PDF-1.4 synthetic','UTF8'),'base64'));
    photo jsonb := jsonb_build_object('kind','damage_photo','name','damage.png','content_base64',
                                     encode(decode('89504e470d0a1a0a00','hex'),'base64'));
    quote jsonb := pdf || '{"name":"quote.pdf","kind":"itemized_quote"}';
    draft jsonb := jsonb_build_object('values',jsonb_build_object('description','a draft'), 'step',1,
                                     'sources','{"description":{"name":"report.pdf","page":1}}'::jsonb,
                                     'documents',jsonb_build_array(pdf));
    packet jsonb := jsonb_build_object('request_id',gen_random_uuid(),'description','Fictional parking collision.',
        'incident_date','2020-05-01','location','Example street','policy_number','TEST','email','test@example.invalid',
        'injury_status','unknown','documents',jsonb_build_array(photo,photo,photo));
    saved jsonb;
    receipt jsonb;
    result jsonb;
    submit_data jsonb;
    append_data jsonb;
    invalid jsonb;
begin
    saved := public.claim_intake_link('save',token,jsonb_build_object('draft',draft,'expected_revision',0));
    if saved <> '{"status":"draft","revision":1}'
       or public.claim_intake_link('save',token,jsonb_build_object('draft',draft,'expected_revision',0)) <> saved
       or public.claim_intake_link('open',token,'{}') <> saved || jsonb_build_object('draft',draft)
    then raise exception 'Draft save, resume or retry failed.'; end if;
    begin
        perform public.claim_intake_link('open',stranger,'{}');
        raise exception 'Unknown bearer opened a private link.';
    exception when sqlstate 'PT404' then null;
    end;
    begin
        perform public.claim_intake_link('save',token,jsonb_build_object('draft',draft || '{"step":2}', 'expected_revision',0));
        raise exception 'Stale draft update succeeded.';
    exception when sqlstate 'PT409' then null;
    end;
    for invalid in select value from jsonb_array_elements(jsonb_build_array(
        draft || '{"unbounded":"x"}',draft || '{"values":{"location":null}}', draft || '{"step":100}',
        draft || '{"sources":{"description":{"name":"a.pdf","page":"1"}}}',
        draft || '{"documents":[{"kind":"incident_report","name":"wrong.pdf","content_base64":"dGVzdA=="}]}',
        draft || '{"documents":[{"kind":null,"name":"wrong.pdf","content_base64":"JVBERi0="}]}'
    )) loop
        begin
            perform public.claim_intake_link('save',token,jsonb_build_object('draft',invalid,'expected_revision',1));
            raise exception 'Invalid draft accepted.';
        exception when sqlstate 'PT400' then null;
        end;
    end loop;
    submit_data := jsonb_build_object('payload',packet,'expected_revision',1);
    begin
        perform public.claim_intake_link('submit',token,submit_data || '{"expected_revision":0}');
        raise exception 'Stale draft submission succeeded.';
    exception when sqlstate 'PT409' then null;
    end;
    receipt := public.claim_intake_link('submit',token,submit_data);
    if receipt->>'status' <> 'submitted' or receipt->>'document_count'<>'3'
       or receipt->'missing_documents' <> '["incident_report","itemized_quote"]' or receipt ? 'draft'
       or receipt ? 'email' or jsonb_array_length(receipt->'documents') <> 3
       or public.claim_intake_link('open',token,'{}') <> receipt
    then raise exception 'Wrong submitted receipt.'; end if;
    begin
        perform public.claim_intake_link('submit',stranger,submit_data || '{"expected_revision":0}');
        raise exception 'Another token accessed the original submission.';
    exception when sqlstate 'PT409' then null;
    end;
    begin
        perform public.claim_intake_link('save',token,jsonb_build_object('draft',draft,'expected_revision',1));
        raise exception 'A saved draft reappeared after submission.';
    exception when sqlstate 'PT409' then null;
    end;
    append_data := jsonb_build_object('request_id',gen_random_uuid(),'documents',jsonb_build_array(pdf,quote));
    begin
        perform public.claim_intake_link('append',token,append_data || jsonb_build_object('documents',jsonb_build_array(pdf,pdf)));
        raise exception 'Same type added twice.';
    exception when sqlstate 'PT409' then null;
    end;
    result := public.claim_intake_link('append',token,append_data);
    if result->>'document_count' <> '5' or result->'missing_documents'<>'[]'::jsonb
       or result->'documents'->4 <> '{"name":"quote.pdf","kind":"itemized_quote"}'::jsonb
       or public.claim_intake_link('append',token,append_data) <> result
       or public.claim_intake_link('open',token,'{}') <> result
       or public.claim_intake_link('submit',token,submit_data) <> result
    then raise exception 'Follow-up addition, receipt or retry failed.'; end if;
    begin
        perform public.claim_intake_link('append',token,append_data || jsonb_build_object('documents',jsonb_build_array(quote)));
        raise exception 'Upload ID reused for different files.';
    exception when sqlstate 'PT409' then null;
    end;
    packet := packet || jsonb_build_object('request_id',gen_random_uuid());
    perform public.submit_claim_intake(packet);
    begin
        perform public.claim_intake_link('submit',stranger,jsonb_build_object('payload',packet,'expected_revision',0));
        raise exception 'Existing unlinked claim was rebound.';
    exception when sqlstate 'PT409' then null;
    end;
    perform set_config('intake_link_test.reference',receipt->>'reference',true);
end;
$test$;
reset role;

do $staff$
declare ref text := current_setting('intake_link_test.reference');
begin
    if not exists (select from claim_intake_private.links l where l.reference=ref and l.draft is null)
       or (select count(*) from claim_intake_private.documents d where d.reference=ref) <> 5
       or not exists (select from claim_intake_private.documents d where d.reference=ref and d.position=5
                      and d.content=convert_to('%PDF-1.4 synthetic','UTF8'))
    then raise exception 'Private records inconsistent.'; end if;
end;
$staff$;
select 'passed' as private_draft_and_followup_check;
rollback;
