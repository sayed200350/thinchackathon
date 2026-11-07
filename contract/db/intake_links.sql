-- Apply after claim_intake.sql. Only the bearer secret opens a packet.
begin;

-- Original submission still accepts three files. Reserve two further positions for
-- the incident report and itemized quote when they arrive after initial intake.
alter table claim_intake_private.documents drop constraint if exists documents_position_check;
alter table claim_intake_private.documents add constraint documents_position_check check (position between 1 and 5);

create table if not exists claim_intake_private.links (
    token_hash bytea primary key check (octet_length(token_hash) = 32),
    revision integer not null default 0,
    draft jsonb,
    reference text unique references claim_intake_private.submissions(reference),
    check (reference is null or draft is null)
);
create table if not exists claim_intake_private.addition_requests (
    reference text not null references claim_intake_private.submissions(reference),
    request_id uuid not null,
    payload_hash bytea not null,
    primary key (reference, request_id)
);
revoke all on claim_intake_private.links, claim_intake_private.addition_requests from public, anon, authenticated;
alter table claim_intake_private.links enable row level security;
alter table claim_intake_private.addition_requests enable row level security;

-- Serialize ownership checks with the original submit-only endpoint, including
-- an unlinked request arriving while a new link with that request ID is submitted.
create or replace function claim_intake_private.lock_packet_request()
returns trigger language plpgsql set search_path = '' as $$
begin
    perform pg_advisory_xact_lock(hashtextextended('intake_request:' || new.request_id::text, 0));
    return new;
end;
$$;
create or replace trigger lock_packet_request before insert on claim_intake_private.submissions
    for each row execute function claim_intake_private.lock_packet_request();

create or replace function claim_intake_private.checked_file(doc jsonb) returns bytea
language plpgsql immutable set search_path = '' as $$
declare
    name text := doc->>'name';
    encoded text := doc->>'content_base64';
    bytes bytea;
begin
    if jsonb_typeof(doc) is distinct from 'object'
       or not (doc ?& array['kind','name','content_base64'])
       or doc - array['kind','name','content_base64'] <> '{}'::jsonb
       or exists (select from unnest(array['kind','name','content_base64']) k where jsonb_typeof(doc->k) <> 'string')
       or doc->>'kind' not in ('incident_report','itemized_quote','damage_photo')
       or length(name) not between 1 and 180 or name ~ '[[:cntrl:]/\\]' or name ~ '^[[:space:]]|[[:space:]]$'
       or length(encoded) not between 4 and 2796204 then
        raise sqlstate 'PT400' using message = 'Invalid attachment metadata or size.';
    end if;
    begin
        bytes := decode(encoded, 'base64');
    exception when invalid_parameter_value then
        raise sqlstate 'PT400' using message = 'Invalid attachment encoding.';
    end;
    if octet_length(bytes) not between 1 and 2097152 or replace(encode(bytes,'base64'), E'\n','') <> encoded
       or not ((name ~* '\.pdf$' and substring(bytes from 1 for 5) = decode('255044462d','hex'))
            or (name ~* '\.png$' and substring(bytes from 1 for 8) = decode('89504e470d0a1a0a','hex'))
            or (name ~* '\.jpe?g$' and substring(bytes from 1 for 3) = decode('ffd8ff','hex'))) then
        raise sqlstate 'PT400' using message = 'Attach a valid PDF, JPEG or PNG of up to 2 MiB.';
    end if;
    return bytes;
end;
$$;

create or replace function claim_intake_private.check_draft(d jsonb) returns void
language plpgsql immutable set search_path = '' as $$
declare
    field_limits constant jsonb := '{"description":2000,"incident_date":10,"location":160,"policy_number":80,"email":254,"injury_status":7}';
    field text;
    v jsonb;
