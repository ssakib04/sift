"use client";

import { FormEvent, useEffect, useState } from "react";

import { SectionLinks } from "@/components/section-links";
import { ApiError, PolicyRecord, apiRequest } from "@/lib/api";

export default function DocsPage() {
  const [policies, setPolicies] = useState<PolicyRecord[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function refresh() {
    const records = await apiRequest<PolicyRecord[]>("/api/v1/policies");
    setPolicies(records);
  }

  useEffect(() => {
    refresh().catch((error: unknown) => {
      setMessage(error instanceof Error ? error.message : "Could not load policies.");
    });
  }, []);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const input = form.elements.namedItem("policy");
    if (!(input instanceof HTMLInputElement) || !input.files?.[0]) {
      setMessage("Choose a PDF or DOCX file.");
      return;
    }
    const body = new FormData();
    body.append("file", input.files[0]);
    setBusy(true);
    setMessage("");
    try {
      await apiRequest<PolicyRecord>("/api/v1/policies", { method: "POST", body });
      form.reset();
      await refresh();
      setMessage("Policy indexed.");
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "Upload failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-950 px-6 py-10 text-slate-100">
      <div className="mx-auto max-w-3xl space-y-8">
        <SectionLinks />
        <header className="space-y-2">
          <p className="text-sm uppercase tracking-[0.2em] text-slate-400">Policies</p>
          <h1 className="text-3xl font-semibold">Company policy index</h1>
          <p className="text-slate-300">Upload a PDF or DOCX. The text is chunked and stored for job-description retrieval.</p>
        </header>
        <form onSubmit={onSubmit} className="space-y-4 rounded-xl border border-slate-800 bg-slate-900 p-5">
          <input name="policy" type="file" accept=".pdf,.docx" className="block w-full text-sm" />
          <button type="submit" disabled={busy} className="rounded-md bg-white px-4 py-2 text-sm font-medium text-slate-950 disabled:opacity-60">
            {busy ? "Indexing..." : "Index policy"}
          </button>
          {message ? <p className="text-sm text-slate-300">{message}</p> : null}
        </form>
        <ul className="space-y-3">
          {policies.map((policy) => (
            <li key={policy.id} className="rounded-xl border border-slate-800 px-4 py-3">
              <p className="font-medium">{policy.filename}</p>
              <p className="text-sm text-slate-400">{policy.chunk_count} chunks</p>
            </li>
          ))}
        </ul>
      </div>
    </main>
  );
}
