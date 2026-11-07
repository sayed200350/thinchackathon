import { Link } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";

import { AsciiColumns } from "@/components/ascii-columns";

import "./landing-replay.css";
import { LANDING_CLAIMS, type LandingClaim, type LandingRoute } from "./landing-data";
import {
  AXIS_MAX,
  LANES,
  LANE_LABEL,
  LANE_RULE,
  V1_THRESHOLD,
  clamp,
  flips,
  fmtEur,
  routeOpen,
  sealedHit,
  why,
  type Segment,
} from "./landing-model";
import { ReplayEngine, type HoverInfo, type StageMode } from "./replay-engine";

const CLAIMS = LANDING_CLAIMS;
const OPEN = CLAIMS.filter((c) => c.status === "open");
const CLOSED = CLAIMS.filter((c) => c.status === "closed");
const PRESETS = [1500, 1200, 1000, 2000];
const prefersReduced = () =>
  typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const easeOut = (t: number) => 1 - Math.pow(1 - t, 4);

/* ------------------------------------------------------------------ small pieces */

function Segments({ parts }: { parts: Segment[] }) {
  return (
    <>
      {parts.map((p, i) =>
        typeof p === "string" ? <span key={i}>{p}</span> : <b key={i}>{p.b}</b>,
      )}
    </>
  );
}

function Badge({ route }: { route: LandingRoute }) {
  return <span className={`pr-badge pr-badge--${route}`}>{LANE_LABEL[route]}</span>;
}

/** Slot-machine digits. Each digit slides its own strip to the target value. */
function Odometer({ value }: { value: number }) {
  const chars = String(value).split("");
  return (
    <span className="pr-odo" aria-label={String(value)}>
      {chars.map((ch, i) => {
        const key = chars.length - i; // stable from the right so units keep their strip
        return /\d/.test(ch) ? (
          <span className="pr-odo__digit" key={key} aria-hidden>
            <span className="pr-odo__strip" style={{ transform: `translateY(-${Number(ch)}em)` }}>
              {"0123456789".split("").map((n) => (
                <span key={n}>{n}</span>
              ))}
            </span>
          </span>
        ) : (
          <span key={key} aria-hidden>
            {ch}
          </span>
        );
      })}
    </span>
  );
}

/** Eases a number toward its target; returns the current animated value. */
function useTween(target: number, duration = 900) {
  const [v, setV] = useState(target);
  const from = useRef(target);
  useEffect(() => {
    if (prefersReduced()) {
      setV(target);
      from.current = target;
      return;
    }
    const start = performance.now(),
      a = from.current;
    let raf = 0;
    const step = (now: number) => {
      const p = clamp((now - start) / duration, 0, 1);
      const cur = a + (target - a) * easeOut(p);
      from.current = cur;
      setV(cur);
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, duration]);
  return v;
}

/** Adds `is-in` once the element scrolls into view. */
function useReveal<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add("is-in");
            io.unobserve(e.target);
          }
        });
      },
      { threshold: 0.12 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return ref;
}

function Mask({ children }: { children: ReactNode }) {
  return (
    <span className="pr-line">
      <span>{children}</span>
    </span>
  );
}

/* ------------------------------------------------------------------ intro, cursor, nav */

function Intro({ onOpen }: { onOpen: () => void }) {
  const [count, setCount] = useState(0);
  const [phase, setPhase] = useState<"count" | "open" | "done">("count");
  const skipped = useRef(false);

  useEffect(() => {
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = "";
    };
  }, []);

  useEffect(() => {
    if (prefersReduced()) {
      setPhase("open");
      onOpen();
      setTimeout(() => setPhase("done"), 0);
      return;
    }
    const total = CLAIMS.length,
      start = performance.now(),
      dur = 1100;
    let raf = 0,
      t1 = 0,
      t2 = 0;
    const step = (now: number) => {
      const p = skipped.current ? 1 : clamp((now - start) / dur, 0, 1);
      setCount(Math.round(easeOut(p) * total));
      if (p < 1) {
        raf = requestAnimationFrame(step);
        return;
      }
      t1 = window.setTimeout(
        () => {
          setPhase("open");
          document.body.style.overflow = "";
          onOpen();
          t2 = window.setTimeout(() => setPhase("done"), 1200);
        },
        skipped.current ? 0 : 250,
      );
    };
    raf = requestAnimationFrame(step);
    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, [onOpen]);

  if (phase === "done") return null;
  return (
    <div
      className={`pr-intro${phase === "open" ? " is-open" : ""}`}
      aria-hidden
      onClick={() => {
        skipped.current = true;
      }}
    >
      <div className="pr-intro__half pr-intro__half--top" />
      <div className="pr-intro__half pr-intro__half--bottom" />
      <div className="pr-intro__guide pr-intro__guide--x" />
      <div className="pr-intro__guide pr-intro__guide--y" />
      <div className="pr-intro__core">
        <div className="pr-intro__count">{String(count).padStart(2, "0")}</div>
        <div className="pr-eyebrow pr-intro__label">Loading open claims · policy v1</div>
      </div>
    </div>
  );
}

