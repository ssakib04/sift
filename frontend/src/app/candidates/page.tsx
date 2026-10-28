"use client";

import Link from "next/link";
import { FormEvent, Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { CandidateCompare } from "@/components/candidate-compare";
import { AppShell } from "@/components/ui/app-shell";
import { buttonClass } from "@/components/ui/button";
import { fieldClass } from "@/components/ui/field";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import {
  ApprovalBatch,
  CandidateGroup,
  CandidateRecord,
  ComparisonRow,
  FinalRanking,
  InterviewHistoryItem,
  JobComparison,
  apiBase,
  apiRequest,
  recruiterToken,
} from "@/lib/api";

type DeskView = "people" | "standing" | "compare" | "final";

function points(value: number | null): string {
  return value === null ? "—" : value.toFixed(1);
}

function when(value: string | null): string {
  if (!value) {
    return "Not ended";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Not ended";
  }
  return date.toLocaleString();
}

function statusLabel(value: string): string {
  if (value === "ended") {
    return "Ended";
  }
  if (value === "started") {
    return "In progress";
  }
  if (value === "invited") {
    return "Invited";
  }
  return value.replaceAll("_", " ");
}

function deskView(value: string | null): DeskView {
  if (value === "standing") {
    return "standing";
  }
  if (value === "compare") {
    return "compare";
  }
  if (value === "final") {
    return "final";
  }
  return "people";
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) {
    return "?";
  }
  if (parts.length === 1) {
    return parts[0].slice(0, 2).toUpperCase();
  }
  return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
}

function byRank(left: CandidateRecord, right: CandidateRecord): number {
  const leftRank = left.rank ?? 10_000;
  const rightRank = right.rank ?? 10_000;
  if (leftRank !== rightRank) {
    return leftRank - rightRank;
  }
  return left.full_name.localeCompare(right.full_name);
}

function CandidatesPageContent() {
  const search = useSearchParams();
  const requestedJobId = search.get("job");
  const view = deskView(search.get("view"));
  const [groups, setGroups] = useState<CandidateGroup[]>([]);
  const [comparisons, setComparisons] = useState<JobComparison[]>([]);
  const [history, setHistory] = useState<InterviewHistoryItem[]>([]);
  const [message, setMessage] = useState("");

  useEffect(() => {
    apiRequest<CandidateGroup[]>("/api/v1/candidates")
      .then(setGroups)
      .catch((error: unknown) => {
        setMessage(error instanceof Error ? error.message : "Could not load candidates.");
      });
    apiRequest<JobComparison[]>("/api/v1/assessments")
      .then(setComparisons)
      .catch((error: unknown) => {
        setMessage(error instanceof Error ? error.message : "Could not load assessments.");
      });
    apiRequest<InterviewHistoryItem[]>("/api/v1/interview-history")
      .then(setHistory)
      .catch((error: unknown) => {
        setMessage(error instanceof Error ? error.message : "Could not load interviews.");
      });
  }, []);

  const opened = groups.find((group) => group.job_id === requestedJobId) ?? null;
  const comparison = opened ? comparisons.find((item) => item.job_id === opened.job_id) : undefined;
  const interviews = opened ? history.filter((item) => item.job_title === opened.job_title) : history;

  useEffect(() => {
    if (requestedJobId && groups.length > 0 && !opened) {
      setMessage("That role has no applicants yet.");
    }
  }, [requestedJobId, groups.length, opened]);

  return (
    <AppShell>
      <div className="mx-auto grid max-w-6xl gap-8 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <div className="space-y-8">
          {opened ? (
            <RoleDesk group={opened} comparison={comparison} view={view} />
          ) : (
            <RoleIndex groups={groups} message={message} />
          )}
        </div>
        <InterviewRail items={interviews} scoped={opened !== null} />
      </div>
    </AppShell>
  );
}

