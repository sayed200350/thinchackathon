import type { LandingClaim, LandingRoute } from "./landing-data";

export const V1_THRESHOLD = 1500;
export const AXIS_MAX = 2500;

export const LANES: LandingRoute[] = ["routine_processing", "request_information", "human_review"];
export const LANE_LABEL: Record<LandingRoute, string> = {
  routine_processing: "Routine",
  request_information: "Request info",
  human_review: "Human review",
};
export const LANE_RULE: Record<LandingRoute, string> = {
  routine_processing: "v1.3",
  request_information: "v1.2",
  human_review: "v1.1",
};

export const fmtEur = (n: number) => "€" + Math.round(n).toLocaleString("en-US");
export const clamp = (v: number, a: number, b: number) => Math.min(b, Math.max(a, v));

/** Route of an open claim under a what-if quote threshold for rule v1.1. */
export function routeOpen(c: LandingClaim, threshold: number): LandingRoute {
  if (c.base === "human_review") return "human_review";
  if (c.quote !== null && c.quote > threshold) return "human_review";
  if (c.quote === null) return "request_information";
  return c.base;
}

/** Closed claims always keep their v1 decision. */
export const route = (c: LandingClaim, t: number): LandingRoute =>
  c.status === "closed" ? c.v1 : routeOpen(c, t);

/** Open claim whose route changes under the threshold. */
export const flips = (c: LandingClaim, t: number) =>
  c.status === "open" && routeOpen(c, t) !== c.v1;

/** Closed claim that would change, but stays sealed. */
export const sealedHit = (c: LandingClaim, t: number) =>
  c.status === "closed" && routeOpen(c, t) !== c.v1;

export type Segment = string | { b: string };

/** One-sentence reason as text segments; `{ b }` segments render bold. */
export function why(c: LandingClaim, t: number): Segment[] {
  const next = routeOpen(c, t);
  if (c.status === "closed") {
    return [
      "Closed claim. Under this rule it would move to ",
      { b: LANE_LABEL[next] },
      ", but it keeps its v1 decision.",
    ];
  }
  if (next === "human_review" && c.base !== "human_review") {
    return [
      "The ",
      { b: fmtEur(c.quote ?? 0) },
      " quote now exceeds the ",
      { b: fmtEur(t) },
      " threshold.",
    ];
  }
  if (c.v1 === "human_review" && next !== "human_review") {
    return [
      "The ",
      { b: fmtEur(c.quote ?? 0) },
      " quote is now within the ",
      { b: fmtEur(t) },
      " threshold and nothing else triggers review.",
    ];
  }
  return [c.explanation];
}
