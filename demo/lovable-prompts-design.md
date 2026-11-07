# Lovable-Prompts: Taktile-Design für die Reviewer-App

Die Prompts nacheinander in Lovable einfügen, jeweils einen pro Nachricht. Nach jedem Schritt kurz die Vorschau prüfen, dann den nächsten.
Hintergrund und Begründungen stehen in `demo/design-system.md`. Es geht nur ums Design: Daten und Logik (Mock-Daten in `policy-data.ts`) bleiben unverändert.

---

## Prompt 1 — Design-Tokens und Schriften

~~~~
Restyle the app with a Taktile-inspired design system. Change design only, no data or logic changes.

1. In src/routes/__root.tsx, add a Google Fonts <link> in head() for "Inter Tight" (400;500), "JetBrains Mono" (400;500) and "EB Garamond" (400), with preconnect to fonts.googleapis.com and fonts.gstatic.com.

2. In src/styles.css, keep the existing @import lines and the existing @theme inline mappings. ADD the new entries from the @theme inline block below to the existing @theme inline block. REPLACE the full :root and .dark blocks with the ones below. REPLACE the @layer base block, but keep the existing "* { border-color }" and "body { background; color }" rules in it. Also set body to font-family var(--font-sans) and add -webkit-font-smoothing: antialiased.

3. Design rules for the whole app:
- Never use font-weight 600 or 700 (no font-semibold, no font-bold). Use font-medium (500) for every heading and emphasis.
- No box shadows on cards, tables or buttons. Separate surfaces with 1px borders only. Popovers and dialogs may use shadow-sm.
- Monospace (font-mono tabular-nums) for claim IDs, rule IDs, amounts, dates and all numbers.

