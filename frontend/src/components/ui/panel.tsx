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
    ? "border-white/15 bg-[linear-gradient(180deg,rgb(92_42_34/0.46),rgb(36_16_14/0.58))] shadow-[inset_0_1px_0_rgb(255_228_206/0.45),inset_0_0_24px_rgb(240_160_75/0.06),0_18px_40px_rgb(6_2_2/0.22)]"
    : "border-white/10 bg-[linear-gradient(180deg,rgb(72_32_26/0.5),rgb(28_12_12/0.62))] shadow-[inset_0_1px_0_rgb(255_220_196/0.28),0_12px_28px_rgb(6_2_2/0.2)]";
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
