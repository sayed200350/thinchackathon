-- Policy-Versionen als Text speichern und vergleichen (Contract-Erweiterung, Entwurf von B).
-- Zweck: Die Reviewer-App lädt eine neue Policy hoch, speichert sie hier und vergleicht sie klauselweise mit der alten.
-- Läuft nach schema.sql im Supabase SQL Editor, idempotent. Keine Änderung an bestehenden Tabellen.
-- Eine Version ist unveränderlich (kein Update/Delete für anon): jede Änderung ist eine neue Version.

create table if not exists public.policies (
  policy_version  text        primary key check (policy_version ~ '^v[0-9]+$'),
  title           text        not null,
  source_filename text,                                   -- z. B. policy_v2.docx; null bei eingefügtem Text
  raw_text        text        not null check (length(trim(raw_text)) > 0),
  clauses         jsonb       not null check (jsonb_typeof(clauses) = 'array' and jsonb_array_length(clauses) > 0),
                                                          -- [{"id":"rule-1","label":"Rule 1","text":"..."}], Reihenfolge wie im Dokument
  uploaded_by     text        not null default 'unknown',
  created_at      timestamptz not null default now()
);

alter table public.policies enable row level security;
drop policy if exists "read all" on public.policies;
create policy "read all" on public.policies for select to anon, authenticated using (true);
drop policy if exists "insert new version" on public.policies;
create policy "insert new version" on public.policies for insert to anon, authenticated with check (true);

grant select on public.policies to anon, authenticated;
grant insert (policy_version, title, source_filename, raw_text, clauses, uploaded_by)
  on public.policies to anon, authenticated;

-- Klauselweiser Vergleich zweier Versionen. Zuordnung über clauses[].id; Leerraum wird ignoriert.
-- status: added (nur in p_to) | removed (nur in p_from) | changed | unchanged
create or replace function public.policy_diff(p_from text, p_to text)
returns table (clause_id text, label text, status text, text_from text, text_to text, sort_order int)
language sql stable security invoker as $$
  with a as (
    select e.value ->> 'id' as id, e.value ->> 'label' as label, e.value ->> 'text' as text, e.n::int as n
    from public.policies p, jsonb_array_elements(p.clauses) with ordinality as e(value, n)
    where p.policy_version = p_from
  ), b as (
    select e.value ->> 'id' as id, e.value ->> 'label' as label, e.value ->> 'text' as text, e.n::int as n
    from public.policies p, jsonb_array_elements(p.clauses) with ordinality as e(value, n)
    where p.policy_version = p_to
  )
  select coalesce(b.id, a.id),
         coalesce(b.label, a.label),
         case when a.id is null then 'added'
              when b.id is null then 'removed'
              when regexp_replace(a.text, '\s+', ' ', 'g') = regexp_replace(b.text, '\s+', ' ', 'g') then 'unchanged'
              else 'changed' end,
         a.text, b.text,
         coalesce(b.n, a.n + 1000)::int
  from a full join b on a.id = b.id
  order by 6;
$$;
grant execute on function public.policy_diff(text, text) to anon, authenticated;

