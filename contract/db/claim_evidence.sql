-- Render with python3 -m backend.evidence_setup --sql-output /tmp/thinc-evidence.sql.
-- The deployment copy contains only a SHA-256 verifier. Never commit either secret.
begin;
create table if not exists claim_intake_private.evidence_config (
    singleton boolean primary key default true check(singleton), verifier bytea not null
);
insert into claim_intake_private.evidence_config(singleton,verifier)
    values(true,decode('__SERVICE_KEY_SHA256__','hex')) on conflict do nothing;
do $$ begin
    if not exists(select from claim_intake_private.evidence_config where verifier=decode('__SERVICE_KEY_SHA256__','hex')) then
        raise exception 'Evidence application credential differs from the installed credential';
    end if;
end $$;
create table if not exists claim_intake_private.evidence_cases (
    reference text primary key references claim_intake_private.submissions(reference),
    initial_hash text not null, state jsonb not null
);
revoke all on claim_intake_private.evidence_cases,claim_intake_private.evidence_config from public,anon,authenticated;
alter table claim_intake_private.evidence_cases enable row level security;
alter table claim_intake_private.evidence_config enable row level security;
alter table claim_intake_private.documents drop constraint if exists documents_position_check;
alter table claim_intake_private.documents add constraint documents_position_check check(position between 1 and 40);
alter table claim_intake_private.documents drop constraint if exists documents_content_check;
alter table claim_intake_private.documents add constraint documents_content_check check(octet_length(content) between 1 and
    (case when kind='damage_photo' and media_type in ('image/jpeg','image/png') then 12582912 else 2097152 end));

create or replace function claim_intake_private.evidence_record(ref text) returns jsonb
language sql stable set search_path='' as $$
    select jsonb_build_object('receipt',claim_intake_private.link_receipt(ref),'state',
        (select state from claim_intake_private.evidence_cases where reference=ref));
$$;
-- Protect derived history if an older client calls the original public write function directly.
create or replace function claim_intake_private.check_evidence_writer() returns trigger
language plpgsql set search_path='' as $$
begin
    if exists(select from claim_intake_private.evidence_cases where reference=new.reference)
       and current_setting('thinc.evidence_writer',true) is distinct from 'on' then
        raise sqlstate 'PT409' using message='Reopen the private receipt to add evidence.';
    end if;
    return new;
end $$;
create or replace trigger check_evidence_writer before insert on claim_intake_private.documents
    for each row execute function claim_intake_private.check_evidence_writer();

