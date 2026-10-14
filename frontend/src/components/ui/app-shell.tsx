import type { ReactNode } from "react";

import { Atmosphere } from "@/components/ui/atmosphere";
import { RecruiterNav } from "@/components/ui/recruiter-nav";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="relative min-h-screen text-ivory">
      <Atmosphere />
      <div className="mx-auto flex min-h-screen max-w-[1440px] flex-col lg:flex-row">
        <RecruiterNav />
        <main className="min-w-0 flex-1 px-6 pb-28 pt-4 lg:px-12 lg:pb-16 lg:pt-12">{children}</main>
      </div>
    </div>
  );
}
