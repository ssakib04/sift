import type { CandidateGroup, CandidateRecord, JobRecord, JobVersion } from "@/lib/api";

import type { PillTone } from "@/components/ui/status-pill";

export type DeskRole = {
  id: string;
  title: string;
  versionLabel: string;
  versionNumber: number;
  checks: number;
  applicants: number;
  posted: boolean;
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

export type DeskInterview = {
  id: string;
  name: string;
  role: string;
  when: string;
  href: string;
};

export type DeskSnapshot = {
  source: "live";
  featured: DeskRole | null;
  roles: DeskRole[];
  review: DeskCandidate[];
  interviews: DeskInterview[];
  counts: {
    activeJobs: number;
    applicants: number;
    interviews: number;
    review: number;
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

function toRole(job: JobRecord, applicants: number): DeskRole | null {
  const version = latestVersion(job);
  if (!version) {
    return null;
  }
  const posted = version.posting_status === "live";
  const meta = [`Version ${version.version_number}`, `${version.queries.length} checks`, `${applicants} applicants`];
  if (version.posting_status && version.posting_status !== "live") {
    meta.push(postingLabel(version.posting_status));
  }
  return {
    id: job.id,
    title: job.title,
    versionLabel: `Version ${version.version_number}`,
    versionNumber: version.version_number,
    checks: version.queries.length,
    applicants,
    posted,
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

function toInterview(candidate: CandidateRecord): DeskInterview | null {
  const when = candidate.scheduled_label?.trim() ?? "";
  if (!when) {
    return null;
  }
  return {
    id: candidate.id,
    name: candidate.full_name || "Unnamed",
    role: candidate.job_title || "Unassigned role",
    when,
    href: `/candidates/${candidate.id}`,
  };
}

export const emptySnapshot: DeskSnapshot = {
  source: "live",
  featured: null,
  roles: [],
  review: [],
  interviews: [],
  counts: { activeJobs: 0, applicants: 0, interviews: 0, review: 0 },
};

export function snapshotFromApi(jobs: JobRecord[], groups: CandidateGroup[]): DeskSnapshot {
  const candidates = groups.flatMap((group) => group.candidates);
  if (jobs.length === 0 && candidates.length === 0) {
    return emptySnapshot;
  }
  const applicantsFor = new Map<string, number>();
  for (const candidate of candidates) {
    if (!candidate.job_id) {
      continue;
    }
    applicantsFor.set(candidate.job_id, (applicantsFor.get(candidate.job_id) ?? 0) + 1);
  }
  const roles = jobs
    .map((job) => toRole(job, applicantsFor.get(job.id) ?? 0))
    .filter((role): role is DeskRole => role !== null);
  const featured = roles.find((role) => role.status === "locked") ?? roles[0] ?? null;
  const review = candidates
    .filter(needsReview)
    .sort((left, right) => (right.aggregate_score ?? -1) - (left.aggregate_score ?? -1))
    .slice(0, 5)
    .map(toCandidate);
  const interviews = candidates.map(toInterview).filter((item): item is DeskInterview => item !== null).slice(0, 4);
  return {
    source: "live",
    featured,
    roles,
    review,
    interviews,
    counts: {
      activeJobs: roles.filter((role) => role.status === "locked").length,
      applicants: candidates.length,
      interviews: candidates.filter((candidate) => (candidate.scheduled_label ?? "").trim().length > 0).length,
      review: candidates.filter(needsReview).length,
    },
  };
}
