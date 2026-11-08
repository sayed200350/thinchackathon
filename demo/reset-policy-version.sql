-- Demo reset: removes ONE uploaded policy version completely (default v2) so it can be uploaded
-- and applied again live. v1, claims and all other versions stay untouched.
-- Run in the Supabase SQL editor. Change the version in the first line if needed.
do $$
declare
  target text := 'v2';
begin
  if target = 'v1' then
    raise exception 'v1 is the baseline and must never be removed';
  end if;
  alter table public.policy_runs disable trigger policy_runs_immutable;
  alter table public.policy_configs disable trigger policy_configs_immutable;
  delete from public.policy_runs where version = target;
  delete from public.policy_configs where version = target;
  alter table public.policy_runs enable trigger policy_runs_immutable;
  alter table public.policy_configs enable trigger policy_configs_immutable;
  delete from public.decisions where policy_version = target;  -- cascades to overrides of that version
  delete from public.policies where version = target;
end $$;
