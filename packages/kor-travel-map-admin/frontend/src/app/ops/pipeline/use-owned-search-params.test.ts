import { describe, expect, it } from "vitest";

import {
  type OwnedQueryState,
  reconcileCommittedQuery,
  recordOwnedWrite,
} from "./use-owned-search-params";

const start: OwnedQueryState = { committed: "", query: "", writes: [] };

function writeAll(...queries: string[]): OwnedQueryState {
  return queries.reduce(recordOwnedWrite, start);
}

describe("reconcileCommittedQuery", () => {
  it("우리 쓰기는 commit 전에도 화면 query다", () => {
    const state = writeAll(
      "status=running",
      "status=running&provider_dataset_id=101",
    );
    expect(state.query).toBe("status=running&provider_dataset_id=101");
  });

  it("앞선 쓰기의 늦은 commit은 화면 query를 되돌리지 않는다", () => {
    const written = writeAll(
      "status=running",
      "status=running&provider_dataset_id=101",
      "status=running&provider_dataset_id=101&sync_scope=target_grids",
    );
    let state = reconcileCommittedQuery(written, "status=running");
    expect(state.query).toBe(written.query);
    state = reconcileCommittedQuery(
      state,
      "status=running&provider_dataset_id=101",
    );
    expect(state.query).toBe(written.query);
    // 이미 반영된 앞 쓰기로 다시 돌아가는 commit(순서 뒤바뀜)도 무시한다.
    state = reconcileCommittedQuery(state, "status=running");
    expect(state.query).toBe(written.query);
    expect(state.writes).toHaveLength(3);
  });

  it("마지막 쓰기가 commit되면 대기 목록을 비운다", () => {
    const written = writeAll("a=1", "a=2");
    const state = reconcileCommittedQuery(written, "a=2");
    expect(state).toEqual({ committed: "a=2", query: "a=2", writes: [] });
  });

  it("우리가 쓴 적 없는 commit은 외부 이동으로 받아들인다", () => {
    const written = writeAll("a=1", "a=2");
    const state = reconcileCommittedQuery(written, "tab=events");
    expect(state).toEqual({
      committed: "tab=events",
      query: "tab=events",
      writes: [],
    });
  });

  it("같은 commit은 상태를 그대로 돌려준다(렌더 중 setState 반복 방지)", () => {
    const state = writeAll("a=1");
    expect(reconcileCommittedQuery(state, "")).toBe(state);
  });
});
