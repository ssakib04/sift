import type { InputHTMLAttributes, SelectHTMLAttributes } from "react";

const controlClass =
  "w-full rounded-control border border-ivory/15 bg-night/50 px-3 py-2.5 text-sm text-ivory placeholder:text-mist/70";

export const fieldClass = controlClass;

export function TextField({ label, ...props }: { label: string } & InputHTMLAttributes<HTMLInputElement>) {
  const id = props.id ?? (typeof props.name === "string" ? props.name : undefined);
  return (
    <label className="grid gap-1.5 text-sm text-mist" htmlFor={id}>
      {label}
      <input id={id} {...props} className={controlClass} />
    </label>
  );
}

export function SelectField({ label, children, ...props }: { label: string } & SelectHTMLAttributes<HTMLSelectElement>) {
  const id = props.id ?? (typeof props.name === "string" ? props.name : undefined);
  return (
    <label className="grid gap-1.5 text-sm text-mist" htmlFor={id}>
      {label}
      <select id={id} {...props} className={controlClass}>
        {children}
      </select>
    </label>
  );
}
