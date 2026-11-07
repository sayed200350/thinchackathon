-- Apply after claim_evidence.sql and staff_corrections.sql.
begin;

create index if not exists submissions_staff_page
    on claim_intake_private.submissions(received_at desc, reference desc);

create or replace function public.claim_staff_read(p_service text, p_action text, p_data jsonb)
returns jsonb language plpgsql stable security definer set search_path = '' set timezone = 'UTC' as $$
declare
    fetch_limit integer;
    before_time timestamptz;
    before_ref text;
    target_ref text;
    file_position integer;
    records jsonb;
    original jsonb;
begin
    if p_service is null or length(p_service) not between 32 and 1024 or not exists (
        select from claim_intake_private.evidence_config where verifier=sha256(convert_to(p_service,'UTF8'))
    ) then
        raise sqlstate 'PT403' using message='Private staff service authentication required.';
    end if;
    if jsonb_typeof(p_data) is distinct from 'object' or p_action is null
       or p_action not in ('inbox','detail','file') then
        raise sqlstate 'PT400' using message='Invalid staff read operation.';
    end if;
    if p_action='inbox' then
        if jsonb_typeof(p_data->'fetch_limit') is distinct from 'number'
           or p_data->>'fetch_limit' !~ '^[0-9]{1,3}$' then
            raise sqlstate 'PT400' using message='Invalid page size.';
        end if;
        fetch_limit := (p_data->>'fetch_limit')::integer;
        if fetch_limit not between 1 and 101 then
            raise sqlstate 'PT400' using message='Invalid page size.';
        end if;
        before_ref := p_data->>'before_ref';
        if (before_ref is null) <> (p_data->>'before_time' is null) then
            raise sqlstate 'PT400' using message='Invalid inbox cursor.';
        end if;
        begin
            before_time := (p_data->>'before_time')::timestamptz;
        exception when invalid_datetime_format or datetime_field_overflow then
            raise sqlstate 'PT400' using message='Invalid inbox cursor.';
        end;
    else
        target_ref := p_data->>'reference';
        if target_ref is null then raise sqlstate 'PT400' using message='A claim reference is required.'; end if;
        fetch_limit := 1;
    end if;
    if p_action='file' then
        if jsonb_typeof(p_data->'position') is distinct from 'number' or p_data->>'position' !~ '^[0-9]{1,2}$' then
            raise sqlstate 'PT400' using message='Invalid attachment position.';
        end if;
        file_position := (p_data->>'position')::integer;
        if file_position >= 40 then raise sqlstate 'PT400' using message='Invalid attachment position.'; end if;
        select jsonb_build_object('name',d.filename,'content_base64',replace(encode(d.content,'base64'),E'\n',''))
            into original from claim_intake_private.documents d
            where d.reference=target_ref and d.position=file_position+1;
        if original is null then raise sqlstate 'PT404' using message='File not found.'; end if;
        return original;
    end if;

    with page as materialized (
        select s.reference,s.received_at,s.policy_number,s.incident_date,s.location,s.description,s.email,s.injury_status
          from claim_intake_private.submissions s
         where (target_ref is null or s.reference=target_ref)
           and (before_time is null or (s.received_at,s.reference)<(before_time,before_ref))
         order by s.received_at desc,s.reference desc limit fetch_limit
    ), rows as (
        select p.received_at,p.reference,
            jsonb_build_object(
                'reference',p.reference,'submitted_at',p.received_at,
                'claimant',to_jsonb(p)-'reference'-'received_at','receipt',r.receipt,
                'quote_versions',coalesce(jsonb_array_length(e.state->'quotes'),(
                    select count(*) from jsonb_array_elements(r.receipt->'documents') d where d->>'kind'='itemized_quote'
                )),
                'state',case when e.state is null or p_action='detail' then e.state
                    else (e.state-'history'-'notes'-'quotes') || jsonb_build_object('quotes',
                        case when jsonb_array_length(e.state->'quotes')>0 then
                            jsonb_build_array(((e.state->'quotes')->-1)-'lines') else '[]'::jsonb end)
                    end,
                'latest_correction',case when p_action='detail' then to_jsonb(c)-'reference'
                    when c.ordinal is not null then jsonb_build_object('ordinal',c.ordinal,'document_count',c.document_count,
                        'policy_version',c.policy_version,'recommendation',c.recommendation) end
            ) || case when p_action='detail' then jsonb_build_object('corrections',coalesce((
                select jsonb_agg(to_jsonb(x)-'reference' order by x.ordinal)
                  from claim_intake_private.staff_corrections x where x.reference=p.reference
            ),'[]'::jsonb)) else '{}'::jsonb end as record
          from page p
          left join claim_intake_private.evidence_cases e on e.reference=p.reference
          cross join lateral (select claim_intake_private.link_receipt(p.reference) as receipt) r
          left join lateral (select * from claim_intake_private.staff_corrections x where x.reference=p.reference
                              order by x.ordinal desc limit 1) c on true
    )
    select coalesce(jsonb_agg(record order by received_at desc,reference desc),'[]'::jsonb) into records from rows;
    if p_action='inbox' then return jsonb_build_object('records',records); end if;
    if jsonb_array_length(records)=0 then raise sqlstate 'PT404' using message='Submitted claim not found.'; end if;
    return records->0;
end $$;

revoke all on function public.claim_staff_read(text,text,jsonb) from public,anon,authenticated;
grant execute on function public.claim_staff_read(text,text,jsonb) to anon;
notify pgrst,'reload schema';
commit;
