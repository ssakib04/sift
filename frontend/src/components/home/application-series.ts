export type ApplicationPeriod = 7 | 30 | 90;

export type ApplicationPoint = {
  date: string;
  count: number;
};

export type ApplicationSeries = {
  period: ApplicationPeriod;
  points: ApplicationPoint[];
  total: number;
  average: number;
  previousTotal: number;
  changePercent: number | null;
};

export type ApplicationSeriesResult =
  | { status: "ready"; series: ApplicationSeries }
  | { status: "empty"; period: ApplicationPeriod }
  | { status: "error"; message: string };

function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function addDays(date: Date, days: number): Date {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

function dateKey(date: Date): string {
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

export function readApplicationSeries(
  period: ApplicationPeriod,
  appliedAt: readonly string[],
  today = new Date(),
): ApplicationSeriesResult {
  const end = startOfDay(today);
  const windowDays = period * 2;
  const counts = new Map<string, number>();
  for (let index = 0; index < windowDays; index += 1) {
    counts.set(dateKey(addDays(end, index - (windowDays - 1))), 0);
  }
  for (const stamp of appliedAt) {
    const parsed = new Date(stamp);
    if (Number.isNaN(parsed.getTime())) {
      continue;
    }
    const key = dateKey(startOfDay(parsed));
    if (!counts.has(key)) {
      continue;
    }
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  const history = [...counts.entries()].map(([date, count]) => ({ date, count }));
  const points = history.slice(-period);
  if (points.length === 0) {
    return { status: "empty", period };
  }
  const previous = history.slice(0, period);
  const total = points.reduce((sum, point) => sum + point.count, 0);
  const previousTotal = previous.reduce((sum, point) => sum + point.count, 0);
  const changePercent = previousTotal === 0 ? null : ((total - previousTotal) / previousTotal) * 100;
  return {
    status: "ready",
    series: {
      period,
      points,
      total,
      average: total / points.length,
      previousTotal,
      changePercent,
    },
  };
}
