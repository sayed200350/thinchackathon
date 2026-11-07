import { createFileRoute } from "@tanstack/react-router";

import { LandingReplay } from "@/components/landing-replay/landing-replay";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Policy Replay" },
      {
        name: "description",
        content:
          "When the policy changes: which open motor claims need a second look, and why. Replay policy v1 against v2.",
      },
      { property: "og:title", content: "Policy Replay" },
      {
        property: "og:description",
        content:
          "When the policy changes: which open motor claims need a second look, and why. Replay policy v1 against v2.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: LandingReplay,
});
