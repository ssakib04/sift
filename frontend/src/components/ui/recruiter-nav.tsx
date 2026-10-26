"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { forgetRecruiter } from "@/lib/api";

const LINKS = [
  { href: "/", label: "Home" },
  { href: "/docs", label: "Policies" },
  { href: "/jobs", label: "Jobs" },
  { href: "/candidates", label: "Candidates" },
  { href: "/interviews", label: "Interviews" },
  { href: "/practice", label: "Practice" },
];

function isCurrent(pathname: string, href: string): boolean {
  if (href === "/") {
    return pathname === "/";
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function RecruiterNav() {
  const pathname = usePathname();
  const router = useRouter();

  function signOut() {
    forgetRecruiter();
    router.push("/login");
  }

  return (
    <header className="flex flex-col gap-4 px-4 pt-4 lg:sticky lg:top-0 lg:h-screen lg:w-40 lg:shrink-0 lg:justify-between lg:px-3 lg:py-6">
      <div className="flex items-center justify-between gap-4 max-lg:pr-[18rem] lg:block">
        <Link href="/" className="font-display text-2xl font-medium tracking-[-0.03em] text-ivory">
          Sift
        </Link>
        <button type="button" onClick={signOut} className="text-sm text-mist hover:text-ivory lg:hidden">
          Sign out
        </button>
      </div>
      <nav className="flex gap-1 overflow-x-auto lg:mt-6 lg:flex-1 lg:flex-col" aria-label="Recruiter">
        {LINKS.map((link) => {
          const current = isCurrent(pathname, link.href);
          return (
            <Link
              key={link.href}
              href={link.href}
              aria-current={current ? "page" : undefined}
              className={`whitespace-nowrap rounded-control px-2.5 py-2 text-sm font-semibold ${
                current ? "bg-ivory/10 text-ivory" : "text-mist hover:bg-ivory/5 hover:text-ivory"
              }`}
            >
              {link.label}
            </Link>
          );
        })}
      </nav>
      <button type="button" onClick={signOut} className="hidden text-left text-sm font-semibold text-mist hover:text-ivory lg:inline">
        Sign out
      </button>
    </header>
  );
}
