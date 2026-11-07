-- Policy Replay — Supabase Schema v1 (Contract)
-- Abgeleitet aus contract/decision-result.md + contract/example-result-DEV-001.json
-- (Engine-Ergebnis von A, Stand 2026-11-07 13:27) und contract/batch-output.md.
-- Feldnamen folgen dem Engine-Contract: case_id, case_status, matched_rule, supporting_facts.
-- Idempotent: kann im Supabase SQL Editor mehrfach ausgeführt werden.
-- Schreibrechte: engine -> decisions, validator -> validation_results (beide Service Role Key),
-- App -> overrides (anon Key, nur Insert), BWL -> business_metrics (Table Editor).

-- ---------------------------------------------------------------------------
-- Tabellen
-- ---------------------------------------------------------------------------

-- Ein Engine-Ergebnis pro Fall und Policy-Version (1:1 das JSON aus dem Contract).
create table if not exists public.decisions (
  case_id          text        not null,
  policy_version   text        not null,                       -- 'v1', 'v2', ...
  case_status      text        not null check (case_status in ('open', 'closed')),
  recommendation   text        not null,                       -- v1: routine_processing | request_information | human_review
  matched_rule     text        not null,                       -- v1: v1.1 | v1.2 | v1.3 | v1.missing
  supporting_facts jsonb       not null default '{}'::jsonb,   -- entscheidende Fakten, normalisiert (bool, Zahl, null = unbekannt)
  explanation      text        not null,                       -- ein englischer Satz für Reviewer
  policy_clause    text,                                       -- OFFEN (Frage an A): Klauseltext zu matched_rule, nicht im Engine-JSON
  created_at       timestamptz not null default now(),
  primary key (case_id, policy_version)
);

-- Reviewer-Korrekturen, nur anhängen (Audit-Historie). Die Engine-Entscheidung bleibt unverändert.
create table if not exists public.overrides (
  id                       bigint generated always as identity primary key,
  case_id                  text        not null,
  policy_version           text        not null,
  original_recommendation  text        not null,   -- decisions.recommendation zum Zeitpunkt der Korrektur
  corrected_recommendation text        not null,
  reason                   text        not null check (length(trim(reason)) > 0),
  reviewer                 text        not null check (length(trim(reviewer)) > 0),
  request_id               text        unique,     -- vom Frontend erzeugt (crypto.randomUUID()), schützt vor Doppel-Speichern
  created_at               timestamptz not null default now(),
  foreign key (case_id, policy_version) references public.decisions (case_id, policy_version) on delete cascade
);
create index if not exists overrides_case_idx on public.overrides (case_id, policy_version, created_at);

-- Erwartete Ergebnisse zur Prüfung der Engine (Labels + eigene Edge Cases).
create table if not exists public.validation_results (
  case_id         text    not null,
  policy_version  text    not null,
  expected        text    not null,              -- erwartete recommendation
  expected_change boolean,                       -- soll sich die Empfehlung gegenüber v1 ändern? (nur für v2 sinnvoll)
  source          text    not null check (source in ('labelled', 'edge_case')),
  primary key (case_id, policy_version)
);

-- Business-Case-Kennzahlen, gepflegt im Supabase Table Editor.
create table if not exists public.business_metrics (
  key   text primary key,
  label text not null,
  value numeric,
  unit  text,
  note  text
);

-- ---------------------------------------------------------------------------
-- Views (security_invoker: RLS der Basistabellen gilt auch für anon)
-- ---------------------------------------------------------------------------

-- Ein Fall pro Zeile: v1 gegen v2 plus letzte Reviewer-Korrektur.
create or replace view public.v_compare with (security_invoker = true) as
select
  coalesce(d1.case_id, d2.case_id)               as case_id,
  coalesce(d1.case_status, d2.case_status)       as case_status,
  d1.recommendation                              as recommendation_v1,
  d2.recommendation                              as recommendation_v2,
  d1.matched_rule                                as rule_v1,
  d2.matched_rule                                as rule_v2,
  d1.explanation                                 as explanation_v1,
  d2.explanation                                 as explanation_v2,
  (d1.recommendation is not null and d2.recommendation is not null
     and d1.recommendation <> d2.recommendation) as changed,
  case when coalesce(d1.case_status, d2.case_status) = 'closed' then false
       when d2.recommendation is null then null            -- v2 steht noch aus
       else d1.recommendation <> d2.recommendation end     as needs_recheck,
  o.corrected_recommendation                     as latest_correction,
  o.policy_version                               as latest_correction_version,
  (select count(*) from public.overrides x
     where x.case_id = coalesce(d1.case_id, d2.case_id)) as override_count
from (select * from public.decisions where policy_version = 'v1') d1
full join (select * from public.decisions where policy_version = 'v2') d2
  on d1.case_id = d2.case_id
left join lateral (
  select corrected_recommendation, policy_version
  from public.overrides x
  where x.case_id = coalesce(d1.case_id, d2.case_id)
  order by x.created_at desc, x.id desc
  limit 1
) o on true;

-- Übergänge v1 -> v2 (Sankey / Matrix).
create or replace view public.v_transition with (security_invoker = true) as
select case_status, recommendation_v1, recommendation_v2, count(*) as cases
from public.v_compare
where recommendation_v1 is not null and recommendation_v2 is not null
group by case_status, recommendation_v1, recommendation_v2;

