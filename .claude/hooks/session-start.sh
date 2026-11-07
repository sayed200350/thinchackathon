#!/usr/bin/env bash
# SessionStart: pull + Anzahl ungelesener Nachrichten. Darf den Start nie blockieren.
cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0
PERSON="${TEAM_PERSON:-}"
if [ -z "$PERSON" ] && [ -f .claude/settings.local.json ]; then
  PERSON=$(grep -o '"TEAM_PERSON"[[:space:]]*:[[:space:]]*"[A-Z]"' .claude/settings.local.json 2>/dev/null | grep -o '[A-Z]"$' | tr -d '"')
fi
PULL=$(GIT_TERMINAL_PROMPT=0 git pull --rebase --autostash 2>&1) || true
echo "[team] git pull: $(echo "$PULL" | tail -n 1)"
if [ -z "$PERSON" ]; then
  echo "[team] TEAM_PERSON nicht gesetzt. Bitte /join <PERSON> ausführen (z. B. /join C)."
  exit 0
fi
N=$(find "team/inbox/$PERSON" -maxdepth 1 -type f -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
echo "[team] Du bist $PERSON. Ungelesene Nachrichten in team/inbox/$PERSON/: ${N:-0}"
[ "${N:-0}" != "0" ] && echo "[team] Bitte /sync ausführen."
exit 0
