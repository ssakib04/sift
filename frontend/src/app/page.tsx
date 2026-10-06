import { SectionLinks } from "@/components/section-links";

export default function HomePage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-100">
      <div className="max-w-lg space-y-3 px-6 text-center">
        <p className="text-sm uppercase tracking-[0.2em] text-slate-400">Sift</p>
        <h1 className="text-3xl font-semibold">Platform shell is running</h1>
        <p className="text-slate-300">
          Foundation services are ready for the next phase of the recruitment workflow.
        </p>
        <div className="flex justify-center pt-4">
          <SectionLinks />
        </div>
      </div>
    </main>
  );
}
