-- Apply after the Retakt workbench tables and field-edit RPC exist.
-- Restrictive policies preserve existing checks for open claims and policy versions.
begin;
do $policies$
declare
  target text;
  tables text[] := array['claims','decisions','overrides','claim_field_changes',
                         'policies','validation_results','business_metrics'];
begin
  -- Newer deployments also keep the engine configuration and replay output in two tables.
  foreach target in array array['policy_configs','policy_runs'] loop
    if to_regclass(format('public.%I', target)) is not null then
      tables := array_append(tables, target);
    end if;
  end loop;
  foreach target in array tables loop
    execute format('alter table public.%I enable row level security', target);
    execute format('drop policy if exists workbench_staff_only on public.%I', target);
    execute format($sql$
      create policy workbench_staff_only on public.%I as restrictive for all to anon, authenticated
        using (current_user = 'authenticated' and auth.jwt()->'app_metadata'->'staff' = 'true'::jsonb)
        with check (current_user = 'authenticated' and auth.jwt()->'app_metadata'->'staff' = 'true'::jsonb)
    $sql$, target);
  end loop;
end $policies$;

-- This existing editor runs with its owner's permissions and needs its own staff check.
create or replace function public.update_claim_fields(p_case_id text, p_fields jsonb, p_editor text)
returns integer language plpgsql security definer set search_path to '' as $$
declare
  old_fields jsonb; k text; v jsonb; n integer := 0;
begin
  if coalesce(auth.jwt()->>'role', '') <> 'service_role'
     and (auth.jwt()->'app_metadata'->'staff') is distinct from 'true'::jsonb then
    raise insufficient_privilege using message = 'Insurer staff access required.';
  end if;
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

revoke all on function public.update_claim_fields(text,jsonb,text) from public, anon;
grant execute on function public.update_claim_fields(text,jsonb,text) to authenticated, service_role;
commit;
