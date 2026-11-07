-- Claimants submit one private packet through the RPC. Staff read these two
-- tables from the Supabase dashboard. No claimant data enters the public demo queue.
begin;

create schema if not exists claim_intake_private;
revoke all on schema claim_intake_private from public, anon, authenticated;

create table if not exists claim_intake_private.submissions (
    reference text primary key default ('CLM-' || gen_random_uuid()::text),
    request_id uuid not null unique,
    payload_hash bytea not null,
    received_at timestamptz not null default now(),
    description text not null,
    incident_date date not null,
    location text not null,
    policy_number text not null,
    email text not null,
    injury_status text not null check (injury_status in ('yes', 'no', 'unknown'))
);

create table if not exists claim_intake_private.documents (
    reference text not null references claim_intake_private.submissions(reference),
    position smallint not null check (position between 1 and 3),
    kind text not null check (kind in ('incident_report', 'itemized_quote', 'damage_photo')),
    filename text not null,
    media_type text not null,
    content bytea not null check (octet_length(content) between 1 and 2097152),
    primary key (reference, position)
);

revoke all on claim_intake_private.submissions, claim_intake_private.documents from public, anon, authenticated;
alter table claim_intake_private.submissions enable row level security;
alter table claim_intake_private.documents enable row level security;

create or replace function public.submit_claim_intake(p_payload jsonb) returns jsonb
language plpgsql security definer set search_path = '' as $intake$
declare
    required_text constant text[] := array['request_id','description','incident_date','location','policy_number','email','injury_status'];
    id uuid;
    details text;
    place text;
    policy text;
    address text;
    incident date;
    files jsonb;
    packet_hash bytea;
    existing_hash bytea;
    claim_ref text;
    file jsonb;
    filename text;
    encoded text;
    contents bytea;
    mime text;
    item_no smallint := 0;
    missing text[] := array['incident_report','itemized_quote'];
begin
    if jsonb_typeof(p_payload) is distinct from 'object'
       or p_payload - (required_text || array['documents']) <> '{}'::jsonb
       or exists (select 1 from unnest(required_text) k where jsonb_typeof(p_payload->k) is distinct from 'string')
       or jsonb_typeof(p_payload->'documents') is distinct from 'array' then
        raise sqlstate 'PT400' using message = 'Invalid claim fields.';
    end if;
    if p_payload->>'request_id' !~* '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' then
        raise sqlstate 'PT400' using message = 'Use a UUIDv4 request ID.';
    end if;
    id := (p_payload->>'request_id')::uuid;
    details := btrim(p_payload->>'description', E' \t\n\r');
    place := btrim(p_payload->>'location', E' \t\n\r');
    policy := btrim(p_payload->>'policy_number', E' \t\n\r');
    address := btrim(p_payload->>'email', E' \t\n\r');
    if length(details) not between 10 and 2000 or length(place) not between 1 and 160
       or length(policy) not between 1 and 80 or length(address) > 254
       or address !~ '^[^[:space:]@]+@[^[:space:]@.]+(\.[^[:space:]@.]+)+$'
       or p_payload->>'injury_status' not in ('yes','no','unknown') then
        raise sqlstate 'PT400' using message = 'Check the incident, policy and contact details.';
    end if;
    if p_payload->>'incident_date' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' then
        raise sqlstate 'PT400' using message = 'Use an incident date in YYYY-MM-DD format.';
    end if;
    begin
        incident := (p_payload->>'incident_date')::date;
    exception when datetime_field_overflow or invalid_datetime_format then
        raise sqlstate 'PT400' using message = 'Use a valid incident date.';
    end;
    if incident > (now() at time zone 'Europe/Berlin')::date then
        raise sqlstate 'PT400' using message = 'The incident date cannot be in the future.';
    end if;
    files := p_payload->'documents';
    if jsonb_array_length(files) > 3 then
        raise sqlstate 'PT400' using message = 'Attach up to three files.';
    end if;
    -- Bound the input before hashing or decoding. Check each file again by decoded size and signature.
    for file in select value from jsonb_array_elements(files) loop
        if jsonb_typeof(file) is distinct from 'object' or file - array['kind','name','content_base64'] <> '{}'::jsonb
           or exists (select 1 from unnest(array['kind','name','content_base64']) k where jsonb_typeof(file->k) is distinct from 'string')
           or file->>'kind' not in ('incident_report','itemized_quote','damage_photo')
           or length(file->>'name') not between 1 and 180 or (file->>'name') ~ '[[:cntrl:]/\\]'
           or (file->>'name') ~ '^[[:space:]]|[[:space:]]$'
           or (file->>'name') !~* '\.(pdf|jpe?g|png)$'
           or length(file->>'content_base64') not between 4 and 2796204 then
            raise sqlstate 'PT400' using message = 'Invalid attachment metadata or size.';
        end if;
        missing := array_remove(missing, file->>'kind');
    end loop;
    packet_hash := sha256(convert_to(jsonb_build_array(id, details, p_payload->>'incident_date', place, policy, address, p_payload->>'injury_status', files)::text, 'UTF8'));
    -- A concurrent duplicate waits for the first transaction to commit or roll back.
    insert into claim_intake_private.submissions (request_id, payload_hash, description, incident_date, location, policy_number, email, injury_status)
        values (id, packet_hash, details, incident, place, policy, address, p_payload->>'injury_status')
        on conflict (request_id) do nothing returning reference into claim_ref;
    if claim_ref is null then
        select s.reference, s.payload_hash into claim_ref, existing_hash from claim_intake_private.submissions s where s.request_id = id;
        if existing_hash is distinct from packet_hash then
            raise sqlstate 'PT409' using message = 'This request ID was already used for a different submission.';
        end if;
    else
        for file in select value from jsonb_array_elements(files) loop
            item_no := item_no + 1;
            filename := file->>'name';
            encoded := file->>'content_base64';
            begin
                contents := decode(encoded, 'base64');
            exception when invalid_parameter_value then
                raise sqlstate 'PT400' using message = 'Invalid attachment encoding.';
            end;
            if octet_length(contents) not between 1 and 2097152
               or replace(encode(contents, 'base64'), E'\n', '') <> encoded then
                raise sqlstate 'PT400' using message = 'Invalid attachment encoding or size.';
            end if;
            if filename ~* '\.pdf$' and substring(contents from 1 for 5) = decode('255044462d','hex') then
                mime := 'application/pdf';
            elsif filename ~* '\.png$' and substring(contents from 1 for 8) = decode('89504e470d0a1a0a','hex') then
                mime := 'image/png';
            elsif filename ~* '\.jpe?g$' and substring(contents from 1 for 3) = decode('ffd8ff','hex') then
                mime := 'image/jpeg';
            else
                raise sqlstate 'PT400' using message = 'Attach a PDF, PNG, or JPEG file with a matching filename.';
            end if;
            insert into claim_intake_private.documents (reference, position, kind, filename, media_type, content)
                values (claim_ref, item_no, file->>'kind', filename, mime, contents);
        end loop;
    end if;
    return jsonb_build_object('reference', claim_ref, 'document_count', jsonb_array_length(files), 'missing_documents', to_jsonb(missing));
end;
$intake$;

revoke all on function public.submit_claim_intake(jsonb) from public;
grant execute on function public.submit_claim_intake(jsonb) to anon, authenticated;
notify pgrst, 'reload schema';
commit;
