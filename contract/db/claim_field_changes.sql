-- Reviewer edits of raw claim fields (claims.source_fields) with a per-field audit log (live, created by Lovable).
-- Run after schema.sql in the Supabase SQL editor; idempotent.
-- Browser roles read the log and call update_claim_fields(); they never write the table directly.
-- Editing a field does not re-run the engine; decisions change only through POST /api/policies/{version}/apply.

create table if not exists public.claim_field_changes (
  id         bigint generated always as identity primary key,
  case_id    text not null references public.claims(case_id) on delete cascade,
  field      text not null,
  old_value  jsonb,
  new_value  jsonb,
  editor     text not null,                                -- self-reported name, 1-80 chars
  created_at timestamptz not null default now()
);
grant select on public.claim_field_changes to anon, authenticated;
grant all on public.claim_field_changes to service_role;
alter table public.claim_field_changes enable row level security;
drop policy if exists "read all" on public.claim_field_changes;
create policy "read all" on public.claim_field_changes for select to anon, authenticated using (true);
create index if not exists claim_field_changes_case_id_created_at_idx
  on public.claim_field_changes(case_id, created_at desc);

-- Updates the given keys of claims.source_fields (only keys that already exist, never case_id),
-- writes one log row per actually changed field and mirrors case_status / claim_summary. Returns the count.
create or replace function public.update_claim_fields(p_case_id text, p_fields jsonb, p_editor text)
returns integer language plpgsql security definer set search_path to '' as $$
declare
  old_fields jsonb; k text; v jsonb; n integer := 0;
begin
  p_editor := btrim(coalesce(p_editor,''));
  if p_editor = '' or length(p_editor) > 80 then
    raise sqlstate 'PT400' using message = 'Editor name required.';
  end if;
  if jsonb_typeof(p_fields) is distinct from 'object' then
    raise sqlstate 'PT400' using message = 'Invalid fields.';
  end if;
  select source_fields into old_fields from public.claims where case_id = p_case_id for update;
  if not found then raise sqlstate 'PT404' using message = 'Unknown case_id.'; end if;
  for k, v in select key, value from jsonb_each(p_fields) loop
    if k = 'case_id' or not (old_fields ? k) then
      raise sqlstate 'PT400' using message = 'Field not editable: ' || k;
    end if;
    if k = 'case_status' and v #>> '{}' not in ('open','closed') then
      raise sqlstate 'PT400' using message = 'Status must be open or closed.';
    end if;
    if old_fields->k is distinct from v then
      insert into public.claim_field_changes(case_id, field, old_value, new_value, editor)
        values (p_case_id, k, old_fields->k, v, p_editor);
      old_fields := jsonb_set(old_fields, array[k], v);
      n := n + 1;
    end if;
  end loop;
  if n > 0 then
    update public.claims set source_fields = old_fields,
      case_status = coalesce(old_fields->>'case_status', case_status),
      claim_summary = coalesce(old_fields->>'claim_summary', claim_summary)
    where case_id = p_case_id;
  end if;
  return n;
end $$;
grant execute on function public.update_claim_fields(text, jsonb, text) to anon, authenticated;
