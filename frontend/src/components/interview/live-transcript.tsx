import { useEffect, useRef } from "react";

import { TranscriptTurn } from "@/lib/api";

export function LiveTranscript({ turns }: { turns: TranscriptTurn[] }) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "nearest" });
  }, [turns]);

  return (
    <section className="space-y-3">
      <h2 className="text-lg font-medium">Live transcript</h2>
      {turns.length === 0 ? <p className="text-sm text-slate-400">Waiting for speech.</p> : null}
      <ol className="max-h-80 space-y-2 overflow-y-auto">
        {turns.map((turn) => {
          const speaking = turn.is_final === false;
          return (
            <li key={turn.id} className="rounded-xl border border-slate-800 px-4 py-3 text-sm">
              <p className="text-slate-400">
                {turn.speaker}
                {speaking ? " · speaking" : ` · ${turn.start_time.toFixed(1)}–${turn.end_time.toFixed(1)}s`}
              </p>
              <p className={speaking ? "text-slate-300" : "text-slate-100"}>{turn.text}</p>
            </li>
          );
        })}
        <div ref={bottomRef} />
      </ol>
    </section>
  );
}