-- Seed: offizielle Policy v1 (data/taktile/policy_v1.docx, Fiktion der Veranstalter). clauses mit dem Referenz-Parser aus contract/db/policy-parser.mjs erzeugt.
insert into public.policies (policy_version, title, source_filename, raw_text, clauses, uploaded_by) values (
  'v1',
  $t$Fictional motor claims policy · v1$t$,
  'policy_v1.docx',
  $raw$Fictional motor claims policy · v1
Participant material · thinc! Munich hackathon · release at case presentation

Purpose and scope
This is an invented policy for a hackathon. It is not legal advice, an insurer policy, or a Taktile customer workflow. Your system recommends the next handling step; it never approves or pays a claim.
The input is one claim record. The claim_summary is descriptive text; the structured fields are the exercise’s source of truth. The three outputs are routine_processing, request_information, and human_review.

Policy v1: decision order
Apply these rules in order. A known reason for human review takes priority over a missing document. Record which policy version and rule produced each recommendation.
1. Send to human_review if the policy was not active on the incident date; claim_type is not motor_own_damage; injury_reported, liability_disputed, duplicate_flag or evidence_conflict is true; or quote_eur is greater than €1,500.
2. Otherwise, send to request_information if incident_report_present or itemized_quote_present is false.
3. Otherwise, send to routine_processing. This means the case may enter the insurer’s normal downstream process. It does not mean payment is approved.

Field definitions
case_status is open or closed. Open claims are still in process; closed claims have been completed. claim_type identifies the kind of claim. repair_type distinguishes standard repair from ev_high_voltage_battery work. quote_eur is the itemized repair estimate in euros. The remaining Boolean fields indicate whether evidence is present or a review trigger is known.
If an input field is absent or unreadable, do not invent a value. Request information unless another known fact already requires human review. Some development and evaluation cases have blank fields; treat a blank as an absent fact.

Participant datasets
Labelled development cases (14): https://drive.google.com/file/d/1T0_dwhKPmdhtZrh97FsBaAjuAmfp8akd/view
Unlabelled practice cases (12): https://drive.google.com/file/d/1TBMn1IWqMeheCaL9fzXPMKwnhb7f-MBj/view
Use the labelled cases to test and improve your system. The practice cases are for your own predictions. A separate evaluation set will be used for judging.
Your prototype must read a CSV in this format and write a results CSV with the columns case_id, recommendation_v1, recommendation_v2, needs_recheck, rule_v1, rule_v2 and explanation. Judges run every team on the same hidden cases in this format.

Quality to report
Report total correct next-step recommendations, incorrect routine_processing recommendations, and unnecessary human_review recommendations. After a policy change, report the changed cases separately and identify any open cases whose recommendation must be revisited. The supplied data contains no reviewer corrections, so show how your system records an override rather than reporting a rate. Explain what you would monitor after deployment when reviewer corrections and final outcomes arrive later.$raw$,
  $json$[
 {
  "id": "purpose-and-scope",
  "label": "Purpose and scope",
  "text": "This is an invented policy for a hackathon. It is not legal advice, an insurer policy, or a Taktile customer workflow. Your system recommends the next handling step; it never approves or pays a claim."
 },
 {
  "id": "purpose-and-scope-2",
  "label": "Purpose and scope (2)",
  "text": "The input is one claim record. The claim_summary is descriptive text; the structured fields are the exercise’s source of truth. The three outputs are routine_processing, request_information, and human_review."
 },
 {
  "id": "decision-order",
  "label": "Decision order",
  "text": "Apply these rules in order. A known reason for human review takes priority over a missing document. Record which policy version and rule produced each recommendation."
 },
 {
  "id": "rule-1",
  "label": "Rule 1",
  "text": "Send to human_review if the policy was not active on the incident date; claim_type is not motor_own_damage; injury_reported, liability_disputed, duplicate_flag or evidence_conflict is true; or quote_eur is greater than €1,500."
 },
 {
  "id": "rule-2",
  "label": "Rule 2",
  "text": "Otherwise, send to request_information if incident_report_present or itemized_quote_present is false."
 },
 {
  "id": "rule-3",
  "label": "Rule 3",
  "text": "Otherwise, send to routine_processing. This means the case may enter the insurer’s normal downstream process. It does not mean payment is approved."
 },
 {
  "id": "field-definitions",
  "label": "Field definitions",
  "text": "case_status is open or closed. Open claims are still in process; closed claims have been completed. claim_type identifies the kind of claim. repair_type distinguishes standard repair from ev_high_voltage_battery work. quote_eur is the itemized repair estimate in euros. The remaining Boolean fields indicate whether evidence is present or a review trigger is known."
 },
 {
  "id": "field-definitions-2",
  "label": "Field definitions (2)",
  "text": "If an input field is absent or unreadable, do not invent a value. Request information unless another known fact already requires human review. Some development and evaluation cases have blank fields; treat a blank as an absent fact."
 },
 {
  "id": "participant-datasets",
  "label": "Participant datasets",
  "text": "Labelled development cases (14): https://drive.google.com/file/d/1T0_dwhKPmdhtZrh97FsBaAjuAmfp8akd/view"
 },
 {
  "id": "participant-datasets-2",
  "label": "Participant datasets (2)",
  "text": "Unlabelled practice cases (12): https://drive.google.com/file/d/1TBMn1IWqMeheCaL9fzXPMKwnhb7f-MBj/view"
 },
 {
  "id": "participant-datasets-3",
  "label": "Participant datasets (3)",
  "text": "Use the labelled cases to test and improve your system. The practice cases are for your own predictions. A separate evaluation set will be used for judging."
 },
 {
  "id": "participant-datasets-4",
  "label": "Participant datasets (4)",
  "text": "Your prototype must read a CSV in this format and write a results CSV with the columns case_id, recommendation_v1, recommendation_v2, needs_recheck, rule_v1, rule_v2 and explanation. Judges run every team on the same hidden cases in this format."
 },
 {
  "id": "quality-to-report",
  "label": "Quality to report",
  "text": "Report total correct next-step recommendations, incorrect routine_processing recommendations, and unnecessary human_review recommendations. After a policy change, report the changed cases separately and identify any open cases whose recommendation must be revisited. The supplied data contains no reviewer corrections, so show how your system records an override rather than reporting a rate. Explain what you would monitor after deployment when reviewer corrections and final outcomes arrive later."
 }
]$json$::jsonb,
  'Taktile (official)'
) on conflict (policy_version) do nothing;
