import { useEffect, useRef } from "react";

import { Panel } from "@/components/ui/panel";
import { TranscriptTurn } from "@/lib/api";

export function LiveTranscript({ turns }: { turns: TranscriptTurn[] }) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "nearest" });
  }, [turns]);

  return (
    <Panel>
      <div className="space-y-3 p-5">
      <h2 className="font-display text-2xl font-medium text-ivory">Live transcript</h2>
      {turns.length === 0 ? <p className="text-sm text-mist">Waiting for speech.</p> : null}
      <ol className="max-h-80 space-y-2 overflow-y-auto">
        {turns.map((turn) => {
          const speaking = turn.is_final === false;
          return (
            <li key={turn.id} className="rounded-control border border-ivory/10 px-4 py-3 text-sm">
              <p className="text-mist">
                {turn.speaker}
                {speaking ? " · speaking" : ` · ${turn.start_time.toFixed(1)}–${turn.end_time.toFixed(1)}s`}
              </p>
              <p className={speaking ? "text-mist" : "text-ivory"}>{turn.text}</p>
            </li>
          );
        })}
        <div ref={bottomRef} />
      </ol>
      </div>
    </Panel>
  );
}
