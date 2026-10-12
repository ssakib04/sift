import { InterviewCopilot } from "@/lib/api";

export function InCallCopilot({ copilot }: { copilot: InterviewCopilot | null }) {
  return (
    <section className="space-y-3">
      <h2 className="text-lg font-medium">In-call copilot</h2>
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
    </section>
  );
}
