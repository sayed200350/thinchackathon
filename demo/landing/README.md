# Landing page

Static, dependency-free landing page for Policy Replay (HTML, CSS, vanilla JS, canvas).

## Run

```sh
python3 -m http.server 8899 --directory demo/landing
```

Open <http://127.0.0.1:8899>.

## What it shows

- **Replay stage:** all 26 claims from the case pack, routed by the real v1 engine. Dragging the threshold of rule v1.1 rewinds the affected claims and replays them into their new lane. Closed claims are sealed and keep their v1 decision.
- **Second look:** one card per claim whose route changes, with the deciding fact.
- **Impact:** live counts and an editable cost sentence (volume, minutes, hourly cost).

The threshold control is a what-if on rule v1.1, **not** the official v2 policy. Replace it with the real v2 change once it is released.

## Regenerate the data

`data.js` is generated from the engine. After changing `engine/` or the CSVs, run from the repository root:

```sh
python3 demo/landing/build_data.py
```

The script asserts that the simulation in `landing.js` reproduces every v1 decision at the €1,500 threshold. Development labels are never written to `data.js`.

Tokens follow `demo/design-system.md`. Animations respect `prefers-reduced-motion`.
