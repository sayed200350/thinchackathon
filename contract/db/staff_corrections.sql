-- Apply after claim_evidence.sql, then staff_inbox.sql. Reuses the installed service verifier.
begin;

create table if not exists claim_intake_private.staff_corrections (
    reference text not null references claim_intake_private.submissions(reference),
    ordinal integer not null check (ordinal > 0),
    document_count integer not null check (document_count >= 0),
    revision integer not null check (revision = document_count + ordinal),
    request_id text not null,
    reviewer text not null,
    reason text not null,
    policy_version text not null,
    previous_recommendation text,
    recommendation text not null check (recommendation in ('routine_processing','request_information','human_review')),
    created_at timestamptz not null default now(),
    primary key(reference, ordinal),
    unique(reference, request_id)
);
alter table claim_intake_private.staff_corrections enable row level security;
revoke all on claim_intake_private.staff_corrections from public, anon, authenticated;

create or replace function public.claim_staff_correct(p_service text, p_reference text, p_data jsonb)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
    field_name text;
    max_len integer;
    docs integer;
    latest claim_intake_private.staff_corrections%rowtype;
    saved claim_intake_private.staff_corrections%rowtype;
    original text;
    effective text;
    version_name text;
    expected integer;
    current_revision integer;
    status integer;
begin
    if p_service is null or length(p_service) not between 32 and 1024 or not exists (
        select from claim_intake_private.evidence_config where verifier = sha256(convert_to(p_service,'UTF8'))
    ) then
        raise sqlstate 'PT403' using message='Private evidence service authentication required.';
    end if;
    if jsonb_typeof(p_data) is distinct from 'object' then
        raise sqlstate 'PT400' using message='Invalid correction.';
    end if;
    for field_name, max_len in values ('request_id',128), ('reviewer',128), ('reason',2000),
                                      ('policy_version',32), ('recommendation',32) loop
        if jsonb_typeof(p_data->field_name) is distinct from 'string'
           or length(btrim(p_data->>field_name)) not between 1 and max_len then
            raise sqlstate 'PT400' using message='Invalid correction field.';
        end if;
    end loop;
    if p_data->>'recommendation' not in ('routine_processing','request_information','human_review')
       or jsonb_typeof(p_data->'expected_revision') is distinct from 'number'
       or p_data->>'expected_revision' !~ '^(0|[1-9][0-9]{0,8})$' then
        raise sqlstate 'PT400' using message='Invalid recommendation or expected revision.';
    end if;
    expected := (p_data->>'expected_revision')::integer;

    -- The claimant, legacy and garage appenders also lock the private link before writing any files.
    -- A submit-only legacy claim has no link; serialize its reviewers on the submission itself.
    perform 1 from claim_intake_private.links where reference=p_reference for update;
    perform 1 from claim_intake_private.submissions where reference=p_reference for update;
    if not found then
        raise sqlstate 'PT404' using message='Unknown submitted claim.';
    end if;
    select count(*) into docs from claim_intake_private.documents where reference=p_reference;
    select * into latest from claim_intake_private.staff_corrections
        where reference=p_reference order by ordinal desc limit 1;
    current_revision := docs + coalesce(latest.ordinal,0);
    select * into saved from claim_intake_private.staff_corrections
        where reference=p_reference and request_id=p_data->>'request_id';
    if found then
        if saved.revision <> expected + 1 or saved.reviewer <> p_data->>'reviewer'
           or saved.reason <> p_data->>'reason' or saved.policy_version <> p_data->>'policy_version'
           or saved.recommendation <> p_data->>'recommendation' then
            raise sqlstate 'PT409' using message='That request ID belongs to a different correction.';
        end if;
        status := 200;
    else
        select state#>>'{decision,recommendation}', state#>>'{decision,policy_version}' into original, version_name
            from claim_intake_private.evidence_cases where reference=p_reference;
        if expected <> current_revision or p_data->>'policy_version' <> coalesce(version_name,'v1') then
            raise sqlstate 'PT409' using message='The evidence, policy or staff decision changed. Reload this claim.';
        end if;
        effective := case when latest.document_count=docs then latest.recommendation else original end;
        if effective=p_data->>'recommendation' then
            raise sqlstate 'PT400' using message='Choose a different recommendation for a correction.';
        end if;
        current_revision := current_revision + 1;
        insert into claim_intake_private.staff_corrections
            (reference,ordinal,document_count,revision,request_id,reviewer,reason,policy_version,previous_recommendation,recommendation)
            values (p_reference,coalesce(latest.ordinal,0)+1,docs,current_revision,p_data->>'request_id',
                    p_data->>'reviewer',p_data->>'reason',p_data->>'policy_version',effective,p_data->>'recommendation')
            returning * into saved;
        status := 201;
    end if;
    return jsonb_build_object('reference',p_reference,'revision',current_revision,'correction',to_jsonb(saved),'status',status);
end $$;
revoke all on function public.claim_staff_correct(text,text,jsonb) from public, anon, authenticated;
grant execute on function public.claim_staff_correct(text,text,jsonb) to anon;
notify pgrst,'reload schema';
commit;
