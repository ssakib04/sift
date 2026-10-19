"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/ui/app-shell";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { ProgressBoard, apiRequest } from "@/lib/api";

export default function ProgressPage() {
  const [boards, setBoards] = useState<ProgressBoard[]>([]);
  const [message, setMessage] = useState("");

  useEffect(() => {
    apiRequest<ProgressBoard[]>("/api/v1/progress")
      .then(setBoards)
      .catch((error: unknown) => {
        setMessage(error instanceof Error ? error.message : "Could not load progress.");
      });
  }, []);

  return (
    <AppShell>
      <div className="mx-auto max-w-6xl space-y-8">
        <PageHeader
          eyebrow="Progress"
          title="Recruitment board"
          lede="Each person sits in the furthest stage already stored for that role."
        />
        {message ? <p className="text-sm text-mist">{message}</p> : null}
        {boards.length === 0 && !message ? (
          <EmptyState
            title="No roles yet"
            detail="Draft a job and the board will track applicants here."
            actionHref="/jobs"
            actionLabel="Open jobs"
          />
        ) : null}
        {boards.map((board) => (
          <section key={board.job_id} className="space-y-3">
            <div className="flex items-baseline justify-between gap-4">
              <h2 className="font-display text-2xl font-medium text-ivory">{board.job_title}</h2>
              <p className="text-sm text-mist">
                {board.applicant_count === 0
                  ? "No applicants"
                  : board.applicant_count === 1
                    ? "1 applicant"
                    : `${board.applicant_count} applicants`}
              </p>
            </div>
            <div className="flex gap-3 overflow-x-auto pb-2">
              {board.columns.map((column) => (
                <div key={column.stage} className="w-56 shrink-0">
                  <Panel>
                    <div className="flex min-h-40 flex-col gap-2 px-3 py-3">
                      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-mist">
                        {column.label} · {column.cards.length}
                      </p>
                      {column.cards.length === 0 ? <p className="text-sm text-mist">Empty</p> : null}
                      {column.cards.map((card) => (
                        <Link
                          key={card.candidate_id}
                          href={`/candidates/${card.candidate_id}`}
                          className="rounded-control border border-ivory/10 px-2 py-2 hover:border-amber/50"
                        >
                          <p className="text-sm font-medium text-ivory">{card.full_name || "Unnamed"}</p>
                          <p className="text-xs text-mist">
                            {card.rank ? `#${card.rank}` : "Unranked"}
                            {card.detail ? ` · ${card.detail}` : ""}
                          </p>
                        </Link>
                      ))}
                    </div>
                  </Panel>
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    </AppShell>
  );
}
