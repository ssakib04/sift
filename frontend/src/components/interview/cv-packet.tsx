import { buttonClass } from "@/components/ui/button";
import { InterviewPacketView } from "@/lib/api";

export function CvPacket({
  packet,
  downloading,
  onDownload,
}: {
  packet: InterviewPacketView | null;
  downloading: "" | "html" | "pdf";
  onDownload: (kind: "html" | "pdf") => void;
}) {
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap gap-2">
        <button type="button" className={buttonClass("secondary")} disabled={!packet || downloading !== ""} onClick={() => onDownload("html")}>
          {downloading === "html" ? "Saving…" : "HTML"}
        </button>
        <button type="button" className={buttonClass("secondary")} disabled={!packet || downloading !== ""} onClick={() => onDownload("pdf")}>
          {downloading === "pdf" ? "Saving…" : "PDF"}
        </button>
      </div>
      <p className="text-sm text-mist">The file includes this CV, the checklist questions, and the transcript.</p>
      {packet ? (
        <>
          <section className="space-y-2">
            <h2 className="text-xs font-semibold uppercase tracking-[0.16em] text-mist">CV</h2>
            <p className="text-sm font-medium text-ivory">{packet.full_name || "Unnamed"}</p>
            <p className="text-sm text-mist">{packet.job_title || "Role"}</p>
            {packet.cv_text ? (
              <pre className="whitespace-pre-wrap font-sans text-sm leading-6 text-ivory">{packet.cv_text}</pre>
            ) : (
              <p className="text-sm text-mist">This CV has no parsed text yet.</p>
            )}
          </section>
          <section className="space-y-2">
            <h2 className="text-xs font-semibold uppercase tracking-[0.16em] text-mist">Checklist</h2>
            {packet.questions.length > 0 ? (
              <ol className="list-decimal space-y-2 pl-5 text-sm leading-6 text-ivory">
                {packet.questions.map((question, index) => (
                  <li key={`${index}-${question}`}>{question}</li>
                ))}
              </ol>
            ) : (
              <p className="text-sm text-mist">No checklist questions are stored for this role.</p>
            )}
          </section>
        </>
      ) : (
        <p className="text-sm text-mist">Opening the CV.</p>
      )}
    </div>
  );
}
