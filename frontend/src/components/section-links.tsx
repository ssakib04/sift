"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { forgetRecruiter } from "@/lib/api";

const LINKS = [
  { href: "/", label: "Home" },
  { href: "/docs", label: "Policies" },
  { href: "/jobs", label: "Jobs" },
  { href: "/candidates", label: "Candidates" },
  { href: "/practice", label: "Practice" },
  { href: "/careers", label: "Careers" },
];

export function SectionLinks() {
  const router = useRouter();

  return (
    <nav className="flex flex-wrap gap-4 text-sm text-mist">
      {LINKS.map((link) => (
        <Link key={link.href} href={link.href} className="hover:text-ivory">
          {link.label}
        </Link>
      ))}
      <button
        type="button"
        className="hover:text-ivory"
        onClick={() => {
          forgetRecruiter();
          router.push("/login");
        }}
      >
        Sign out
      </button>
    </nav>
  );
}
