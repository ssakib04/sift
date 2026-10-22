"use client";

import { useId, useMemo, useState } from "react";

import {
  readApplicationSeries,
  type ApplicationPeriod,
  type ApplicationPoint,
  type ApplicationSeries,
  type ApplicationSeriesResult,
} from "@/components/home/application-series";

const PERIODS: ApplicationPeriod[] = [7, 30, 90];

const VIEW = { width: 960, height: 196, left: 40, right: 16, top: 14, bottom: 28 };

function parseKey(key: string): Date {
  const [year, month, day] = key.split("-").map(Number);
  return new Date(year, (month ?? 1) - 1, day ?? 1);
}

function formatShort(key: string): string {
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" }).format(parseKey(key));
}

function formatChange(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  const prefix = rounded > 0 ? "+" : "";
  return `${prefix}${rounded.toFixed(1)}%`;
}

function axisTicks(max: number): number[] {
  const rough = Math.max(max, 1) / 4;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const residual = rough / magnitude;
  const step = residual >= 7.5 ? 10 * magnitude : residual >= 3.5 ? 5 * magnitude : residual >= 1.5 ? 2 * magnitude : magnitude;
  const top = Math.max(step, Math.ceil(Math.max(max, 1) / step) * step);
  const ticks: number[] = [];
  for (let value = 0; value <= top + step * 0.001; value += step) {
    ticks.push(Math.round(value));
  }
  return ticks;
}

function labelIndexes(length: number): number[] {
  if (length <= 7) {
    return Array.from({ length }, (_, index) => index);
  }
  const desired = 6;
  const indexes = new Set<number>();
  for (let slot = 0; slot < desired; slot += 1) {
    indexes.add(Math.round((slot * (length - 1)) / (desired - 1)));
  }
  return [...indexes].sort((left, right) => left - right);
}

function monotonePath(points: { x: number; y: number }[]): string {
  const count = points.length;
  if (count === 0) {
    return "";
  }
  if (count === 1) {
    return `M ${points[0].x.toFixed(2)} ${points[0].y.toFixed(2)}`;
  }
  const slopes: number[] = [];
  const widths: number[] = [];
  for (let index = 0; index < count - 1; index += 1) {
    widths.push(points[index + 1].x - points[index].x || 1);
    slopes.push((points[index + 1].y - points[index].y) / widths[index]);
  }
  const tangents = new Array<number>(count).fill(0);
  tangents[0] = slopes[0];
  tangents[count - 1] = slopes[count - 2];
  for (let index = 1; index < count - 1; index += 1) {
    tangents[index] = slopes[index - 1] * slopes[index] <= 0 ? 0 : (slopes[index - 1] + slopes[index]) / 2;
  }
  for (let index = 0; index < count - 1; index += 1) {
    if (slopes[index] === 0) {
      tangents[index] = 0;
      tangents[index + 1] = 0;
      continue;
    }
    const left = tangents[index] / slopes[index];
    const right = tangents[index + 1] / slopes[index];
    const magnitude = Math.hypot(left, right);
    if (magnitude > 3) {
      const scale = 3 / magnitude;
      tangents[index] = scale * left * slopes[index];
      tangents[index + 1] = scale * right * slopes[index];
    }
  }
  const commands = [`M ${points[0].x.toFixed(2)} ${points[0].y.toFixed(2)}`];
  for (let index = 0; index < count - 1; index += 1) {
    const distance = widths[index] / 3;
    const c1x = points[index].x + distance;
    const c1y = points[index].y + tangents[index] * distance;
    const c2x = points[index + 1].x - distance;
    const c2y = points[index + 1].y - tangents[index + 1] * distance;
    commands.push(
      `C ${c1x.toFixed(2)} ${c1y.toFixed(2)}, ${c2x.toFixed(2)} ${c2y.toFixed(2)}, ${points[index + 1].x.toFixed(2)} ${points[index + 1].y.toFixed(2)}`,
    );
  }
  return commands.join(" ");
}

