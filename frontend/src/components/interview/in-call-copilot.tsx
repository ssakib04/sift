import { FormEvent, useState } from "react";

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
    <section className="space-y-3">
      <h2 className="text-lg font-medium">In-call copilot</h2>
      {profileMissing ? <p className="text-sm text-slate-300">No CV is stored for this person.</p> : null}
      {copilot ? (
        <div className="space-y-3 text-sm">
          <div>
            <p className="text-slate-400">Explored</p>
            <ul className="list-disc pl-5 text-slate-100">
              {copilot.explored.length === 0 ? <li>Nothing explored yet.</li> : null}
              {copilot.explored.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
          <div>
            <p className="text-slate-400">Coverage gaps</p>
            <ul className="list-disc pl-5 text-slate-100">
              {copilot.gaps.length === 0 ? <li>No open gaps.</li> : null}
              {copilot.gaps.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
          {copilot.suggested_question ? (
            <p className="rounded-xl border border-slate-800 px-4 py-3 text-slate-100">{copilot.suggested_question}</p>
          ) : null}
        </div>
      ) : (
        <p className="text-sm text-slate-400">The copilot updates as the transcript grows.</p>
      )}
      <form className="space-y-2" onSubmit={submit}>
        <label className="block text-sm text-slate-400" htmlFor="copilot-ask">
          Ask for questions from the CV and what has already been said
        </label>
        <textarea
          id="copilot-ask"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          rows={3}
          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
        />
        <button
          type="submit"
          disabled={asking || question.trim().length === 0}
          className="rounded-lg border border-slate-700 px-4 py-2 text-sm disabled:opacity-60"
        >
          {asking ? "Asking" : "Ask"}
        </button>
      </form>
      {reply ? (
        <div className="space-y-2 text-sm">
          <p className="text-slate-100">{reply.reply}</p>
          {reply.questions.length > 0 ? (
            <ul className="list-disc pl-5 text-slate-100">
              {reply.questions.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
