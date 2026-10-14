import type { DeskSnapshot } from "@/components/home/desk";

export const sampleSnapshot: DeskSnapshot = {
  source: "sample",
  featured: {
    id: "sample-platform",
    title: "Senior Backend Engineer",
    versionLabel: "Version 3",
    status: "locked",
    tone: "locked",
    summary:
      "Own the hiring workflow from a locked job profile through CV reading and the live interview desk. Python, FastAPI, and careful evidence over guesswork.",
    meta: "v3 · 10 checks · posted",
    href: "/jobs",
  },
  roles: [
    {
      id: "sample-product",
      title: "Product Engineer",
      versionLabel: "Version 1",
      status: "draft",
      tone: "draft",
      summary: "Shape the recruiter desk: roles, review queues, and the handoff into a live interview.",
      meta: "v1 · 8 checks",
      href: "/jobs",
    },
    {
      id: "sample-ops",
      title: "Recruiting Operations",
      versionLabel: "Version 2",
      status: "locked",
      tone: "locked",
      summary: "Keep policy, inbox intake, and candidate care moving without losing the thread of a search.",
      meta: "v2 · 6 checks · posted",
      href: "/jobs",
    },
  ],
  review: [
    {
      id: "sample-nadia",
      name: "Nadia Rahman",
      role: "Senior Backend Engineer",
      detail: "Score 0.86 · Not invited · parsed",
      label: "not invited",
      href: "/candidates",
      tone: "attention",
    },
    {
      id: "sample-julian",
      name: "Julian Okonkwo",
      role: "Senior Backend Engineer",
      detail: "Score 0.74 · Not invited · parsed",
      label: "not invited",
      href: "/candidates",
      tone: "attention",
    },
    {
      id: "sample-mira",
      name: "Mira Chen",
      role: "Product Engineer",
      detail: "No score · Not invited · pending",
      label: "not invited",
      href: "/candidates",
      tone: "attention",
    },
  ],
  counts: {
    roles: 3,
    locked: 2,
    waiting: 3,
  },
};
