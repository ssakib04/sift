type CartoonAvatarProps = {
  mouth: number;
};

export function CartoonAvatar({ mouth }: CartoonAvatarProps) {
  const open = Math.min(1, Math.max(0, mouth));
  const gap = 2 + open * 16;

  return (
    <div className="absolute inset-0 grid place-items-center bg-umber">
      <div className="flex flex-col items-center gap-5">
        <svg viewBox="0 0 200 230" className="sift-avatar h-72 w-72" role="img" aria-label="AI interviewer">
          <ellipse cx="100" cy="196" rx="58" ry="28" fill="#e2b07a" />
          <ellipse cx="100" cy="188" rx="34" ry="16" fill="#f6e3c4" />
          <path d="M52 78c8-34 22-52 48-52 8 18 8 36 2 52z" fill="#c4894e" />
          <path d="M148 78c-8-34-22-52-48-52-8 18-8 36-2 52z" fill="#c4894e" />
          <circle cx="100" cy="112" r="70" fill="#f4d7b0" />
          <ellipse cx="68" cy="128" rx="16" ry="9" fill="#e7b09a" opacity="0.55" />
          <ellipse cx="132" cy="128" rx="16" ry="9" fill="#e7b09a" opacity="0.55" />
          <circle cx="74" cy="108" r="18" fill="#f8e7cf" />
          <circle cx="126" cy="108" r="18" fill="#f8e7cf" />
          <ellipse className="sift-avatar-eye" cx="74" cy="110" rx="8" ry="9" fill="#3d2a22" />
          <ellipse className="sift-avatar-eye" cx="126" cy="110" rx="8" ry="9" fill="#3d2a22" />
          <circle cx="77" cy="106" r="2.4" fill="#fff8ee" />
          <circle cx="129" cy="106" r="2.4" fill="#fff8ee" />
          <path d="M90 132h20l-10 12z" fill="#e09a4e" />
          {open > 0.08 ? (
            <ellipse cx="100" cy={144 + gap * 0.35} rx={7 + open * 4} ry={Math.max(2, gap * 0.72)} fill="#6a3a32" />
          ) : null}
          <path d={`M88 ${142 + gap}h24l-12 10z`} fill="#d08a42" />
        </svg>
        <style>{`
          .sift-avatar { transform-origin: 100px 150px; animation: sift-avatar-bob 4.6s ease-in-out infinite; }
          .sift-avatar-eye { transform-box: fill-box; transform-origin: center; animation: sift-avatar-blink 5.4s infinite; }
          @keyframes sift-avatar-bob { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(4px); } }
          @keyframes sift-avatar-blink { 0%, 46%, 52%, 100% { transform: scaleY(1); } 49% { transform: scaleY(0.08); } }
        `}</style>
        <p className="text-sm text-ivory">AI interviewer</p>
      </div>
    </div>
  );
}
