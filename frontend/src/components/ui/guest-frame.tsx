import type { ReactNode } from "react";

import { Atmosphere } from "@/components/ui/atmosphere";

export function GuestFrame({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  return (
    <div className="relative min-h-screen text-ivory">
      <Atmosphere />
      <main className={`relative mx-auto px-6 py-12 ${wide ? "max-w-5xl" : "flex min-h-screen max-w-lg items-center"}`}>{children}</main>
    </div>
  );
}
