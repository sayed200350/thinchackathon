-- Policy versions as uploaded by the reviewer app (live schema, created by Lovable).
-- Replaces the earlier draft (policy_version/title/raw_text/clauses + policy_diff), which was never deployed.
-- Run after schema.sql in the Supabase SQL editor; idempotent.
--
-- Rules:
--   * One row per version; anon/authenticated may read and insert.
--   * Seeded placeholders (v1, v2) start with content = ''. The app may fill such a placeholder exactly once
--     ("fill policy placeholder"); a row with text is immutable for browser roles. No delete for browser roles.
--   * Applying a version is server-side only: POST /api/policies/{version}/apply (backend/policy_apply.py)
--     reads policies.content and writes policy_configs / policy_runs / decisions (see policy_runs.sql).

create table if not exists public.policies (
  id         uuid        primary key default gen_random_uuid(),
  version    text        not null unique check (length(trim(version)) between 1 and 40),
  name       text        not null check (length(trim(name)) between 1 and 200),
  file_name  text,                                         -- e.g. policy_v1.docx; null for a placeholder
  content    text        not null default '' check (length(content) <= 2000000),  -- plain text, one paragraph per line
  created_at timestamptz not null default now()
);

alter table public.policies enable row level security;
grant select, insert on public.policies to anon, authenticated;
grant update (name, file_name, content) on public.policies to anon, authenticated;
grant all on public.policies to service_role;

drop policy if exists "read policies" on public.policies;
create policy "read policies" on public.policies for select to anon, authenticated using (true);
drop policy if exists "upload policies" on public.policies;
create policy "upload policies" on public.policies for insert to anon, authenticated with check (true);
drop policy if exists "fill policy placeholder" on public.policies;
create policy "fill policy placeholder" on public.policies for update to anon, authenticated
  using (content = '')
  with check (length(trim(content)) > 0);

insert into public.policies (version, name, created_at) values
  ('v1', 'Policy v1', now() - interval '1 day'),
  ('v2', 'Policy v2', now())
on conflict (version) do nothing;