begin
    if jsonb_typeof(d) is distinct from 'object' or not (d ?& array['values','step','documents','sources'])
       or d - array['values','step','documents','sources'] <> '{}'::jsonb
       or jsonb_typeof(d->'values') <> 'object' or jsonb_typeof(d->'sources') <> 'object'
       or jsonb_typeof(d->'step') <> 'number' or d->>'step' !~ '^([0-9]|1[0-6])$'
       or jsonb_typeof(d->'documents') <> 'array' then
        raise sqlstate 'PT400' using message = 'Invalid draft.';
    end if;
    if jsonb_array_length(d->'documents') > 3 then
        raise sqlstate 'PT400' using message = 'Attach up to three files.';
    end if;
    for field, v in select * from jsonb_each(d->'values') loop
        if not (field_limits ? field) or jsonb_typeof(v) <> 'string'
           or length(d->'values'->>field) > (field_limits->>field)::integer then
            raise sqlstate 'PT400' using message = 'Invalid draft field.';
        end if;
    end loop;
    for field, v in select * from jsonb_each(d->'sources') loop
        if not (field_limits ? field) or jsonb_typeof(v) <> 'object'
           or not (v ?& array['name','page']) or v - array['name','page'] <> '{}'::jsonb
           or jsonb_typeof(v->'name') <> 'string' or length(v->>'name') not between 1 and 180
           or v->>'name' ~ '[[:cntrl:]/\\]' or jsonb_typeof(v->'page') <> 'number'
           or v->>'page' !~ '^([1-9][0-9]{0,2}|1000)$' then
            raise sqlstate 'PT400' using message = 'Invalid source citation.';
        end if;
    end loop;
    perform claim_intake_private.checked_file(value) from jsonb_array_elements(d->'documents');
end;
$$;

create or replace function claim_intake_private.link_receipt(ref text) returns jsonb
language sql stable set search_path = '' as $$
    select jsonb_build_object(
        'status', 'submitted', 'reference', ref, 'document_count', count(*),
        'documents', coalesce(jsonb_agg(jsonb_build_object('kind',kind,'name',filename) order by position), '[]'::jsonb),
        'missing_documents', array_remove(array[
            case when count(*) filter (where kind='incident_report')=0 then 'incident_report' end,
            case when count(*) filter (where kind='itemized_quote')=0 then 'itemized_quote' end
        ], null)
    ) from claim_intake_private.documents where reference=ref;
$$;

create or replace function public.claim_intake_link(p_action text, p_token text, p_data jsonb) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
    key_hash bytea;
    link claim_intake_private.links%rowtype;
    expected integer;
    id uuid;
    saved_ref text;
    packet jsonb;
    files jsonb;
    doc jsonb;
    file_bytes bytea;
    file_mime text;
    position_next integer;
    old_digest bytea;
    digest bytea;
