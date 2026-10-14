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
  return (
    <section
      className={`relative overflow-hidden rounded-card border border-ivory/10 bg-night/65 backdrop-blur-2xl ${
        elevated ? "shadow-lift" : "shadow-[0_18px_50px_rgb(16_9_8/0.35)]"
      } ${className}`}
    >
      <span aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-ivory/30 to-transparent" />
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