-- Regel-Impact: wie viele Fälle entscheidet jede Regel, und wie viele davon ändern sich v1 -> v2.
create or replace view public.v_rule_impact with (security_invoker = true) as
select
  d.policy_version,
  d.matched_rule,
  count(*)                                              as cases,
  count(*) filter (where d.case_status = 'open')        as open_cases,
  count(*) filter (where c.changed)                     as changed_cases,
  count(*) filter (where c.needs_recheck)               as needs_recheck_cases
from public.decisions d
join public.v_compare c on c.case_id = d.case_id
group by d.policy_version, d.matched_rule;

-- Vier-Felder-Prüfung: erwartete Änderung (validation_results v2) gegen tatsächliche Änderung (Engine).
create or replace view public.v_change_check with (security_invoker = true) as
select
  v.case_id,
  v.source,
  c.case_status,
  v.expected_change,
  c.changed as actual_change,
  case
    when c.changed is null or v.expected_change is null then 'pending'
    when v.expected_change and c.changed         then 'true_positive'   -- Änderung erwartet und erkannt
    when not v.expected_change and c.changed     then 'false_positive'  -- unnötiger Recheck
    when v.expected_change and not c.changed     then 'false_negative'  -- verpasste Änderung
    else 'true_negative'
  end as quadrant
from public.validation_results v
left join public.v_compare c on c.case_id = v.case_id
where v.policy_version = 'v2';

-- Fehlerquote pro Version und Quelle (Nenner: alle Fälle mit Erwartung, wie eval/ von A).
create or replace view public.v_error_rate with (security_invoker = true) as
select
  v.policy_version,
  v.source,
  count(*)                                                        as cases,
  count(d.case_id)                                                as decided,
  count(*) filter (where d.recommendation = v.expected)           as correct,
  count(*) filter (where d.recommendation <> v.expected)          as errors,
  count(*) filter (where d.recommendation = 'routine_processing'
                     and v.expected <> 'routine_processing')      as incorrect_routine,
  count(*) filter (where d.recommendation = 'human_review'
                     and v.expected <> 'human_review')            as unnecessary_review,
  round(count(*) filter (where d.recommendation <> v.expected)::numeric
        / nullif(count(*), 0), 4)                                 as error_rate
from public.validation_results v
left join public.decisions d
  on d.case_id = v.case_id and d.policy_version = v.policy_version
group by v.policy_version, v.source;

-- KPI-Kacheln fürs Dashboard (key, label, value, unit, target). Enthält business_metrics.
create or replace view public.v_kpis with (security_invoker = true) as
select 'open_claims' as key, 'Open claims' as label,
       count(*) filter (where case_status = 'open')::numeric as value, 'claims' as unit, null::numeric as target
  from public.v_compare
union all
select 'needs_recheck', 'Open claims needing a second look',
       count(*) filter (where needs_recheck)::numeric, 'claims', null
  from public.v_compare
union all
select 'closed_changed', 'Closed claims changed by v2',
       (count(*) filter (where case_status = 'closed' and changed)
        + (select count(*) from public.overrides o
             join public.decisions d using (case_id, policy_version)
            where d.case_status = 'closed'))::numeric,
       'claims', 0
  from public.v_compare
union all
select 'overrides', 'Reviewer corrections', count(*)::numeric, 'corrections', null
  from public.overrides
union all
select 'error_rate_' || policy_version, 'Error rate ' || policy_version,
       round(sum(errors)::numeric / nullif(sum(cases), 0), 4), 'ratio', 0
  from public.v_error_rate
 group by policy_version
union all
select key, label, value, unit, null
  from public.business_metrics;

-- ---------------------------------------------------------------------------
-- Row Level Security: Lesen für alle, Insert nur auf overrides.
-- Service Role (engine, validator) umgeht RLS.
-- ---------------------------------------------------------------------------
alter table public.decisions          enable row level security;
alter table public.overrides          enable row level security;
alter table public.validation_results enable row level security;
alter table public.business_metrics   enable row level security;

drop policy if exists "read all" on public.decisions;
create policy "read all" on public.decisions          for select to anon, authenticated using (true);
drop policy if exists "read all" on public.overrides;
create policy "read all" on public.overrides          for select to anon, authenticated using (true);
drop policy if exists "read all" on public.validation_results;
create policy "read all" on public.validation_results for select to anon, authenticated using (true);
drop policy if exists "read all" on public.business_metrics;
create policy "read all" on public.business_metrics   for select to anon, authenticated using (true);

-- Insert für alle, aber nur auf offene Claims (geschlossene Claims bleiben unverändert, KPI closed_changed = 0).
drop policy if exists "insert open claims" on public.overrides;
create policy "insert open claims" on public.overrides for insert to anon, authenticated
  with check (exists (
    select 1 from public.decisions d
     where d.case_id = overrides.case_id
       and d.policy_version = overrides.policy_version
       and d.case_status = 'open'
  ));

grant select on public.decisions, public.overrides, public.validation_results, public.business_metrics,
                public.v_compare, public.v_transition, public.v_rule_impact, public.v_change_check,
                public.v_error_rate, public.v_kpis
  to anon, authenticated;
grant insert (case_id, policy_version, original_recommendation, corrected_recommendation, reason, reviewer, request_id)
  on public.overrides to anon, authenticated;
