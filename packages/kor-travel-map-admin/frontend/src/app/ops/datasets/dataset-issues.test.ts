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
  datasetKey = "dataset",
  provider = "provider",
  providerIssue = 0,
}: {
  dataset?: number;
  datasetKey?: string;
  provider?: string;
  providerIssue?: number;
} = {}): OpsDatasetIssueRow {
  return {
    provider,
    dataset_key: datasetKey,
    dataset_issues: { open_count: dataset, severity_counts: {} },
    provider_issues: { open_count: providerIssue, severity_counts: {} },
  };
}

describe("ops datasets open issue projection", () => {
  it.each([
    {
      label: "provider-only",
      row: issueRow({ providerIssue: 1 }),
      hasIssue: true,
      count: 1,
    },
    {
      label: "dataset-only",
      row: issueRow({ dataset: 2 }),
      hasIssue: true,
      count: 2,
    },
    {
      label: "both",
      row: issueRow({ dataset: 2, providerIssue: 3 }),
      hasIssue: true,
      count: 5,
    },
    { label: "neither", row: issueRow(), hasIssue: false, count: 0 },
  ])("$label 행은 dataset 또는 provider open issue를 반영한다", ({
    row,
    hasIssue,
    count,
  }) => {
    expect(datasetRowHasOpenIssue(row)).toBe(hasIssue);
    expect(datasetRowOpenIssueCount(row)).toBe(count);
  });

  it("scope 반복 행은 dataset/provider 귀속 단위로 한 번만 합산한다", () => {
    expect(
      datasetGridOpenIssueCount([
        issueRow({ dataset: 2, providerIssue: 3 }),
        issueRow({ dataset: 2, providerIssue: 3 }),
        issueRow({ dataset: 4, datasetKey: "other", providerIssue: 3 }),
        issueRow({ dataset: 1, provider: "other-provider", providerIssue: 2 }),
      ]),
    ).toBe(12);
  });

  it("severity 요약은 0건을 빼고 괄호를 닫는다", () => {
    expect(
      datasetIssueSeveritySummary({ critical: 1, info: 0, warning: 2 }),
    ).toBe(" (critical 1 · warning 2)");
    expect(datasetIssueSeveritySummary({ info: 0 })).toBe("");
  });
});
