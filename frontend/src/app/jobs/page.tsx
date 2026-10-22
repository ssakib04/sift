"use client";

import Link from "next/link";
import { FormEvent, Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { AppShell } from "@/components/ui/app-shell";
import { buttonClass } from "@/components/ui/button";
import { fieldClass, SelectField, TextField } from "@/components/ui/field";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { StatusPill } from "@/components/ui/status-pill";
import {
  ApiError,
  CandidateGroup,
  CandidateRecord,
  ChecklistQuery,
  CvUploadResult,
  JobRecord,
  apiRequest,
} from "@/lib/api";

const CATEGORIES = ["Information Technology", "Engineering", "Operations", "Human Resources", "Research", "None"];

type DraftQuery = ChecklistQuery;
type JobTab = "brief" | "people";
type IndexView = "roles" | "create";

function excerpt(text: string): string {
  const line = text.replace(/\s+/g, " ").trim();
  if (line.length <= 140) {
    return line;
  }
  return `${line.slice(0, 137).trim()}…`;
}

function jobTab(value: string | null): JobTab {
  return value === "people" ? "people" : "brief";
}

function indexView(value: string | null): IndexView {
  return value === "create" ? "create" : "roles";
}

function JobsPageContent() {
  const router = useRouter();
  const search = useSearchParams();
  const requestedJobId = search.get("job");
  const tab = jobTab(search.get("tab"));
  const view = indexView(search.get("view"));
  const [job, setJob] = useState<JobRecord | null>(null);
  const [jobs, setJobs] = useState<JobRecord[]>([]);
  const [groups, setGroups] = useState<CandidateGroup[]>([]);
  const [description, setDescription] = useState("");
  const [queries, setQueries] = useState<DraftQuery[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [candidates, setCandidates] = useState<CandidateRecord[]>([]);

  function applyJob(record: JobRecord) {
    const latest = record.versions[record.versions.length - 1];
    setJob(record);
    setDescription(latest?.description ?? "");
    setQueries(latest?.queries ?? []);
  }

  async function refreshLists() {
    const [records, people] = await Promise.all([
      apiRequest<JobRecord[]>("/api/v1/jobs"),
      apiRequest<CandidateGroup[]>("/api/v1/candidates").catch(() => [] as CandidateGroup[]),
    ]);
    setJobs(records);
    setGroups(people);
  }

  useEffect(() => {
    let cancelled = false;
    refreshLists().catch(() => {
      if (!cancelled) {
        setJobs([]);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!requestedJobId) {
      setJob(null);
      return;
    }
    let cancelled = false;
    apiRequest<JobRecord>(`/api/v1/jobs/${requestedJobId}`)
      .then((record) => {
        if (!cancelled) {
          applyJob(record);
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setMessage(error instanceof ApiError ? error.message : "Could not open that role.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [requestedJobId]);

  async function onCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload = {
      title: String(form.get("title") || ""),
      seniority: String(form.get("seniority") || "Mid-Level"),
      required_skills: String(form.get("required_skills") || "")
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
      preferred_skills: String(form.get("preferred_skills") || "")
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
      qualifications: String(form.get("qualifications") || ""),
      minimum_years: Number(form.get("minimum_years") || 0),
      technical_weight: Number(form.get("technical_weight") || 0.5),
      experience_weight: Number(form.get("experience_weight") || 0.3),
      qualification_weight: Number(form.get("qualification_weight") || 0.2),
      contract: String(form.get("contract") || "Full Time"),
      category: String(form.get("category") || "Information Technology"),
    };
    setBusy(true);
    setMessage("");
    try {
      const created = await apiRequest<JobRecord>("/api/v1/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      applyJob(created);
      await refreshLists();
      setMessage("Draft ready. Read the brief, then approve it when the checklist should freeze.");
      router.push(`/jobs?job=${created.id}&tab=brief`);
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "Job generation failed.");
    } finally {
      setBusy(false);
    }
  }

  async function saveDraft() {
    if (!job) {
      return;
    }
    const latest = job.versions[job.versions.length - 1];
    setBusy(true);
    setMessage("");
    try {
      const updated = await apiRequest<JobRecord>(`/api/v1/jobs/${job.id}/versions/${latest.version_number}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ description, queries }),
      });
      applyJob(updated);
      setMessage("Draft saved.");
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "Could not save the draft.");
    } finally {
      setBusy(false);
    }
  }

  async function approve() {
    if (!job) {
      return;
    }
    const latest = job.versions[job.versions.length - 1];
    setBusy(true);
    setMessage("");
    try {
      if (latest.status === "draft") {
        await apiRequest<JobRecord>(`/api/v1/jobs/${job.id}/versions/${latest.version_number}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ description, queries }),
        });
      }
      const locked = await apiRequest<JobRecord>(`/api/v1/jobs/${job.id}/versions/${latest.version_number}/approve`, {
        method: "POST",
      });
      applyJob(locked);
      await refreshLists();
      const posted = locked.versions[locked.versions.length - 1];
      setMessage(`Checklist locked. Posting status: ${posted.posting_status ?? "unknown"}. Applicants can email a CV.`);
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "Approval failed.");
    } finally {
      setBusy(false);
    }
  }

  async function newVersion() {
    if (!job) {
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const opened = await apiRequest<JobRecord>(`/api/v1/jobs/${job.id}/versions`, { method: "POST" });
      applyJob(opened);
      await refreshLists();
      setMessage("A new draft is open. The previous checklist stays frozen.");
      router.push(`/jobs?job=${opened.id}&tab=brief`);
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "Could not open a new version.");
    } finally {
      setBusy(false);
    }
  }

  async function loadCandidates(jobId: string) {
    const rows = await apiRequest<CandidateRecord[]>(`/api/v1/jobs/${jobId}/candidates`);
    setCandidates(rows);
  }

  async function uploadCvs(files: File[]) {
    if (!job || files.length === 0) {
      return;
    }
    if (files.length > 20) {
      setMessage("Upload at most 20 CVs at a time.");
      return;
    }
    const body = new FormData();
    for (const file of files) {
      body.append("files", file);
    }
    setBusy(true);
    setMessage("");
    try {
      const result = await apiRequest<CvUploadResult>(`/api/v1/jobs/${job.id}/cvs`, { method: "POST", body });
      await loadCandidates(job.id);
      await refreshLists();
      const parts = [`${result.scored} scored`];
      if (result.duplicate > 0) {
        parts.push(`${result.duplicate} already stored`);
      }
      if (result.parse_failed > 0) {
        parts.push(`${result.parse_failed} could not be read`);
      }
      if (result.invalid > 0) {
        parts.push(`${result.invalid} were not PDF or DOCX`);
      }
      if (result.failed > 0) {
        parts.push(`${result.failed} failed`);
      }
      setMessage(`Upload finished. ${parts.join(", ")}. Invites go to anyone who newly enters the top 3.`);
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "Could not upload those CVs.");
    } finally {
      setBusy(false);
    }
  }

  async function checkInbox() {
    setBusy(true);
    setMessage("");
    try {
      const result = await apiRequest<{ processed: number }>("/api/v1/screening/poll", { method: "POST" });
      if (job) {
        await loadCandidates(job.id);
      }
      await refreshLists();
      setMessage(`Inbox checked. ${result.processed} new CV${result.processed === 1 ? "" : "s"} scored.`);
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "Could not read the inbox.");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    const hasLockedVersion = job?.versions.some((version) => version.status === "locked") ?? false;
    if (!job || !hasLockedVersion) {
      setCandidates([]);
      return;
    }
    let cancelled = false;
    apiRequest<CandidateRecord[]>(`/api/v1/jobs/${job.id}/candidates`)
      .then((rows) => {
        if (!cancelled) {
          setCandidates(rows);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setCandidates([]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [job]);

  const counts = new Map(groups.map((group) => [group.job_id, group.candidates.length]));
  const latest = job?.versions[job.versions.length - 1];
  const locked = latest?.status === "locked";
  const opened = requestedJobId && job && job.id === requestedJobId ? job : null;

  return (
    <AppShell>
      <div className="mx-auto max-w-4xl space-y-8">
        {requestedJobId && !opened ? (
          <p className="text-sm text-mist">Opening this role…</p>
        ) : opened && latest ? (
          <RoleDesk
            job={opened}
            latestNumber={latest.version_number}
            latestStatus={latest.status}
            locked={locked}
            tab={tab}
            description={description}
            queries={queries}
            candidates={candidates}
            busy={busy}
            message={message}
            onDescription={setDescription}
            onQueries={setQueries}
            onSave={() => void saveDraft()}
            onApprove={() => void approve()}
            onNewVersion={() => void newVersion()}
            onUpload={(files) => void uploadCvs(files)}
            onInbox={() => void checkInbox()}
          />
        ) : (
          <RoleIndex
            jobs={jobs}
            counts={counts}
            view={view}
            busy={busy}
            message={message}
            onCreate={onCreate}
            onInbox={() => void checkInbox()}
          />
        )}
      </div>
    </AppShell>
  );
}

function RoleIndex({
  jobs,
  counts,
  view,
  busy,
  message,
  onCreate,
  onInbox,
}: {
  jobs: JobRecord[];
  counts: Map<string, number>;
  view: IndexView;
  busy: boolean;
  message: string;
  onCreate: (event: FormEvent<HTMLFormElement>) => void;
  onInbox: () => void;
}) {
  return (
    <div id="roles" className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageHeader
          eyebrow="Jobs"
          title="Roles"
          lede="This is where a role is drafted, locked, and filled. Applicants email a CV once the role is locked."
        />
        <button type="button" onClick={onInbox} disabled={busy} className={buttonClass("secondary")}>
          {busy ? "Checking inbox…" : "Check inbox"}
        </button>
      </div>
      <p className="max-w-xl text-sm text-mist">
        Unread CVs in the apply mailbox are matched to locked roles and scored. Open a card to read the brief or the people already in.
      </p>
      <div className="flex w-fit rounded-full border border-ivory/10 bg-[#120e10]/45 p-1" role="tablist" aria-label="Jobs">
        <DeskTab href="/jobs" selected={view === "roles"} label="Existing roles" />
        <DeskTab href="/jobs?view=create" selected={view === "create"} label="Create a role" />
      </div>
      {message ? <p className="text-sm text-mist">{message}</p> : null}
      {view === "create" ? <CreateForm busy={busy} onCreate={onCreate} /> : <RoleGrid jobs={jobs} counts={counts} />}
    </div>
  );
}

function RoleGrid({ jobs, counts }: { jobs: JobRecord[]; counts: Map<string, number> }) {
  if (jobs.length === 0) {
    return <p className="text-sm text-mist">No roles yet. Create one, then approve the brief before CVs can match it.</p>;
  }
  return (
    <ul className="grid gap-3 sm:grid-cols-2">
      {jobs.map((record) => {
        const version = record.versions[record.versions.length - 1];
        const people = counts.get(record.id) ?? 0;
        const status = version?.status ?? "unknown";
        return (
          <li key={record.id}>
            <Panel>
              <Link href={`/jobs?job=${record.id}&tab=brief`} className="block p-5 hover:bg-ivory/[0.03]">
                <span className="flex items-center justify-between gap-3">
                  <StatusPill label={status} tone={status === "locked" ? "locked" : "draft"} />
                  <span className="text-xs font-semibold uppercase tracking-[0.14em] text-mist">v{version?.version_number ?? "?"}</span>
                </span>
                <h2 className="mt-3 font-display text-3xl font-medium tracking-[-0.03em] text-ivory">{record.title}</h2>
                <p className="mt-3 line-clamp-2 text-sm text-mist">{excerpt(version?.description ?? "No description yet.")}</p>
                <p className="mt-4 text-sm text-mist">
                  {people} {people === 1 ? "applicant" : "applicants"}
                </p>
              </Link>
            </Panel>
          </li>
        );
      })}
    </ul>
  );
}

function CreateForm({ busy, onCreate }: { busy: boolean; onCreate: (event: FormEvent<HTMLFormElement>) => void }) {
  return (
    <form id="create" onSubmit={onCreate}>
      <Panel>
        <div className="grid gap-4 p-5">
          <div className="space-y-1">
            <h2 className="font-display text-2xl font-medium text-ivory">Draft a role by hand</h2>
            <p className="text-sm text-mist">
              The brief and checklist are generated from these facts and your policies. Approving locks the brief. People still apply by email.
            </p>
          </div>
          <TextField name="title" label="Title" required />
          <div className="grid gap-3 sm:grid-cols-3">
            <SelectField name="seniority" label="Seniority" defaultValue="Mid-Level">
              <option>Junior</option>
              <option>Mid-Level</option>
              <option>Senior</option>
              <option>Not specified</option>
            </SelectField>
            <SelectField name="contract" label="Contract" defaultValue="Full Time">
              <option>Full Time</option>
              <option>Part Time</option>
              <option>Freelance</option>
              <option>Internship</option>
            </SelectField>
            <SelectField name="category" label="Category" defaultValue="Information Technology">
              {CATEGORIES.map((category) => (
                <option key={category}>{category}</option>
              ))}
            </SelectField>
          </div>
          <TextField name="required_skills" label="Required skills" required placeholder="Python, FastAPI" />
          <TextField name="preferred_skills" label="Preferred skills" placeholder="LangGraph, pgvector" />
          <TextField name="qualifications" label="Qualifications" required />
          <div className="grid gap-3 sm:grid-cols-4">
            <TextField name="minimum_years" label="Minimum years" type="number" min={0} defaultValue={3} />
            <TextField name="technical_weight" label="Technical weight" type="number" step="0.01" defaultValue={0.5} />
            <TextField name="experience_weight" label="Experience weight" type="number" step="0.01" defaultValue={0.3} />
            <TextField name="qualification_weight" label="Qualification weight" type="number" step="0.01" defaultValue={0.2} />
          </div>
          <button type="submit" disabled={busy} className={`w-fit ${buttonClass()}`}>
            {busy ? "Drafting…" : "Generate draft"}
          </button>
        </div>
      </Panel>
    </form>
  );
}

function RoleDesk({
  job,
  latestNumber,
  latestStatus,
  locked,
  tab,
  description,
  queries,
  candidates,
  busy,
  message,
  onDescription,
  onQueries,
  onSave,
  onApprove,
  onNewVersion,
  onUpload,
  onInbox,
}: {
  job: JobRecord;
  latestNumber: number;
  latestStatus: string;
  locked: boolean;
  tab: JobTab;
  description: string;
  queries: DraftQuery[];
  candidates: CandidateRecord[];
  busy: boolean;
  message: string;
  onDescription: (value: string) => void;
  onQueries: (queries: DraftQuery[]) => void;
  onSave: () => void;
  onApprove: () => void;
  onNewVersion: () => void;
  onUpload: (files: File[]) => void;
  onInbox: () => void;
}) {
  const latest = job.versions[job.versions.length - 1];
  const canTakePeople = job.versions.some((version) => version.status === "locked");
  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <Link href="/jobs" className="text-xs font-semibold uppercase tracking-[0.16em] text-mist hover:text-ivory">
          All roles
        </Link>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="space-y-3">
            <h1 className="font-display text-4xl font-medium leading-none tracking-[-0.03em] text-ivory sm:text-5xl">{job.title}</h1>
            <p className="flex flex-wrap items-center gap-2 text-sm text-mist">
              <StatusPill label={latestStatus} tone={locked ? "locked" : "draft"} />
              <span>Version {latestNumber}</span>
            </p>
          </div>
          <div className="flex rounded-full border border-ivory/10 bg-[#120e10]/45 p-1" role="tablist" aria-label="Role">
            <DeskTab href={`/jobs?job=${job.id}&tab=brief`} selected={tab === "brief"} label="Brief" />
            <DeskTab href={`/jobs?job=${job.id}&tab=people`} selected={tab === "people"} label="Applicants" />
          </div>
        </div>
      </div>
      {message ? <p className="text-sm text-mist">{message}</p> : null}
      {tab === "people" ? (
        <Applicants
          job={job}
          candidates={candidates}
          ready={canTakePeople}
          busy={busy}
          onUpload={onUpload}
          onInbox={onInbox}
        />
      ) : (
        <Brief
          description={description}
          queries={queries}
          locked={locked}
          busy={busy}
          applyUrl={latest?.apply_url ?? null}
          postingDetail={latest?.posting_detail ?? null}
          externalPostingId={latest?.external_posting_id ?? null}
          onDescription={onDescription}
          onQueries={onQueries}
          onSave={onSave}
          onApprove={onApprove}
          onNewVersion={onNewVersion}
        />
      )}
    </div>
  );
}

function Brief({
  description,
  queries,
  locked,
  busy,
  applyUrl,
  postingDetail,
  externalPostingId,
  onDescription,
  onQueries,
  onSave,
  onApprove,
  onNewVersion,
}: {
  description: string;
  queries: DraftQuery[];
  locked: boolean;
  busy: boolean;
  applyUrl: string | null;
  postingDetail: string | null;
  externalPostingId: string | null;
  onDescription: (value: string) => void;
  onQueries: (queries: DraftQuery[]) => void;
  onSave: () => void;
  onApprove: () => void;
  onNewVersion: () => void;
}) {
  return (
    <Panel>
      <div id="brief" className="space-y-4 p-5">
        <div className="space-y-1">
          <h2 className="font-display text-2xl font-medium text-ivory">Description and questions</h2>
          <p className="text-sm text-mist">
            {locked
              ? "This version is frozen. Open a new version if the brief needs to change."
              : "Edit the description and the checklist, then approve when it should stop changing."}
          </p>
        </div>
        <label className="grid gap-1.5 text-sm text-mist">
          Description
          <textarea
            value={description}
            onChange={(event) => onDescription(event.target.value)}
            readOnly={locked}
            rows={8}
            className={fieldClass}
          />
        </label>
        <ol className="space-y-3">
          {queries.map((query, index) => (
            <li key={query.query_id} className="rounded-control border border-ivory/10 p-3 text-sm">
              <p className="text-mist">
                {query.query_id} · {query.dimension} · {query.requirement_type} · weight {query.weight.toFixed(2)}
              </p>
              <textarea
                value={query.question}
                readOnly={locked}
                rows={2}
                onChange={(event) => {
                  const next = [...queries];
                  next[index] = { ...query, question: event.target.value };
                  onQueries(next);
                }}
                className={`mt-2 ${fieldClass}`}
              />
            </li>
          ))}
        </ol>
        <div className="flex flex-wrap gap-3">
          {locked ? (
            <button type="button" onClick={onNewVersion} disabled={busy} className={buttonClass()}>
              New version
            </button>
          ) : (
            <>
              <button type="button" onClick={onSave} disabled={busy} className={buttonClass("secondary")}>
                Save draft
              </button>
              <button type="button" onClick={onApprove} disabled={busy} className={buttonClass()}>
                Approve and post
              </button>
            </>
          )}
        </div>
        {applyUrl && !applyUrl.includes("/careers/") ? (
          <p className="text-sm text-mist">
            Apply link:{" "}
            <a className="underline" href={applyUrl}>
              {applyUrl}
            </a>
          </p>
        ) : null}
        {postingDetail?.startsWith("http") ? (
          <p className="text-sm text-mist">
            Channel:{" "}
            <a className="underline" href={postingDetail}>
              {postingDetail}
            </a>
          </p>
        ) : externalPostingId ? (
          <p className="text-sm text-mist">PostAJob {externalPostingId}</p>
        ) : null}
      </div>
    </Panel>
  );
}

function Applicants({
  job,
  candidates,
  ready,
  busy,
  onUpload,
  onInbox,
}: {
  job: JobRecord;
  candidates: CandidateRecord[];
  ready: boolean;
  busy: boolean;
  onUpload: (files: File[]) => void;
  onInbox: () => void;
}) {
  if (!ready) {
    return (
      <div id="people">
        <Panel>
          <p className="p-5 text-sm text-mist">Approve the brief before people can apply. A draft does not receive CVs.</p>
        </Panel>
      </div>
    );
  }
  return (
    <div id="people">
    <Panel>
      <div className="space-y-4 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <h2 className="font-display text-2xl font-medium text-ivory">People for this role</h2>
            <p className="max-w-xl text-sm text-mist">
              Mail a PDF or DOCX to {job.apply_email}. Subject: {job.mail_subject}. The job id {job.id} also matches. Upload does the same scoring, and invites still go to the top 3.
            </p>
          </div>
          <Link href={`/candidates?job=${job.id}&view=people`} className="text-sm font-semibold text-amber hover:text-peach">
            Open the portrait desk
          </Link>
        </div>
        <div className="flex flex-wrap gap-3">
          <label className={`${buttonClass("secondary")} cursor-pointer`}>
            {busy ? "Working…" : "Upload CVs"}
            <input
              type="file"
              accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              multiple
              disabled={busy}
              className="sr-only"
              onChange={(event) => {
                const chosen = event.target.files ? Array.from(event.target.files) : [];
                event.target.value = "";
                onUpload(chosen);
              }}
            />
          </label>
          <button type="button" onClick={onInbox} disabled={busy} className={buttonClass("secondary")}>
            Check inbox
          </button>
        </div>
        {candidates.length === 0 ? <p className="text-sm text-mist">No applicants yet.</p> : null}
        <ul className="divide-y divide-ivory/10">
          {candidates.map((candidate) => (
            <li key={candidate.id} className="flex items-baseline justify-between gap-4 py-3 text-sm">
              <Link href={`/candidates/${candidate.id}`} className="font-medium text-ivory hover:text-amber">
                {candidate.rank ? `#${candidate.rank}` : "Unranked"} · {candidate.full_name || "Unnamed"}
              </Link>
              <span className="text-mist">
                {candidate.aggregate_score !== null ? candidate.aggregate_score.toFixed(2) : candidate.parse_status}
                {candidate.invited ? " · invited" : ""}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </Panel>
    </div>
  );
}

function DeskTab({ href, selected, label }: { href: string; selected: boolean; label: string }) {
  return (
    <Link
      href={href}
      role="tab"
      aria-selected={selected}
      className={`rounded-full px-4 py-1.5 text-sm font-semibold ${selected ? "bg-amber text-night" : "text-mist hover:text-ivory"}`}
    >
      {label}
    </Link>
  );
}

export default function JobsPage() {
  return (
    <Suspense fallback={<AppShell><p className="text-sm text-mist">Opening jobs…</p></AppShell>}>
      <JobsPageContent />
    </Suspense>
  );
}
