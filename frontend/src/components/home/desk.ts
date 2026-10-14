import type { CandidateGroup, CandidateRecord, JobRecord, JobVersion } from "@/lib/api";

import type { PillTone } from "@/components/ui/status-pill";

export type DeskRole = {
  id: string;
  title: string;
  versionLabel: string;
  status: string;
  tone: PillTone;
  summary: string;
  meta: string;
  href: string;
};

export type DeskCandidate = {
  id: string;
  name: string;
  role: string;
  detail: string;
  label: string;
  href: string;
  tone: PillTone;
};

export type DeskSnapshot = {
  source: "live" | "sample";
  featured: DeskRole | null;
  roles: DeskRole[];
  review: DeskCandidate[];
  counts: {
    roles: number;
    locked: number;
    waiting: number;
  };
};

function latestVersion(job: JobRecord): JobVersion | undefined {
  return job.versions[job.versions.length - 1];
}

function postingLabel(status: string): string {
  if (status === "live") {
    return "Posted";
  }
  if (status === "not_configured") {
    return "Not posted";
  }
  if (status === "failed") {
    return "Posting failed";
  }
  return status.replaceAll("_", " ");
}

function toneFor(status: string): PillTone {
  if (status === "locked" || status === "parsed") {
    return "locked";
  }
  if (status === "draft" || status === "pending") {
    return "draft";
  }
  if (status === "failed") {
    return "attention";
  }
  return "neutral";
}

function summarize(description: string): string {
  const clean = description.replace(/\s+/g, " ").trim();
  if (!clean) {
    return "The draft is open. Review the description and checklist before it is locked.";
  }
  if (clean.length <= 180) {
    return clean;
  }
  return `${clean.slice(0, 177).trimEnd()}…`;
}

function toRole(job: JobRecord): DeskRole | null {
  const version = latestVersion(job);
  if (!version) {
    return null;
  }
  const meta = [`v${version.version_number}`, `${version.queries.length} checks`];
  if (version.posting_status) {
    meta.push(postingLabel(version.posting_status));
  }
  return {
    id: job.id,
    title: job.title,
    versionLabel: `Version ${version.version_number}`,
    status: version.status,
    tone: toneFor(version.status),
    summary: summarize(version.description),
    meta: meta.join(" · "),
    href: `/jobs?job=${job.id}`,
  };
}

function needsReview(candidate: CandidateRecord): boolean {
  return !candidate.invited || candidate.parse_status !== "parsed";
}

function toCandidate(candidate: CandidateRecord): DeskCandidate {
  const score = candidate.aggregate_score !== null ? `Score ${candidate.aggregate_score.toFixed(2)}` : "No score";
  const invited = candidate.invited ? "Invited" : "Not invited";
  return {
    id: candidate.id,
    name: candidate.full_name || "Unnamed",
    role: candidate.job_title || "Unassigned role",
    detail: `${score} · ${invited} · ${candidate.parse_status}`,
    label: candidate.invited ? candidate.parse_status : "not invited",
    href: `/candidates/${candidate.id}`,
    tone: candidate.invited ? toneFor(candidate.parse_status) : "attention",
  };
}

export function snapshotFromApi(jobs: JobRecord[], groups: CandidateGroup[]): DeskSnapshot | null {
  const candidates = groups.flatMap((group) => group.candidates);
  if (jobs.length === 0 && candidates.length === 0) {
    return null;
  }
  const roles = jobs.map(toRole).filter((role): role is DeskRole => role !== null);
  const featured = roles.find((role) => role.status === "locked") ?? roles[0] ?? null;
  const review = candidates
    .filter(needsReview)
    .sort((left, right) => (right.aggregate_score ?? -1) - (left.aggregate_score ?? -1))
    .slice(0, 5)
    .map(toCandidate);
  return {
    source: "live",
    featured,
    roles: roles.filter((role) => role.id !== featured?.id),
    review,
    counts: {
      roles: jobs.length,
      locked: roles.filter((role) => role.status === "locked").length,
      waiting: candidates.filter((candidate) => !candidate.invited).length,
    },
  };
}
