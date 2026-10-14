export function PageHeader({ eyebrow, title, lede }: { eyebrow?: string; title: string; lede?: string }) {
  return (
    <header className="max-w-2xl space-y-3">
      {eyebrow ? <p className="text-xs font-semibold uppercase tracking-[0.22em] text-mist">{eyebrow}</p> : null}
      <h1 className="font-display text-4xl font-medium leading-[1.05] tracking-[-0.03em] text-ivory sm:text-5xl lg:text-6xl">
        {title}
      </h1>
      {lede ? <p className="max-w-xl text-base leading-7 text-mist">{lede}</p> : null}
    </header>
  );
}
