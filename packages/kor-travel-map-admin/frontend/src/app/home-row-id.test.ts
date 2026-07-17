import { describe, expect, it } from "vitest";

import { canonicalPipelineRootRowId } from "./home-row-id";

describe("canonicalPipelineRootRowId", () => {
  it("같은 UUID의 import job과 update request를 서로 다른 행으로 식별한다", () => {
    const id = "11111111-1111-4111-8111-111111111111";
    const rowIds = [
      canonicalPipelineRootRowId({ kind: "import_job", id }),
      canonicalPipelineRootRowId({ kind: "update_request", id }),
    ];

    expect(rowIds).toEqual([`import_job:${id}`, `update_request:${id}`]);
    expect(new Set(rowIds).size).toBe(2);
  });
});
