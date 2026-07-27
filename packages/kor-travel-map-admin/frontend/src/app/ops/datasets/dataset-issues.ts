import type { OpsDatasetGridRow } from "@/api/datasets";

export type OpsDatasetIssueRow = Pick<
  OpsDatasetGridRow,
  "provider" | "dataset_key" | "dataset_issues" | "provider_issues"
>;

/** 행에 표시되는 dataset/provider open issue의 합계. */
export function datasetRowOpenIssueCount(row: OpsDatasetIssueRow): number {
  return row.dataset_issues.open_count + row.provider_issues.open_count;
}

export function datasetRowHasOpenIssue(row: OpsDatasetIssueRow): boolean {
  return datasetRowOpenIssueCount(row) > 0;
}

/** 0보다 큰 severity별 건수를 사람이 읽는 괄호 묶음으로 표시한다. */
export function datasetIssueSeveritySummary(
  counts: Readonly<Record<string, number>>,
): string {
  const parts: string[] = [];
  for (const [severity, count] of Object.entries(counts)) {
    if (count > 0) parts.push(`${severity} ${count}`);
  }
  return parts.length > 0 ? ` (${parts.join(" · ")})` : "";
}

/**
 * 그리드 요약용 open issue 합계.
 *
 * dataset issue는 scope마다, provider issue는 provider의 모든 dataset/scope 행마다
 * 반복되므로 각각 provider+dataset, provider 단위로 한 번만 합산한다.
 */
export function datasetGridOpenIssueCount(
  rows: readonly OpsDatasetIssueRow[],
): number {
  const datasetCountsByProvider = new Map<string, Map<string, number>>();
  const providerCounts = new Map<string, number>();

  for (const row of rows) {
    const datasetCounts = datasetCountsByProvider.get(row.provider) ?? new Map();
    datasetCounts.set(
      row.dataset_key,
      Math.max(
        datasetCounts.get(row.dataset_key) ?? 0,
        row.dataset_issues.open_count,
      ),
    );
    datasetCountsByProvider.set(row.provider, datasetCounts);
    providerCounts.set(
      row.provider,
      Math.max(
        providerCounts.get(row.provider) ?? 0,
        row.provider_issues.open_count,
      ),
    );
  }

  const datasetTotal = [...datasetCountsByProvider.values()].reduce(
    (total, counts) =>
      total + [...counts.values()].reduce((sum, count) => sum + count, 0),
    0,
  );
  const providerTotal = [...providerCounts.values()].reduce(
    (total, count) => total + count,
    0,
  );
  return datasetTotal + providerTotal;
}
