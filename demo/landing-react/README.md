# Landing (React port)

Animated landing for Retakt, the Lovable reviewer app (`app/`): intro, ASCII colonnade with a live claim readout, claim-routing stage with a
draggable v1.1 threshold, clause diff, second-look cards, impact numbers and an editable cost sentence.
Styled like the app (black, white accent, 16px cards, rim light). Ported from `demo/landing/` (plain HTML/JS) and tested in a copy of the latest app
(`tsc`, `eslint`, `vitest` pass, no console errors, landing → `/queue` → logo → landing works).

`app/` is owned by Lovable, so nothing here was applied to it. These files are ready to drop in.

## Files

| File | Purpose |
| --- | --- |
| `landing-data.ts` | The 26 claims decided by the real v1 engine. **Generated**, do not edit. |
| `landing-model.ts` | Threshold what-if logic (mirrors `demo/landing/build_data.py`). |
| `replay-engine.ts` | Canvas animation engine, framework-free. |
| `landing-replay.tsx` | The page component `LandingReplay`. |
| `landing-replay.css` | Styles, every selector prefixed `pr-`. |
| `taktile-logo.tsx` | Taktile icon (five bars, taken from taktile.com/icon.svg), uses `currentColor`. |
| `index.route.example.tsx` | Replacement for `app/src/routes/index.tsx`. |

## Apply it

1. Copy `landing-data.ts`, `landing-model.ts`, `replay-engine.ts`, `landing-replay.tsx` and `landing-replay.css`
   to `app/src/components/landing-replay/`.
2. Replace `app/src/routes/index.tsx` with `index.route.example.tsx`. The "Open reviewer queue" buttons link to `/queue`.
3. Run `npx eslint --fix src/components/landing-replay` (the generated data file is not Prettier-formatted).

Needs nothing new: React, TanStack Router and the Inter Tight / JetBrains Mono fonts that `__root.tsx` already loads.
The hero shows the app's existing `AsciiColumns` (`@/components/ascii-columns`) on the right, so that file must stay in `app/`.
The nav shows the Taktile icon from `taktile-logo.tsx` (copy it to `app/src/components/`).

## Regenerate the data

After changing `engine/` or the CSVs, from the repository root:

```sh
python3 demo/landing/build_data.py
```

This rewrites `demo/landing/data.js` and `demo/landing-react/landing-data.ts`, and asserts that the simulation
reproduces every v1 decision at the €1,500 threshold. Development labels are never written.

## Caveats

- The threshold control is a what-if on rule v1.1, **not** the official v2 policy. Swap it for the real change when v2 is released.
- The cost sentence uses placeholder assumptions (12,000 claims, 25 min, €55/h). Replace them before showing it as a business case.
- The newest app (`origin/main` of `rafik-324/thinc-hack`) reads the same 26 claims live from Supabase, so the landing and `/queue` agree
  (10 routine, 5 request info, 11 human review at v1). The landing itself ships its own generated copy and works offline.
- Animations respect `prefers-reduced-motion`.
