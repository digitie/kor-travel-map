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

  it("provider의 legacy dataset_key를 datasets URL 계약으로 변환한다", () => {
    expect(
      hrefFor("provider", "python-kma-api", {
        dataset_key: "kma_vilage_fcst",
        sync_scope: "target_grids",
      }),
    ).toBe(
      "/ops/datasets?provider=python-kma-api&dataset=kma_vilage_fcst&sync_scope=target_grids",
    );
  });

  it("빈 provider 선택값은 URL query에 남기지 않는다", () => {
    expect(
      hrefFor("provider", "python-kma-api", {
        dataset_key: null,
        sync_scope: undefined,
      }),
    ).toBe("/ops/datasets?provider=python-kma-api");
  });

  it("호출부 query가 canonical 엔티티 identity를 덮어쓰지 못한다", () => {
    expect(
      hrefFor("provider", "python-kma-api", {
        provider: "wrong-provider",
        dataset: "wrong-dataset",
        dataset_key: "kma_vilage_fcst",
        sync_scope: "target_grids",
      }),
    ).toBe(
      "/ops/datasets?provider=python-kma-api&dataset=kma_vilage_fcst&sync_scope=target_grids",
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