```css
@theme inline {
  --font-sans: "Inter Tight", ui-sans-serif, system-ui, sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, SFMono-Regular, monospace;
  --font-serif: "EB Garamond", ui-serif, Georgia, serif;

  --color-contrast: var(--contrast);
  --color-decision-fast-soft: var(--decision-fast-soft);
  --color-decision-fast-line: var(--decision-fast-line);
  --color-decision-standard-soft: var(--decision-standard-soft);
  --color-decision-standard-line: var(--decision-standard-line);
  --color-decision-specialist-soft: var(--decision-specialist-soft);
  --color-decision-specialist-line: var(--decision-specialist-line);
  --color-decision-reject-soft: var(--decision-reject-soft);
  --color-decision-reject-line: var(--decision-reject-line);

  --ease-snappy: cubic-bezier(.65, 0, .35, 1);
  --ease-panel: cubic-bezier(.22, 1, .36, 1);
  --ease-settle: cubic-bezier(.16, 1, .3, 1);
}

:root {
  --radius: 0.5rem;

  --background: oklch(0.992 0.001 17.2);          /* wool-grey */
  --foreground: oklch(0.182 0 0);                 /* charcoal */
  --card: oklch(0.974 0.001 17.2);                /* wool-grey-200 */
  --card-foreground: oklch(0.182 0 0);
  --popover: oklch(0.992 0.001 17.2);
  --popover-foreground: oklch(0.182 0 0);
  --primary: oklch(0.182 0 0);                    /* charcoal */
  --primary-foreground: oklch(0.992 0.001 17.2);
  --secondary: oklch(0.955 0 0);                  /* wool-grey-300 */
  --secondary-foreground: oklch(0.182 0 0);
  --muted: oklch(0.955 0 0);
  --muted-foreground: oklch(0.509 0.004 17.3);    /* charcoal-300 */
  --accent: oklch(0.955 0 0);
  --accent-foreground: oklch(0.182 0 0);
  --destructive: oklch(0.528 0.127 29.3);         /* error */
  --destructive-foreground: oklch(0.992 0.001 17.2);
  --border: oklch(0.921 0.003 17.2);              /* wool-grey-400 */
  --input: oklch(0.901 0.005 17.3);               /* wool-grey-500 */
  --ring: oklch(0.182 0 0);

  --contrast: oklch(0.668 0.224 37.0);            /* #ff4d00 */

  --chart-1: oklch(0.182 0 0);
  --chart-2: oklch(0.761 0.133 237.1);
  --chart-3: oklch(0.759 0.134 62.2);
  --chart-4: oklch(0.763 0.164 155.7);
  --chart-5: oklch(0.663 0.172 273.4);

  --sidebar: oklch(0.974 0.001 17.2);
  --sidebar-foreground: oklch(0.182 0 0);
  --sidebar-primary: oklch(0.182 0 0);
  --sidebar-primary-foreground: oklch(0.992 0.001 17.2);
  --sidebar-accent: oklch(0.955 0 0);
  --sidebar-accent-foreground: oklch(0.182 0 0);
  --sidebar-border: oklch(0.921 0.003 17.2);
  --sidebar-ring: oklch(0.182 0 0);

  /* Entscheidungen: Text / Fläche (100) / Linie (300) */
  --decision-fast: oklch(0.45 0.10 158);
  --decision-fast-foreground: oklch(0.992 0.001 17.2);
  --decision-fast-soft: oklch(0.956 0.039 159.3);
  --decision-fast-line: oklch(0.849 0.122 158.1);
  --decision-standard: oklch(0.45 0.08 240);
  --decision-standard-foreground: oklch(0.992 0.001 17.2);
  --decision-standard-soft: oklch(0.898 0.031 237.6);
  --decision-standard-line: oklch(0.757 0.075 236.7);
  --decision-specialist: oklch(0.50 0.11 62);
  --decision-specialist-soft: oklch(0.955 0.026 82.4);
  --decision-specialist-line: oklch(0.842 0.098 72.3);
  --decision-reject: oklch(0.528 0.127 29.3);
  --decision-reject-soft: oklch(0.934 0.029 17.7);
  --decision-reject-line: oklch(0.799 0.102 21.0);
}

.dark {
  --background: oklch(0.146 0.002 17.4);          /* charcoal-600 */
  --foreground: oklch(0.992 0.001 17.2);
  --card: oklch(0.239 0 0);                       /* charcoal-500 */
  --card-foreground: oklch(0.992 0.001 17.2);
  --popover: oklch(0.146 0.002 17.4);
  --popover-foreground: oklch(0.992 0.001 17.2);
  --primary: oklch(0.992 0.001 17.2);
  --primary-foreground: oklch(0.182 0 0);
  --secondary: oklch(0.320 0.004 17.4);           /* charcoal-400 */
  --secondary-foreground: oklch(0.992 0.001 17.2);
  --muted: oklch(0.320 0.004 17.4);
  --muted-foreground: oklch(0.679 0.004 17.2);    /* charcoal-200 */
  --accent: oklch(0.320 0.004 17.4);
  --accent-foreground: oklch(0.992 0.001 17.2);
  --destructive: oklch(0.688 0.171 23.1);         /* red-400 */
  --destructive-foreground: oklch(0.182 0 0);
  --border: oklch(0.320 0.004 17.4);
  --input: oklch(0.320 0.004 17.4);
  --ring: oklch(0.992 0.001 17.2);

  --contrast: oklch(0.668 0.224 37.0);

  --chart-1: oklch(0.992 0.001 17.2);
  --chart-2: oklch(0.761 0.133 237.1);
  --chart-3: oklch(0.759 0.134 62.2);
  --chart-4: oklch(0.763 0.164 155.7);
  --chart-5: oklch(0.663 0.172 273.4);

  --sidebar: oklch(0.146 0.002 17.4);
  --sidebar-foreground: oklch(0.992 0.001 17.2);
  --sidebar-primary: oklch(0.992 0.001 17.2);
  --sidebar-primary-foreground: oklch(0.182 0 0);
  --sidebar-accent: oklch(0.320 0.004 17.4);
  --sidebar-accent-foreground: oklch(0.992 0.001 17.2);
  --sidebar-border: oklch(0.320 0.004 17.4);
  --sidebar-ring: oklch(0.992 0.001 17.2);

  --decision-fast: oklch(0.849 0.122 158.1);
  --decision-fast-foreground: oklch(0.182 0 0);
  --decision-fast-soft: oklch(0.849 0.122 158.1 / 15%);
  --decision-fast-line: oklch(0.849 0.122 158.1 / 40%);
  --decision-standard: oklch(0.757 0.075 236.7);
  --decision-standard-foreground: oklch(0.182 0 0);
  --decision-standard-soft: oklch(0.757 0.075 236.7 / 15%);
  --decision-standard-line: oklch(0.757 0.075 236.7 / 40%);
  --decision-specialist: oklch(0.842 0.098 72.3);
  --decision-specialist-soft: oklch(0.842 0.098 72.3 / 15%);
  --decision-specialist-line: oklch(0.842 0.098 72.3 / 40%);
  --decision-reject: oklch(0.799 0.102 21.0);
  --decision-reject-soft: oklch(0.799 0.102 21.0 / 15%);
  --decision-reject-line: oklch(0.799 0.102 21.0 / 40%);
}

@layer base {
  h1, h2, h3, h4 { font-weight: 500; letter-spacing: -0.03em; line-height: 1.04; text-wrap: balance; }
  .eyebrow { font-family: var(--font-mono); font-size: .75rem; font-weight: 500; letter-spacing: .02em; text-transform: uppercase; color: var(--muted-foreground); }
}
```
~~~~

