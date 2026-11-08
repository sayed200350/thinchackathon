-- Policy apply: engine configuration per uploaded policy version + one audit row per engine run.
-- Run once in the Supabase SQL editor (idempotent). Writes: backend with the service role key only.
-- Reads: everyone (anon/authenticated), like decisions.
--
-- Flow (POST /api/policies/{version}/apply, backend/policy_apply.py):
--   policies.content (uploaded text)  --LLM + verbatim citation check-->  policy_configs (immutable)
--   policy_configs + claims.source_fields  --engine-->  decisions (one row per open claim and version)
--                                                    +  policy_runs (append-only run log)

create table if not exists public.policy_configs (
  version text primary key references public.policies (version),
  policy_id text not null,
  baseline_version text not null,
  config jsonb not null check (jsonb_typeof(config) = 'object'),
  config_hash text not null,
  source_hash text not null,
  interpretation jsonb not null,
  created_at timestamptz not null default now()
);

create table if not exists public.policy_runs (
  id bigint generated always as identity primary key,
  version text not null references public.policy_configs (version),
  baseline_version text not null,
  config_hash text not null,
  claims_total integer not null,
  open_evaluated integer not null,
  closed_retained integer not null,
  changed integer not null,
  needs_recheck integer not null,
  rows jsonb not null,
  created_at timestamptz not null default now()
);

create or replace function public.reject_policy_config_change() returns trigger
language plpgsql as $fn$
begin
  raise exception 'policy_configs and policy_runs are append-only';
end
$fn$;

drop trigger if exists policy_configs_immutable on public.policy_configs;
create trigger policy_configs_immutable before update or delete on public.policy_configs for each row execute function public.reject_policy_config_change();

drop trigger if exists policy_runs_immutable on public.policy_runs;
create trigger policy_runs_immutable before update or delete on public.policy_runs for each row execute function public.reject_policy_config_change();

alter table public.policy_configs enable row level security;
alter table public.policy_runs enable row level security;

drop policy if exists "read all" on public.policy_configs;
create policy "read all" on public.policy_configs for select to anon, authenticated using (true);

drop policy if exists "read all" on public.policy_runs;
create policy "read all" on public.policy_runs for select to anon, authenticated using (true);

revoke all on public.policy_configs from anon, authenticated;
revoke all on public.policy_runs from anon, authenticated;
grant select on public.policy_configs to anon, authenticated;
grant select on public.policy_runs to anon, authenticated;
grant select, insert on public.policy_configs to service_role;
grant select, insert on public.policy_runs to service_role;
grant select on public.policies to service_role;
grant select, insert, update on public.decisions to service_role;
grant select on public.claims to service_role;

-- Comparison per claim: every applied version against the baseline it amends (closed claims keep
-- the baseline decision, so they never count as changed). The Policy Update dashboard reads this.
create or replace view public.v_policy_changes with (security_invoker = true) as
select
  pc.version,
  pc.baseline_version,
  b.case_id,
  b.case_status,
  b.recommendation                                  as recommendation_before,
  coalesce(n.recommendation, b.recommendation)      as recommendation_after,
  b.matched_rule                                    as rule_before,
  coalesce(n.matched_rule, b.matched_rule)          as rule_after,
  coalesce(n.explanation, b.explanation)            as explanation_after,
  coalesce(n.policy_clause, b.policy_clause)        as clause_after,
  n.case_id is not null and n.recommendation <> b.recommendation as changed
from public.policy_configs pc
join public.decisions b on b.policy_version = pc.baseline_version
left join public.decisions n on n.policy_version = pc.version and n.case_id = b.case_id;

grant select on public.v_policy_changes to anon, authenticated;
