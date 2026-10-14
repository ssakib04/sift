import Link from "next/link";
import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost";

const variants: Record<Variant, string> = {
  primary: "bg-action text-ivory hover:brightness-90",
  secondary: "border border-ivory/15 bg-ivory/5 text-ivory hover:bg-ivory/10",
  ghost: "text-mist hover:text-ivory",
};

export function buttonClass(variant: Variant = "primary", className = ""): string {
  return [
    "inline-flex items-center justify-center rounded-control px-4 py-2.5 text-sm font-semibold",
    "transition-colors disabled:cursor-not-allowed disabled:opacity-60",
    variants[variant],
    className,
  ]
    .filter(Boolean)
    .join(" ");
}

export function Button({
  variant = "primary",
  className = "",
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return <button type={type} className={buttonClass(variant, className)} {...props} />;
}

export function ButtonLink({
  href,
  variant = "primary",
  className = "",
  children,
}: {
  href: string;
  variant?: Variant;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Link href={href} className={buttonClass(variant, className)}>
      {children}
    </Link>
  );
}
