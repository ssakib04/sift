"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";

import { ApplicationsChart } from "@/components/home/applications-chart";
import {
  snapshotFromApi,
  type DeskCandidate,
  type DeskInterview,
  type DeskRole,
  type DeskSnapshot,
} from "@/components/home/desk";
import { ButtonLink } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { StatusPill } from "@/components/ui/status-pill";
import { ApiError, CandidateGroup, JobRecord, apiRequest } from "@/lib/api";

type Phase = "loading" | "ready" | "error";

function greetingFor(date: Date): string {
  const hour = date.getHours();
  if (hour < 12) {
    return "Good morning";
  }
  if (hour < 17) {
    return "Good afternoon";
  }
  return "Good evening";
}

function roleLabel(role: DeskRole): string {
  if (role.posted) {
    return "Posted";
  }
  if (role.status === "locked") {
    return "Locked";
  }
  if (role.status === "draft") {
    return "Draft";
  }
  return role.status.replaceAll("_", " ");
}

function nextAction(role: DeskRole): string {
  if (role.status === "draft") {
    return "Review job";
  }
  if (role.status === "locked") {
    return "View job";
  }
  return "Open role";
}

export function RecruiterHome() {
  const [phase, setPhase] = useState<Phase>("loading");
  const [snapshot, setSnapshot] = useState<DeskSnapshot | null>(null);
  const [appliedAt, setAppliedAt] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [greeting, setGreeting] = useState("Welcome back");
  const [deskDate, setDeskDate] = useState("");

  useEffect(() => {
    const now = new Date();
    setGreeting(greetingFor(now));
    setDeskDate(
      new Intl.DateTimeFormat("en-US", { weekday: "long", month: "short", day: "numeric" }).format(now),
    );
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([apiRequest<JobRecord[]>("/api/v1/jobs"), apiRequest<CandidateGroup[]>("/api/v1/candidates")])
      .then(([jobs, groups]) => {
        if (cancelled) {
          return;
        }
        setSnapshot(snapshotFromApi(jobs, groups));
        setAppliedAt(groups.flatMap((group) => group.candidates.map((candidate) => candidate.created_at)));
        setPhase("ready");
      })
      .catch((error: unknown) => {
        if (cancelled) {
          return;
        }
        setMessage(error instanceof ApiError ? error.message : "The desk could not be opened.");
        setPhase("error");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div id="home" className="relative space-y-4" aria-busy={phase === "loading"}>
      <header className="flex flex-wrap items-center justify-between gap-6 pr-16">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-mist">
            Recruiter desk{deskDate ? ` · ${deskDate}` : ""}
          </p>
          <h1 className="mt-2 font-display text-4xl font-medium leading-none tracking-[-0.03em] text-ivory sm:text-5xl">
            {greeting}
          </h1>
          <p className="mt-2 text-sm text-mist">Here is where your hiring stands today.</p>
        </div>
        {phase === "ready" && snapshot ? <DeskPulse snapshot={snapshot} /> : null}
      </header>
      {phase === "loading" ? <p className="text-sm text-mist">Opening the desk…</p> : null}
      {phase === "error" ? (
        <Glass className="p-8">
          <EmptyState title="The desk is unavailable" detail={message} actionHref="/jobs" actionLabel="Open jobs" />
        </Glass>
      ) : null}
      {phase === "ready" && snapshot ? <Desk snapshot={snapshot} appliedAt={appliedAt} /> : null}
    </div>
  );
}

function Glass({
  children,
  elevation = "primary",
  className = "",
}: {
  children: ReactNode;
  elevation?: "primary" | "secondary";
  className?: string;
}) {
  const face =
    elevation === "primary"
      ? "border-white/15 bg-[linear-gradient(180deg,rgb(48_24_32/0.34),rgb(18_10_14/0.44))] shadow-[inset_0_1px_0_rgb(255_228_220/0.4),inset_0_0_24px_rgb(212_168_180/0.08),0_18px_40px_rgb(20_10_16/0.16)]"
      : "border-white/10 bg-[linear-gradient(180deg,rgb(40_20_26/0.36),rgb(16_10_12/0.46))] shadow-[inset_0_1px_0_rgb(255_220_214/0.26),0_12px_28px_rgb(20_10_16/0.14)]";
  return (
    <section className={`relative overflow-hidden rounded-card border backdrop-blur-xl ${face} ${className}`}>
      <span aria-hidden className="pointer-events-none absolute inset-x-6 top-0 h-px bg-gradient-to-r from-transparent via-peach/70 to-transparent" />
      <div className="relative">{children}</div>
    </section>
  );
}

function Desk({ snapshot, appliedAt }: { snapshot: DeskSnapshot; appliedAt: readonly string[] }) {
  const metrics = [
    {
      label: "Active jobs",
      value: snapshot.counts.activeJobs,
      detail: "Currently open",
      href: "/jobs",
      icon: <BriefcaseIcon />,
    },
    {
      label: "Applicants",
      value: snapshot.counts.applicants,
      detail: "Across all jobs",
      href: "/candidates",
      icon: <PeopleIcon />,
    },
    {
      label: "Interviews",
      value: snapshot.counts.interviews,
      detail: "Scheduled",
      href: "/interviews",
      icon: <CalendarIcon />,
    },
    {
      label: "Need review",
      value: snapshot.counts.review,
      detail: "Pending decisions",
      href: "/candidates",
      icon: <ClockIcon />,
    },
  ];

  return (
    <div className="space-y-4">
      <Glass>
        <ApplicationsChart appliedAt={appliedAt} />
      </Glass>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {metrics.map((metric) => (
          <MetricCard key={metric.label} {...metric} />
        ))}
      </div>
      <div className="grid items-start gap-5 lg:grid-cols-12">
        <div className="lg:col-span-7">
          {snapshot.featured ? (
            <FeaturedRole role={snapshot.featured} />
          ) : (
            <Glass className="p-8 sm:p-10">
              <EmptyState
                title="No role is open yet"
                detail="Generate a draft, then lock the checklist when it is ready to receive applicants."
                actionHref="/jobs"
                actionLabel="Create a role"
              />
            </Glass>
          )}
        </div>
        <div className="space-y-4 lg:col-span-5">
          {snapshot.interviews.length > 0 ? <InterviewList interviews={snapshot.interviews} /> : null}
          <ReviewList people={snapshot.review} />
        </div>
      </div>
      <RoleList roles={snapshot.roles} />
    </div>
  );
}

function DeskPulse({ snapshot }: { snapshot: DeskSnapshot }) {
  const next = snapshot.interviews[0];
  const waiting = snapshot.counts.review;
  return (
    <Link
      href={next?.href ?? "/candidates"}
      className="max-w-xs text-right"
    >
      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-peach">{next ? "Next interview" : "Attention"}</p>
      <p className="mt-1 font-semibold text-ivory">{next ? next.name : waiting === 0 ? "No one is waiting" : `${waiting} waiting`}</p>
      <p className="text-sm text-mist">{next ? next.when : "Open the review queue"}</p>
    </Link>
  );
}

function MetricCard({
  label,
  value,
  detail,
  href,
  icon,
}: {
  label: string;
  value: number;
  detail: string;
  href: string;
  icon: ReactNode;
}) {
  return (
    <Glass elevation="secondary">
      <Link href={href} className="flex h-full min-h-[9.5rem] flex-col justify-between p-4 hover:bg-ivory/[0.03] sm:min-h-[10.75rem] sm:p-5">
        <span className="flex items-center justify-between">
          <span className="flex h-9 w-9 items-center justify-center rounded-control border border-amber/25 bg-amber/10 text-amber">
            {icon}
          </span>
          <span aria-hidden className="text-mist">
            →
          </span>
        </span>
        <span className="mt-4 block">
          <span className="block font-display text-4xl font-medium leading-none tracking-[-0.03em] text-ivory tabular-nums">{value}</span>
          <span className="mt-2 block text-xs font-semibold uppercase tracking-[0.14em] text-mist">{label}</span>
          <span className="mt-1 block text-sm text-mist">{detail}</span>
        </span>
      </Link>
    </Glass>
  );
}

function FeaturedRole({ role }: { role: DeskRole }) {
  return (
    <Glass>
      <div className="flex flex-col sm:flex-row">
        <div className="flex-1 space-y-6 p-7 sm:p-8">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs font-semibold uppercase tracking-[0.22em] text-mist">Featured role</p>
            <StatusPill label={roleLabel(role)} tone={role.tone} />
          </div>
          <div className="space-y-3">
            <h2 className="max-w-xl font-display text-4xl font-medium leading-[1.08] tracking-[-0.03em] text-ivory">
              {role.title}
            </h2>
            <p className="max-w-xl text-sm leading-6 text-mist">{role.summary}</p>
          </div>
          <p className="text-sm text-mist">{role.meta}</p>
          <div className="flex flex-wrap gap-3">
            <ButtonLink href={role.href}>Open role</ButtonLink>
            <ButtonLink href="/candidates" variant="secondary">
              Review applicants
            </ButtonLink>
          </div>
        </div>
        <div
          aria-hidden
          className="relative min-h-36 overflow-hidden sm:w-52 lg:w-60"
        >
          <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_70%_42%,rgb(212_163_148/0.92),rgb(160_96_96/0.55)_36%,rgb(48_24_28/0.94)_74%)]" />
          <div className="absolute inset-x-0 bottom-0 h-1/2 bg-gradient-to-t from-night/70 to-transparent" />
          <div className="absolute left-[18%] top-[38%] h-16 w-40 rounded-full bg-[#d4a394]/45 blur-2xl" />
        </div>
      </div>
    </Glass>
  );
}

function ReviewList({ people }: { people: DeskCandidate[] }) {
  return (
    <Glass elevation="secondary" className="h-full">
      <div className="space-y-4 p-6 sm:p-7">
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-1">
            <h2 className="font-display text-2xl font-medium tracking-[-0.02em] text-ivory">Needs your attention</h2>
            <p className="text-sm leading-6 text-mist">Not invited yet, or a CV still unread.</p>
          </div>
          <Link href="/candidates" className="shrink-0 text-sm font-semibold text-amber hover:text-peach">
            View all
          </Link>
        </div>
        {people.length === 0 ? <p className="text-sm text-mist">No one is waiting.</p> : null}
        <ul className="space-y-1">
          {people.map((person) => (
            <li key={person.id}>
              <Link href={person.href} className="block rounded-control px-3 py-3 hover:bg-ivory/[0.04]">
                <span className="flex items-start justify-between gap-3">
                  <span className="block font-semibold text-ivory">{person.name}</span>
                  <StatusPill label={person.label} tone={person.tone} />
                </span>
                <span className="mt-1 block text-sm text-mist">{person.role}</span>
                <span className="mt-1 block text-sm text-mist">{person.detail}</span>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </Glass>
  );
}

function InterviewList({ interviews }: { interviews: DeskInterview[] }) {
  return (
    <Glass elevation="secondary" className="h-full">
      <div className="space-y-4 p-6 sm:p-7">
        <div className="flex items-start justify-between gap-3">
          <h2 className="font-display text-2xl font-medium tracking-[-0.02em] text-ivory">Upcoming interviews</h2>
          <Link href="/interviews" className="shrink-0 text-sm font-semibold text-amber hover:text-peach">
            View all
          </Link>
        </div>
        <ul className="divide-y divide-ivory/10">
          {interviews.map((interview) => (
            <li key={interview.id}>
              <Link href={interview.href} className="flex items-start justify-between gap-3 py-3 hover:text-amber">
                <span>
                  <span className="block text-sm font-semibold text-peach">{interview.when}</span>
                  <span className="mt-1 block font-semibold text-ivory">{interview.name}</span>
                  <span className="mt-1 block text-sm text-mist">{interview.role}</span>
                </span>
                <span aria-hidden className="pt-1 text-mist">
                  →
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </Glass>
  );
}

function RoleList({ roles }: { roles: DeskRole[] }) {
  const visible = roles.slice(0, 6);
  return (
    <Glass elevation="secondary">
      <div className="space-y-4 p-6 sm:p-7">
        <div className="flex items-center justify-between gap-3">
          <h2 className="font-display text-2xl font-medium tracking-[-0.02em] text-ivory">Your jobs</h2>
          <Link href="/jobs" className="text-sm font-semibold text-amber hover:text-peach">
            View all jobs
          </Link>
        </div>
        {roles.length === 0 ? <p className="text-sm text-mist">No roles are on file.</p> : null}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[32rem] text-left text-sm">
            <thead>
              <tr className="text-xs font-semibold uppercase tracking-[0.16em] text-mist">
                <th className="pb-3 pr-4 font-semibold">Role</th>
                <th className="pb-3 pr-4 font-semibold">Status</th>
                <th className="pb-3 pr-4 font-semibold">Applicants</th>
                <th className="pb-3 font-semibold">Next action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ivory/10">
              {visible.map((role) => (
                <tr key={role.id}>
                  <td className="py-3 pr-4">
                    <Link href={role.href} className="font-semibold text-ivory hover:text-amber">
                      {role.title}
                    </Link>
                    <span className="mt-1 block text-mist">v{role.versionNumber}</span>
                  </td>
                  <td className="py-3 pr-4">
                    <StatusPill label={roleLabel(role)} tone={role.tone} />
                  </td>
                  <td className="py-3 pr-4 tabular-nums text-ivory">{role.applicants}</td>
                  <td className="py-3">
                    <Link href={role.href} className="font-semibold text-amber hover:text-peach">
                      {nextAction(role)}
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </Glass>
  );
}

function BriefcaseIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M8 7V6a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v1" stroke="currentColor" strokeWidth="1.6" />
      <rect x="3.5" y="7" width="17" height="13" rx="2" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  );
}

function PeopleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="9" cy="9" r="3" stroke="currentColor" strokeWidth="1.6" />
      <path d="M4 18.5c.6-2.4 2.5-3.5 5-3.5s4.4 1.1 5 3.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <circle cx="16.5" cy="9.5" r="2.2" stroke="currentColor" strokeWidth="1.6" />
      <path d="M16 15c1.8.2 3.2 1.1 3.8 3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

function CalendarIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="3.5" y="5" width="17" height="15" rx="2" stroke="currentColor" strokeWidth="1.6" />
      <path d="M8 3.5V7M16 3.5V7M3.5 10h17" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

function ClockIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="8" stroke="currentColor" strokeWidth="1.6" />
      <path d="M12 8v4.5l3 2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}
