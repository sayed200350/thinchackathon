// Referenz-Parser (gleicher Code steht im Lovable-Prompt). blocks: [{kind:'h'|'p', text}] in Dokumentreihenfolge.
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
