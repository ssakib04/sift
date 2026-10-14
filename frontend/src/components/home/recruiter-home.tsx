"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { snapshotFromApi, type DeskCandidate, type DeskRole, type DeskSnapshot } from "@/components/home/desk";
import { sampleSnapshot } from "@/components/home/sample-desk";
import { ButtonLink } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
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

export function RecruiterHome() {
  const [phase, setPhase] = useState<Phase>("loading");
  const [snapshot, setSnapshot] = useState<DeskSnapshot | null>(null);
  const [message, setMessage] = useState("");
  const [greeting, setGreeting] = useState("Welcome back");

  useEffect(() => {
    setGreeting(greetingFor(new Date()));
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([apiRequest<JobRecord[]>("/api/v1/jobs"), apiRequest<CandidateGroup[]>("/api/v1/candidates")])
      .then(([jobs, groups]) => {
        if (cancelled) {
          return;
        }
        setSnapshot(snapshotFromApi(jobs, groups) ?? sampleSnapshot);
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
    <div className="space-y-8" aria-busy={phase === "loading"}>
      <PageHeader
        eyebrow="Recruiter desk"
        title={greeting}
        lede="Roles, applicants, and the next decision, held in one quiet place."
      />
      {phase === "loading" ? <p className="text-sm text-mist">Opening the desk…</p> : null}
      {phase === "error" ? (
        <Panel className="p-8">
          <EmptyState
            title="The desk is unavailable"
            detail={message}
            actionHref="/jobs"
            actionLabel="Open jobs"
          />
        </Panel>
      ) : null}
      {phase === "ready" && snapshot ? <Desk snapshot={snapshot} /> : null}
    </div>
  );
}

function Desk({ snapshot }: { snapshot: DeskSnapshot }) {
  return (
    <div className="space-y-6">
      {snapshot.source === "sample" ? (
        <p className="text-sm text-mist">This is a sample desk. It clears as soon as a role or candidate is on file.</p>
      ) : null}
      <div className="grid items-start gap-6 lg:grid-cols-12">
        <div className="lg:col-span-8">
          {snapshot.featured ? (
            <FeaturedRole role={snapshot.featured} />
          ) : (
            <Panel className="p-8 sm:p-10">
              <EmptyState
                title="No role is open yet"
                detail="Generate a draft, then lock the checklist when it is ready to receive applicants."
                actionHref="/jobs"
                actionLabel="Create a role"
              />
            </Panel>
          )}
        </div>
        <div className="lg:col-span-4">
          <ReviewList people={snapshot.review} />
        </div>
      </div>
      <Counts counts={snapshot.counts} />
      <RoleList roles={snapshot.roles} />
    </div>
  );
}

function FeaturedRole({ role }: { role: DeskRole }) {
  return (
    <Panel glow elevated>
      <div className="space-y-8 p-8 sm:p-10">
        <div className="space-y-4">
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-mist">Featured role</p>
          <h2 className="max-w-xl font-display text-4xl font-medium leading-[1.08] tracking-[-0.03em] text-ivory sm:text-5xl">
            {role.title}
          </h2>
          <p className="max-w-xl text-base leading-7 text-mist">{role.summary}</p>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-sm text-mist">
          <StatusPill label={role.status} tone={role.tone} />
          <span>{role.meta}</span>
        </div>
        <div className="flex flex-wrap gap-3">
          <ButtonLink href={role.href}>Open role</ButtonLink>
          <ButtonLink href="/candidates" variant="secondary">
            Review applicants
          </ButtonLink>
        </div>
      </div>
    </Panel>
  );
}

function ReviewList({ people }: { people: DeskCandidate[] }) {
  return (
    <Panel wash>
      <div className="space-y-5 p-6 sm:p-7">
        <div className="space-y-1">
          <h2 className="font-display text-2xl font-medium tracking-[-0.02em] text-ivory">Waiting on you</h2>
          <p className="text-sm leading-6 text-mist">People who are not invited yet, or whose CV is still unread.</p>
        </div>
        {people.length === 0 ? <p className="text-sm text-mist">No one is waiting.</p> : null}
        <ul className="space-y-2">
          {people.map((person) => (
            <li key={person.id}>
              <Link href={person.href} className="block rounded-control px-3 py-3 hover:bg-raised">
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
    </Panel>
  );
}

function Counts({ counts }: { counts: DeskSnapshot["counts"] }) {
  const items = [
    { label: "Roles", value: counts.roles },
    { label: "Locked profiles", value: counts.locked },
    { label: "Waiting", value: counts.waiting },
  ];
  return (
    <Panel>
      <dl className="grid sm:grid-cols-3">
        {items.map((item, index) => (
          <div key={item.label} className={`px-6 py-6 ${index > 0 ? "sm:border-l sm:border-line" : ""}`}>
            <dt className="text-xs font-semibold uppercase tracking-[0.18em] text-mist">{item.label}</dt>
            <dd className="mt-2 font-display text-4xl font-medium tracking-[-0.03em] text-ivory">{item.value}</dd>
          </div>
        ))}
      </dl>
    </Panel>
  );
}

function RoleList({ roles }: { roles: DeskRole[] }) {
  return (
    <Panel>
      <div className="space-y-4 p-6 sm:p-7">
        <h2 className="font-display text-2xl font-medium tracking-[-0.02em] text-ivory">Other roles</h2>
        {roles.length === 0 ? <p className="text-sm text-mist">The featured role is the only one on file.</p> : null}
        <ul className="divide-y divide-line">
          {roles.slice(0, 4).map((role) => (
            <li key={role.id}>
              <Link href={role.href} className="flex flex-wrap items-center justify-between gap-3 py-4 hover:text-amber">
                <span>
                  <span className="block font-semibold text-ivory">{role.title}</span>
                  <span className="mt-1 block text-sm text-mist">{role.meta}</span>
                </span>
                <StatusPill label={role.status} tone={role.tone} />
              </Link>
            </li>
          ))}
        </ul>
        {roles.length > 4 ? (
          <ButtonLink href="/jobs" variant="secondary">
            All roles
          </ButtonLink>
        ) : null}
      </div>
    </Panel>
  );
}
