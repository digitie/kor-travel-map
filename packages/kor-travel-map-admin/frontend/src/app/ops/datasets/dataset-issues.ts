import type { OpsDatasetGridRow } from "@/api/datasets";

export type OpsDatasetIssueRow = Pick<
  OpsDatasetGridRow,
  "provider_dataset_id" | "dataset_issues"
>;

/** 행에 표시되는 provider dataset open issue 수다. */
export function datasetRowOpenIssueCount(row: OpsDatasetIssueRow): number {
  return row.dataset_issues.open_count;
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
 * 같은 provider dataset의 issue projection은 scope마다 반복되므로
 * provider_dataset_id 단위로 한 번만 합산한다.
 */
export function datasetGridOpenIssueCount(
  rows: readonly OpsDatasetIssueRow[],
): number {
  const countsByProviderDatasetId = new Map<number, number>();

  for (const row of rows) {
    countsByProviderDatasetId.set(
      row.provider_dataset_id,
      Math.max(
        countsByProviderDatasetId.get(row.provider_dataset_id) ?? 0,
        row.dataset_issues.open_count,
      ),
    );
  }

  return [...countsByProviderDatasetId.values()].reduce(
    (total, count) => total + count,
    0,
  );
}