function RoleIndex({ groups, message }: { groups: CandidateGroup[]; message: string }) {
  return (
    <div id="candidates" className="space-y-6">
      <PageHeader
        eyebrow="Candidates"
        title="Roles"
        lede="Open a role to see its people, standing, or the final ranking of those who finished."
      />
      {message ? <p className="text-sm text-mist">{message}</p> : null}
      {groups.length === 0 && !message ? <p className="text-sm text-mist">No candidates yet.</p> : null}
      <ul className="grid gap-3 sm:grid-cols-2">
        {groups.map((group) => {
          const people = [...group.candidates].sort(byRank);
          const lead = people.find((person) => person.rank !== null) ?? people[0];
          return (
            <li key={group.job_id}>
              <Panel>
                <Link href={`/candidates?job=${group.job_id}&view=people`} className="block p-5 hover:bg-ivory/[0.03]">
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-mist">
                    {people.length} {people.length === 1 ? "applicant" : "applicants"}
                  </p>
                  <h2 className="mt-2 font-display text-3xl font-medium tracking-[-0.03em] text-ivory">{group.job_title}</h2>
                  <p className="mt-3 text-sm text-mist">
                    {lead?.rank ? `#${lead.rank} ${lead.full_name || "Unnamed"}` : "No ranking yet"}
                  </p>
                </Link>
              </Panel>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function RoleDesk({
  group,
  comparison,
  view,
}: {
  group: CandidateGroup;
  comparison: JobComparison | undefined;
  view: DeskView;
}) {
  const people = [...group.candidates].sort(byRank);
  return (
    <div id={view} className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-3">
          <Link href="/candidates" className="text-xs font-semibold uppercase tracking-[0.16em] text-mist hover:text-ivory">
            All roles
          </Link>
          <h1 className="font-display text-4xl font-medium leading-none tracking-[-0.03em] text-ivory sm:text-5xl">
            {group.job_title}
          </h1>
          <p className="text-sm text-mist">
            {people.length} {people.length === 1 ? "applicant" : "applicants"}, ordered by rank.
          </p>
        </div>
        <div className="flex rounded-full border border-ivory/10 bg-[#120e10]/45 p-1" role="tablist" aria-label="Role view">
          <ViewTab jobId={group.job_id} view="people" current={view} label="Candidates" />
          <ViewTab jobId={group.job_id} view="standing" current={view} label="Standing" />
          <ViewTab jobId={group.job_id} view="compare" current={view} label="Compare" />
          <ViewTab jobId={group.job_id} view="final" current={view} label="Final ranking" />
        </div>
      </div>
      {view === "people" ? <PeopleGrid people={people} /> : null}
      {view === "standing" ? <Standing people={people} comparison={comparison} /> : null}
      {view === "compare" ? <CompareDesk jobId={group.job_id} people={people} /> : null}
      {view === "final" ? <FinalRankingDesk jobId={group.job_id} /> : null}
    </div>
  );
}

function ViewTab({
  jobId,
  view,
  current,
  label,
}: {
  jobId: string;
  view: DeskView;
  current: DeskView;
  label: string;
}) {
  const search = useSearchParams();
  const selected = view === current;
  const params = new URLSearchParams();
  params.set("job", jobId);
  params.set("view", view);
  if (view === "compare") {
    const left = search.get("left");
    const right = search.get("right");
    if (left) {
      params.set("left", left);
    }
    if (right) {
      params.set("right", right);
    }
  }
  return (
    <Link
      href={`/candidates?${params.toString()}#${view}`}
      role="tab"
      aria-selected={selected}
      className={`rounded-full px-4 py-1.5 text-sm font-semibold ${
        selected ? "bg-amber text-night" : "text-mist hover:text-ivory"
      }`}
    >
      {label}
    </Link>
  );
}

function PeopleGrid({ people }: { people: CandidateRecord[] }) {
  return (
    <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
      {people.map((person) => {
        const name = person.full_name || "Unnamed";
        return (
          <li key={person.id}>
            <Panel>
              <Link href={`/candidates/${person.id}`} className="block p-3 hover:bg-ivory/[0.03]">
                <Portrait person={person} />
                <p className="mt-3 text-center text-sm font-medium text-ivory">{name}</p>
              </Link>
            </Panel>
          </li>
        );
      })}
    </ul>
  );
}

function Portrait({ person }: { person: CandidateRecord }) {
  const [src, setSrc] = useState("");

  useEffect(() => {
    if (!person.has_photo) {
      setSrc("");
      return;
    }
    const controller = new AbortController();
    let objectUrl = "";
    fetch(`${apiBase()}/api/v1/candidates/${person.id}/photo`, {
      cache: "no-store",
      headers: { Authorization: `Bearer ${recruiterToken()}` },
      signal: controller.signal,
    })
      .then((response) => (response.ok ? response.blob() : null))
      .then((blob) => {
        if (!blob || controller.signal.aborted) {
          return;
        }
        objectUrl = URL.createObjectURL(blob);
        setSrc(objectUrl);
      })
      .catch(() => undefined);
    return () => {
      controller.abort();
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [person.has_photo, person.id]);

  const name = person.full_name || "Unnamed";
  return (
    <div className="relative aspect-square overflow-hidden rounded-[14px] bg-[linear-gradient(180deg,rgb(92_52_62/0.72),rgb(24_14_18/0.94))]">
      {src ? (
        <img src={src} alt="" className="h-full w-full object-contain" />
      ) : (
        <div className="grid h-full place-items-center">
          <span className="font-display text-4xl text-ivory/85">{initials(name)}</span>
        </div>
      )}
      {person.rank ? (
        <span className="absolute left-2 top-2 rounded-full border border-white/20 bg-[#120e10]/75 px-2 py-0.5 text-xs font-semibold text-ivory">
          #{person.rank}
        </span>
      ) : (
        <span className="absolute left-2 top-2 rounded-full border border-white/15 bg-[#120e10]/75 px-2 py-0.5 text-xs font-semibold text-mist">
          Unranked
        </span>
      )}
    </div>
  );
}

function pairFrom(left: string | null, right: string | null, people: CandidateRecord[]): string[] {
  const known = new Set(people.map((person) => person.id));
  const picked: string[] = [];
  for (const id of [left, right]) {
    if (id && known.has(id) && !picked.includes(id)) {
      picked.push(id);
    }
  }
  return picked.slice(0, 2);
}

function nextPair(current: string[], id: string): string[] {
  if (current.includes(id)) {
    return current.filter((item) => item !== id);
  }
  if (current.length >= 2) {
    return [current[1], id];
  }
  return [...current, id];
}

function CompareDesk({ jobId, people }: { jobId: string; people: CandidateRecord[] }) {
  const search = useSearchParams();
  const router = useRouter();
  const picked = pairFrom(search.get("left"), search.get("right"), people);

  function choose(id: string) {
    const next = nextPair(picked, id);
    const params = new URLSearchParams();
    params.set("job", jobId);
    params.set("view", "compare");
    if (next[0]) {
      params.set("left", next[0]);
    }
    if (next[1]) {
      params.set("right", next[1]);
    }
    router.replace(`/candidates?${params.toString()}#compare`, { scroll: false });
  }

  return (
    <div className="space-y-6">
      <p className="text-sm text-mist">
        {people.length < 2
          ? "This role needs two applicants before a comparison can be made."
          : "Choose two people. A third choice replaces the earlier one."}
      </p>
      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
        {people.map((person) => {
          const name = person.full_name || "Unnamed";
          const order = picked.indexOf(person.id);
          const selected = order >= 0;
          return (
            <li key={person.id}>
              <Panel>
                <button
                  type="button"
                  aria-pressed={selected}
                  onClick={() => choose(person.id)}
                  className="block w-full p-3 text-left hover:bg-ivory/[0.03]"
                >
                  <div className={`relative rounded-[14px] ${selected ? "ring-2 ring-amber" : ""}`}>
                    <Portrait person={person} />
                    {selected ? (
                      <span className="absolute bottom-2 right-2 grid h-7 w-7 place-items-center rounded-full bg-amber text-xs font-semibold text-night">
                        {order + 1}
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-3 text-center text-sm font-medium text-ivory">{name}</p>
                </button>
              </Panel>
            </li>
          );
        })}
      </ul>
      {picked.length === 1 ? <p className="text-sm text-ivory">Choose one more person.</p> : null}
      {picked.length === 2 ? <CandidateCompare leftId={picked[0]} rightId={picked[1]} /> : null}
    </div>
  );
}

function hasMasterScores(comparison: JobComparison | undefined): comparison is JobComparison {
  return Boolean(
    comparison?.rows.some(
      (row) =>
        row.overall_score !== null ||
        row.technical_dimension !== null ||
        row.experience_dimension !== null ||
        row.qualification_dimension !== null ||
        row.interview_qa !== null,
    ),
  );
}

function ratio(value: number | null): string {
  return value === null ? "—" : value.toFixed(2);
}

function skipReason(reason: string): string {
  if (reason === "already_mailed") {
    return "already received an approval mail";
  }
  if (reason === "missing_email") {
    return "has no email address";
  }
  if (reason === "mail_failed") {
    return "could not be mailed";
  }
  return reason;
}

function FinalRankingDesk({ jobId }: { jobId: string }) {
  const [ranking, setRanking] = useState<FinalRanking | null>(null);
  const [count, setCount] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    apiRequest<FinalRanking>(`/api/v1/jobs/${jobId}/final-ranking`)
      .then((payload) => {
        if (active) {
          setRanking(payload);
        }
      })
      .catch((error: unknown) => {
        if (active) {
          setNotice(error instanceof Error ? error.message : "Could not load the final ranking.");
        }
      });
    return () => {
      active = false;
    };
  }, [jobId]);

  async function sendApprovals(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const chosen = Number(count);
    if (!Number.isInteger(chosen) || chosen < 1) {
      setNotice("Enter how many of the top should get the approval mail.");
      return;
    }
    setBusy(true);
    setNotice("");
    try {
      const result = await apiRequest<ApprovalBatch>(`/api/v1/jobs/${jobId}/approvals`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ count: chosen }),
      });
      const sent = result.mailed.map((person) => person.full_name || "Unnamed");
      const held = result.skipped.map((person) => `${person.full_name || "Unnamed"} ${skipReason(person.reason)}`);
      const parts: string[] = [];
      if (sent.length > 0) {
        parts.push(`Approval mail sent to ${sent.join(", ")}.`);
      }
      if (held.length > 0) {
        parts.push(held.join(". ") + ".");
      }
      if (parts.length === 0) {
        parts.push("No approval mail was sent.");
      }
      setNotice(parts.join(" "));
      setRanking(await apiRequest<FinalRanking>(`/api/v1/jobs/${jobId}/final-ranking`));
    } catch (error: unknown) {
      setNotice(error instanceof Error ? error.message : "The approval mail could not be sent.");
    } finally {
      setBusy(false);
    }
  }

  const rows = ranking?.rows ?? [];
  return (
    <Panel>
      <div className="space-y-4 px-5 py-4">
        <div className="space-y-1">
          <h2 className="font-display text-2xl font-medium text-ivory">Final ranking</h2>
          <p className="text-sm text-mist">
            People who finished CV screening, the interview, and the assessment, ordered by master score. Choose how many of the top receive an approval letter.
          </p>
        </div>
        {ranking && rows.length === 0 ? (
          <p className="text-sm text-mist">Nobody has finished the full pipeline for this role yet.</p>
        ) : null}
        {rows.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="text-mist">
                <tr>
                  <th className="py-2 pr-3 font-semibold">Rank</th>
                  <th className="py-2 pr-3 font-semibold">Candidate</th>
                  <th className="py-2 pr-3 font-semibold">Overall</th>
                  <th className="py-2 pr-3 font-semibold">Suitability</th>
                  <th className="py-2 pr-3 font-semibold">CV</th>
                  <th className="py-2 pr-3 font-semibold">Interview</th>
                  <th className="py-2 pr-3 font-semibold">Quiz</th>
                  <th className="py-2 font-semibold">Approval</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.candidate_id} className="border-t border-ivory/10">
                    <td className="py-2 pr-3 text-ivory">#{row.rank}</td>
                    <td className="py-2 pr-3">
                      <Link href={`/candidates/${row.candidate_id}`} className="font-medium text-ivory hover:text-amber">
                        {row.full_name || "Unnamed"}
                      </Link>
                    </td>
                    <td className="py-2 pr-3 text-ivory">{points(row.overall_score)}</td>
                    <td className="py-2 pr-3 text-mist">{row.suitability_label || "—"}</td>
                    <td className="py-2 pr-3 text-mist">{ratio(row.cv_score)}</td>
                    <td className="py-2 pr-3 text-mist">{points(row.interview_score)}</td>
                    <td className="py-2 pr-3 text-mist">{row.quiz_score === null ? "—" : row.quiz_score}</td>
                    <td className="py-2 text-mist">{row.approval_mailed_at ? "Mailed" : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        <form onSubmit={(event) => void sendApprovals(event)} className="flex flex-wrap items-end gap-3">
          <label className="grid min-w-52 flex-1 gap-1.5 text-sm text-mist">
            How many of the top should get the approval letter?
            <input
              type="number"
              min={1}
              max={Math.max(rows.length, 1)}
              inputMode="numeric"
              value={count}
              onChange={(event) => setCount(event.target.value)}
              className={fieldClass}
              disabled={rows.length === 0}
            />
          </label>
          <button type="submit" className={buttonClass()} disabled={busy || rows.length === 0 || count.trim() === ""}>
            {busy ? "Sending…" : "Send approval letters"}
          </button>
        </form>
        {notice ? <p className="text-sm text-ivory">{notice}</p> : null}
      </div>
    </Panel>
  );
}

function Standing({ people, comparison }: { people: CandidateRecord[]; comparison: JobComparison | undefined }) {
  const rankOf = new Map(people.map((person) => [person.id, person.rank]));
  const rows = comparison
    ? [...comparison.rows].sort((left, right) => compareStanding(left, right, rankOf))
    : [];
  if (!hasMasterScores(comparison)) {
    return (
      <Panel>
        <div className="px-5 py-4">
          <p className="mb-3 text-sm text-mist">Ordered by rank. These CV scores set that order until a master assessment is scored.</p>
          <table className="w-full text-left text-sm">
            <thead className="text-mist">
              <tr>
                <th className="py-2 pr-3 font-semibold">Rank</th>
                <th className="py-2 pr-3 font-semibold">Candidate</th>
                <th className="py-2 pr-3 font-semibold">CV</th>
                <th className="py-2 font-semibold">Quiz</th>
              </tr>
            </thead>
            <tbody>
              {people.map((person) => (
                <tr key={person.id} className="border-t border-ivory/10">
                  <td className="py-2 pr-3 text-ivory">{person.rank ? `#${person.rank}` : "—"}</td>
                  <td className="py-2 pr-3">
                    <Link href={`/candidates/${person.id}`} className="font-medium text-ivory hover:text-amber">
                      {person.full_name || "Unnamed"}
                    </Link>
                  </td>
                  <td className="py-2 pr-3 text-ivory">{ratio(person.aggregate_score)}</td>
                  <td className="py-2 text-mist">{person.mcq_score === null ? "—" : person.mcq_score}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    );
  }
  return (
    <Panel>
      <div className="overflow-x-auto px-4 py-3">
        <p className="mb-3 text-sm text-mist">
          Master score · CV {(comparison.cv_weight * 100).toFixed(1)}% · Interview{" "}
          {(comparison.interview_weight * 100).toFixed(1)}%
        </p>
        <table className="w-full min-w-[760px] text-left text-sm">
          <thead className="text-mist">
            <tr>
              <th className="py-2 pr-3 font-semibold">Rank</th>
              <th className="py-2 pr-3 font-semibold">Candidate</th>
              <th className="py-2 pr-3 font-semibold">Overall</th>
              <th className="py-2 pr-3 font-semibold">Suitability</th>
              <th className="py-2 pr-3 font-semibold">Technical</th>
              <th className="py-2 pr-3 font-semibold">Experience</th>
              <th className="py-2 pr-3 font-semibold">Qualification</th>
              <th className="py-2 pr-3 font-semibold">Interview Q&A</th>
              <th className="py-2 font-semibold">Key gap</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.candidate_id} className="border-t border-ivory/10">
                <td className="py-2 pr-3 text-ivory">{rankOf.get(row.candidate_id) ? `#${rankOf.get(row.candidate_id)}` : "—"}</td>
                <td className="py-2 pr-3">
                  <Link href={`/candidates/${row.candidate_id}`} className="font-medium text-ivory hover:text-amber">
                    {row.full_name || "Unnamed"}
                  </Link>
                </td>
                <td className="py-2 pr-3 text-ivory">{points(row.overall_score)}</td>
                <td className="py-2 pr-3 text-ivory">{row.suitability_label || "—"}</td>
                <td className="py-2 pr-3 text-mist">{points(row.technical_dimension)}</td>
                <td className="py-2 pr-3 text-mist">{points(row.experience_dimension)}</td>
                <td className="py-2 pr-3 text-mist">{points(row.qualification_dimension)}</td>
                <td className="py-2 pr-3 text-mist">{points(row.interview_qa)}</td>
                <td className="max-w-xs py-2 text-mist">{row.key_gap}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

function compareStanding(left: ComparisonRow, right: ComparisonRow, rankOf: Map<string, number | null>): number {
  const leftRank = rankOf.get(left.candidate_id) ?? 10_000;
  const rightRank = rankOf.get(right.candidate_id) ?? 10_000;
  if (leftRank !== rightRank) {
    return leftRank - rightRank;
  }
  return (right.overall_score ?? -1) - (left.overall_score ?? -1);
}

function InterviewRail({ items, scoped }: { items: InterviewHistoryItem[]; scoped: boolean }) {
  return (
    <aside className="space-y-3 lg:sticky lg:top-20 lg:mt-10 lg:self-start">
      <h2 className="font-display text-2xl font-medium text-ivory">{scoped ? "This role" : "Interviews"}</h2>
      {items.length === 0 ? <p className="text-sm text-mist">{scoped ? "No interviews for this role." : "No interviews yet."}</p> : null}
      <ul className="space-y-2">
        {items.map((item) => (
          <li key={item.session_id}>
            <Panel>
              <div className="space-y-1 px-4 py-3">
                <Link href={`/candidates/${item.candidate_id}`} className="font-medium text-ivory hover:text-amber">
                  {item.full_name}
                </Link>
                {scoped ? null : <p className="text-sm text-mist">{item.job_title}</p>}
                <p className="text-sm text-mist">
                  {item.conductor} · {statusLabel(item.status)}
                  {item.interview_score !== null ? ` · Interview ${item.interview_score.toFixed(1)}` : ""}
                </p>
                <p className="text-sm text-mist">{when(item.ended_at)}</p>
              </div>
            </Panel>
          </li>
        ))}
      </ul>
    </aside>
  );
}

export default function CandidatesPage() {
  return (
    <Suspense fallback={<AppShell><p className="text-sm text-mist">Opening candidates…</p></AppShell>}>
      <CandidatesPageContent />
    </Suspense>
  );
}
