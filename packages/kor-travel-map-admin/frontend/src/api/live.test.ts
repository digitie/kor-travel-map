import { QueryClient, type QueryKey } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { __testing } from "./live";

function seedQuery(queryClient: QueryClient, queryKey: QueryKey) {
  queryClient.setQueryData(queryKey, { ok: true });
  expect(queryClient.getQueryState(queryKey)?.isInvalidated).toBe(false);
}

describe("ops live invalidation", () => {
  it("import_job 단건 topic을 canonical pipeline/datasets cache에만 반영한다", () => {
    const queryClient = new QueryClient();
    const pipelineDetailKey = [
      "pipeline",
      "execution",
      "import_job",
      "job-1",
      {},
    ];
    const pipelineEventsKey = ["pipeline", "events", "live", {}];
    const datasetsKey = ["ops-datasets"];
    const legacyImportJobKey = ["import-job", "job-1"];

    seedQuery(queryClient, pipelineDetailKey);
    seedQuery(queryClient, pipelineEventsKey);
    seedQuery(queryClient, datasetsKey);
    seedQuery(queryClient, legacyImportJobKey);

    __testing.invalidateLiveTopic(queryClient, "import_job:job-1");

    expect(queryClient.getQueryState(pipelineDetailKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(pipelineEventsKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(datasetsKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(legacyImportJobKey)?.isInvalidated).toBe(
      false,
    );
  });

  it("feature_update_requests topic이 feature 지도/상세/admin 목록을 갱신 대상으로 만든다", () => {
    const queryClient = new QueryClient();
    const featureMapKey = ["features", "viewport", "6/54/24", "", "summary", 500];
    const featureDetailKey = ["feature", "f_1111011100_p_mock"];
    const adminFeaturesKey = ["admin-features", { page_size: 50 }];
    const pipelineOverviewKey = ["pipeline", "overview", 20];
    const pipelineExecutionsKey = ["pipeline", "executions", "live", {}];
    const datasetsKey = ["ops-datasets"];
    const datasetDetailKey = [
      "ops-dataset",
      "python-kma-api",
      "kma_vilage_fcst",
      "target_grids",
    ];

    seedQuery(queryClient, featureMapKey);
    seedQuery(queryClient, featureDetailKey);
    seedQuery(queryClient, adminFeaturesKey);
    seedQuery(queryClient, pipelineOverviewKey);
    seedQuery(queryClient, pipelineExecutionsKey);
    seedQuery(queryClient, datasetsKey);
    seedQuery(queryClient, datasetDetailKey);

    __testing.invalidateLiveTopic(queryClient, "feature_update_requests");

    expect(queryClient.getQueryState(featureMapKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(featureDetailKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(adminFeaturesKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(pipelineOverviewKey)?.isInvalidated).toBe(
      true,
    );
    expect(queryClient.getQueryState(pipelineExecutionsKey)?.isInvalidated).toBe(
      true,
    );
    expect(queryClient.getQueryState(datasetsKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(datasetDetailKey)?.isInvalidated).toBe(true);
  });

  it("feature_update_request 단건 topic도 feature surface를 갱신 대상으로 만든다", () => {
    const queryClient = new QueryClient();
    const featureMapKey = ["features", "viewport", "6/54/24", "", "summary", 500];
    const featureDetailKey = ["feature", "f_1111011100_p_mock"];
    const pipelineDetailKey = [
      "pipeline",
      "execution",
      "update_request",
      "request-1",
      {},
    ];
    const datasetDetailKey = [
      "ops-dataset",
      "python-kma-api",
      "kma_vilage_fcst",
      "target_grids",
    ];

    seedQuery(queryClient, featureMapKey);
    seedQuery(queryClient, featureDetailKey);
    seedQuery(queryClient, pipelineDetailKey);
    seedQuery(queryClient, datasetDetailKey);

    __testing.invalidateLiveTopic(
      queryClient,
      "feature_update_request:request-1",
    );

    expect(queryClient.getQueryState(featureMapKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(featureDetailKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(pipelineDetailKey)?.isInvalidated).toBe(
      true,
    );
    expect(queryClient.getQueryState(datasetDetailKey)?.isInvalidated).toBe(true);
  });

  it("Dagster run 단건 topic이 pipeline run 상세·목록과 datasets를 무효화한다", () => {
    const queryClient = new QueryClient();
    const runDetailKey = ["pipeline", "dagster-run", "run-1", {}];
    const runListKey = ["pipeline", "dagster-runs", 20];
    const schedulesKey = ["pipeline", "schedules"];
    const datasetsKey = ["ops-datasets"];

    seedQuery(queryClient, runDetailKey);
    seedQuery(queryClient, runListKey);
    seedQuery(queryClient, schedulesKey);
    seedQuery(queryClient, datasetsKey);

    __testing.invalidateLiveTopic(queryClient, "dagster_run:run-1");

    expect(queryClient.getQueryState(runDetailKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(runListKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(schedulesKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(datasetsKey)?.isInvalidated).toBe(true);
  });
});
