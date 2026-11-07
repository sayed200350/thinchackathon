import type { LandingClaim, LandingRoute } from "./landing-data";
import { LANES, LANE_RULE, V1_THRESHOLD, clamp, fmtEur, route, sealedHit } from "./landing-model";

/**
 * Canvas engine for the replay stage. Framework-free: React owns the lifecycle
 * (create in an effect, destroy on cleanup) and reads state through callbacks.
 */

export type StageMode = "idle" | "rewind" | "play";

export interface HoverInfo {
  claim: LandingClaim;
  now: LandingRoute;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface EngineCallbacks {
  onMode: (mode: StageMode) => void;
  onCounts: (counts: Record<LandingRoute, number>) => void;
  onHover: (info: HoverInfo | null) => void;
  onLanes: (
    cy: Record<LandingRoute, number>,
    narrow: boolean,
    laneX0: number,
    y0: Record<LandingRoute, number>,
  ) => void;
}

interface Pt {
  x: number;
  y: number;
}
interface Anim {
  from: Pt;
  to: Pt;
  c1: Pt;
  c2: Pt;
  start: number;
  dur: number;
  ease: (t: number) => number;
  trail: boolean;
  resolve: () => void;
}
interface Token {
  c: LandingClaim;
  i: number;
  x: number;
  y: number;
  route: LandingRoute | null;
  anim: Anim | null;
  trail: Pt[];
  flash: number;
  shake: number;
  hover: boolean;
}

const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const easeOut = (t: number) => 1 - Math.pow(1 - t, 4);
const bezier = (a: number, b: number, c: number, d: number, t: number) => {
  const u = 1 - t;
  return u * u * u * a + 3 * u * u * t * b + 3 * u * t * t * c + t * t * t * d;
};

// Dark palette. Orange is hard-coded on purpose: it marks "changed" and nothing else.
const C = {
  ink: "#fdfcfc",
  ink150: "#686565",
  ink200: "#9a9797",
  ink300: "#bebaba",
  edge: "rgba(253,252,252,0.16)",
  grid: "rgba(253,252,252,0.045)",
  contrast: "#ff4d00",
  card: "#0b0a0a",
  lane: {
    routine_processing: { soft: "rgba(131,230,175,0.13)", line: "#83e6af", text: "#83e6af" },
    request_information: { soft: "rgba(243,193,130,0.13)", line: "#f3c182", text: "#f3c182" },
    human_review: { soft: "rgba(130,184,218,0.14)", line: "#82b8da", text: "#82b8da" },
  } as Record<LandingRoute, { soft: string; line: string; text: string }>,
};

export class ReplayEngine {
  private ctx: CanvasRenderingContext2D;
  private tokens: Token[];
  private L = {
    W: 0,
    H: 0,
    dpr: 1,
    tw: 66,
    th: 22,
    gap: 6,
    gateX: 0,
    laneX0: 0,
    laneX1: 0,
    narrow: false,
    lanes: {} as Record<LandingRoute, { y0: number; y1: number; cy: number }>,
    intake: [] as Pt[],
  };
  private threshold = V1_THRESHOLD;
  private busy = false;
  private pending: { next: number; all: boolean } | null = null;
  private firstRunDone = false;
  private visible = false;
  private raf = 0;
  private destroyed = false;
  private reduced: boolean;
  private ro: ResizeObserver;
  private io: IntersectionObserver;

