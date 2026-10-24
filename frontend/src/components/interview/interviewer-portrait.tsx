import portrait from "./interviewer.jpg";

type InterviewerPortraitProps = {
  mouth: number;
};

export function InterviewerPortrait({ mouth }: InterviewerPortraitProps) {
  const level = Math.min(1, Math.max(0, mouth));
  const drop = level * 8;

  return (
    <div className="absolute inset-0 overflow-hidden bg-[#241010]">
      <img src={portrait.src} alt="" className="absolute inset-0 h-full w-full object-cover object-center" />
      <img
        src={portrait.src}
        alt=""
        aria-hidden
        className="absolute inset-0 h-full w-full object-cover object-center"
        style={{ clipPath: "inset(56% 0 0 0)", transform: `translateY(${drop}px)` }}
      />
      <span
        aria-hidden
        className="sift-blink pointer-events-none absolute left-[34%] top-[37%] h-[6%] w-[8%] rounded-[50%] bg-[#1a0c0c]"
        style={{ animation: "sift-interviewer-blink 7.6s infinite" }}
      />
      <span
        aria-hidden
        className="sift-blink pointer-events-none absolute left-[54%] top-[37%] h-[6%] w-[8%] rounded-[50%] bg-[#1a0c0c]"
        style={{ animation: "sift-interviewer-blink 7.6s infinite" }}
      />
      <style>{`
        @keyframes sift-interviewer-blink {
          0%, 94%, 100% { opacity: 0; transform: scaleY(0.2); }
          95.5%, 97% { opacity: 0.38; transform: scaleY(1); }
        }
        @media (prefers-reduced-motion: reduce) {
          .sift-blink { animation: none !important; opacity: 0; }
        }
      `}</style>
    </div>
  );
}
