const dateTimeFormatter = new Intl.DateTimeFormat("ko-KR", {
  dateStyle: "short",
  timeStyle: "medium",
});

const compactNumberFormatter = new Intl.NumberFormat("ko-KR");

export function formatDateTime(value: string | number | null | undefined): string {
  if (value === null || value === undefined) {
    return "-";
  }
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "-";
  }
  return dateTimeFormatter.format(date);
}

export function formatCount(value: number | null | undefined): string {
  return compactNumberFormatter.format(value ?? 0);
}

export function shortId(value: string | null | undefined, size = 12): string {
  if (!value) {
    return "-";
  }
  return value.length > size ? `${value.slice(0, size)}...` : value;
}