begin
    if p_token is null or p_token !~ '^[0-9a-f]{64}$' or p_action is null
       or p_action not in ('open','save','submit','append') or jsonb_typeof(p_data) is distinct from 'object' then
        raise sqlstate 'PT400' using message = 'Invalid private link request.';
    end if;
    key_hash := sha256(convert_to(p_token,'UTF8'));
    if p_action = 'open' then
        if p_data <> '{}'::jsonb then
            raise sqlstate 'PT400' using message = 'Invalid private link request.';
        end if;
        select * into link from claim_intake_private.links where token_hash=key_hash;
        if not found then
            raise sqlstate 'PT404' using message = 'Private link not found.';
        end if;
        if link.reference is not null then
            return claim_intake_private.link_receipt(link.reference);
        end if;
        return jsonb_build_object('status','draft','revision',link.revision,'draft',link.draft);
    end if;

    if p_action in ('save','submit') then
        if jsonb_typeof(p_data->'expected_revision') is distinct from 'number'
           or p_data->>'expected_revision' !~ '^(0|[1-9][0-9]{0,8})$' then
            raise sqlstate 'PT400' using message = 'Invalid draft revision.';
        end if;
        expected := (p_data->>'expected_revision')::integer;
        insert into claim_intake_private.links (token_hash) values (key_hash) on conflict do nothing;
    end if;
    select * into link from claim_intake_private.links where token_hash=key_hash for update;
    if not found then
        raise sqlstate 'PT404' using message = 'Private link not found.';
    end if;

    if p_action = 'save' then
        if not (p_data ? 'draft') or p_data - array['draft','expected_revision'] <> '{}'::jsonb then
            raise sqlstate 'PT400' using message = 'Invalid draft.';
        end if;
        if link.reference is not null then
            raise sqlstate 'PT409' using message = 'This claim has already been submitted.';
        end if;
        perform claim_intake_private.check_draft(p_data->'draft');
        if p_data->'draft'=link.draft and expected in (link.revision,link.revision-1) then
            return jsonb_build_object('status','draft','revision',link.revision);
        end if;
        if expected <> link.revision then
            raise sqlstate 'PT409' using message = 'This draft changed. Reopen the private link.';
        end if;
        update claim_intake_private.links set revision=revision+1, draft=p_data->'draft' where token_hash=key_hash;
        return jsonb_build_object('status','draft','revision',link.revision+1);
    end if;

    if p_action = 'submit' then
        packet := p_data->'payload';
        if p_data - array['payload','expected_revision'] <> '{}'::jsonb
           or (packet->>'request_id') is null
           or packet->>'request_id' !~* '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' then
            raise sqlstate 'PT400' using message = 'Invalid claim submission.';
        end if;
        id := (packet->>'request_id')::uuid;
        perform pg_advisory_xact_lock(hashtextextended('intake_request:' || id::text, 0));
        select reference into saved_ref from claim_intake_private.submissions where request_id=id;
        if saved_ref is distinct from link.reference then
            raise sqlstate 'PT409' using message = 'This submission conflicts with the existing claim.';
        end if;
        if link.reference is null and expected <> link.revision then
            raise sqlstate 'PT409' using message = 'This draft changed. Reopen the private link.';
        end if;
        saved_ref := public.submit_claim_intake(packet)->>'reference';
        update claim_intake_private.links set reference=saved_ref, draft=null where token_hash=key_hash;
        return claim_intake_private.link_receipt(saved_ref);
    end if;

    if link.reference is null then
        raise sqlstate 'PT409' using message = 'Submit the claim before adding follow-up documents.';
    end if;
    files := p_data->'documents';
    if p_data - array['documents','request_id'] <> '{}'::jsonb or jsonb_typeof(files) is distinct from 'array'
       or jsonb_typeof(p_data->'request_id') is distinct from 'string'
       or p_data->>'request_id' !~* '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' then
        raise sqlstate 'PT400' using message = 'Invalid upload request.';
    end if;
    if jsonb_array_length(files) not between 1 and 3 or octet_length(files::text)>8500000 then
        raise sqlstate 'PT400' using message = 'Choose between one and three files of up to 2 MiB each.';
    end if;
    id := (p_data->>'request_id')::uuid;
    digest := sha256(convert_to(files::text,'UTF8'));
    select r.payload_hash into old_digest from claim_intake_private.addition_requests r
        where r.reference=link.reference and r.request_id=id;
    if found then
        if old_digest<>digest then
            raise sqlstate 'PT409' using message = 'This upload request was already used for different files.';
        end if;
        return claim_intake_private.link_receipt(link.reference);
    end if;
    select count(*) into position_next from claim_intake_private.documents where reference=link.reference;
    for doc in select value from jsonb_array_elements(files) loop
        file_bytes := claim_intake_private.checked_file(doc);
        if doc->>'kind' not in ('incident_report','itemized_quote') or exists (
            select from claim_intake_private.documents d where d.reference=link.reference and d.kind=doc->>'kind'
        ) then
            raise sqlstate 'PT409' using message = 'Only one file per outstanding document type can be added. Reopen the link.';
        end if;
        file_mime := case when doc->>'name' ~* '\.pdf$' then 'application/pdf'
                          when doc->>'name' ~* '\.png$' then 'image/png' else 'image/jpeg' end;
        position_next := position_next + 1;
        insert into claim_intake_private.documents (reference,position,kind,filename,media_type,content)
            values (link.reference,position_next,doc->>'kind',doc->>'name',file_mime,file_bytes);
    end loop;
    insert into claim_intake_private.addition_requests values (link.reference,id,digest);
    return claim_intake_private.link_receipt(link.reference);
end;
$$;

revoke all on function claim_intake_private.lock_packet_request(), claim_intake_private.checked_file(jsonb),
    claim_intake_private.check_draft(jsonb), claim_intake_private.link_receipt(text) from public, anon, authenticated;
revoke all on function public.claim_intake_link(text,text,jsonb) from public, anon, authenticated;
grant execute on function public.claim_intake_link(text,text,jsonb) to anon, authenticated;
notify pgrst, 'reload schema';
commit;
