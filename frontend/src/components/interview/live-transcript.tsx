import { useEffect, useRef } from "react";

import { TranscriptTurn } from "@/lib/api";

export function LiveTranscript({ turns }: { turns: TranscriptTurn[] }) {
  const listRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    const list = listRef.current;
    if (!list) {
      return;
    }
    list.scrollTop = list.scrollHeight;
  }, [turns]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      {turns.length === 0 ? <p className="text-sm text-mist">Waiting for speech.</p> : null}
      <ol ref={listRef} className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
        {turns.map((turn) => {
          const speaking = turn.is_final === false;
          return (
            <li key={turn.id} className="rounded-control border border-ivory/10 px-3 py-2 text-sm">
              <p className="text-mist">
                {turn.speaker}
                {speaking ? " · speaking" : ` · ${turn.start_time.toFixed(1)}–${turn.end_time.toFixed(1)}s`}
              </p>
              <p className={speaking ? "text-mist" : "text-ivory"}>{turn.text}</p>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