---

## Prompt 2 — App-Shell (Sidebar und Header)

~~~~
Restyle src/components/app-shell.tsx in the new Taktile style. Design only.

- Sidebar: bg-card, 1px right border. Remove the square logo icon box. The wordmark "Policy Replay" uses text-lg font-medium tracking-tight. Below it, a small eyebrow "CLAIMS REVIEW" (use the .eyebrow class).
- Nav links: text-sm, rounded-sm, no background on the active item. Inactive links are text-muted-foreground, hover:text-foreground. The active link is text-foreground with a 2px left bar in bg-foreground. Icons are lucide with strokeWidth={1.5}, size 16px.
- Remove the "Claims review prototype" footer text. Replace it with a mono caption "Policy v1 · v2 preview".
- Header: height 65px (h-[65px]), bg-background, 1px bottom border, no backdrop-blur. Left side: the current page name as eyebrow text. Right side: the v1 / v2 / Compare toggle group with rounded-sm segments, active segment bg-foreground text-background, and font-mono text-xs labels.
- Replace the orange "Preview" badge with a small outline chip: rounded-sm, border-contrast/40, text-contrast, .eyebrow style, text "V2 PREVIEW".
~~~~

---

## Prompt 3 — Entscheidungs-Badge und Claims Queue

~~~~
Restyle the decision badge and the Claims Queue page (src/routes/index.tsx). Design only.

DecisionBadge (src/components/decision-badge.tsx):
- Base classes: "inline-flex items-center gap-1.5 rounded-sm border px-2 py-0.5 text-xs font-medium whitespace-nowrap" (rounded-sm instead of rounded-full).
- Before the label, add a 6px dot: <span className="size-1.5 rounded-full bg-current opacity-70" />.
- Color classes:
  fast_track:        "bg-decision-fast-soft text-decision-fast border-decision-fast-line"
  standard_review:   "bg-decision-standard-soft text-decision-standard border-decision-standard-line"
  specialist_review: "bg-decision-specialist-soft text-decision-specialist border-decision-specialist-line"
  reject:            "bg-decision-reject-soft text-decision-reject border-decision-reject-line"
- Size lg: px-3 py-1 text-sm.

Claims Queue page:
- Page header: an eyebrow "CLAIMS QUEUE" above the h1. The h1 uses text-3xl font-medium tracking-tight (no font-semibold). The subline uses text-sm text-muted-foreground, with the numbers in font-mono.
- Filter card: no Card padding change, but the labels are the .eyebrow style. Select triggers and the switch are rounded-sm.
- Table container: rounded-lg, 1px border, overflow-hidden, no shadow. The header row is bg-card, and the header cells are .eyebrow style with h-10.
- Rows: h-11, hover:bg-card. Claim ID cell is font-mono text-sm. The rule badge is font-mono, rounded-sm, variant outline.
- CHANGED claims (isChanged(claim) true): the row gets a 2px left accent "shadow-[inset_2px_0_0_var(--contrast)]". In compare mode, show "[v1 badge] → [v2 badge]" with the arrow as lucide ArrowRight 14px in text-contrast (replace ArrowRightLeft and the text-decision-specialist color).
- Status badges: Open = outline rounded-sm. Closed = secondary rounded-sm with a Lock icon. Overridden = rounded-sm, border-foreground/20, font-mono text-[10px] uppercase.
~~~~

