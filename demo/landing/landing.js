/* Policy Replay landing — replay stage, threshold what-if, second-look cards, impact. */
(() => {
  "use strict";

  const CLAIMS = window.POLICY_REPLAY_CLAIMS || [];
  const V1_THRESHOLD = 1500;
  const AXIS_MAX = 2500;
  const REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const FINE_POINTER = window.matchMedia("(hover: hover) and (pointer: fine)").matches;

  const LANES = ["routine_processing", "request_information", "human_review"];
  const LANE_LABEL = {
    routine_processing: "Routine",
    request_information: "Request info",
    human_review: "Human review",
  };
  const LANE_RULE = { routine_processing: "v1.3", request_information: "v1.2", human_review: "v1.1" };
  const C = {
    wool: "#fdfcfc", wool200: "#f7f6f6", wool400: "#e7e4e4", wool500: "#e2dddd",
    ink: "#121212", ink150: "#bebaba", ink200: "#9a9797", ink300: "#686565", contrast: "#ff4d00",
    lane: {
      routine_processing: { soft: "#dbf9e7", line: "#83e6af", text: "#2f7a52" },
      request_information: { soft: "#f9efdd", line: "#f3c182", text: "#9a5a12" },
      human_review: { soft: "#cbe1f0", line: "#82b8da", text: "#2c5a7a" },
    },
  };

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const fmtEur = (n) => "€" + Math.round(n).toLocaleString("en-US");
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const easeInOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
  const easeOut = (t) => 1 - Math.pow(1 - t, 4);
  const sleep = (ms) => new Promise((r) => setTimeout(r, REDUCED ? 0 : ms));

  /* ---------- Decision model (mirrors build_data.py) ---------- */
  // Route for an open claim under a what-if v1.1 quote threshold.
  function routeOpen(c, threshold) {
    if (c.base === "human_review") return "human_review";
    if (c.quote !== null && c.quote > threshold) return "human_review";
    if (c.quote === null) return "request_information";
    return c.base;
  }
  const route = (c, t) => (c.status === "closed" ? c.v1 : routeOpen(c, t));
  const flips = (c, t) => c.status === "open" && routeOpen(c, t) !== c.v1;
  const sealedHit = (c, t) => c.status === "closed" && routeOpen(c, t) !== c.v1;

  function why(c, t) {
    const next = routeOpen(c, t);
    if (c.status === "closed") {
      return `Closed claim. Under this rule it would move to <b>${LANE_LABEL[next]}</b>, but it keeps its v1 decision.`;
    }
    if (next === "human_review" && c.base !== "human_review") {
      return `The <b>${fmtEur(c.quote)}</b> quote now exceeds the <b>${fmtEur(t)}</b> threshold.`;
    }
    if (c.v1 === "human_review" && next !== "human_review") {
      return `The <b>${fmtEur(c.quote)}</b> quote is now within the <b>${fmtEur(t)}</b> threshold and nothing else triggers review.`;
    }
    return escapeHtml(c.explanation);
  }

  const OPEN = CLAIMS.filter((c) => c.status === "open");
  const CLOSED = CLAIMS.filter((c) => c.status === "closed");

  /* ---------- Timecode (25 fps broadcast style) ---------- */
  let tcFrames = 0;
  let tcSpeed = 1;
  const tcEls = [$("#timecode"), $("#stage-tc")];
  function tcString(f) {
    f = Math.max(0, Math.floor(f));
    const ff = f % 25, s = Math.floor(f / 25) % 60, m = Math.floor(f / 1500) % 60, h = Math.floor(f / 90000);
    return [h, m, s, ff].map((v) => String(v).padStart(2, "0")).join(":");
  }

  /* ---------- Odometer ---------- */
  function odometer(el) {
    let current = "";
    return (value) => {
      const str = String(value);
      if (str === current) return;
      const rebuild = str.length !== current.length;
      if (rebuild) {
        el.innerHTML = "";
        el.classList.add("odo");
        for (const ch of str) {
          const d = document.createElement("span");
          d.className = "odo__digit";
          if (/\d/.test(ch)) {
            const strip = document.createElement("span");
            strip.className = "odo__strip";
            strip.innerHTML = "0123456789".split("").map((n) => `<span>${n}</span>`).join("");
            d.appendChild(strip);
          } else {
            d.className = "odo__static";
            d.textContent = ch;
          }
          el.appendChild(d);
        }
      }
      const digits = $$(".odo__digit, .odo__static", el);
      requestAnimationFrame(() => {
        str.split("").forEach((ch, i) => {
          const strip = digits[i] && digits[i].querySelector(".odo__strip");
          if (strip) strip.style.transform = `translateY(-${Number(ch)}em)`;
        });
      });
      el.setAttribute("aria-label", str);
      current = str;
    };
  }

  /* ---------- Replay stage (canvas) ---------- */
  const stageEl = $("#stage");
  const wrap = $("#stage-wrap");
  const canvas = $("#stage-canvas");
  const ctx = canvas.getContext("2d");
  const tip = $("#tip");
  const laneLabelsEl = $("#lane-labels");
  const modeEl = $("#stage-mode");
  const bannerEl = $("#stage-banner");
  const summaryEl = $("#stage-summary");

  const L = { W: 0, H: 0, dpr: 1, tw: 64, th: 22, gap: 6, gateX: 0, laneX0: 0, laneX1: 0, lanes: {}, intake: [], narrow: false };
  const tokens = CLAIMS.map((c, i) => ({
    c, i, x: 0, y: 0, route: null, anim: null, trail: [], flash: 0, shake: 0, hover: false,
  }));
  const laneCounters = {};
  let busy = false;
  let pendingThreshold = null;
  let threshold = V1_THRESHOLD;
  let stageVisible = false;
  let firstRunDone = false;

  LANES.forEach((lane) => {
    const el = document.createElement("div");
    el.className = "lane-label";
    el.innerHTML = `<span class="eyebrow">${LANE_RULE[lane]} · ${LANE_LABEL[lane]}</span><span class="lane-label__count"></span>`;
    laneLabelsEl.appendChild(el);
    laneCounters[lane] = { el, set: odometer(el.querySelector(".lane-label__count")) };
  });

  function layout() {
    const r = wrap.getBoundingClientRect();
    L.dpr = Math.min(window.devicePixelRatio || 1, 2);
    L.W = r.width; L.H = r.height;
    canvas.width = Math.round(L.W * L.dpr);
    canvas.height = Math.round(L.H * L.dpr);
    L.narrow = L.W < 720;
    L.tw = L.narrow ? 50 : 66;
    L.th = L.narrow ? 18 : 22;
    L.gap = L.narrow ? 5 : 6;
    const pad = L.narrow ? 12 : 22;
    const labelW = L.narrow ? 0 : 190;
    L.gateX = L.W * (L.narrow ? 0.34 : 0.36);
    L.laneX0 = L.W * (L.narrow ? 0.45 : 0.47);
    L.laneX1 = L.W - pad - labelW;

    const top = 22, bandH = (L.H - top * 2) / 3;
    LANES.forEach((lane, i) => {
      const y0 = top + bandH * i;
      L.lanes[lane] = { y0, y1: y0 + bandH, cy: y0 + bandH / 2 + (L.narrow ? 8 : 0) };
      const lbl = laneCounters[lane].el;
      if (L.narrow) {
        lbl.style.cssText = `left:${L.laneX0}px; right:auto; top:${y0 + 10}px; transform:none; text-align:left;`;
      } else {
        lbl.style.cssText = `top:${y0 + bandH / 2}px;`;
      }
    });

    // Intake grid on the left, centred vertically.
    const cols = Math.max(1, Math.ceil((CLAIMS.length * (L.th + L.gap)) / (L.H - 80)));
    const rows = Math.ceil(CLAIMS.length / cols);
    const gridH = rows * (L.th + L.gap) - L.gap;
    const y0 = (L.H - gridH) / 2 + 8;
    L.intake = CLAIMS.map((_, i) => ({
      x: pad + (i % cols) * (L.tw + L.gap) + L.tw / 2,
      y: y0 + Math.floor(i / cols) * (L.th + L.gap) + L.th / 2,
    }));
  }

  // Slot positions for every token currently in a lane, sorted by claim ID.
  function laneSlots() {
    const slots = new Map();
    const usable = L.laneX1 - L.laneX0;
    const cols = Math.max(1, Math.floor((usable + L.gap) / (L.tw + L.gap)));
    LANES.forEach((lane) => {
      const members = tokens.filter((t) => t.route === lane).sort((a, b) => a.c.id.localeCompare(b.c.id));
      const rows = Math.ceil(members.length / cols);
      const lb = L.lanes[lane];
      const gapY = Math.min(L.gap, ((lb.y1 - lb.y0 - 12) - rows * L.th) / Math.max(1, rows - 1));
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

  function animate(t, to, { via = true, dur = 1000, delay = 0, ease = easeInOut, trail = false } = {}) {
    return new Promise((resolve) => {
      const from = { x: t.x, y: t.y };
      const c1 = via ? { x: L.gateX, y: from.y } : from;
      const c2 = via ? { x: L.gateX, y: to.y } : to;
      if (REDUCED) { t.x = to.x; t.y = to.y; resolve(); return; }
      t.anim = { from, to, c1, c2, start: performance.now() + delay, dur, ease, trail, resolve };
    });
  }

  function bezier(a, b, c, d, t) {
    const u = 1 - t;
    return u * u * u * a + 3 * u * u * t * b + 3 * u * t * t * c + t * t * t * d;
  }

  function setMode(mode) {
    stageEl.classList.toggle("is-rewind", mode === "rewind");
    stageEl.classList.toggle("is-play", mode === "play");
    modeEl.textContent = mode === "rewind" ? "Rewinding" : mode === "play" ? "Replaying" : "Ready";
    bannerEl.textContent = mode === "rewind" ? "◀◀ Rewind" : `▶ Replay · v1.1 > ${fmtEur(threshold)}`;
    tcSpeed = mode === "rewind" ? -6 : mode === "play" ? 2 : 1;
  }

  function updateLaneCounts() {
    LANES.forEach((lane) => laneCounters[lane].set(tokens.filter((t) => t.route === lane).length));
  }

  async function firstRun() {
    firstRunDone = true;
    busy = true;
    tokens.forEach((t) => { t.route = null; t.x = L.intake[t.i].x; t.y = L.intake[t.i].y; });
    updateLaneCounts();
    await sleep(400);
    setMode("play");
    tokens.forEach((t) => { t.route = route(t.c, threshold); });
    const slots = laneSlots();
    const order = [...tokens].sort((a, b) => a.i - b.i);
    const runs = order.map((t, k) =>
      animate(t, slots.get(t), { dur: 1150, delay: k * 55, trail: true }).then(() => {
        t.flash = 1;
        updateLaneCounts();
      }));
    await Promise.all(runs);
    setMode("idle");
    busy = false;
    flushPending();
  }

  async function applyThreshold(next, { all = false } = {}) {
    if (busy) { pendingThreshold = { next, all }; return; }
    if (!firstRunDone) { threshold = next; return; }
    busy = true;
    threshold = next;
    const movers = tokens.filter((t) => all || (t.c.status === "open" && route(t.c, next) !== t.route));
    const sealed = tokens.filter((t) => sealedHit(t.c, next));
    sealed.forEach((t) => { t.shake = 1; });

    if (movers.length) {
      setMode("rewind");
      await Promise.all(movers.map((t, k) =>
        animate(t, L.intake[t.i], { dur: 760, delay: k * 18, ease: easeInOut, trail: true })));
      movers.forEach((t) => { t.route = null; });
      updateLaneCounts();
      await sleep(160);
      setMode("play");
      movers.forEach((t) => { t.route = route(t.c, next); });
      const slots = laneSlots();
      const stayers = tokens.filter((t) => t.route && !movers.includes(t));
      stayers.forEach((t) => animate(t, slots.get(t), { via: false, dur: 650, ease: easeOut }));
      await Promise.all(movers.map((t, k) =>
        animate(t, slots.get(t), { dur: 1150, delay: k * 70, trail: true }).then(() => {
          t.flash = 1;
          updateLaneCounts();
        })));
      setMode("idle");
    }
    busy = false;
    flushPending();
  }

  function flushPending() {
    if (!pendingThreshold) return;
    const p = pendingThreshold;
    pendingThreshold = null;
    applyThreshold(p.next, { all: p.all });
  }

  function roundRect(x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function drawScene(now) {
    const { W, H, dpr } = L;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);

    // Background measure grid.
    ctx.strokeStyle = "rgba(18,18,18,0.045)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let x = 0.5; x < W; x += 32) { ctx.moveTo(x, 0); ctx.lineTo(x, H); }
    for (let y = 0.5; y < H; y += 32) { ctx.moveTo(0, y); ctx.lineTo(W, y); }
    ctx.stroke();

    // Lane bands and guides.
    LANES.forEach((lane) => {
      const lb = L.lanes[lane];
      const count = tokens.filter((t) => t.route === lane).length;
      ctx.fillStyle = count ? "rgba(253,252,252,0.75)" : "rgba(253,252,252,0.4)";
      ctx.fillRect(L.laneX0 - 12, lb.y0 + 6, W - L.laneX0 + 12, lb.y1 - lb.y0 - 12);
      ctx.strokeStyle = C.wool500;
      ctx.beginPath();
      ctx.moveTo(L.laneX0 - 12, lb.y0 + 6.5); ctx.lineTo(W, lb.y0 + 6.5);
      ctx.stroke();
      // Gate to lane guide.
      ctx.setLineDash([2, 4]);
      ctx.strokeStyle = C.ink150;
      ctx.beginPath();
      ctx.moveTo(L.gateX, lb.cy); ctx.lineTo(L.laneX0 - 12, lb.cy);
      ctx.stroke();
      ctx.setLineDash([]);
      // Gate node.
      ctx.fillStyle = C.lane[lane].line;
      ctx.strokeStyle = C.ink;
      ctx.beginPath();
      ctx.rect(L.gateX - 4, lb.cy - 4, 8, 8);
      ctx.fill(); ctx.stroke();
      ctx.fillStyle = C.ink300;
      ctx.font = `500 ${L.narrow ? 9 : 10}px "JetBrains Mono", monospace`;
      ctx.textAlign = "left";
      ctx.fillText(LANE_RULE[lane], L.gateX + 9, lb.cy - 8);
    });

    // Gate rail.
    ctx.strokeStyle = C.ink;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(L.gateX + 0.5, L.lanes.routine_processing.cy);
    ctx.lineTo(L.gateX + 0.5, L.lanes.human_review.cy);
    ctx.stroke();

    ctx.fillStyle = C.ink300;
    ctx.font = `500 ${L.narrow ? 9 : 10}px "JetBrains Mono", monospace`;
    ctx.fillText("INTAKE", L.intake[0].x - L.tw / 2, Math.max(14, L.intake[0].y - L.th / 2 - 10));
    ctx.textAlign = "center";
    ctx.fillText(`RULES · v1.1 > ${fmtEur(threshold)}`, L.gateX, 14);

    // Advance animations and trails.
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
        if (p >= 1) { t.anim = null; a.resolve(); }
      }
      if (t.trail.length > 22 || (!t.anim && t.trail.length)) t.trail.shift();
    });

    // Trails.
    tokens.forEach((t) => {
      if (t.trail.length < 2) return;
      for (let k = 1; k < t.trail.length; k++) {
        const p0 = t.trail[k - 1], p1 = t.trail[k];
        ctx.strokeStyle = `rgba(255,77,0,${(k / t.trail.length) * 0.55})`;
        ctx.lineWidth = 1 + (k / t.trail.length) * 2;
        ctx.beginPath(); ctx.moveTo(p0.x, p0.y); ctx.lineTo(p1.x, p1.y); ctx.stroke();
      }
    });

    // Tokens.
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    tokens.forEach((t) => {
      const lane = t.route;
      const changed = t.c.status === "open" && lane && lane !== t.c.v1;
      const moving = !!t.anim;
      let dx = 0;
      if (t.shake > 0) { dx = Math.sin(t.shake * 40) * 4 * t.shake; t.shake = Math.max(0, t.shake - 0.02); }
      const x = t.x - L.tw / 2 + dx, y = t.y - L.th / 2;
      const scale = t.hover ? 1.08 : 1;
      ctx.save();
      ctx.translate(t.x + dx, t.y);
      ctx.scale(scale, scale);
      ctx.translate(-(t.x + dx), -t.y);
      roundRect(x, y, L.tw, L.th, 3);
      if (!lane || moving) {
        ctx.fillStyle = C.wool;
        ctx.fill();
        ctx.strokeStyle = moving ? C.contrast : C.ink150;
      } else {
        ctx.fillStyle = changed ? C.wool : C.lane[lane].soft;
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
        ctx.strokeStyle = changed ? `rgba(255,77,0,${t.flash})` : `rgba(18,18,18,${t.flash * 0.35})`;
        ctx.lineWidth = 1;
        roundRect(x - r / 2, y - r / 2, L.tw + r, L.th + r, 4);
        ctx.stroke();
        t.flash = Math.max(0, t.flash - 0.03);
      }
    });
    ctx.textBaseline = "alphabetic";
  }

  /* Hover tooltip */
  let hovered = null;
  canvas.addEventListener("pointermove", (ev) => {
    const r = canvas.getBoundingClientRect();
    const x = ev.clientX - r.left, y = ev.clientY - r.top;
    const hit = tokens.find((t) => Math.abs(t.x - x) <= L.tw / 2 && Math.abs(t.y - y) <= L.th / 2);
    if (hovered && hovered !== hit) hovered.hover = false;
    hovered = hit || null;
    document.getElementById("cursor").classList.toggle("is-hover", !!hit);
    if (!hit) { tip.classList.remove("is-on"); return; }
    hit.hover = true;
    const c = hit.c;
    const now = hit.route || route(c, threshold);
    const changed = c.status === "open" && now !== c.v1;
    tip.innerHTML = `
      <div class="tip__head"><span class="tip__id">${c.id}</span><span class="eyebrow">${c.quote === null ? "no quote" : fmtEur(c.quote)} · ${c.status}</span></div>
      <p class="tip__summary">${escapeHtml(c.summary)}</p>
      <div class="tip__route">${badge(c.v1)}${changed ? `<span class="arrow">→</span>${badge(now)}<span class="tag tag--changed">changed</span>` : ""}${c.status === "closed" ? '<span class="tag tag--locked">sealed</span>' : ""}</div>
      <p class="tip__why">${changed || sealedHit(c, threshold) ? why(c, threshold) : escapeHtml(c.explanation)}</p>`;
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    let left = hit.x + 18, top = hit.y - th / 2;
    if (left + tw > L.W - 8) left = hit.x - tw - 18;
    top = clamp(top, 8, L.H - th - 8);
    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;
    tip.classList.add("is-on");
  });
  canvas.addEventListener("pointerleave", () => {
    if (hovered) hovered.hover = false;
    hovered = null;
    tip.classList.remove("is-on");
    document.getElementById("cursor").classList.remove("is-hover");
  });

  function badge(r) { return `<span class="badge badge--${r}">${LANE_LABEL[r]}</span>`; }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
  }

  /* ---------- Scrubber, diff, cards, impact ---------- */
  const input = $("#threshold");
  const scrub = $("#scrub");
  const ticksEl = $("#scrub-ticks");
  const numEl = $("#threshold-num");
  const pct = (v) => (clamp(v, 0, AXIS_MAX) / AXIS_MAX) * 100;

  $("#scrub-v1").style.left = `${pct(V1_THRESHOLD)}%`;
  const tickEls = CLAIMS.filter((c) => c.quote !== null).map((c) => {
    const tick = document.createElement("i");
    tick.className = "scrub__tick" + (c.status === "closed" ? " is-closed" : "");
    tick.style.left = `${pct(c.quote)}%`;
    const label = document.createElement("span");
    label.className = "scrub__tick-label";
    label.style.left = `${pct(c.quote)}%`;
    label.textContent = c.id;
    ticksEl.append(tick, label);
    return { c, tick };
  });

  const odos = {};
  $$("[data-odo]").forEach((el) => { odos[el.dataset.odo] = odometer(el); });

  function renderControls(t) {
    numEl.textContent = fmtEur(t);
    const changed = t !== V1_THRESHOLD;
    numEl.classList.toggle("is-changed", changed);
    scrub.classList.toggle("is-changed", changed);
    $("#scrub-handle").style.left = `${pct(t)}%`;
    const fill = $("#scrub-fill");
    fill.style.left = `${pct(Math.min(t, V1_THRESHOLD))}%`;
    fill.style.width = `${Math.abs(pct(t) - pct(V1_THRESHOLD))}%`;
    tickEls.forEach(({ c, tick }) => {
      tick.classList.toggle("is-over", c.quote > t);
      tick.classList.toggle("is-changed", flips(c, t) || sealedHit(c, t));
    });
    $$(".presets .chip[data-value]").forEach((b) => b.classList.toggle("is-active", Number(b.dataset.value) === t));
  }

  function renderDiff(t) {
    const flipped = OPEN.filter((c) => flips(c, t));
    const sealedN = CLOSED.filter((c) => sealedHit(c, t)).length;
    const diff = $("#diff");
    diff.classList.toggle("is-changed", t !== V1_THRESHOLD);
    $("#diff-new").textContent = fmtEur(t);
    $("#diff-status").textContent = t === V1_THRESHOLD ? "No change from v1" : `What-if · ${fmtEur(V1_THRESHOLD)} → ${fmtEur(t)}`;
    $("#diff-flips").textContent = `${flipped.length} open claim${flipped.length === 1 ? "" : "s"} change route`;
    $("#diff-sealed").textContent = `${sealedN} closed claim${sealedN === 1 ? "" : "s"} would change but stay sealed`;
    summaryEl.textContent = t === V1_THRESHOLD ? "v1 baseline" : `${flipped.length} changed · ${sealedN} sealed`;
  }

  const cardsEl = $("#cards");
  const cardMap = new Map();
  function renderCards(t) {
    const list = OPEN.filter((c) => flips(c, t)).sort((a, b) => (a.quote ?? 0) - (b.quote ?? 0));
    const ids = new Set(list.map((c) => c.id));
    $("#sl-title").textContent = list.length
      ? `${list.length} claim${list.length === 1 ? "" : "s"} need${list.length === 1 ? "s" : ""} a second look.`
      : "Nothing to recheck.";

    for (const [id, el] of cardMap) {
      if (!ids.has(id)) {
        cardMap.delete(id);
        el.classList.add("is-leaving");
        el.style.opacity = "0";
        el.style.transform = "translateY(12px) scale(.97)";
        setTimeout(() => el.remove(), REDUCED ? 0 : 320);
      }
    }
    list.forEach((c, k) => {
      const next = routeOpen(c, t);
      const html = `
        <div class="card__head"><span class="card__id">${c.id}</span><span class="card__quote">${fmtEur(c.quote)}</span></div>
        <div class="card__route">${badge(c.v1)}<span class="arrow">→</span>${badge(next)}</div>
        <p class="card__why">${why(c, t)}</p>`;
      let el = cardMap.get(c.id);
      if (!el) {
        el = document.createElement("article");
        el.className = "card";
        el.style.animationDelay = `${k * 70}ms`;
        attachTilt(el);
        cardMap.set(c.id, el);
      }
      if (el.dataset.html !== html) { el.innerHTML = html; el.dataset.html = html; }
      // Insert in sort order without re-attaching cards that are already in place,
      // which would restart their entrance animation.
      const live = $$(".card:not(.is-leaving)", cardsEl);
      if (live[k] !== el) cardsEl.insertBefore(el, live[k] || null);
    });
    let empty = $(".empty", cardsEl);
    if (!list.length && !empty) {
      empty = document.createElement("div");
      empty.className = "empty mono";
      empty.textContent = "At the v1 threshold no open claim changes route. Drag rule v1.1 above to simulate a policy update.";
      cardsEl.appendChild(empty);
    } else if (list.length && empty) {
      empty.remove();
    }

    const hits = CLOSED.filter((c) => sealedHit(c, t));
    $("#sealed-copy").innerHTML = hits.length
      ? `<b>${CLOSED.length} closed claims are sealed.</b> ${hits.map((c) => `${c.id} (${fmtEur(c.quote)})`).join(", ")} would move to ${LANE_LABEL[routeOpen(hits[0], t)]} under this rule, but closed claims keep their v1 decision and are never flagged for recheck.`
      : `<b>${CLOSED.length} closed claims are sealed.</b> They keep their v1 decision and are never flagged for recheck.`;
  }

  function attachTilt(el) {
    if (!FINE_POINTER || REDUCED) return;
    el.addEventListener("pointermove", (ev) => {
      const r = el.getBoundingClientRect();
      const px = (ev.clientX - r.left) / r.width - 0.5;
      const py = (ev.clientY - r.top) / r.height - 0.5;
      el.style.transform = `rotateX(${(-py * 8).toFixed(2)}deg) rotateY(${(px * 10).toFixed(2)}deg) translateZ(0)`;
    });
    el.addEventListener("pointerleave", () => { el.style.transform = ""; });
  }

  // Impact numbers and the fill-in-the-blanks calculator.
  const fields = { volume: $("#in-volume"), minutes: $("#in-minutes"), rate: $("#in-rate") };
  const num = (el) => Number(String(el.value).replace(/[^\d.]/g, "")) || 0;
  const tweens = new WeakMap();
  function tweenText(el, target, fmt) {
    const from = tweens.get(el) ?? 0;
    tweens.set(el, target);
    if (REDUCED) { el.textContent = fmt(target); return; }
    const start = performance.now(), dur = 900;
    const step = (now) => {
      const p = clamp((now - start) / dur, 0, 1);
      el.textContent = fmt(from + (target - from) * easeOut(p));
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  function renderImpact(t) {
    const reviewNow = OPEN.filter((c) => routeOpen(c, t) === "human_review").length;
    const reviewV1 = OPEN.filter((c) => c.v1 === "human_review").length;
    odos.replayed && odos.replayed(CLAIMS.length);
    odos.flips && odos.flips(OPEN.filter((c) => flips(c, t)).length);
    odos.review && odos.review(reviewNow);
    odos.sealed && odos.sealed(CLOSED.length);

    const delta = Math.round(num(fields.volume) * ((reviewNow - reviewV1) / OPEN.length));
    const cost = (delta * num(fields.minutes) / 60) * num(fields.rate);
    const outReviews = $("#out-reviews"), outCost = $("#out-cost");
    outReviews.className = "result" + (delta > 0 ? " is-up" : delta < 0 ? " is-down" : "");
    outCost.className = outReviews.className;
    tweenText(outReviews, delta, (v) => {
      const n = Math.round(v);
      return n === 0 ? "no change in reviews" : `${n > 0 ? "+" : "−"}${Math.abs(n).toLocaleString("en-US")} ${n > 0 ? "more" : "fewer"} reviews`;
    });
    tweenText(outCost, cost, (v) => (Math.round(v) === 0 ? "€0" : `${v > 0 ? "+" : "−"}${fmtEur(Math.abs(v))}`));
  }

  Object.values(fields).forEach((el) => {
    const fit = () => { el.size = Math.max(2, el.value.length); };
    fit();
    el.addEventListener("input", () => { fit(); renderImpact(threshold); });
    el.addEventListener("blur", () => {
      if (el === fields.volume) el.value = num(el).toLocaleString("en-US");
      fit();
    });
  });

  function preview(t) {
    renderControls(t);
    renderDiff(t);
    renderCards(t);
    renderImpact(t);
  }

  input.addEventListener("input", () => preview(Number(input.value)));
  input.addEventListener("change", () => applyThreshold(Number(input.value)));
  $$(".presets .chip[data-value]").forEach((b) => b.addEventListener("click", () => {
    input.value = b.dataset.value;
    preview(Number(input.value));
    applyThreshold(Number(input.value));
  }));
  $("#replay-btn").addEventListener("click", () => applyThreshold(Number(input.value), { all: true }));

  /* ---------- Hero ticker ---------- */
  const tickerItems = CLAIMS.map((c) =>
    `<span class="ticker__item"><b>${c.id}</b>${c.quote === null ? "no quote" : fmtEur(c.quote)}<span>→ ${LANE_LABEL[c.v1].toLowerCase()}</span><span>${c.rule}</span></span>`).join("");
  $("#ticker").innerHTML = tickerItems + tickerItems;
  $("#hero-open").textContent = OPEN.length;

  /* ---------- Hero ring: one tick per claim, cycling through the pack ---------- */
  const ringTicks = $("#ring-ticks");
  const NS = "http://www.w3.org/2000/svg";
  // Invisible full circle so the group's bounding box is centred on the ring.
  const ringBox = document.createElementNS(NS, "circle");
  ringBox.setAttribute("r", 236); ringBox.setAttribute("fill", "none"); ringBox.setAttribute("stroke", "none");
  ringTicks.appendChild(ringBox);
  const ringLines = CLAIMS.map((c, i) => {
    const angle = (i / CLAIMS.length) * 360;
    const line = document.createElementNS(NS, "line");
    const len = c.status === "closed" ? 14 : 22;
    line.setAttribute("x1", 0); line.setAttribute("x2", 0);
    line.setAttribute("y1", -236 + 0); line.setAttribute("y2", -236 + len);
    line.setAttribute("stroke", C.lane[c.v1].line);
    line.setAttribute("transform", `rotate(${angle})`);
    if (c.status === "closed") line.setAttribute("stroke-dasharray", "3 2");
    ringTicks.appendChild(line);
    return line;
  });
  let ringIndex = 0;
  function ringStep() {
    const c = CLAIMS[ringIndex];
    ringLines.forEach((l, i) => l.classList.toggle("is-active", i === ringIndex));
    $("#ring-step").textContent = `Claim ${String(ringIndex + 1).padStart(2, "0")} / ${CLAIMS.length}`;
    $("#ring-id").textContent = c.id;
    $("#ring-quote").textContent = c.quote === null ? "no quote" : fmtEur(c.quote);
    $("#ring-route").innerHTML = badge(c.v1);
    $$(".ring__core > *").forEach((el) => {
      el.classList.remove("swap");
      void el.offsetWidth; // restart the animation
      el.classList.add("swap");
    });
    ringIndex = (ringIndex + 1) % CLAIMS.length;
  }
  ringStep();
  if (!REDUCED) setInterval(ringStep, 1800);

  /* ---------- Reveal on scroll ---------- */
  const revealObs = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (e.isIntersecting) { e.target.classList.add("is-in"); revealObs.unobserve(e.target); }
    });
  }, { threshold: 0.12 });

  const stageObs = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      stageVisible = e.isIntersecting;
      if (stageVisible && !firstRunDone) firstRun();
    });
  }, { threshold: 0.35 });

  /* ---------- Cursor, nav state, magnetic buttons ---------- */
  const cursor = $("#cursor");
  const nav = $("#nav");
  const pointer = { x: -100, y: -100, sx: -100, sy: -100 };
  if (FINE_POINTER && !REDUCED) {
    document.body.classList.add("has-cursor");
    window.addEventListener("pointermove", (ev) => {
      pointer.x = ev.clientX; pointer.y = ev.clientY;
      cursor.classList.add("is-on");
      const target = ev.target instanceof Element ? ev.target : null;
      if (target && target !== canvas) cursor.classList.toggle("is-hover", !!target.closest("a, button, input"));
      cursor.classList.toggle("on-dark", !!(target && target.closest("[data-dark], .intro")));
    });
    document.addEventListener("pointerleave", () => cursor.classList.remove("is-on"));
  }
  const cx = $(".cursor__x"), cy = $(".cursor__y"), cdot = $(".cursor__dot"), cread = $(".cursor__read");

  $$("[data-magnetic]").forEach((el) => {
    if (!FINE_POINTER || REDUCED) return;
    el.addEventListener("pointermove", (ev) => {
      const r = el.getBoundingClientRect();
      const dx = ev.clientX - (r.left + r.width / 2), dy = ev.clientY - (r.top + r.height / 2);
      el.style.transform = `translate(${dx * 0.18}px, ${dy * 0.3}px)`;
    });
    el.addEventListener("pointerleave", () => { el.style.transform = ""; });
  });

  const darkSections = $$("[data-dark]");
  function updateNav() {
    const mid = nav.offsetHeight / 2;
    nav.classList.toggle("on-dark", darkSections.some((s) => {
      const r = s.getBoundingClientRect();
      return r.top <= mid && r.bottom >= mid;
    }));
  }
  window.addEventListener("scroll", updateNav, { passive: true });

  /* ---------- Main loop ---------- */
  let last = performance.now(), tcAcc = 0;
  function loop(now) {
    const dt = now - last; last = now;
    tcAcc += dt;
    while (tcAcc >= 40) { tcFrames = Math.max(0, tcFrames + tcSpeed); tcAcc -= 40; }
    const tc = tcString(tcFrames);
    tcEls[0].textContent = tc;
    tcEls[1].textContent = "TC " + tc;

    if (stageVisible || busy) drawScene(now);

    if (cursor.classList.contains("is-on")) {
      pointer.sx += (pointer.x - pointer.sx) * 0.35;
      pointer.sy += (pointer.y - pointer.sy) * 0.35;
      cx.style.transform = `translateY(${pointer.y}px)`;
      cy.style.transform = `translateX(${pointer.x}px)`;
      cdot.style.transform = `translate(${pointer.sx}px, ${pointer.sy}px)`;
      cread.style.transform = `translate(${pointer.x + 12}px, ${pointer.y + 10}px)`;
      cread.textContent = `x ${String(Math.round(pointer.x)).padStart(4, "0")} · y ${String(Math.round(pointer.y + window.scrollY)).padStart(4, "0")}`;
    }
    requestAnimationFrame(loop);
  }

  /* ---------- Intro ---------- */
  async function intro() {
    const el = $("#intro");
    const countEl = $("#intro-count");
    const finish = () => {
      el.classList.add("is-open");
      document.body.classList.remove("is-locked");
      setTimeout(() => {
        el.classList.add("is-done");
        $(".hero").classList.add("is-in");
      }, REDUCED ? 0 : 450);
    };
    if (REDUCED) { finish(); return; }
    let skipped = false;
    el.addEventListener("click", () => { skipped = true; }, { once: true });
    const total = CLAIMS.length, start = performance.now(), dur = 1100;
    await new Promise((resolve) => {
      const step = (now) => {
        const p = skipped ? 1 : clamp((now - start) / dur, 0, 1);
        countEl.textContent = String(Math.round(easeOut(p) * total)).padStart(2, "0");
        if (p < 1) requestAnimationFrame(step); else resolve();
      };
      requestAnimationFrame(step);
    });
    await sleep(skipped ? 0 : 250);
    finish();
  }

  /* ---------- Boot ---------- */
  layout();
  tokens.forEach((t) => { t.x = L.intake[t.i].x; t.y = L.intake[t.i].y; });
  updateLaneCounts();
  preview(threshold);
  $$("[data-reveal]").forEach((el) => { if (!el.classList.contains("hero")) revealObs.observe(el); });
  stageObs.observe(stageEl);

  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      layout();
      const slots = laneSlots();
      tokens.forEach((t) => {
        if (t.anim) return;
        const p = t.route ? slots.get(t) : L.intake[t.i];
        t.x = p.x; t.y = p.y;
      });
    }, 120);
  });

  (document.fonts ? document.fonts.ready : Promise.resolve()).then(() => {
    requestAnimationFrame(loop);
    intro();
    updateNav();
  });
})();
