"use client";

import { FormEvent, useEffect, useState } from "react";

import { AppShell } from "@/components/ui/app-shell";
import { buttonClass } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { ApiError, PolicyRecord, QuestionBankRecord, apiRequest } from "@/lib/api";

type PolicySummary = {
  id: string;
  summary: string;
};

function kind(filename: string): string {
  const suffix = filename.split(".").pop()?.toLowerCase() ?? "";
  if (suffix === "pdf") {
    return "PDF";
  }
  if (suffix === "docx") {
    return "DOCX";
  }
  return "FILE";
}

export default function DocsPage() {
  const [policies, setPolicies] = useState<PolicyRecord[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [chosen, setChosen] = useState<File | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [summaries, setSummaries] = useState<Record<string, string>>({});
  const [reading, setReading] = useState(false);
  const [banks, setBanks] = useState<QuestionBankRecord[]>([]);
  const [bankFile, setBankFile] = useState<File | null>(null);
  const [bankBusy, setBankBusy] = useState(false);
  const [bankMessage, setBankMessage] = useState("");

  async function refresh() {
    const [records, stored] = await Promise.all([
      apiRequest<PolicyRecord[]>("/api/v1/policies"),
      apiRequest<QuestionBankRecord[]>("/api/v1/question-bank"),
    ]);
    setPolicies(records);
    setBanks(stored);
  }

  useEffect(() => {
    refresh().catch((error: unknown) => {
      setMessage(error instanceof Error ? error.message : "Could not load policies.");
    });
  }, []);

  useEffect(() => {
    const doc = new URLSearchParams(window.location.search).get("doc");
    if (!doc) {
      return;
    }
    const policy = policies.find((item) => item.id === doc);
    if (!policy || openId === policy.id) {
      return;
    }
    void openPolicy(policy);
  }, [policies]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!chosen) {
      setMessage("Choose a PDF or DOCX file.");
      return;
    }
    const body = new FormData();
    body.append("file", chosen);
    setBusy(true);
    setMessage("");
    try {
      await apiRequest<PolicyRecord>("/api/v1/policies", { method: "POST", body });
      setChosen(null);
      await refresh();
      setMessage("Policy indexed.");
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "Upload failed.");
    } finally {
      setBusy(false);
    }
  }

  async function onBank(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!bankFile) {
      setBankMessage("Choose a PDF or DOCX file.");
      return;
    }
    const body = new FormData();
    body.append("file", bankFile);
    setBankBusy(true);
    setBankMessage("");
    try {
      await apiRequest<QuestionBankRecord>("/api/v1/question-bank", { method: "POST", body });
      setBankFile(null);
      await refresh();
      setBankMessage("Question bank added.");
    } catch (error) {
      setBankMessage(error instanceof ApiError ? error.message : "Upload failed.");
    } finally {
      setBankBusy(false);
    }
  }

  async function openPolicy(policy: PolicyRecord) {
    if (openId === policy.id) {
      setOpenId(null);
      return;
    }
    setOpenId(policy.id);
    if (summaries[policy.id]) {
      return;
    }
    setReading(true);
    try {
      const result = await apiRequest<PolicySummary>(`/api/v1/policies/${policy.id}/summary`);
      setSummaries((current) => ({ ...current, [policy.id]: result.summary }));
    } catch (error) {
      setSummaries((current) => ({
        ...current,
        [policy.id]: error instanceof ApiError ? error.message : "The summary could not be read.",
      }));
    } finally {
      setReading(false);
    }
  }

  const open = policies.find((policy) => policy.id === openId) ?? null;

  return (
    <AppShell>
      <div id="policies" className="mx-auto max-w-4xl space-y-8">
        <PageHeader
          eyebrow="Policies"
          title="Company policy index"
          lede="Add a PDF or DOCX. Each document sits in the index, and a card opens a short summary from the local model."
        />
        <form onSubmit={onSubmit}>
          <Panel>
            <div className="space-y-4 p-5">
              <label className="flex cursor-pointer items-center justify-between gap-4 rounded-control border border-dashed border-ivory/20 bg-ivory/[0.03] px-4 py-4 hover:border-ivory/35">
                <span className="min-w-0">
                  <span className="block truncate text-sm font-semibold text-ivory">
                    {chosen ? chosen.name : "Choose a PDF or DOCX"}
                  </span>
                  <span className="mt-1 block text-xs text-mist">Up to 10 MB. The text is stored for job descriptions.</span>
                </span>
                <span className="shrink-0 rounded-full border border-ivory/15 px-3 py-1 text-xs font-semibold text-ivory">Browse</span>
                <input
                  name="policy"
                  type="file"
                  accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                  className="sr-only"
                  onChange={(event) => setChosen(event.target.files?.[0] ?? null)}
                />
              </label>
              <button type="submit" disabled={busy || !chosen} className={buttonClass()}>
                {busy ? "Indexing..." : "Index policy"}
              </button>
              {message ? <p className="text-sm text-mist">{message}</p> : null}
            </div>
          </Panel>
        </form>
        <form onSubmit={onBank}>
          <Panel>
            <div className="space-y-4 p-5">
              <div>
                <p className="font-medium text-ivory">Company question bank</p>
                <p className="mt-1 text-sm text-mist">
                  Add a PDF or DOCX of interview questions. Related questions are asked as written during a call. When
                  none fit, the interviewer writes its own.
                </p>
              </div>
              <label className="flex cursor-pointer items-center justify-between gap-4 rounded-control border border-dashed border-ivory/20 bg-ivory/[0.03] px-4 py-4 hover:border-ivory/35">
                <span className="min-w-0">
                  <span className="block truncate text-sm font-semibold text-ivory">
                    {bankFile ? bankFile.name : "Choose a PDF or DOCX"}
                  </span>
                  <span className="mt-1 block text-xs text-mist">Up to 10 MB. One question per line, or numbered.</span>
                </span>
                <span className="shrink-0 rounded-full border border-ivory/15 px-3 py-1 text-xs font-semibold text-ivory">
                  Browse
                </span>
                <input
                  name="question-bank"
                  type="file"
                  accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                  className="sr-only"
                  onChange={(event) => setBankFile(event.target.files?.[0] ?? null)}
                />
              </label>
              <button type="submit" disabled={bankBusy || !bankFile} className={buttonClass()}>
                {bankBusy ? "Adding..." : "Add questions"}
              </button>
              {bankMessage ? <p className="text-sm text-mist">{bankMessage}</p> : null}
              {banks.length === 0 ? <p className="text-sm text-mist">No question banks yet.</p> : null}
              <ul className="space-y-2">
                {banks.map((bank) => (
                  <li key={bank.id} className="flex items-baseline justify-between gap-4 text-sm">
                    <span className="truncate text-ivory">{bank.filename}</span>
                    <span className="shrink-0 text-mist">
                      {bank.question_count} {bank.question_count === 1 ? "question" : "questions"}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </Panel>
        </form>
        {policies.length === 0 ? <p className="text-sm text-mist">No policies indexed yet.</p> : null}
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {policies.map((policy) => {
            const selected = policy.id === openId;
            return (
              <li key={policy.id}>
                <Panel>
                  <button
                    type="button"
                    aria-pressed={selected}
                    onClick={() => void openPolicy(policy)}
                    className={`flex aspect-square w-full flex-col justify-between p-4 text-left hover:bg-ivory/[0.03] ${
                      selected ? "bg-ivory/[0.04]" : ""
                    }`}
                  >
                    <span className="text-xs font-semibold uppercase tracking-[0.16em] text-peach">{kind(policy.filename)}</span>
                    <span>
                      <span className="line-clamp-3 font-medium text-ivory">{policy.filename}</span>
                      <span className="mt-2 block text-sm text-mist">
                        {policy.chunk_count} {policy.chunk_count === 1 ? "chunk" : "chunks"}
                      </span>
                    </span>
                  </button>
                </Panel>
              </li>
            );
          })}
        </ul>
        {open ? (
          <Panel>
            <div id="policy" className="space-y-2 p-5">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-mist">Summary</p>
              <p className="font-medium text-ivory">{open.filename}</p>
              <p className="max-w-2xl text-sm leading-6 text-mist">
                {summaries[open.id] ?? (reading ? "Reading this policy on the local model…" : "")}
              </p>
            </div>
          </Panel>
        ) : null}
      </div>
    </AppShell>
  );
}