function ChartFigure({ series }: { series: ApplicationSeries }) {
  const gradientId = useId().replace(/:/g, "");
  const [hover, setHover] = useState<number | null>(null);
  const ticks = useMemo(() => axisTicks(Math.max(...series.points.map((point) => point.count), 1)), [series.points]);
  const yMax = ticks[ticks.length - 1] || 1;
  const plotWidth = VIEW.width - VIEW.left - VIEW.right;
  const plotHeight = VIEW.height - VIEW.top - VIEW.bottom;
  const coordinates = series.points.map((point, index) => {
    const x = VIEW.left + (series.points.length === 1 ? plotWidth / 2 : (index / (series.points.length - 1)) * plotWidth);
    const y = VIEW.top + (1 - point.count / yMax) * plotHeight;
    return { x, y };
  });
  const line = monotonePath(coordinates);
  const baseline = VIEW.top + plotHeight;
  const area =
    coordinates.length > 0
      ? `${line} L ${coordinates[coordinates.length - 1].x.toFixed(2)} ${baseline} L ${coordinates[0].x.toFixed(2)} ${baseline} Z`
      : "";
  const labels = new Set(labelIndexes(series.points.length));
  const active = hover ?? series.points.length - 1;
  const activePoint = series.points[active];
  const activeCoord = coordinates[active];
  const radius = series.points.length > 40 ? 2.4 : 3.5;

  function move(clientX: number, bounds: DOMRect) {
    const x = ((clientX - bounds.left) / bounds.width) * VIEW.width;
    let nearest = 0;
    let distance = Number.POSITIVE_INFINITY;
    coordinates.forEach((point, index) => {
      const delta = Math.abs(point.x - x);
      if (delta < distance) {
        distance = delta;
        nearest = index;
      }
    });
    setHover(nearest);
  }

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${VIEW.width} ${VIEW.height}`}
        className="h-auto w-full touch-none"
        role="img"
        aria-label={`Daily applications for the last ${series.period} days`}
        onMouseMove={(event) => move(event.clientX, event.currentTarget.getBoundingClientRect())}
        onMouseLeave={() => setHover(null)}
        onTouchStart={(event) => {
          const touch = event.touches[0];
          if (touch) {
            move(touch.clientX, event.currentTarget.getBoundingClientRect());
          }
        }}
      >
        <defs>
          <linearGradient id={`${gradientId}-line`} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#f0a04b" />
            <stop offset="100%" stopColor="#c4452d" />
          </linearGradient>
          <linearGradient id={`${gradientId}-fill`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#f0a04b" stopOpacity="0.22" />
            <stop offset="100%" stopColor="#f0a04b" stopOpacity="0" />
          </linearGradient>
        </defs>
        {ticks.map((tick) => {
          const y = VIEW.top + (1 - tick / yMax) * plotHeight;
          return (
            <g key={tick}>
              <line x1={VIEW.left} x2={VIEW.width - VIEW.right} y1={y} y2={y} stroke="rgb(247 241 234 / 0.1)" />
              <text x={VIEW.left - 10} y={y + 4} textAnchor="end" fill="#cdbcae" fontSize="11">
                {tick}
              </text>
            </g>
          );
        })}
        {series.points.map((point, index) =>
          labels.has(index) ? (
            <text
              key={point.date}
              x={coordinates[index].x}
              y={VIEW.height - 8}
              textAnchor="middle"
              fill="#cdbcae"
              fontSize="11"
            >
              {formatShort(point.date)}
            </text>
          ) : null,
        )}
        <path d={area} fill={`url(#${gradientId}-fill)`} />
        <path d={line} fill="none" stroke={`url(#${gradientId}-line)`} strokeWidth="2.4" strokeLinejoin="round" strokeLinecap="round" />
        {coordinates.map((point, index) => (
          <circle
            key={series.points[index].date}
            cx={point.x}
            cy={point.y}
            r={index === active ? radius + 1.6 : radius}
            fill={index === active ? "#f4b880" : "#f0a04b"}
            stroke="#2a1210"
            strokeWidth="1.4"
          />
        ))}
        {activeCoord ? (
          <line
            x1={activeCoord.x}
            x2={activeCoord.x}
            y1={VIEW.top}
            y2={baseline}
            stroke="rgb(240 160 75 / 0.35)"
            strokeDasharray="3 4"
          />
        ) : null}
      </svg>
      {activePoint && activeCoord ? (
        <div
          className="pointer-events-none absolute z-10 rounded-control border border-amber/30 bg-[rgb(42_18_16/0.94)] px-3 py-2 text-left shadow-[0_12px_30px_rgb(8_3_3/0.45)]"
          style={{
            left: `${(activeCoord.x / VIEW.width) * 100}%`,
            top: `${(activeCoord.y / VIEW.height) * 100}%`,
            transform: `translate(${
              activeCoord.x / VIEW.width > 0.78 ? "calc(-100% - 8px)" : activeCoord.x / VIEW.width < 0.22 ? "8px" : "-50%"
            }, ${activeCoord.y < 72 ? "8px" : "calc(-100% - 8px)"})`,
          }}
        >
          <p className="text-xs font-semibold text-ivory">{formatShort(activePoint.date)}</p>
          <p className="text-xs text-peach">
            {activePoint.count} {activePoint.count === 1 ? "application" : "applications"}
          </p>
        </div>
      ) : null}
    </div>
  );
}

