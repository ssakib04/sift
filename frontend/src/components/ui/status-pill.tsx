export type PillTone = "locked" | "draft" | "attention" | "neutral";

const tones: Record<PillTone, string> = {
  locked: "bg-celadon/20 text-ivory",
  draft: "bg-amber/20 text-ivory",
  attention: "bg-coral/25 text-ivory",
  neutral: "bg-ivory/10 text-mist",
};

export function StatusPill({ label, tone }: { label: string; tone: PillTone }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold capitalize ${tones[tone]}`}>
      {label}
    </span>
  );
}
