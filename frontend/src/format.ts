export const num = (v: number | null | undefined) =>
  v == null
    ? "—"
    : new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 }).format(v);
export const date = (v: string) =>
  new Date(v).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

export function convertTime(value: number, from: string, to: string) {
  const factors: Record<string, number> = { minutes: 1, hours: 60, days: 1440 };
  return factors[from] && factors[to]
    ? (value * factors[from]) / factors[to]
    : value;
}
