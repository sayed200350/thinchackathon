# Lovable-Prompt: Update-Seite (Policy hochladen und vergleichen)

Voraussetzung: `contract/db/policies.sql` ist im Supabase SQL Editor ausgeführt.

```
Build a new page "/update" (sidebar item "Update", replaces the current placeholder tab) for the existing Policy Replay app. It lets a policy owner upload a NEW policy, stores it in Supabase, and compares it clause by clause with the previous one.

DATA — use the Supabase client already connected. Do NOT create tables, migrations or enable Lovable Cloud. The table `public.policies` and the function `public.policy_diff` already exist:
- policies(policy_version text PK like 'v1','v2', title, source_filename, raw_text, clauses jsonb [{id,label,text}], uploaded_by, created_at). Read for everyone, insert allowed, no update/delete (versions are immutable).
- rpc policy_diff(p_from text, p_to text) -> rows (clause_id, label, status 'added'|'removed'|'changed'|'unchanged', text_from, text_to, sort_order).

LAYOUT — reuse the existing Card, Button, Badge, Table components, tokens, mono numbers and the `eyebrow` label style. Page title "Policy update", subtitle "Upload a new policy and see exactly what changes."

ROW 1: three boxes side by side (grid-cols-3, equal height).
1) "Active policy": the latest saved version from `policies` (order by created_at desc). Show version badge (e.g. v1), title, source_filename, created date, clause count. Skeleton while loading.
2) "New policy": a dashed drop zone, accepts .docx .txt .md (drag & drop or click) and a small link "paste text instead" that switches the zone to a textarea. After a file is chosen show file name, size and "N clauses found" (parsed clauses count) with a small remove (x). Parse errors: red inline message, no toast.
3) "Update": the primary button "Update" next to the upload, large. Under it: "Will be saved as v{next}" where next = highest existing number + 1. Button is disabled until a policy is parsed (>= 1 clause) and shows a spinner while saving. Under the button, a muted line "Saved versions are never overwritten."

ON "Update": 
a) insert into `policies` { policy_version: 'v{next}', title, source_filename (null for pasted text), raw_text, clauses, uploaded_by: reviewer name from localStorage key "reviewerName" or 'unknown' }.
b) on success call rpc policy_diff(previousVersion, newVersion), show toast "Policy v{next} saved", keep the result in state and render ROW 2 and the table below. On a duplicate-version error (409/23505) refetch the versions and ask the user to press Update again. On any other error show the message inline in box 3.

ROW 2 (appears after Update): four stat cards: "Changed", "Added", "Removed", "Unchanged" (counts from the diff). Changed uses the amber decision color, Added green, Removed red, Unchanged muted. Next to them a short sentence: "N of M clauses differ from v{prev}."

SECTION "Clause comparison": one card per clause in sort_order, skipping nothing. Header: label + status badge. Body: two columns "v{prev}" and "v{next}". For status 'changed' highlight the words that differ (simple word-level diff: removed words red with strikethrough in the left column, added words green in the right column). 'added': left column "— not in v{prev}". 'removed': right column "— not in v{next}". 'unchanged' cards are collapsed by default; a toggle "Show unchanged (K)" expands them. Order: changed, added, removed first, then unchanged.

PAST VERSIONS: below, a small table of all saved versions (version, title, file, uploaded by, date) from `policies`. Clicking a row sets it as the "from" side and re-runs policy_diff against the newest version.

NOTE shown at the bottom in muted text: "Comparison is text-based. The affected claims appear once policy v{next} has been run on the claims."

PARSING (implement exactly this, do not improve it; the seed data for v1 was created with the same code):
- .docx: use the `mammoth` npm package in the browser (mammoth.convertToHtml with arrayBuffer). From the HTML build blocks: every <h1>,<h2>,<h3> -> {kind:'h', text}; every <p> and <li> -> {kind:'p', text}. Keep document order, drop empty ones.
- .txt/.md/pasted: split into non-empty lines. A line is a heading if it starts with '#' (strip the #'s) OR has at most 6 words and no '.' ':' ';' at the end and the next non-empty line is longer than the line. Everything else is a paragraph.
- then call parsePolicy(blocks) -> { title, clauses }:

```js
export function parsePolicy(blocks) {
  const slug = (s) => s.toLowerCase().replace(/^policy v\d+:\s*/, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  const clauses = []; let title = null; let section = null; let n = 0;
  for (const b of blocks) {
    const text = b.text.replace(/\s+/g, ' ').trim();
    if (!text) continue;
    if (b.kind === 'h') { const name = text.replace(/^policy v\d+:\s*/i, ''); section = { id: slug(text), label: name.charAt(0).toUpperCase() + name.slice(1), count: 0 }; continue; }
    if (!section) { title ??= text; continue; }
    const rule = text.match(/^(\d+)\.\s+(.*)$/);
    if (rule) { clauses.push({ id: `rule-${rule[1]}`, label: `Rule ${rule[1]}`, text: rule[2] }); continue; }
    section.count += 1;
    clauses.push({ id: section.count === 1 ? section.id : `${section.id}-${section.count}`,
                   label: section.count === 1 ? section.label : `${section.label} (${section.count})`, text });
  }
  return { title: title ?? 'Untitled policy', clauses };
}
```

title is stored in `policies.title`; clauses go to `policies.clauses`; raw_text = all block texts joined with a newline (headings preceded by an empty line).

STYLE: same look as the rest of the app, dense and professional, English labels, no login. Never use red/green for anything except the diff statuses. Must work at 1280px width.
```
