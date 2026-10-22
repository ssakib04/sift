import type { ReactNode } from "react";

export function Panel({
  children,
  className = "",
  glow = false,
  wash = false,
  elevated = false,
}: {
  children: ReactNode;
  className?: string;
  glow?: boolean;
  wash?: boolean;
  elevated?: boolean;
}) {
  const face = elevated || glow
    ? "border-white/15 bg-[linear-gradient(180deg,rgb(48_24_32/0.34),rgb(18_10_14/0.44))] shadow-[inset_0_1px_0_rgb(255_228_220/0.4),inset_0_0_24px_rgb(212_168_180/0.08),0_18px_40px_rgb(20_10_16/0.16)]"
    : "border-white/10 bg-[linear-gradient(180deg,rgb(40_20_26/0.36),rgb(16_10_12/0.46))] shadow-[inset_0_1px_0_rgb(255_220_214/0.26),0_12px_28px_rgb(20_10_16/0.14)]";
  return (
    <section className={`relative overflow-hidden rounded-card border backdrop-blur-xl ${face} ${className}`}>
      <span aria-hidden className="pointer-events-none absolute inset-x-6 top-0 h-px bg-gradient-to-r from-transparent via-peach/70 to-transparent" />
      {glow ? (
        <>
          <span aria-hidden className="pointer-events-none absolute -right-8 -top-20 h-80 w-80 rounded-full bg-ember/40 blur-3xl" />
          <span aria-hidden className="pointer-events-none absolute -bottom-20 left-0 h-56 w-96 rounded-full bg-crimson/40 blur-3xl" />
          <span aria-hidden className="pointer-events-none absolute inset-x-0 bottom-0 h-px bg-gradient-to-r from-transparent via-amber/80 to-transparent" />
        </>
      ) : null}
      {wash && !glow ? (
        <span aria-hidden className="pointer-events-none absolute -right-10 -top-16 h-48 w-48 rounded-full bg-ember/25 blur-3xl" />
      ) : null}
      <div className="relative">{children}</div>
    </section>
  );
}
