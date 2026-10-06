import Link from "next/link";

const LINKS = [
  { href: "/", label: "Home" },
  { href: "/docs", label: "Policies" },
  { href: "/jobs", label: "Jobs" },
  { href: "/careers", label: "Careers" },
];

export function SectionLinks() {
  return (
    <nav className="flex flex-wrap gap-4 text-sm text-slate-300">
      {LINKS.map((link) => (
        <Link key={link.href} href={link.href} className="hover:text-white">
          {link.label}
        </Link>
      ))}
    </nav>
  );
}
