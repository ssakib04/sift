import { FormEvent, useState } from "react";

import { buttonClass } from "@/components/ui/button";
import { fieldClass } from "@/components/ui/field";
import { CopilotAnswer, InterviewCopilot } from "@/lib/api";

export function InCallCopilot({
  copilot,
  reply,
  asking,
  onAsk,
}: {
  copilot: InterviewCopilot | null;
  reply: CopilotAnswer | null;
  asking: boolean;
  onAsk: (question: string) => void;
}) {
  const [question, setQuestion] = useState("");
  const profileMissing = copilot?.profile_available === false || reply?.profile_available === false;

  function submit(event: FormEvent) {
    event.preventDefault();
    const cleaned = question.trim();
    if (!cleaned || asking) {
      return;
    }
    onAsk(cleaned);
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1 text-sm">
      {profileMissing ? <p className="text-sm text-mist">No CV is stored for this person.</p> : null}
      {copilot ? (
        <div className="space-y-3">
          <div>
            <p className="text-mist">Explored</p>
            <ul className="list-disc pl-5 text-ivory">
              {copilot.explored.length === 0 ? <li>Nothing explored yet.</li> : null}
              {copilot.explored.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
          <div>
            <p className="text-mist">Coverage gaps</p>
            <ul className="list-disc pl-5 text-ivory">
              {copilot.gaps.length === 0 ? <li>No open gaps.</li> : null}
              {copilot.gaps.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
          {copilot.suggested_question ? (
            <p className="rounded-control border border-ivory/10 px-4 py-3 text-ivory">{copilot.suggested_question}</p>
          ) : null}
        </div>
      ) : (
        <p className="text-sm text-mist">Questions appear as the transcript grows.</p>
      )}
      {reply ? (
        <div className="space-y-2">
          <p className="text-ivory">{reply.reply}</p>
          {reply.questions.length > 0 ? (
            <ul className="list-disc pl-5 text-ivory">
              {reply.questions.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      </div>
      <form className="space-y-2" onSubmit={submit}>
        <label className="block text-sm text-mist" htmlFor="copilot-ask">
          Ask for the next question
        </label>
        <textarea id="copilot-ask" value={question} onChange={(event) => setQuestion(event.target.value)} rows={2} className={fieldClass} />
        <button type="submit" disabled={asking || question.trim().length === 0} className={buttonClass("secondary")}>
          {asking ? "Asking" : "Ask"}
        </button>
      </form>
    </div>
  );
}
