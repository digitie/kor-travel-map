import { describe, expect, it } from "vitest";

import { hrefFor } from "@/lib/entity-href";

describe("hrefFor", () => {
  it.each([
    ["importJob", "job/id", "/ops/pipeline?execution=import_job:job%2Fid"],
    [
      "updateRequest",
      "request/id",
      "/ops/pipeline?execution=update_request:request%2Fid",
    ],
    [
      "loadBatch",
      "batch/id",
      "/ops/pipeline?load_batch_id=batch%2Fid",
    ],
    [
      "schedule",
      "daily/job",
      "/ops/pipeline?tab=schedules&schedule=daily%2Fjob",
    ],
  ] as const)(
    "%s 엔티티를 통합 pipeline으로 연결한다",
    (kind, id, expected) => {
      expect(hrefFor(kind, id)).toBe(expected);
    },
  );

  it("provider dataset membership은 canonical triple로만 datasets URL을 만든다", () => {
    expect(
      hrefFor("providerDataset", 101, {
        sync_scope: "target_grids",
        operation_key: "refresh_targeted",
      }),
    ).toBe(
      "/ops/datasets?provider_dataset_id=101&sync_scope=target_grids&operation_key=refresh_targeted",
    );
  });

  it("triple 일부가 없는 provider dataset membership 링크를 만들지 않는다", () => {
    expect(hrefFor("providerDataset", 101)).toBeNull();
    expect(
      hrefFor("providerDataset", 101, { sync_scope: "target_grids" }),
    ).toBeNull();
  });

  it("호출부 query가 canonical 엔티티 identity를 덮어쓰지 못한다", () => {
    expect(
      hrefFor("providerDataset", 101, {
        provider: "wrong-provider",
        dataset: "wrong-dataset",
        sync_scope: "target_grids",
        operation_key: "refresh_targeted",
      }),
    ).toBe(
      "/ops/datasets?provider_dataset_id=101&sync_scope=target_grids&operation_key=refresh_targeted",
    );
    expect(
      hrefFor("loadBatch", "batch-a", {
        kind: "update_request",
        load_batch_id: "wrong-batch",
      }),
    ).toBe("/ops/pipeline?load_batch_id=batch-a");
    expect(
      hrefFor("schedule", "daily-a", {
        tab: "executions",
        schedule: "wrong-schedule",
      }),
    ).toBe("/ops/pipeline?tab=schedules&schedule=daily-a");
  });
});
