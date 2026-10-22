import { Suspense, type ReactNode } from "react";

import { ApplicantNotices } from "@/components/applicant-notices";
import { Atmosphere } from "@/components/ui/atmosphere";
import { HashScroll } from "@/components/ui/hash-scroll";
import { RecruiterNav } from "@/components/ui/recruiter-nav";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="relative min-h-screen text-ivory">
      <Atmosphere />
      <ApplicantNotices />
      <Suspense fallback={null}>
        <HashScroll />
      </Suspense>
      <div className="mx-auto flex min-h-screen max-w-[1440px] flex-col lg:flex-row">
        <RecruiterNav />
        <main className="min-w-0 flex-1 px-5 pb-10 pt-4 lg:pb-16 lg:pl-6 lg:pr-8 lg:pt-8">{children}</main>
      </div>
    </div>
  );
}
