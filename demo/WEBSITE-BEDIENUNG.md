# Bedienung der Reviewer-App: was man wo macht

## Immer sichtbar

**Seitenleiste (links)**
- **Overview**, **Policy Update**, **History**: zu den drei Seiten wechseln.
- Pfeil-Button: Seitenleiste ein- oder ausklappen.

**Kopfleiste (oben)**
- **Testdaten / Live**: Testdaten sind eingebaute Demo-Claims. Live sind die echten Claims aus Supabase.
- **Policy Version** (Dropdown): wählt die Version, gegen die v1 verglichen wird, z. B. v2.
- **Change policy**: übernimmt die gewählte Version. Ein Punkt am Button zeigt eine noch nicht übernommene Auswahl. Bei Live und einer neuen Version läuft dabei die Engine („Running engine…“).

## Overview: offene Claims bearbeiten

- **Filter-Buttons**: *All decisions* und je ein Button pro Entscheidung, z. B. fast_track, standard_review, human_review oder reject.
- **Zeile anklicken**: öffnet rechts die Detailansicht mit Entscheidung, Regel, Begründung und entscheidenden Fakten.
- **Edit claim**: öffnet die Korrektur mit drei Feldern.
  - *Neue Entscheidung* (Dropdown)
  - *Grund*: „Why is the engine's decision wrong?“
  - *Prüfer:in*: „Your name“
  - Danach **Save correction →** oder **Cancel**.
  - Die Zeile bekommt das Badge „Overridden“. Die Korrektur erscheint in der Override-Historie und im Audit-Trail.
- **Claim fields** (nur bei Live): Felder eines Claims ändern und **Save N** klicken. Dafür muss „Edited by“ ausgefüllt sein. Die Änderungen erscheinen in der Feld-Historie.

## Policy Update: neue Policy einspielen und vergleichen

**Upload-Leiste (oben, aufklappbar über „Expand“)**
1. **Datei**: in das Feld ziehen oder hineinklicken. Erlaubt sind .docx, .pdf, .txt, .md, .json, .yaml und .csv.
2. **Version** (z. B. `v2`) und **Name** eintragen.
3. **Upload & apply**: lädt die Policy hoch und lässt gleich alle Claims neu prüfen (ca. 30 s).
4. Alternativ eine schon hochgeladene Policy im Dropdown **Policy to apply** wählen und **Update** klicken.

**Hinweis-Karte**: Ist eine Version hochgeladen, aber noch nicht angewendet, erscheint der Button **Apply vX now**.

**Auswertung (nur lesen)**
- **KPIs**: Anzahl Claims, Changed by vX und mehr.
- **Decisions under policy v1**: Verteilung der Entscheidungen.
- **Decision heatmap v1 × vX**: Felder abseits der Diagonale sind Claims, die sich ändern.
- **Changed claims per rule**: Regel 1–3 und Missing data.
- **Changed claims**: Liste mit alter und neuer Entscheidung. Ein Klick öffnet die Detailansicht.
- **Is it correct?**: Fehlerquote gegen die validierten Ergebnisse.
- **Manual review vs. Retakt**: Kostenvergleich.
- **Audit trail**: die letzten Overrides.

## History: geschlossene Claims ansehen

- Liste aller geschlossenen Claims mit Schloss-Symbol und grauen Badges.
- **Zeile anklicken**: Die Detailansicht öffnet sich nur zum Lesen. Statt „Edit claim“ steht dort: „Closed — the decision is protected and cannot be corrected.“

## Typischer Workflow

1. **Policy v2 kommt.** Auf *Policy Update* in der Upload-Leiste die Datei wählen, Version `v2` und einen Namen eintragen und **Upload & apply** klicken.
2. **Engine läuft** etwa eine halbe Minute. Danach meldet ein Hinweis, wie viele offene Claims neu geprüft wurden, wie viele sich geändert haben und wie viele einen zweiten Blick brauchen. Geschlossene Claims behalten ihre Entscheidung.
3. **Auswirkung ansehen.** Heatmap, „Changed claims per rule“ und die Liste *Changed claims* zeigen, was sich durch v2 ändert und wegen welcher Regel.
4. **Claims prüfen.** Auf *Overview* mit dem Filter-Button z. B. *human_review* wählen und die Claims einzeln öffnen. Die Detailansicht zeigt Regel, Begründung und Fakten.
5. **Korrigieren, wenn nötig.** **Edit claim** → neue Entscheidung, Grund und Name eintragen → **Save correction →**. Die Korrektur steht danach im Audit-Trail.
6. **Nachschauen.** Abgeschlossene Fälle stehen unter *History* und sind dort nicht mehr änderbar.

> Hinweis: Korrekturen über „Edit claim“ werden im Moment nur im Browser gehalten, nicht in der Datenbank. Upload & apply braucht das laufende Backend (`python3 -m backend`).
