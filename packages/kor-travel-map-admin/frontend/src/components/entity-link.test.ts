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

  it("sync_scope가 없으면 provider dataset 링크를 만들지 않는다", () => {
    expect(hrefFor("providerDataset", 101)).toBeNull();
  });

  it("operation_key가 없으면 그 축을 빼고 링크를 만든다", () => {
    // 앞 판은 이것도 null이었다. 그러면 **refresh membership이 없는 catalog 전용
    // dataset**(`operation_key`가 빈 값)이 어떤 entity 링크로도 도달할 수 없었다 —
    // 축이 하나 덜 적힌 것을 "틀린 링크"로 다뤘기 때문이다. 대상 페이지는 (id, scope)로 유일하게 결정하고, 형제 operation
    // 때문에 둘 이상이면 그쪽이 명시 거부한다.
    expect(hrefFor("providerDataset", 101, { sync_scope: "target_grids" })).toBe(
      "/ops/datasets?provider_dataset_id=101&sync_scope=target_grids",
    );
    expect(
      hrefFor("providerDataset", 101, {
        sync_scope: "target_grids",
        operation_key: "",
      }),
    ).toBe("/ops/datasets?provider_dataset_id=101&sync_scope=target_grids");
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