function Crosshair() {
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const fine = window.matchMedia("(hover: hover) and (pointer: fine)").matches;
    const el = root.current;
    if (!fine || prefersReduced() || !el) return;
    const x = el.querySelector<HTMLElement>(".pr-cursor__x")!;
    const y = el.querySelector<HTMLElement>(".pr-cursor__y")!;
    const dot = el.querySelector<HTMLElement>(".pr-cursor__dot")!;
    const read = el.querySelector<HTMLElement>(".pr-cursor__read")!;
    const p = { x: -100, y: -100, sx: -100, sy: -100 };
    let raf = 0;
    document.documentElement.classList.add("pr-no-cursor");
    const move = (ev: PointerEvent) => {
      p.x = ev.clientX;
      p.y = ev.clientY;
      el.classList.add("is-on");
      const t = ev.target instanceof Element ? ev.target : null;
      el.classList.toggle("is-hover", !!t?.closest("a, button, input, canvas"));
    };
    const loop = () => {
      p.sx += (p.x - p.sx) * 0.35;
      p.sy += (p.y - p.sy) * 0.35;
      x.style.transform = `translateY(${p.y}px)`;
      y.style.transform = `translateX(${p.x}px)`;
      dot.style.transform = `translate(${p.sx}px, ${p.sy}px)`;
      read.style.transform = `translate(${p.x + 12}px, ${p.y + 10}px)`;
      read.textContent = `x ${String(Math.round(p.x)).padStart(4, "0")} · y ${String(Math.round(p.y + window.scrollY)).padStart(4, "0")}`;
      raf = requestAnimationFrame(loop);
    };
    const leave = () => el.classList.remove("is-on");
    window.addEventListener("pointermove", move);
    document.addEventListener("pointerleave", leave);
    raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("pointermove", move);
      document.removeEventListener("pointerleave", leave);
      document.documentElement.classList.remove("pr-no-cursor");
    };
  }, []);
  return (
    <div className="pr-cursor" ref={root} aria-hidden>
      <div className="pr-cursor__x" />
      <div className="pr-cursor__y" />
      <div className="pr-cursor__dot" />
      <div className="pr-cursor__read" />
    </div>
  );
}

