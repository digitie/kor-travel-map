import { describe, expect, it } from "vitest";

import {
  datasetGridOpenIssueCount,
  datasetIssueSeveritySummary,
  datasetRowHasOpenIssue,
  datasetRowOpenIssueCount,
  type OpsDatasetIssueRow,
} from "./dataset-issues";

function issueRow({
  dataset = 0,
  providerDatasetId = 1,
}: {
  dataset?: number;
  providerDatasetId?: number;
} = {}): OpsDatasetIssueRow {
  return {
    provider_dataset_id: providerDatasetId,
    dataset_issues: { open_count: dataset, severity_counts: {} },
  };
}

describe("ops datasets open issue projection", () => {
  it.each([
    {
      label: "open",
      row: issueRow({ dataset: 2 }),
      hasIssue: true,
      count: 2,
    },
    { label: "neither", row: issueRow(), hasIssue: false, count: 0 },
  ])("$label 행은 provider dataset open issue를 반영한다", ({
    row,
    hasIssue,
    count,
  }) => {
    expect(datasetRowHasOpenIssue(row)).toBe(hasIssue);
    expect(datasetRowOpenIssueCount(row)).toBe(count);
  });

  it("scope 반복 행은 provider_dataset_id 단위로 한 번만 합산한다", () => {
    expect(
      datasetGridOpenIssueCount([
        issueRow({ providerDatasetId: 11, dataset: 2 }),
        issueRow({ providerDatasetId: 11, dataset: 3 }),
        issueRow({ providerDatasetId: 12, dataset: 4 }),
        issueRow({ providerDatasetId: 13, dataset: 1 }),
      ]),
    ).toBe(8);
  });

  it("severity 요약은 0건을 빼고 괄호를 닫는다", () => {
    expect(
      datasetIssueSeveritySummary({ critical: 1, info: 0, warning: 2 }),
    ).toBe(" (critical 1 · warning 2)");
    expect(datasetIssueSeveritySummary({ info: 0 })).toBe("");
  });
});
