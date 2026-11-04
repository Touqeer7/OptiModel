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