  constructor(
    private canvas: HTMLCanvasElement,
    private wrap: HTMLElement,
    private claims: LandingClaim[],
    private cb: EngineCallbacks,
  ) {
    this.ctx = canvas.getContext("2d")!;
    this.reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    this.tokens = claims.map((c, i) => ({
      c,
      i,
      x: 0,
      y: 0,
      route: null,
      anim: null,
      trail: [],
      flash: 0,
      shake: 0,
      hover: false,
    }));
    this.layout();
    this.tokens.forEach((t) => {
      const p = this.L.intake[t.i]!;
      t.x = p.x;
      t.y = p.y;
    });
    this.emitCounts();

    this.ro = new ResizeObserver(() => this.onResize());
    this.ro.observe(wrap);
    this.io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          this.visible = e.isIntersecting;
          if (this.visible && !this.firstRunDone) void this.firstRun();
        });
      },
      { threshold: 0.35 },
    );
    this.io.observe(wrap);

    canvas.addEventListener("pointermove", this.onMove);
    canvas.addEventListener("pointerleave", this.onLeave);
    this.raf = requestAnimationFrame(this.loop);
  }

  destroy() {
    this.destroyed = true;
    cancelAnimationFrame(this.raf);
    this.ro.disconnect();
    this.io.disconnect();
    this.canvas.removeEventListener("pointermove", this.onMove);
    this.canvas.removeEventListener("pointerleave", this.onLeave);
  }

  /** Called whenever the user releases the threshold control. */
  setThreshold(next: number) {
    void this.apply(next, false);
  }
  replayAll() {
    void this.apply(this.threshold, true);
  }
  getRouteOf(id: string) {
    return this.tokens.find((t) => t.c.id === id)?.route ?? null;
  }

  private sleep(ms: number) {
    return new Promise<void>((r) => setTimeout(r, this.reduced ? 0 : ms));
  }

  private layout() {
    const { L } = this;
    const r = this.wrap.getBoundingClientRect();
    L.dpr = Math.min(window.devicePixelRatio || 1, 2);
    L.W = r.width;
    L.H = r.height;
    this.canvas.width = Math.round(L.W * L.dpr);
    this.canvas.height = Math.round(L.H * L.dpr);
    L.narrow = L.W < 720;
    L.tw = L.narrow ? 50 : 66;
    L.th = L.narrow ? 18 : 22;
    L.gap = L.narrow ? 5 : 6;
    const pad = L.narrow ? 12 : 22;
    const labelW = L.narrow ? 0 : 190;
    L.gateX = L.W * (L.narrow ? 0.34 : 0.36);
    L.laneX0 = L.W * (L.narrow ? 0.45 : 0.47);
    L.laneX1 = L.W - pad - labelW;

    const top = 22,
      bandH = (L.H - top * 2) / 3;
    LANES.forEach((lane, i) => {
      const y0 = top + bandH * i;
      L.lanes[lane] = { y0, y1: y0 + bandH, cy: y0 + bandH / 2 + (L.narrow ? 8 : 0) };
    });
    this.cb.onLanes(
      Object.fromEntries(LANES.map((l) => [l, L.lanes[l].cy])) as Record<LandingRoute, number>,
      L.narrow,
      L.laneX0,
      Object.fromEntries(LANES.map((l) => [l, L.lanes[l].y0])) as Record<LandingRoute, number>,
    );

    const n = this.claims.length;
    const cols = Math.max(1, Math.ceil((n * (L.th + L.gap)) / (L.H - 80)));
    const rows = Math.ceil(n / cols);
    const gridH = rows * (L.th + L.gap) - L.gap;
    const y0 = (L.H - gridH) / 2 + 8;
    L.intake = this.claims.map((_, i) => ({
      x: pad + (i % cols) * (L.tw + L.gap) + L.tw / 2,
      y: y0 + Math.floor(i / cols) * (L.th + L.gap) + L.th / 2,
    }));
  }

  private onResize = () => {
    this.layout();
    const slots = this.laneSlots();
    this.tokens.forEach((t) => {
      if (t.anim) return;
      const p = (t.route ? slots.get(t) : this.L.intake[t.i])!;
      t.x = p.x;
      t.y = p.y;
    });
  };

  private laneSlots() {
    const { L } = this;
    const slots = new Map<Token, Pt>();
    const usable = L.laneX1 - L.laneX0;
    const cols = Math.max(1, Math.floor((usable + L.gap) / (L.tw + L.gap)));
    LANES.forEach((lane) => {
      const members = this.tokens
        .filter((t) => t.route === lane)
        .sort((a, b) => a.c.id.localeCompare(b.c.id));
      const rows = Math.ceil(members.length / cols);
      const lb = L.lanes[lane];
      const gapY = Math.min(L.gap, (lb.y1 - lb.y0 - 12 - rows * L.th) / Math.max(1, rows - 1));
      const h = rows * L.th + (rows - 1) * gapY;
      const startY = lb.cy - h / 2 + L.th / 2;
      members.forEach((t, k) => {
        slots.set(t, {
          x: L.laneX0 + (k % cols) * (L.tw + L.gap) + L.tw / 2,
          y: startY + Math.floor(k / cols) * (L.th + gapY),
        });
      });
    });
    return slots;
  }

  private animate(
    t: Token,
    to: Pt,
    o: {
      via?: boolean;
      dur?: number;
      delay?: number;
      ease?: (x: number) => number;
      trail?: boolean;
    } = {},
  ) {
    const { via = true, dur = 1000, delay = 0, ease = easeInOut, trail = false } = o;
    return new Promise<void>((resolve) => {
      const from = { x: t.x, y: t.y };
      const c1 = via ? { x: this.L.gateX, y: from.y } : from;
      const c2 = via ? { x: this.L.gateX, y: to.y } : to;
      if (this.reduced) {
        t.x = to.x;
        t.y = to.y;
        resolve();
        return;
      }
      t.anim = { from, to, c1, c2, start: performance.now() + delay, dur, ease, trail, resolve };
    });
  }

  private emitCounts() {
    const counts = { routine_processing: 0, request_information: 0, human_review: 0 } as Record<
      LandingRoute,
      number
    >;
    this.tokens.forEach((t) => {
      if (t.route) counts[t.route] += 1;
    });
    this.cb.onCounts(counts);
  }

  private async firstRun() {
    this.firstRunDone = true;
    this.busy = true;
    this.tokens.forEach((t) => {
      const p = this.L.intake[t.i]!;
      t.route = null;
      t.x = p.x;
      t.y = p.y;
    });
    this.emitCounts();
    await this.sleep(400);
    this.cb.onMode("play");
    this.tokens.forEach((t) => {
      t.route = route(t.c, this.threshold);
    });
    const slots = this.laneSlots();
    await Promise.all(
      this.tokens.map((t, k) =>
        this.animate(t, slots.get(t)!, { dur: 1150, delay: k * 55, trail: true }).then(() => {
          t.flash = 1;
          this.emitCounts();
        }),
      ),
    );
    this.cb.onMode("idle");
    this.busy = false;
    this.flush();
  }

  private async apply(next: number, all: boolean) {
    if (this.destroyed) return;
    if (this.busy) {
      this.pending = { next, all };
      return;
    }
    if (!this.firstRunDone) {
      this.threshold = next;
      return;
    }
    this.busy = true;
    this.threshold = next;
    const movers = this.tokens.filter(
      (t) => all || (t.c.status === "open" && route(t.c, next) !== t.route),
    );
    this.tokens
      .filter((t) => sealedHit(t.c, next))
      .forEach((t) => {
        t.shake = 1;
      });

    if (movers.length) {
      this.cb.onMode("rewind");
      await Promise.all(
        movers.map((t, k) =>
          this.animate(t, this.L.intake[t.i]!, { dur: 760, delay: k * 18, trail: true }),
        ),
      );
      movers.forEach((t) => {
        t.route = null;
      });
      this.emitCounts();
      await this.sleep(160);
      this.cb.onMode("play");
      movers.forEach((t) => {
        t.route = route(t.c, next);
      });
      const slots = this.laneSlots();
      this.tokens
        .filter((t) => t.route && !movers.includes(t))
        .forEach((t) => {
          void this.animate(t, slots.get(t)!, { via: false, dur: 650, ease: easeOut });
        });
      await Promise.all(
        movers.map((t, k) =>
          this.animate(t, slots.get(t)!, { dur: 1150, delay: k * 70, trail: true }).then(() => {
            t.flash = 1;
            this.emitCounts();
          }),
        ),
      );
      this.cb.onMode("idle");
    }
    this.busy = false;
    this.flush();
  }

  private flush() {
    if (!this.pending) return;
    const p = this.pending;
    this.pending = null;
    void this.apply(p.next, p.all);
  }

  private onMove = (ev: PointerEvent) => {
    const r = this.canvas.getBoundingClientRect();
    const x = ev.clientX - r.left,
      y = ev.clientY - r.top;
    const hit =
      this.tokens.find(
        (t) => Math.abs(t.x - x) <= this.L.tw / 2 && Math.abs(t.y - y) <= this.L.th / 2,
      ) ?? null;
    this.tokens.forEach((t) => {
      t.hover = t === hit;
    });
    if (!hit) {
      this.cb.onHover(null);
      return;
    }
    this.cb.onHover({
      claim: hit.c,
      now: hit.route ?? route(hit.c, this.threshold),
      x: hit.x,
      y: hit.y,
      width: this.L.W,
      height: this.L.H,
    });
  };
  private onLeave = () => {
    this.tokens.forEach((t) => {
      t.hover = false;
    });
    this.cb.onHover(null);
  };

  private loop = (now: number) => {
    if (this.destroyed) return;
    if (this.visible || this.busy) this.draw(now);
    this.raf = requestAnimationFrame(this.loop);
  };

  private rr(x: number, y: number, w: number, h: number, r: number) {
    const c = this.ctx;
    c.beginPath();
    c.moveTo(x + r, y);
    c.arcTo(x + w, y, x + w, y + h, r);
    c.arcTo(x + w, y + h, x, y + h, r);
    c.arcTo(x, y + h, x, y, r);
    c.arcTo(x, y, x + w, y, r);
    c.closePath();
  }

  private draw(now: number) {
    const { ctx, L, tokens } = this;
    const { W, H, dpr } = L;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);

    ctx.strokeStyle = C.grid;
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let x = 0.5; x < W; x += 32) {
      ctx.moveTo(x, 0);
      ctx.lineTo(x, H);
    }
    for (let y = 0.5; y < H; y += 32) {
      ctx.moveTo(0, y);
      ctx.lineTo(W, y);
    }
    ctx.stroke();

    const mono = `500 ${L.narrow ? 9 : 10}px "JetBrains Mono", monospace`;
    LANES.forEach((lane) => {
      const lb = L.lanes[lane];
      const count = tokens.filter((t) => t.route === lane).length;
      ctx.fillStyle = count ? "rgba(253,252,252,0.035)" : "rgba(253,252,252,0.015)";
      ctx.fillRect(L.laneX0 - 12, lb.y0 + 6, W - L.laneX0 + 12, lb.y1 - lb.y0 - 12);
      ctx.strokeStyle = C.edge;
      ctx.beginPath();
      ctx.moveTo(L.laneX0 - 12, lb.y0 + 6.5);
      ctx.lineTo(W, lb.y0 + 6.5);
      ctx.stroke();
      ctx.setLineDash([2, 4]);
      ctx.strokeStyle = C.ink150;
      ctx.beginPath();
      ctx.moveTo(L.gateX, lb.cy);
      ctx.lineTo(L.laneX0 - 12, lb.cy);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = C.lane[lane].line;
      ctx.strokeStyle = C.card;
      ctx.beginPath();
      ctx.rect(L.gateX - 4, lb.cy - 4, 8, 8);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = C.ink200;
      ctx.font = mono;
      ctx.textAlign = "left";
      ctx.fillText(LANE_RULE[lane], L.gateX + 9, lb.cy - 8);
    });

    ctx.strokeStyle = C.ink200;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(L.gateX + 0.5, L.lanes.routine_processing.cy);
    ctx.lineTo(L.gateX + 0.5, L.lanes.human_review.cy);
    ctx.stroke();

    ctx.fillStyle = C.ink200;
    ctx.font = mono;
    ctx.textAlign = "left";
    const first = L.intake[0]!;
    ctx.fillText("INTAKE", first.x - L.tw / 2, Math.max(14, first.y - L.th / 2 - 10));
    ctx.textAlign = "center";
    ctx.fillText(`RULES · v1.1 > ${fmtEur(this.threshold)}`, L.gateX, 14);

    tokens.forEach((t) => {
      const a = t.anim;
      if (a) {
        const p = clamp((now - a.start) / a.dur, 0, 1);
        if (p > 0) {
          const e = a.ease(p);
          t.x = bezier(a.from.x, a.c1.x, a.c2.x, a.to.x, e);
          t.y = bezier(a.from.y, a.c1.y, a.c2.y, a.to.y, e);
          if (a.trail) t.trail.push({ x: t.x, y: t.y });
        }
        if (p >= 1) {
          t.anim = null;
          a.resolve();
        }
      }
      if (t.trail.length > 22 || (!t.anim && t.trail.length)) t.trail.shift();
    });

    tokens.forEach((t) => {
      if (t.trail.length < 2) return;
      for (let k = 1; k < t.trail.length; k++) {
        const p0 = t.trail[k - 1]!,
          p1 = t.trail[k]!;
        ctx.strokeStyle = `rgba(255,77,0,${(k / t.trail.length) * 0.6})`;
        ctx.lineWidth = 1 + (k / t.trail.length) * 2;
        ctx.beginPath();
        ctx.moveTo(p0.x, p0.y);
        ctx.lineTo(p1.x, p1.y);
        ctx.stroke();
      }
    });

    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    tokens.forEach((t) => {
      const lane = t.route;
      const changed = t.c.status === "open" && !!lane && lane !== t.c.v1;
      const moving = !!t.anim;
      let dx = 0;
      if (t.shake > 0) {
        dx = Math.sin(t.shake * 40) * 4 * t.shake;
        t.shake = Math.max(0, t.shake - 0.02);
      }
      const x = t.x - L.tw / 2 + dx,
        y = t.y - L.th / 2;
      ctx.save();
      const s = t.hover ? 1.08 : 1;
      ctx.translate(t.x + dx, t.y);
      ctx.scale(s, s);
      ctx.translate(-(t.x + dx), -t.y);
      this.rr(x, y, L.tw, L.th, 3);
      if (!lane || moving) {
        ctx.fillStyle = C.card;
        ctx.fill();
        ctx.strokeStyle = moving ? C.contrast : C.ink150;
      } else {
        ctx.fillStyle = changed ? C.card : C.lane[lane].soft;
        ctx.fill();
        ctx.strokeStyle = changed ? C.contrast : C.lane[lane].line;
      }
      ctx.lineWidth = changed || moving ? 1.5 : 1;
      if (t.c.status === "closed") ctx.setLineDash([3, 2]);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = changed ? C.contrast : lane && !moving ? C.lane[lane].text : C.ink;
      ctx.font = `500 ${L.narrow ? 9 : 10.5}px "JetBrains Mono", monospace`;
      ctx.fillText(t.c.id, t.x + dx, t.y + 0.5);
      ctx.restore();

      if (t.flash > 0) {
        const r = (1 - t.flash) * 26;
        ctx.strokeStyle = changed
          ? `rgba(255,77,0,${t.flash})`
          : `rgba(253,252,252,${t.flash * 0.35})`;
        ctx.lineWidth = 1;
        this.rr(x - r / 2, y - r / 2, L.tw + r, L.th + r, 4);
        ctx.stroke();
        t.flash = Math.max(0, t.flash - 0.03);
      }
    });
    ctx.textBaseline = "alphabetic";
  }
}