function Summary({ series }: { series: ApplicationSeries }) {
  const change = series.changePercent;
  const changeClass = change === null ? "text-ivory" : change >= 0 ? "text-celadon" : "text-coral";
  const items = [
    { value: String(series.total), label: "This period", className: "text-ivory" },
    { value: series.average.toFixed(1), label: "Daily average", className: "text-ivory" },
    {
      value: change === null ? "—" : formatChange(change),
      label: `Vs. previous ${series.period}d`,
      className: changeClass,
    },
  ];
  return (
    <dl className="flex flex-wrap gap-x-8 gap-y-2">
      {items.map((item) => (
        <div key={item.label}>
          <dd className={`font-display text-2xl font-medium tracking-[-0.03em] tabular-nums ${item.className}`}>{item.value}</dd>
          <dt className="text-xs text-mist">{item.label}</dt>
        </div>
      ))}
    </dl>
  );
}

function ChartBody({ result }: { result: ApplicationSeriesResult }) {
  if (result.status === "error") {
    return <p className="py-16 text-sm text-mist">{result.message}</p>;
  }
  if (result.status === "empty") {
    return <p className="py-16 text-sm text-mist">No applications in this window.</p>;
  }
  return (
    <div className="space-y-3">
      <ChartFigure key={result.series.period} series={result.series} />
      <p className="sr-only">
        {result.series.points.map((point: ApplicationPoint) => `${formatShort(point.date)}: ${point.count}`).join(", ")}
      </p>
    </div>
  );
}

export function ApplicationsChart({ appliedAt }: { appliedAt: readonly string[] }) {
  const [period, setPeriod] = useState<ApplicationPeriod>(30);
  const result = useMemo(() => readApplicationSeries(period, appliedAt), [period, appliedAt]);

  return (
    <div className="space-y-3 p-5 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
        <div className="min-w-0 max-w-md space-y-1">
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-mist">Recruitment analytics</p>
          <h2 className="font-display text-3xl font-medium tracking-[-0.03em] text-ivory">Candidates Applied</h2>
          <p className="text-sm text-mist">Applications received each day.</p>
        </div>
        {result.status === "ready" ? <Summary series={result.series} /> : null}
        <div className="flex shrink-0 rounded-full border border-ivory/10 bg-night/45 p-1" role="group" aria-label="Chart period">
          {PERIODS.map((choice) => {
            const selected = choice === period;
            return (
              <button
                key={choice}
                type="button"
                aria-pressed={selected}
                onClick={() => setPeriod(choice)}
                className={`rounded-full px-3 py-1 text-xs font-semibold tracking-wide ${
                  selected ? "bg-amber text-night" : "text-mist hover:text-ivory"
                }`}
              >
                {choice}D
              </button>
            );
          })}
        </div>
      </div>
      <ChartBody result={result} />
    </div>
  );
}
