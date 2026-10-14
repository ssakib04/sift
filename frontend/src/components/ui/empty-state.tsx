import { ButtonLink } from "@/components/ui/button";

export function EmptyState({
  title,
  detail,
  actionHref,
  actionLabel,
}: {
  title: string;
  detail?: string;
  actionHref?: string;
  actionLabel?: string;
}) {
  return (
    <div className="space-y-4">
      <p className="font-display text-2xl font-medium tracking-[-0.02em] text-ivory">{title}</p>
      {detail ? <p className="text-sm leading-6 text-mist">{detail}</p> : null}
      {actionHref && actionLabel ? <ButtonLink href={actionHref}>{actionLabel}</ButtonLink> : null}
    </div>
  );
}
