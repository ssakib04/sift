"use client";

import { FormEvent, useEffect, useState } from "react";

import { AppShell } from "@/components/ui/app-shell";
import { buttonClass } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
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
    <AppShell>
      <div className="mx-auto max-w-3xl space-y-8">
        <PageHeader
          eyebrow="Policies"
          title="Company policy index"
          lede="Upload a PDF or DOCX. The text is chunked and stored for job-description retrieval."
        />
        <form onSubmit={onSubmit}>
          <Panel>
            <div className="space-y-4 p-5">
              <input name="policy" type="file" accept=".pdf,.docx" className="block w-full text-sm text-mist" />
              <button type="submit" disabled={busy} className={buttonClass()}>
                {busy ? "Indexing..." : "Index policy"}
              </button>
              {message ? <p className="text-sm text-mist">{message}</p> : null}
            </div>
          </Panel>
        </form>
        <ul className="space-y-3">
          {policies.map((policy) => (
            <li key={policy.id}>
              <Panel>
                <div className="px-4 py-3">
                  <p className="font-medium text-ivory">{policy.filename}</p>
                  <p className="text-sm text-mist">{policy.chunk_count} chunks</p>
                </div>
              </Panel>
            </li>
          ))}
        </ul>
      </div>
    </AppShell>
  );
}