create or replace function public.claim_evidence_io(p_service text,p_action text,p_token text,p_data jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare
    lk claim_intake_private.links%rowtype;
    k bytea;
    ref text;
    known_ref text;
    rev integer;
    request uuid;
    fingerprint bytea;
    docs jsonb;
    doc jsonb;
    packet jsonb;
    item integer;
    mime text;
    output jsonb;
begin
    if p_service is null or length(p_service) not between 32 and 1024 or not exists (
      select from claim_intake_private.evidence_config where verifier=sha256(convert_to(p_service,'UTF8'))) then
        raise sqlstate 'PT403' using message='Private evidence service authentication required.';
    end if;
    if jsonb_typeof(p_data) is distinct from 'object' or p_action is null or p_action not in
      ('staff','file','open','save','submit','append') then
        raise sqlstate 'PT400' using message='Invalid evidence operation.';
    end if;
    if p_action in ('staff','file') then
        ref := p_data->>'reference';
        if not exists(select from claim_intake_private.evidence_cases where reference=ref) then
            raise sqlstate 'PT404' using message='Claim evidence not found.';
        end if;
        if p_action='staff' then
            return claim_intake_private.evidence_record(ref) || jsonb_build_object('incident_date',
                (select incident_date from claim_intake_private.submissions where reference=ref));
        end if;
        select jsonb_build_object('name',filename,'content_base64',replace(encode(content,'base64'),E'\n','')) into output
            from claim_intake_private.documents where reference=ref and position=(p_data->>'position')::integer+1;
        if output is null then raise sqlstate 'PT404' using message='File not found.'; end if;
        return output;
    end if;
    if p_token is null or p_token !~ '^[0-9a-f]{64}$' then raise sqlstate 'PT400' using message='Invalid private link.'; end if;
    k := sha256(convert_to(p_token,'UTF8'));
    if p_action in ('save','submit') then
        insert into claim_intake_private.links(token_hash) values(k) on conflict do nothing;
    end if;
    select * into lk from claim_intake_private.links where token_hash=k for update;
    if not found then raise sqlstate 'PT404' using message='Private link not found.'; end if;
    ref := lk.reference;
    if p_action='open' then
        if ref is not null then return claim_intake_private.evidence_record(ref); end if;
        return jsonb_build_object('receipt',jsonb_build_object('status','draft','revision',lk.revision,'draft',lk.draft));
    end if;
    if p_action='save' then
        if ref is not null then raise sqlstate 'PT409' using message='Claim already submitted.'; end if;
        rev := (p_data->>'revision')::integer;
        if lk.draft=p_data->'draft' and rev in (lk.revision,lk.revision-1) then
            return jsonb_build_object('receipt',jsonb_build_object('status','draft','revision',lk.revision));
        end if;
        if rev is distinct from lk.revision then raise sqlstate 'PT409' using message='This draft changed. Reopen the link.'; end if;
        update claim_intake_private.links set draft=p_data->'draft', revision=revision+1 where token_hash=k;
        return jsonb_build_object('receipt',jsonb_build_object('status','draft','revision',rev+1));
    end if;
    perform set_config('thinc.evidence_writer','on',true);
    if p_action='submit' then
        packet := p_data->'payload';
        request := (packet->>'request_id')::uuid;
        perform pg_advisory_xact_lock(hashtextextended('intake_request:'||request::text,0));
        select reference into known_ref from claim_intake_private.submissions where request_id=request;
        if known_ref is not null or ref is not null then
            if ref=known_ref and exists(select from claim_intake_private.evidence_cases
                where reference=ref and initial_hash=p_data->>'hash') then return claim_intake_private.evidence_record(ref); end if;
            raise sqlstate 'PT409' using message='This submission conflicts with an existing claim.';
        end if;
        if lk.revision is distinct from (p_data->>'revision')::integer then
            raise sqlstate 'PT409' using message='This draft changed. Reopen the link.'; end if;
        ref := p_data->>'reference';
        insert into claim_intake_private.submissions(reference,request_id,payload_hash,description,incident_date,location,policy_number,email,injury_status)
            values(ref,request,sha256(convert_to(packet::text,'UTF8')),packet->>'description',(packet->>'incident_date')::date,
                packet->>'location',packet->>'policy_number',packet->>'email',packet->>'injury_status');
        insert into claim_intake_private.evidence_cases values(ref,p_data->>'hash',p_data->'state');
        update claim_intake_private.links set reference=ref,draft=null where token_hash=k;
        docs := packet->'documents';
        item := 0;
    else
        if ref is null then raise sqlstate 'PT409' using message='Submit the claim before adding paperwork.'; end if;
        request := (p_data->>'request_id')::uuid;
        select payload_hash into fingerprint from claim_intake_private.addition_requests where reference=ref and request_id=request;
        if found then
            if fingerprint<>decode(p_data->>'hash','hex') then raise sqlstate 'PT409' using message='Request was used for different files.'; end if;
            return claim_intake_private.evidence_record(ref);
        end if;
        select count(*) into item from claim_intake_private.documents where reference=ref;
        if item is distinct from (p_data->>'offset')::integer then raise sqlstate 'PT409' using message='The receipt changed. Reopen it.'; end if;
        docs := p_data->'documents';
        if item+jsonb_array_length(docs)>40 then raise sqlstate 'PT400' using message='Evidence file limit reached.'; end if;
        if exists(select from jsonb_array_elements(docs) a where a->>'kind'='incident_report') and
            exists(select from claim_intake_private.documents where reference=ref and kind='incident_report') then
            raise sqlstate 'PT409' using message='Incident report already received.';
        end if;
        insert into claim_intake_private.addition_requests values(ref,request,decode(p_data->>'hash','hex'));
        update claim_intake_private.evidence_cases set state=p_data->'state' where reference=ref;
        if not found then raise sqlstate 'PT409' using message='No evidence history found.'; end if;
    end if;
    for doc in select value from jsonb_array_elements(docs) loop
        item := item+1;
        mime := case when doc->>'name' ~* '\.pdf$' then 'application/pdf'
                when doc->>'name' ~* '\.png$' then 'image/png' else 'image/jpeg' end;
        insert into claim_intake_private.documents(reference,position,kind,filename,media_type,content)
            values(ref,item,doc->>'kind',doc->>'name',mime,decode(doc->>'content_base64','base64'));
    end loop;
    return claim_intake_private.evidence_record(ref);
end $$;
revoke all on function claim_intake_private.evidence_record(text),claim_intake_private.check_evidence_writer() from public,anon,authenticated;
revoke all on function public.claim_evidence_io(text,text,text,jsonb) from public,anon,authenticated;
grant execute on function public.claim_evidence_io(text,text,text,jsonb) to anon;
notify pgrst,'reload schema';
commit;
