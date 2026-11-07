# Policy Replay — Design-Schema (angelehnt an taktile.com)

Quelle: taktile.com am 2026-11-07. Die Werte stammen direkt aus deren CSS (Tailwind-v4-Tokens). Die Hex-Werte sind original. Die oklch-Werte sind daraus umgerechnet, weil `app/src/styles.css` oklch verlangt.

Ziel: Die Reviewer-App soll für die Taktile-Jury wie ein Teil der Taktile-Plattform wirken. Sie übernimmt Farben, Typo-Logik, Radien und Bewegung, nicht aber Logo, Bilder oder Texte.

---

## 1. Designprinzipien (was Taktile ausmacht)

1. **Warmes Schwarz-Weiß statt Blau-Grau.** Die Grundfarben sind „Wool Grey“ (leicht warmes Off-White) und „Charcoal“ (fast schwarz). Es gibt keine bunte Primärfarbe. Buttons sind schwarz auf hell oder hell auf schwarz.
2. **Farbe nur mit Bedeutung.** Bunte Töne kommen nur in Pastell-Paaren vor (`100` als Fläche, `300` als Linie), etwa für Agent- oder Status-Kennzeichnungen. Ein einziger Signal-Ton (`contrast` #ff4d00) markiert das, worauf man schauen soll.
3. **Große, leichte Headlines.** Alle Überschriften haben das Gewicht 500 (nie bold), enge Laufweite −0.03em und eine Zeilenhöhe von 1.04.
4. **Mono für Daten.** Zahlen, IDs, Regel-Codes und Eyebrows stehen in der Mono-Schrift. Das wirkt technisch und präzise.
5. **Linien statt Schatten.** Es gibt keine Box-Shadows. Flächen trennen sich über 1px-Ränder in `wool-grey-400/500` und über leichte Tonsprünge (`wool-grey` → `wool-grey-200`).
6. **Kleine Radien.** Buttons und Badges nutzen 4px, Karten 8–12px. Pillen-Formen kommen kaum vor.
7. **Abwechselnd helle und dunkle Sektionen.** Dunkle Blöcke (`charcoal-600`) setzen Schwerpunkte. In der App eignen sie sich für die Policy-Impact-Zusammenfassung.

---

## 2. Farben

### 2.1 Neutrale Töne (Basis)

| Token | Hex | oklch | Verwendung |
|---|---|---|---|
| `wool-grey` | #fdfcfc | oklch(0.992 0.001 17.2) | Seitenhintergrund hell, Text auf dunkel |
| `wool-grey-200` | #f7f6f6 | oklch(0.974 0.001 17.2) | Karten, Sidebar, Tabellenkopf |
| `wool-grey-300` | #f0f0f0 | oklch(0.955 0 0) | Hover, Muted-Fläche, Accent |
| `wool-grey-400` | #e7e4e4 | oklch(0.921 0.003 17.2) | Rahmen, Trennlinien |
| `wool-grey-500` | #e2dddd | oklch(0.901 0.005 17.3) | stärkere Rahmen, Container-Kanten |
| `charcoal-150` | #bebaba | oklch(0.792 0.005 17.3) | deaktivierter Text auf hell |
| `charcoal-200` | #9a9797 | oklch(0.679 0.004 17.2) | Muted-Text auf dunkel |
| `charcoal-300` | #686565 | oklch(0.509 0.004 17.3) | Muted-Text auf hell |
| `charcoal-400` | #353232 | oklch(0.320 0.004 17.4) | Rahmen auf dunkel |
| `charcoal-500` | #1f1f1f | oklch(0.239 0 0) | Karten auf dunkel |
| `charcoal` | #121212 | oklch(0.182 0 0) | Text hell, Primary-Button |
| `charcoal-600` | #0b0a0a | oklch(0.146 0.002 17.4) | Hintergrund dunkler Sektionen |

### 2.2 Signal- und Systemfarben

| Token | Hex | oklch | Verwendung |
|---|---|---|---|
| `contrast` | #ff4d00 | oklch(0.668 0.224 37.0) | **Nur ein Zweck:** „Entscheidung hat sich durch v2 geändert“ bzw. „braucht zweiten Blick“. Nie für Buttons. |
| `error` | #a84a3e | oklch(0.528 0.127 29.3) | Fehler und destruktive Aktionen |
| `blue` | #487cff | oklch(0.622 0.203 264.8) | Links und Fokus (sparsam) |
| `parlor-blue` | #99c5e1 | oklch(0.802 0.061 236.5) | Linien-Grafiken, Deko |

### 2.3 Pastell-Paare (von Taktile „agent“ genannt)

Pro Farbe gibt es eine Fläche (`100`) und eine Linie oder einen Punkt (`300`). Für Text auf der Fläche nimmt man eine abgedunkelte Variante (`text`, nicht von Taktile, aber im selben Farbton und mit AA-Kontrast auf `100`).

| Farbe | 100 (Fläche) | 300 (Linie/Punkt) | Text (eigene Ableitung) |
|---|---|---|---|
| green | #dbf9e7 · oklch(0.956 0.039 159.3) | #83e6af · oklch(0.849 0.122 158.1) | oklch(0.45 0.10 158) |
| blue | #cbe1f0 · oklch(0.898 0.031 237.6) | #82b8da · oklch(0.757 0.075 236.7) | oklch(0.45 0.08 240) |
| orange | #f9efdd · oklch(0.955 0.026 82.4) | #f3c182 · oklch(0.842 0.098 72.3) | oklch(0.50 0.11 62) |
| red | #fce2e2 · oklch(0.934 0.029 17.7) | #f8a3a1 · oklch(0.799 0.102 21.0) | oklch(0.528 0.127 29.3) |
| purple | #dfe7fe · oklch(0.929 0.032 270.5) | #9eb3fd · oklch(0.779 0.109 271.6) | oklch(0.48 0.13 272) |
| yellow | #f9f7e2 · oklch(0.972 0.028 102.5) | #f2e194 · oklch(0.906 0.098 97.2) | oklch(0.50 0.09 95) |

### 2.4 Entscheidungsfarben (App-spezifisch)

Diese Zuordnung passt zu `app/src/components/decision-badge.tsx`:

| Entscheidung | Paar | Begründung |
|---|---|---|
| `fast_track` | green | unkritisch, läuft durch |
| `standard_review` | blue | normaler Arbeitsgang, neutral |
| `specialist_review` | orange | Aufmerksamkeit nötig |
| `reject` | red | negativ |
| **v1 → v2 geändert** | `contrast` (#ff4d00) | der Kern der Story: „zweiter Blick“ |

### 2.5 Chart-Palette

Die Reihenfolge ist bei hellem und dunklem Hintergrund gut unterscheidbar (Taktile-`400`-Töne):
1. charcoal #121212 (dunkel: wool-grey) · 2. blue-400 #4fbdfb · 3. orange-400 #ed9c4e · 4. green-400 #3fd084 · 5. purple-400 #7387fb
Für Vorher/Nachher-Vergleiche (v1 vs. v2): v1 = `charcoal-200`, v2 = `charcoal`; die Differenz wird in `contrast` hervorgehoben.

---

## 3. Typografie

### 3.1 Schriften

| Rolle | Taktile | Für uns (frei verfügbar, Google Fonts) |
|---|---|---|
| Sans | Söhne (Buch 400, Kräftig 500) | **Inter Tight** 400/500 |
| Mono | Söhne Mono | **JetBrains Mono** 400/500 |
| Serif (Zitate, selten) | EB Garamond | **EB Garamond** 400 |

Söhne ist eine kommerzielle Schrift (Klim Type Foundry) und darf ohne Lizenz nicht eingebunden werden. Inter Tight kommt ihr in Laufweite und Wirkung am nächsten.

Es werden nur die Gewichte 400 und 500 verwendet. Kein 600/700.

### 3.2 Schriftgrößen

Taktile hat eine Mobile- und eine Desktop-Größe pro Stufe. Für die App reicht meist die kleinere (Mobile-)Größe, denn die Desktop-Größen sind für eine Marketing-Seite gedacht.

| Stil | Mobil | Desktop | Gewicht | Laufweite | Zeilenhöhe | In der App |
|---|---|---|---|---|---|---|
| `d2` | 2.5rem | 4.5rem | 500 | −0.03em | 1.04 | große KPI-Zahl (Mono-Variante) |
| `h1` | 2.25rem | 3.75rem | 500 | −0.03em | 1.04 | Seitentitel (nur Policy-Impact) |
| `h2` | 2rem | 3.125rem | 500 | −0.03em | 1.04 | — |
| `h3` | 1.75rem | 2.625rem | 500 | −0.02em | 1.15 | Seitentitel, Claim-ID im Detail |
| `h4` | 1.5625rem | 2.1875rem | 500 | −0.02em | 1.15 | Abschnittstitel |
| `s1` | 1.25rem | 1.5rem | 400 | −0.01em | 1.15 | Karten-Titel, Untertitel |
| `body` | 1rem | – | 400 | 0 | 1.5 | Fließtext |
| `body-s` | 0.875rem | – | 400 | 0 | 1.5 | Tabelle, Formulare (**App-Standard**) |
| `caption` | 0.75rem | – | 400 | +0.02em | 1.5 | Metadaten, Hilfetext |
| `eyebrow` | 0.75rem | – | 500 Mono | +0.02em, UPPERCASE | 1.5 | Sektions-Label über Überschriften |

Zu jeder Stufe gibt es eine `-buch`-Variante mit Gewicht 400, etwa für ruhige Zwischenüberschriften.

### 3.3 Regeln
- Bei Headlines immer `text-balance` setzen.
- Zahlen in Tabellen bekommen `font-mono tabular-nums`.
- Über jedem Seitenbereich steht eine Eyebrow, z. B. `POLICY IMPACT`, `CLAIM`, `AUDIT TRAIL`.

---

## 4. Abstände, Raster, Radien

- **Spacing-Basis:** 4px (`--spacing: .25rem`), Standard bei Tailwind.
- **Container:** Inhalt maximal 84.5rem (1352px), Seitenrand 1rem mobil und 1.5rem ab md.
- **Navbar-Höhe:** 4rem + 1px Rahmen.
- **Sektionsabstand:** Eyebrow → Headline 3rem (`gap-12`), zwischen Sektionen 6rem bzw. in der App 3rem.
- **Radien:** In der App `--radius: 0.5rem` setzen. Daraus ergibt sich die Taktile-Skala genau:

| Klasse | Wert | Verwendung |
|---|---|---|
| `rounded-sm` | 4px | Buttons, Badges, Inputs, Tags |
| `rounded-md` | 6px | Dropdowns, Tooltips |
| `rounded-lg` | 8px | Karten, Tabellen-Container |
| `rounded-xl` | 12px | große Panels, Dialoge |
| `rounded-2xl` | 16px | Hero- oder Impact-Block |

- **Schatten:** keine. Höchstens für Popover/Dialog `shadow-sm`. Sonst trennen 1px-Rahmen.

---

## 5. Bewegung

| Token | Wert | Verwendung |
|---|---|---|
| `press` | 90ms | Button-Active |
| `default` | 150ms `cubic-bezier(.4,0,.2,1)` | Hover, Farben |
| `role-in` | 180ms `cubic-bezier(.65,0,.35,1)` | Badges oder Zeilen einblenden |
| `nav-panel` | 300ms `cubic-bezier(.22,1,.36,1)` | Sheets, Drawer, Dropdowns |
| `button-arrow` | 480ms `cubic-bezier(.65,0,.35,1)` | Pfeil im CTA rollt nach rechts |
| `step-swap` | 500ms `cubic-bezier(.4,0,.2,1)` | Wechsel v1 ↔ v2 |
| `card-in` | 700ms `cubic-bezier(.25,.46,.45,.94)` | Karten erscheinen gestaffelt |
| `hero-settle` | `cubic-bezier(.16,1,.3,1)` | Zahlen- oder KPI-Count-up |

Signature-Detail: Primäre CTAs haben einen Pfeil (→). Beim Hover rollt er nach rechts heraus, und ein neuer kommt von links nach. Die Animation läuft mit `button-arrow` 480ms.

Bei `prefers-reduced-motion` werden alle Animationen ausgeschaltet.

---

## 6. Komponenten

### Buttons (Höhe 36px, `rounded-sm`, `body-s` 500)
| Variante | Hell | Dunkel |
|---|---|---|
| Primary | bg `charcoal`, Text `wool-grey`, Hover `charcoal-400` | bg `wool-grey`, Text `charcoal` |
| Secondary | bg `wool-grey-300`, Text `charcoal`, Hover `wool-grey-400` | bg wool-grey 20 % transparent, Text `wool-grey` |
| Outline | 1px `wool-grey-500`, Hover bg `wool-grey-200` | 1px `charcoal-400` |
| Ghost | nur Text `charcoal-300` → Hover `charcoal` | `charcoal-200` → `wool-grey` |
| Destructive | bg `error`, Text `wool-grey` | gleich |

Der Fokus-Ring ist 2px in `charcoal` (dunkel: `wool-grey`) mit 2px Offset.

### Entscheidungs-Badge
- Form: `rounded-sm` (statt der bisherigen Pille), `px-2 py-0.5`, `caption` mit Gewicht 500.
- Fläche `{farbe}-100`, Rahmen `{farbe}-300`, Text `{farbe}-text`. Davor ein 6px-Punkt in `{farbe}-300`.
- Dunkel: Fläche `{farbe}-300` mit 15 % Deckkraft, Text `{farbe}-300`.

### „Geändert“-Marker (v1 → v2)
- Zeigt `[alte Badge] → [neue Badge]`, der Pfeil in `contrast`.
- In der Tabelle bekommt die Zeile links eine 2px-Kante in `contrast`. Der Zeilenhintergrund bleibt neutral.
- Ein Eyebrow-Chip `CHANGED`: Mono, uppercase, Text `contrast`, Rahmen `contrast` mit 30 %.

### Tabelle (Claim-Liste)
- Container `rounded-lg`, Rahmen `wool-grey-400`, Kopfzeile bg `wool-grey-200`, Text `caption` uppercase `charcoal-300`.
- Zeilen 44px hoch, Trennlinie `wool-grey-400`, Hover bg `wool-grey-200`.
- Claim-ID, Beträge und Datum stehen in Mono `tabular-nums`.

### Karten / KPI-Tiles
- bg `wool-grey-200`, Rahmen `wool-grey-400`, `rounded-lg`, Padding 20–24px.
- Oben ein Eyebrow-Label, darunter die Zahl in `d2`-Mono (Mobilgröße 2.5rem), darunter `caption` in `charcoal-300`.
- Ist die Zahl ein Delta, steht das Vorzeichen in `contrast` (z. B. „+12 Claims geändert“).

### Dunkler Impact-Block (Policy-Impact-Seite)
- bg `charcoal-600`, Text `wool-grey`, Muted `charcoal-200`, Karten `charcoal-500`, Rahmen `charcoal-400`, `rounded-xl`.
- Er erinnert an die dunklen Sektionen von taktile.com und ist das Bild für den Demo-Screenshot.

### Begründungen / Regel-Trace (Detailansicht)
- Eine Liste aus Regelzeilen: links der Regel-Code in Mono (`R-07`), in der Mitte die Begründung in `body-s`, rechts das Ergebnis-Badge.
- Gefeuerte Regeln haben Text `charcoal` und einen Punkt in `{farbe}-300`. Nicht gefeuerte Regeln sind `charcoal-150` und eingeklappt.
- Regeln, die in v2 neu sind oder sich geändert haben, bekommen den Marker `contrast`.

### Korrektur-Formular
- Inputs: Höhe 36px, `rounded-sm`, Rahmen `wool-grey-500`, bg `wool-grey`. Beim Fokus wird der Rahmen `charcoal` und es erscheint der Ring.
- Labels in `caption` 500 `charcoal-300`, Pflichtfelder ohne Sternchen, dafür mit Hilfetext.
- Primary-Button „Korrektur speichern →“.

### Audit-Timeline
- Eine vertikale 1px-Linie in `wool-grey-500`, Knoten 8px.
- Zeitstempel in Mono `caption` `charcoal-300`, Person/Aktion in `body-s` 500, Diff in Mono auf `wool-grey-200`.

### Navigation / App-Shell
- Topbar 65px, bg `wool-grey` mit Rahmen unten `wool-grey-400`. Die Wortmarke „Policy Replay“ in `s1` 500.
- Nav-Links in `body-s` `charcoal-300`. Der aktive Link ist `charcoal` mit einer 1px-Unterlinie.

---

## 7. Ikonografie
- Taktile nutzt „Material Symbols Sharp“ mit eckigen Formen. In der App nehmen wir **lucide-react** (schon installiert), mit `strokeWidth={1.5}` und Größe 16px. Das wirkt ähnlich leicht.

---

## 8. Umsetzung in Lovable (zum Einfügen)

Prompt für Lovable:

> Stelle das Design auf ein Taktile-inspiriertes System um. Ersetze in `src/styles.css` die `:root`- und `.dark`-Blöcke durch die Werte unten. Ergänze die neuen Tokens in `@theme inline`. Lade „Inter Tight“ (400, 500), „JetBrains Mono“ (400, 500) und „EB Garamond“ (400) per `<link>` in `__root.tsx` und setze `--font-sans`, `--font-mono` und `--font-serif`. Headlines bekommen nur Gewicht 500, Laufweite −0.03em und Zeilenhöhe 1.04. Es gibt keine Schatten, Flächen trennen sich über 1px-Rahmen. Die DecisionBadge wird `rounded-sm` und bekommt einen farbigen Punkt. Entscheidungen, die sich von v1 zu v2 ändern, bekommen eine `contrast`-Markierung (linke 2px-Kante in der Tabelle und einen Pfeil zwischen alter und neuer Badge). Die KPI-Zahlen stehen in Mono.

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

DecisionBadge neu (Klassen):
```ts
fast_track:        "bg-decision-fast-soft text-decision-fast border-decision-fast-line",
standard_review:   "bg-decision-standard-soft text-decision-standard border-decision-standard-line",
specialist_review: "bg-decision-specialist-soft text-decision-specialist border-decision-specialist-line",
reject:            "bg-decision-reject-soft text-decision-reject border-decision-reject-line",
// Basis: "inline-flex items-center gap-1.5 rounded-sm border px-2 py-0.5 text-xs font-medium"
// Punkt: <span className="size-1.5 rounded-full bg-current opacity-60" />
```

---

## 9. Was wir bewusst nicht übernehmen
- Logo, Fotos, Hero-Linien-Animationen und Texte von taktile.com.
- Söhne (Lizenz). Stattdessen Inter Tight.
- Riesige Display-Größen (bis 7.8rem). Für eine Arbeits-App sind sie zu groß; `h3`/`h4` reichen als Seitentitel.
