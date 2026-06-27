import { QueryClient, type QueryKey } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { __testing } from "./live";

function seedQuery(queryClient: QueryClient, queryKey: QueryKey) {
  queryClient.setQueryData(queryKey, { ok: true });
  expect(queryClient.getQueryState(queryKey)?.isInvalidated).toBe(false);
}

describe("ops live invalidation", () => {
  it("feature_update_requests topic이 feature 지도/상세/admin 목록을 갱신 대상으로 만든다", () => {
    const queryClient = new QueryClient();
    const featureMapKey = ["features", "viewport", "6/54/24", "", "summary", 500];
    const featureDetailKey = ["feature", "f_1111011100_p_mock"];
    const adminFeaturesKey = ["admin-features", { page_size: 50 }];

    seedQuery(queryClient, featureMapKey);
    seedQuery(queryClient, featureDetailKey);
    seedQuery(queryClient, adminFeaturesKey);

    __testing.invalidateLiveTopic(queryClient, "feature_update_requests");

    expect(queryClient.getQueryState(featureMapKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(featureDetailKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(adminFeaturesKey)?.isInvalidated).toBe(true);
  });

  it("feature_update_request 단건 topic도 feature surface를 갱신 대상으로 만든다", () => {
    const queryClient = new QueryClient();
    const featureMapKey = ["features", "viewport", "6/54/24", "", "summary", 500];
    const featureDetailKey = ["feature", "f_1111011100_p_mock"];

    seedQuery(queryClient, featureMapKey);
    seedQuery(queryClient, featureDetailKey);

    __testing.invalidateLiveTopic(
      queryClient,
      "feature_update_request:request-1",
    );

    expect(queryClient.getQueryState(featureMapKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(featureDetailKey)?.isInvalidated).toBe(true);
  });
});
