import { useEffect, useRef } from "react";

import { TranscriptTurn } from "@/lib/api";

export function LiveTranscript({ turns, candidateName }: { turns: TranscriptTurn[]; candidateName: string }) {
  const listRef = useRef<HTMLUListElement>(null);
  const name = candidateName.trim() || "Candidate";

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
      <ul ref={listRef} className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pr-1">
        {turns.map((turn) => {
          const mine = turn.speaker === "recruiter";
          const speaking = turn.is_final === false;
          return (
            <li key={turn.id} className={`flex ${mine ? "justify-end" : "justify-start"}`}>
              <div className={`flex max-w-[85%] flex-col ${mine ? "items-end" : "items-start"}`}>
                <p className={`mb-1 text-xs ${mine ? "text-peach" : "text-amber"}`}>
                  {mine ? "You" : name}
                  {speaking ? " · speaking" : ""}
                </p>
                <p
                  className={`rounded-2xl px-3 py-2 text-sm ${
                    mine
                      ? "rounded-br-md bg-rust/35 text-peach"
                      : "rounded-bl-md border border-ivory/10 bg-ivory/10 text-ivory"
                  }`}
                >
                  {turn.text}
                </p>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