---

## Prompt 4 — Claim-Detailseite

~~~~
Restyle the claim detail page (src/routes/claims.$claimId.tsx). Design only.

- Back link: text-sm text-muted-foreground with an ArrowLeft icon (strokeWidth 1.5).
- Header: eyebrow "CLAIM" above. The claim ID is the title in font-mono text-3xl font-medium tracking-tight. Next to it are the status badges (rounded-sm).
- The v1 / v2 comparison boxes: rounded-lg, 1px border, bg-card, p-5. The box labels ("Policy v1", "Policy v2") use the .eyebrow style. If the rule changed, the v2 box gets border-contrast/40 and the "Changed" badge becomes a rounded-sm outline chip with text-contrast, border-contrast/40, font-mono uppercase text-[10px]. The arrow between the old and new decision uses text-contrast.
- Clause texts: text-sm leading-relaxed text-muted-foreground. Rule IDs are font-mono.
- "Decisive fact" and "Explanation" headings: use the .eyebrow style instead of text-sm font-semibold.
- Button "Correct decision": the primary button style (bg-primary text-primary-foreground rounded-sm h-9) with the PencilLine icon. In the dialog, inputs and selects are rounded-sm h-9, and labels use text-xs font-medium text-muted-foreground. The save button is primary and reads "Save correction →".
- Override history as a vertical timeline: a 1px left line in border-border, an 8px dot per entry (bg-foreground). Each entry shows the timestamp in font-mono text-xs text-muted-foreground, then the old badge → new badge, then the reason in text-sm. No boxed list items.
~~~~

---

## Prompt 5 — Policy-Impact-Seite

~~~~
Restyle the Policy Impact page (src/routes/policy-impact.tsx). Design only.

- Page header: eyebrow "POLICY IMPACT · V1 → V2" above. The h1 uses text-3xl font-medium tracking-tight.
- Wrap the KPI row in a dark impact block: a section with rounded-xl bg-[oklch(0.146_0.002_17.4)] text-[oklch(0.992_0.001_17.2)] p-6. Inside, the KPI cards use bg-[oklch(0.239_0_0)], a 1px border in border-[oklch(0.320_0.004_17.4)] and rounded-lg. KPI labels use the .eyebrow style in text-[oklch(0.679_0.004_17.2)]. KPI values use font-mono text-4xl font-medium tracking-tight tabular-nums. Values that represent change (changed claims, deltas) are text-contrast. Optionally add the "dark" class to that section so the shadcn tokens switch automatically.
- All other cards: rounded-lg, 1px border, no shadow, bg-background. Card titles use the .eyebrow style instead of text-base.
- Heatmap v1 × v2: the cell background uses the foreground color with opacity scaled by count (bg-foreground/5 … bg-foreground/80). Numbers are font-mono. Diagonal cells (unchanged) stay neutral. Off-diagonal cells (changed) get a 1px border in border-contrast/50.
- Bar chart (recharts): bars use fill var(--foreground), and bars for changed rules use var(--contrast). Bar radius is [2,2,0,0]. Grid lines use stroke var(--border) and are horizontal only. Axis ticks are 11px in the font-mono family with fill var(--muted-foreground). The tooltip has a rounded-sm, 1px border and no shadow.
- Changed claims table: the same style as the Claims Queue table (eyebrow header, font-mono IDs, a 2px contrast left accent on every row).
- The "Is it correct?" section: the heading is text-xl font-medium. The cards are bordered, with icons stroke 1.5 in text-muted-foreground.
~~~~

---

## Prompt 6 — Feinschliff (optional)

~~~~
Final polish for the Taktile-style design:
- Primary buttons: add a trailing "→" arrow that slides 2px to the right on hover (transition 480ms, cubic-bezier(.65,0,.35,1)).
- Interaction transitions: 150ms for colors. Sheets, dialogs and dropdowns use 300ms cubic-bezier(.22,1,.36,1).
- Respect prefers-reduced-motion by disabling all non-essential transitions.
- Check every page: no font-semibold or font-bold left, no shadows on cards, all numbers and IDs in font-mono, all badges rounded-sm.
~~~~
