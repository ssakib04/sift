"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Panel } from "@/components/ui/panel";
import { CandidateCompareReport, CompareSide, apiRequest } from "@/lib/api";

export function CandidateCompare({ leftId, rightId }: { leftId: string; rightId: string }) {
  const [report, setReport] = useState<CandidateCompareReport | null>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    let stop = false;
    setReport(null);
    setMessage("");
    apiRequest<CandidateCompareReport>("/api/v1/candidates/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ left_id: leftId, right_id: rightId }),
    })
      .then((next) => {
        if (!stop) {
          setReport(next);
        }
      })
      .catch((error: unknown) => {
        if (!stop) {
          setMessage(error instanceof Error ? error.message : "Could not compare these candidates.");
        }
      });
    return () => {
      stop = true;
    };
  }, [leftId, rightId]);

  if (message) {
    return <p className="text-sm text-mist">{message}</p>;
  }
  if (!report) {
    return <p className="text-sm text-mist">Comparing the stored scores.</p>;
  }
  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        <SideCard side={report.left} edge={report.left_edge} />
        <SideCard side={report.right} edge={report.right_edge} />
      </div>
      <Panel>
        <div className="space-y-5 p-5 sm:p-6">
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-mist">Comparison</p>
            <p className="font-display text-2xl font-medium leading-snug text-ivory">{report.summary}</p>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-mist">Tradeoff</p>
            <p className="mt-2 text-sm leading-6 text-ivory">{report.tradeoff}</p>
          </div>
          <p className="text-sm text-mist">Every figure comes from the stored scores.</p>
        </div>
      </Panel>
    </div>
  );
}

function SideCard({ side, edge }: { side: CompareSide; edge: string }) {
  return (
    <Panel>
      <div className="space-y-4 p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <Link href={`/candidates/${side.candidate_id}`} className="font-display text-2xl font-medium text-ivory hover:text-amber">
              {side.full_name || "Unnamed"}
            </Link>
            <p className="mt-1 text-sm text-mist">{side.rank ? `Rank #${side.rank}` : "Unranked"}</p>
          </div>
          {side.suitability_label ? (
            <span className="rounded-full border border-ivory/15 px-2.5 py-1 text-xs font-semibold text-ivory">{side.suitability_label}</span>
          ) : null}
        </div>
        <dl className="grid grid-cols-2 gap-3 text-sm">
          <Score label="CV" value={side.cv_score === null ? "—" : side.cv_score.toFixed(2)} />
          <Score label="Quiz" value={side.mcq_score === null ? "—" : String(side.mcq_score)} />
          <Score label="Interview" value={side.interview_score === null ? "—" : side.interview_score.toFixed(1)} />
          <Score label="Master" value={side.overall_score === null ? "—" : side.overall_score.toFixed(1)} />
        </dl>
        <div className="space-y-2">
          <Meter label="Technical" value={side.technical_score} />
          <Meter label="Experience" value={side.experience_score} />
          <Meter label="Qualification" value={side.qualification_score} />
        </div>
        <p className="text-sm leading-6 text-ivory">{edge}</p>
      </div>
    </Panel>
  );
}

function Score({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs font-semibold uppercase tracking-[0.14em] text-mist">{label}</dt>
      <dd className="mt-1 font-display text-2xl text-ivory">{value}</dd>
    </div>
  );
}

function Meter({ label, value }: { label: string; value: number | null }) {
  const width = value === null ? 0 : Math.max(0, Math.min(100, value * 100));
  const text = value === null ? "—" : value.toFixed(2);
  return (
    <div className="grid grid-cols-[7.5rem_minmax(0,1fr)_2.5rem] items-center gap-2 text-xs text-mist">
      <span>{label}</span>
      <span className="h-1.5 overflow-hidden rounded-full bg-ivory/10">
        <span className="block h-full rounded-full bg-amber" style={{ width: `${width}%` }} />
      </span>
      <span className="text-right text-ivory">{text}</span>
    </div>
  );
}