function Timecode({ speed, className }: { speed: number; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const speedRef = useRef(speed);
  speedRef.current = speed;
  useEffect(() => {
    let frames = 0,
      acc = 0,
      last = performance.now(),
      raf = 0;
    const fmt = (f: number) => {
      f = Math.max(0, Math.floor(f));
      const ff = f % 25,
        s = Math.floor(f / 25) % 60,
        m = Math.floor(f / 1500) % 60,
        h = Math.floor(f / 90000);
      return [h, m, s, ff].map((v) => String(v).padStart(2, "0")).join(":");
    };
    const loop = (now: number) => {
      acc += now - last;
      last = now;
      while (acc >= 40) {
        frames = Math.max(0, frames + speedRef.current);
        acc -= 40;
      }
      if (ref.current) ref.current.textContent = fmt(frames);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);
  return (
    <span ref={ref} className={className}>
      00:00:00:00
    </span>
  );
}

/* ------------------------------------------------------------------ hero readout */

/** Cycles through the claims, like a viewfinder caption over the colonnade. */
function ClaimReadout() {
  const [i, setI] = useState(0);
  useEffect(() => {
    if (prefersReduced()) return;
    const id = setInterval(() => setI((v) => (v + 1) % CLAIMS.length), 1800);
    return () => clearInterval(id);
  }, []);
  const c = CLAIMS[i]!;
  return (
    <div className="pr-readout" aria-hidden>
      <span className="pr-eyebrow">
        Claim {String(i + 1).padStart(2, "0")} / {CLAIMS.length}
      </span>
      <div className="pr-readout__row" key={c.id}>
        <span className="pr-readout__id">{c.id}</span>
        <span className="pr-readout__quote">{c.quote === null ? "no quote" : fmtEur(c.quote)}</span>
        <Badge route={c.v1} />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ scroll-driven ticker */

/**
 * Claim ticker that follows the scroll direction: it drifts left while the page scrolls
 * down and right while it scrolls up. Faster scrolling speeds it up; velocity is eased so
 * direction changes glide instead of snapping. Static under prefers-reduced-motion.
 */
function Ticker({ items }: { items: ReactNode }) {
  const track = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = track.current;
    if (!el || prefersReduced()) return;
    const BASE = 38; // px/s while idle
    let x = 0;
    let v = -BASE; // current velocity, px/s (negative = left)
    let dir = -1; // -1 = left (scrolling down), +1 = right (scrolling up)
    let boost = 0;
    let lastY = window.scrollY;
    let lastT = performance.now();
    let raf = 0;

    const onScroll = () => {
      const now = performance.now();
      const dy = window.scrollY - lastY;
      const dt = Math.max(1, now - lastT);
      if (dy !== 0) {
        dir = dy > 0 ? -1 : 1;
        boost = Math.min(Math.abs(dy / dt) * 220, 520);
      }
      lastY = window.scrollY;
      lastT = now;
    };

    let frameT = performance.now();
    const loop = (now: number) => {
      const dt = Math.min(0.05, (now - frameT) / 1000);
      frameT = now;
      const decay = Math.pow(0.94, dt * 60); // frame-rate independent easing
      boost *= decay;
      v += (dir * (BASE + boost) - v) * (1 - Math.pow(0.94, dt * 60));
      x += v * dt;
      const half = el.scrollWidth / 2;
      if (half > 0) {
        if (x <= -half) x += half;
        if (x > 0) x -= half;
      }
      el.style.transform = `translate3d(${x.toFixed(2)}px,0,0)`;
      raf = requestAnimationFrame(loop);
    };

    window.addEventListener("scroll", onScroll, { passive: true });
    raf = requestAnimationFrame(loop);
    return () => {
      window.removeEventListener("scroll", onScroll);
      cancelAnimationFrame(raf);
    };
  }, []);

  return (
    <div className="pr-ticker" aria-hidden>
      <div className="pr-ticker__track" ref={track}>
        {items}
        {items}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ replay stage */

interface LaneGeo {
  cy: Record<LandingRoute, number>;
  y0: Record<LandingRoute, number>;
  narrow: boolean;
  laneX0: number;
}

function ReplayStage({
  threshold,
  onPreview,
  engineRef,
  onMode,
}: {
  threshold: number;
  onPreview: (t: number) => void;
  engineRef: React.MutableRefObject<ReplayEngine | null>;
  onMode: (m: StageMode) => void;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [mode, setMode] = useState<StageMode>("idle");
  const [counts, setCounts] = useState<Record<LandingRoute, number>>({
    routine_processing: 0,
    request_information: 0,
    human_review: 0,
  });
  const [hover, setHover] = useState<HoverInfo | null>(null);
  const [geo, setGeo] = useState<LaneGeo | null>(null);
  const thresholdRef = useRef(threshold);
  thresholdRef.current = threshold;

  useEffect(() => {
    const engine = new ReplayEngine(canvasRef.current!, wrapRef.current!, CLAIMS, {
      onMode: (m) => {
        setMode(m);
        onMode(m);
      },
      onCounts: setCounts,
      onHover: setHover,
      onLanes: (cy, narrow, laneX0, y0) => setGeo({ cy, narrow, laneX0, y0 }),
    });
    engineRef.current = engine;
    return () => {
      engine.destroy();
      engineRef.current = null;
    };
  }, [engineRef, onMode]);

  const commit = (t: number) => engineRef.current?.setThreshold(t);
  const pct = (v: number) => (clamp(v, 0, AXIS_MAX) / AXIS_MAX) * 100;
  const changed = threshold !== V1_THRESHOLD;
  const hitOrder = CLAIMS.filter(
    (c) => c.quote !== null && (flips(c, threshold) || sealedHit(c, threshold)),
  )
    .sort((x, y) => (x.quote ?? 0) - (y.quote ?? 0))
    .map((c) => c.id);
  const flippedCount = OPEN.filter((c) => flips(c, threshold)).length;
  const sealedCount = CLOSED.filter((c) => sealedHit(c, threshold)).length;
  const hoverChanged = hover
    ? hover.claim.status === "open" && hover.now !== hover.claim.v1
    : false;

  return (
    <div
      className={`pr-stage${mode === "rewind" ? " is-rewind" : ""}${mode === "play" ? " is-play" : ""}`}
    >
      <div className="pr-stage__hud pr-eyebrow">
        <span className="pr-stage__mode">
          <i />
          {mode === "rewind" ? "Rewinding" : mode === "play" ? "Replaying" : "Ready"}
        </span>
        <span className="pr-mono">
          TC <Timecode speed={mode === "rewind" ? -6 : mode === "play" ? 2 : 1} />
        </span>
        <span>{changed ? `${flippedCount} changed · ${sealedCount} sealed` : "v1 baseline"}</span>
      </div>

      <div className="pr-stage__canvas" ref={wrapRef}>
        <canvas
          ref={canvasRef}
          role="img"
          aria-label="Animated routing of claims into three decision lanes"
        />
        <div className="pr-stage__lanes">
          {geo &&
            LANES.map((lane) => (
              <div
                key={lane}
                className="pr-lane-label"
                style={
                  geo.narrow
                    ? ({
                        left: geo.laneX0,
                        top: geo.y0[lane] + 10,
                        textAlign: "left",
                      } as CSSProperties)
                    : ({ top: geo.cy[lane] } as CSSProperties)
                }
              >
                <span className="pr-eyebrow">
                  {LANE_RULE[lane]} · {LANE_LABEL[lane]}
                </span>
                <span className="pr-lane-label__count">
                  <Odometer value={counts[lane]} />
                </span>
              </div>
            ))}
        </div>
        <div className="pr-stage__fx" />
        <div className="pr-stage__flash" />
        <div className="pr-stage__banner pr-eyebrow pr-mono">
          {mode === "rewind" ? "◀◀ Rewind" : `▶ Replay · v1.1 > ${fmtEur(threshold)}`}
        </div>
        {hover && (
          <div
            className="pr-tip is-on"
            style={{
              left: hover.x + 18 + 320 > hover.width - 8 ? hover.x - 338 : hover.x + 18,
              top: clamp(hover.y - 70, 8, hover.height - 200),
            }}
            role="status"
          >
            <div className="pr-tip__head">
              <span className="pr-tip__id">{hover.claim.id}</span>
              <span className="pr-eyebrow">
                {hover.claim.quote === null ? "no quote" : fmtEur(hover.claim.quote)} ·{" "}
                {hover.claim.status}
              </span>
            </div>
            <p className="pr-tip__summary">{hover.claim.summary}</p>
            <div className="pr-tip__route">
              <Badge route={hover.claim.v1} />
              {hoverChanged && (
                <>
                  <span className="pr-arrow">→</span>
                  <Badge route={hover.now} />
                  <span className="pr-tag pr-tag--changed">changed</span>
                </>
              )}
              {hover.claim.status === "closed" && <span className="pr-tag">sealed</span>}
            </div>
            <p className="pr-tip__why">
              {hoverChanged || sealedHit(hover.claim, threshold) ? (
                <Segments parts={why(hover.claim, threshold)} />
              ) : (
                hover.claim.explanation
              )}
            </p>
          </div>
        )}
      </div>

      <div className="pr-controls">
        <div className="pr-controls__value">
          <span className="pr-eyebrow">Rule v1.1 · human review if quote &gt;</span>
          <span className={`pr-controls__num${changed ? " is-changed" : ""}`}>
            {fmtEur(threshold)}
          </span>
        </div>
        <div className={`pr-scrub${changed ? " is-changed" : ""}`}>
          <div className="pr-scrub__scale">
            {[0, 500, 1000, 1500, 2000, 2500].map((v, k, a) => (
              <span
                key={v}
                style={{
                  left: `${pct(v)}%`,
                  transform:
                    k === 0
                      ? "none"
                      : k === a.length - 1
                        ? "translateX(-100%)"
                        : "translateX(-50%)",
                }}
              >
                {fmtEur(v)}
              </span>
            ))}
          </div>
          <div className="pr-scrub__axis" />
          <div
            className="pr-scrub__fill"
            style={{
              left: `${pct(Math.min(threshold, V1_THRESHOLD))}%`,
              width: `${Math.abs(pct(threshold) - pct(V1_THRESHOLD))}%`,
            }}
          />
          {CLAIMS.filter((c) => c.quote !== null).map((c) => {
            const hit = flips(c, threshold) || sealedHit(c, threshold);
            const slot = hit ? hitOrder.indexOf(c.id) : 0;
            return (
              <span key={c.id}>
                <i
                  className={`pr-scrub__tick${c.status === "closed" ? " is-closed" : ""}${(c.quote as number) > threshold ? " is-over" : ""}${hit ? " is-changed" : ""}`}
                  style={{ left: `${pct(c.quote as number)}%` }}
                />
                {hit && (
                  <span
                    className="pr-scrub__tick-label"
                    style={{ left: `${pct(c.quote as number)}%`, top: 62 + (slot % 3) * 10 }}
                  >
                    {c.id}
                  </span>
                )}
              </span>
            );
          })}
          <div className="pr-scrub__v1" style={{ left: `${pct(V1_THRESHOLD)}%` }}>
            <span>v1</span>
          </div>
          <input
            type="range"
            min={0}
            max={AXIS_MAX}
            step={50}
            value={threshold}
            aria-label="Quote threshold for human review in euros"
            onChange={(e) => onPreview(Number(e.target.value))}
            onPointerUp={(e) => commit(Number((e.target as HTMLInputElement).value))}
            onKeyUp={(e) => commit(Number((e.target as HTMLInputElement).value))}
          />
          <div className="pr-scrub__handle" style={{ left: `${pct(threshold)}%` }} />
        </div>
        <div className="pr-presets" role="group" aria-label="Threshold presets">
          {PRESETS.map((v) => (
            <button
              key={v}
              type="button"
              className={`pr-chip${threshold === v ? " is-active" : ""}`}
              onClick={() => {
                onPreview(v);
                commit(v);
              }}
            >
              {v === V1_THRESHOLD ? "v1 · " : ""}
              {fmtEur(v)}
            </button>
          ))}
          <button type="button" className="pr-chip" onClick={() => engineRef.current?.replayAll()}>
            ↻ Replay all
          </button>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ sections below the stage */

function Diff({ threshold }: { threshold: number }) {
  const ref = useReveal<HTMLDivElement>();
  const changed = threshold !== V1_THRESHOLD;
  const flipped = OPEN.filter((c) => flips(c, threshold)).length;
  const sealed = CLOSED.filter((c) => sealedHit(c, threshold)).length;
  return (
    <div className={`pr-diff pr-fade${changed ? " is-changed" : ""}`} ref={ref}>
      <div className="pr-diff__bar pr-eyebrow">
        <span>Clause diff</span>
        <span>
          {changed
            ? `What-if · ${fmtEur(V1_THRESHOLD)} → ${fmtEur(threshold)}`
            : "No change from v1"}
        </span>
      </div>
      <div className="pr-diff__body">
        <span className="pr-diff__rule">v1.1</span>Send the claim to human review if the repair
        quote exceeds <span className="pr-diff__old">{fmtEur(V1_THRESHOLD)}</span>
        <span className="pr-diff__new">{fmtEur(threshold)}</span>.
      </div>
      <div className="pr-diff__foot">
        <span>
          {flipped} open claim{flipped === 1 ? "" : "s"} change route
        </span>
        <span>
          {sealed} closed claim{sealed === 1 ? "" : "s"} would change but stay sealed
        </span>
      </div>
    </div>
  );
}

function Cards({ threshold }: { threshold: number }) {
  const list = OPEN.filter((c) => flips(c, threshold)).sort(
    (a, b) => (a.quote ?? 0) - (b.quote ?? 0),
  );
  const hits = CLOSED.filter((c) => sealedHit(c, threshold));
  const secRef = useReveal<HTMLElement>();
  return (
    <section className="pr-section is-reveal" id="second-look" ref={secRef}>
      <div className="pr-wrap">
        <div className="pr-section__head">
          <div className="pr-eyebrow">02 · Second look</div>
          <div>
            <h2 className="pr-section__title">
              <Mask>
                {list.length
                  ? `${list.length} claim${list.length === 1 ? "" : "s"} need${list.length === 1 ? "s" : ""} a second look.`
                  : "Nothing to recheck."}
              </Mask>
            </h2>
            <p className="pr-section__copy pr-fade">
              Every card is one claim whose route changes, with the deciding fact in one sentence.
              That is the reviewer’s whole to-do list after a policy update.
            </p>
          </div>
        </div>
        <div className="pr-cards" aria-live="polite">
          {list.map((c, k) => (
            <Card key={c.id} c={c} t={threshold} delay={k * 70} />
          ))}
          {!list.length && (
            <div className="pr-empty">
              At the v1 threshold no open claim changes route. Drag rule v1.1 above to simulate a
              policy update.
            </div>
          )}
        </div>
        <div className="pr-sealed pr-fade">
          <span className="pr-sealed__lock" aria-hidden>
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
            >
              <rect x="4" y="11" width="16" height="10" rx="1" />
              <path d="M8 11V7a4 4 0 0 1 8 0v4" />
            </svg>
          </span>
          <p>
            <b>{CLOSED.length} closed claims are sealed.</b>{" "}
            {hits.length
              ? `${hits.map((c) => `${c.id} (${fmtEur(c.quote ?? 0)})`).join(", ")} would move to ${LANE_LABEL[routeOpen(hits[0]!, threshold)]} under this rule, but closed claims keep their v1 decision and are never flagged for recheck.`
              : "They keep their v1 decision and are never flagged for recheck."}
          </p>
        </div>
      </div>
    </section>
  );
}

function Card({ c, t, delay }: { c: LandingClaim; t: number; delay: number }) {
  const ref = useRef<HTMLElement>(null);
  const onMove = (ev: React.PointerEvent) => {
    if (prefersReduced() || ev.pointerType !== "mouse" || !ref.current) return;
    const r = ref.current.getBoundingClientRect();
    const px = (ev.clientX - r.left) / r.width - 0.5,
      py = (ev.clientY - r.top) / r.height - 0.5;
    ref.current.style.transform = `rotateX(${(-py * 8).toFixed(2)}deg) rotateY(${(px * 10).toFixed(2)}deg)`;
  };
  return (
    <article
      ref={ref}
      className="pr-card"
      style={{ animationDelay: `${delay}ms` }}
      onPointerMove={onMove}
      onPointerLeave={() => {
        if (ref.current) ref.current.style.transform = "";
      }}
    >
      <div className="pr-card__head">
        <span className="pr-card__id">{c.id}</span>
        <span className="pr-card__quote">{fmtEur(c.quote ?? 0)}</span>
      </div>
      <div className="pr-card__route">
        <Badge route={c.v1} />
        <span className="pr-arrow">→</span>
        <Badge route={routeOpen(c, t)} />
      </div>
      <p className="pr-card__why">
        <Segments parts={why(c, t)} />
      </p>
    </article>
  );
}

function Impact({ threshold }: { threshold: number }) {
  const ref = useReveal<HTMLElement>();
  const [volume, setVolume] = useState("12,000");
  const [minutes, setMinutes] = useState("25");
  const [rate, setRate] = useState("55");
  const num = (s: string) => Number(s.replace(/[^\d.]/g, "")) || 0;

  const flipped = OPEN.filter((c) => flips(c, threshold)).length;
  const reviewNow = OPEN.filter((c) => routeOpen(c, threshold) === "human_review").length;
  const reviewV1 = OPEN.filter((c) => c.v1 === "human_review").length;
  const delta = Math.round(num(volume) * ((reviewNow - reviewV1) / OPEN.length));
  const cost = ((delta * num(minutes)) / 60) * num(rate);
  const tDelta = useTween(delta),
    tCost = useTween(cost);
  const cls = delta > 0 ? "is-up" : delta < 0 ? "is-down" : "";
  const n = Math.round(tDelta);

  return (
    <section className="pr-section pr-dark is-reveal" id="impact" ref={ref}>
      <div className="pr-wrap">
        <div className="pr-section__head">
          <div className="pr-eyebrow">03 · Impact</div>
          <div>
            <h2 className="pr-section__title">
              <Mask>One rule. Measurable</Mask>
              <Mask>before it ships.</Mask>
            </h2>
            <p className="pr-section__copy pr-fade">
              The numbers update with the threshold above. They are computed from the{" "}
              {CLAIMS.length} claims in the case pack, so they show direction, not a forecast.
            </p>
          </div>
        </div>
        <div className="pr-stats pr-fade">
          <div className="pr-stat">
            <div className="pr-eyebrow">Claims replayed</div>
            <div className="pr-stat__num">
              <Odometer value={CLAIMS.length} />
            </div>
            <div className="pr-stat__note">dev + practice pack</div>
          </div>
          <div className="pr-stat">
            <div className="pr-eyebrow">Change route</div>
            <div className="pr-stat__num pr-accent">
              <Odometer value={flipped} />
            </div>
            <div className="pr-stat__note">open claims, need a second look</div>
          </div>
          <div className="pr-stat">
            <div className="pr-eyebrow">Human review</div>
            <div className="pr-stat__num">
              <Odometer value={reviewNow} />
            </div>
            <div className="pr-stat__note">open claims under this rule</div>
          </div>
          <div className="pr-stat">
            <div className="pr-eyebrow">Sealed</div>
            <div className="pr-stat__num">
              <Odometer value={CLOSED.length} />
            </div>
            <div className="pr-stat__note">closed, keep v1</div>
          </div>
        </div>

        <p className="pr-calc pr-fade">
          <span className="pr-muted">With</span>{" "}
          <Field
            value={volume}
            onChange={setVolume}
            label="Claims per year"
            onBlur={() => setVolume(num(volume).toLocaleString("en-US"))}
          />{" "}
          <span className="pr-muted">claims a year,</span>{" "}
          <Field value={minutes} onChange={setMinutes} label="Minutes per human review" />{" "}
          <span className="pr-muted">minutes per human review and €</span>
          <Field value={rate} onChange={setRate} label="Reviewer cost per hour in euros" />
          <span className="pr-muted">/h, this rule change means</span>{" "}
          <span className={`pr-result ${cls}`}>
            {n === 0
              ? "no change in reviews"
              : `${n > 0 ? "+" : "−"}${Math.abs(n).toLocaleString("en-US")} ${n > 0 ? "more" : "fewer"} reviews`}
          </span>{" "}
          <span className="pr-muted">and</span>{" "}
          <span className={`pr-result ${cls}`}>
            {Math.round(tCost) === 0 ? "€0" : `${tCost > 0 ? "+" : "−"}${fmtEur(Math.abs(tCost))}`}
          </span>{" "}
          <span className="pr-muted">reviewer cost per year.</span>
        </p>
        <p className="pr-calc__foot">
          Volume, minutes and hourly cost are editable assumptions. The change in review share comes
          from the {OPEN.length} open sample claims at the selected threshold.
        </p>
      </div>
    </section>
  );
}

function Field({
  value,
  onChange,
  label,
  onBlur,
}: {
  value: string;
  onChange: (v: string) => void;
  label: string;
  onBlur?: () => void;
}) {
  return (
    <input
      className="pr-field"
      value={value}
      inputMode="numeric"
      aria-label={label}
      size={Math.max(2, value.length)}
      onChange={(e) => onChange(e.target.value)}
      onBlur={onBlur}
    />
  );
}

/* ------------------------------------------------------------------ page */

export function LandingReplay() {
  const [threshold, setThreshold] = useState(V1_THRESHOLD);
  const [introDone, setIntroDone] = useState(false);
  const [mode, setMode] = useState<StageMode>("idle");
  const engineRef = useRef<ReplayEngine | null>(null);
  const heroRef = useRef<HTMLElement>(null);
  const replayRef = useReveal<HTMLElement>();
  const diffWrap = useReveal<HTMLElement>();
  const finalRef = useReveal<HTMLElement>();

  const onOpen = useCallback(() => setIntroDone(true), []);
  const onMode = useCallback((m: StageMode) => setMode(m), []);
  const ticker = useMemo(
    () =>
      CLAIMS.map((c) => (
        <span className="pr-ticker__item" key={c.id}>
          <b>{c.id}</b>
          {c.quote === null ? "no quote" : fmtEur(c.quote)}
          <span>→ {LANE_LABEL[c.v1].toLowerCase()}</span>
          <span>{c.rule}</span>
        </span>
      )),
    [],
  );

  return (
    <div className="pr-root">
      <Intro onOpen={onOpen} />
      <div className="pr-grain" aria-hidden />
      <Crosshair />

      <header className="pr-nav">
        <a className="pr-nav__brand" href="#top">
          <span className="pr-nav__mark" aria-hidden />
          Policy Replay
        </a>
        <nav className="pr-nav__links" aria-label="Sections">
          <a href="#replay">Replay</a>
          <a href="#second-look">Second look</a>
          <a href="#impact">Impact</a>
        </nav>
        <div className="pr-nav__hud pr-eyebrow">
          <span className="pr-rec">
            <i />
            Rec
          </span>
          <Timecode speed={mode === "rewind" ? -6 : mode === "play" ? 2 : 1} className="pr-tc" />
          <Link to="/queue" className="pr-nav__cta">
            Open queue →
          </Link>
        </div>
      </header>

      <main id="top">
        <section className={`pr-hero${introDone ? " is-in" : ""}`} ref={heroRef}>
          <div className="pr-hero__ascii" aria-hidden>
            <AsciiColumns className="pr-hero__ascii-canvas" />
          </div>
          <ClaimReadout />
          <div className="pr-hero__frame" aria-hidden>
            <i />
            <i />
            <i />
            <i />
          </div>
          <div className="pr-wrap pr-hero__top">
            <div className="pr-hero__meta pr-eyebrow pr-fade">
              <span>Taktile track · thinc! hack MUC</span>
              <span>Motor claims · policy v1 → v2</span>
            </div>
            <h1 className="pr-hero__title">
              <Mask>Policy changed.</Mask>
              <Mask>
                <span className="pr-ghost">Every open claim</span>
              </Mask>
              <Mask>replays.</Mask>
            </h1>
          </div>
          <div className="pr-wrap pr-hero__bottom">
            <p className="pr-hero__lede pr-fade">
              Policy Replay re-runs <strong>{OPEN.length} open motor claims</strong> through the new
              rules and shows the reviewer exactly{" "}
              <strong>which ones need a second look, and why.</strong>
            </p>
            <div className="pr-hero__cta pr-fade">
              <a className="pr-btn" href="#replay">
                Watch the replay{" "}
                <span className="pr-btn__arrow">
                  <span>→</span>
                  <span>→</span>
                </span>
              </a>
              <Link className="pr-btn pr-btn--ghost" to="/queue">
                Open reviewer queue
              </Link>
            </div>
          </div>
          <Ticker items={ticker} />
        </section>

        <section className="pr-section is-reveal" id="replay" ref={replayRef}>
          <div className="pr-wrap">
            <div className="pr-section__head">
              <div className="pr-eyebrow">01 · Replay</div>
              <div>
                <h2 className="pr-section__title">
                  <Mask>Drag the rule.</Mask>
                  <Mask>Watch claims re-route.</Mask>
                </h2>
                <p className="pr-section__copy pr-fade">
                  Each tile is a real claim from the case pack, decided by our v1 engine. Move rule
                  v1.1’s quote threshold and the affected claims rewind and replay into their new
                  route. Closed claims are sealed and keep their v1 decision.
                </p>
              </div>
            </div>
            <div className="pr-fade">
              <ReplayStage
                threshold={threshold}
                onPreview={setThreshold}
                engineRef={engineRef}
                onMode={onMode}
              />
            </div>
          </div>
        </section>

        <section className="pr-section pr-section--flush is-reveal" ref={diffWrap}>
          <div className="pr-wrap">
            <Diff threshold={threshold} />
          </div>
        </section>

        <Cards threshold={threshold} />
        <Impact threshold={threshold} />

        <section className="pr-final is-reveal" ref={finalRef}>
          <div className="pr-wrap">
            <div className="pr-eyebrow">04 · Rollout</div>
            <h2 className="pr-final__title">
              <Mask>Know who needs</Mask>
              <Mask>
                <span className="pr-accent">a second look</span>
              </Mask>
              <Mask>before you ship.</Mask>
            </h2>
            <div className="pr-final__row">
              <p className="pr-hero__lede pr-fade">
                Every decision is explained, every reviewer override is saved with its reason, and
                closed claims stay untouched.
              </p>
              <div className="pr-hero__cta pr-fade">
                <Link className="pr-btn" to="/queue">
                  Open reviewer queue{" "}
                  <span className="pr-btn__arrow">
                    <span>→</span>
                    <span>→</span>
                  </span>
                </Link>
                <a className="pr-btn pr-btn--ghost" href="#replay">
                  Replay again
                </a>
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="pr-footer">
        <div className="pr-wrap">
          <p>
            Decisions come from the Policy Replay v1 engine run on the Taktile case pack (14
            development and 12 practice claims). The threshold control is a what-if simulation of
            rule v1.1, not the official v2 policy, which is released on Saturday at 18:00.
          </p>
          <p className="pr-mono">Policy Replay · 2026</p>
        </div>
      </footer>
    </div>
  );
}
