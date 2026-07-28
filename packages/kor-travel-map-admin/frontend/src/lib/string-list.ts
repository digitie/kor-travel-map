export function uniqueSorted(values: readonly string[]): string[] {
  const normalized = values.flatMap((value) => {
    const trimmed = value.trim();
    return trimmed ? [trimmed] : [];
  });
  return Array.from(new Set(normalized)).sort((left, right) =>
    left.localeCompare(right),
  );
}
