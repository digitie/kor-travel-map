import { describe, expect, it } from "vitest";

import {
  canonicalFeatureUpdateIdempotencyBody,
  featureUpdateCreationStatus,
  featureUpdateIdempotencyOperationKey,
} from "./feature-update-idempotency";

describe("feature update idempotency", () => {
  it.each([
    [
      {
        providers: ["tourapi", "kma"],
        dataset_keys: ["spots", "forecast"],
        scope: {
          type: "feature_ids",
          feature_ids: ["feature-b", "feature-a"],
        },
      },
      {
        providers: ["kma", "tourapi"],
        dataset_keys: ["forecast", "spots"],
        scope: {
          type: "feature_ids",
          feature_ids: ["feature-a", "feature-b"],
        },
      },
    ],
    [
      {
        providers: ["tourapi", "kma"],
        dataset_keys: ["spots", "forecast"],
        scope: {
          type: "cache_target_keys",
          target_keys: ["target-b", "target-a"],
        },
      },
      {
        providers: ["kma", "tourapi"],
        dataset_keys: ["forecast", "spots"],
        scope: {
          type: "cache_target_keys",
          target_keys: ["target-a", "target-b"],
        },
      },
    ],
  ])("set 의미 배열 순서가 달라도 같은 operation key다", async (left, right) => {
    await expect(
      featureUpdateIdempotencyOperationKey("feature-update:create", left),
    ).resolves.toBe(
      await featureUpdateIdempotencyOperationKey("feature-update:create", right),
    );
  });

  it("정규화 중 원본 body를 변경하지 않는다", () => {
    const body = {
      providers: ["z", "a"],
      dataset_keys: ["b", "a"],
      scope: { type: "feature_ids", feature_ids: ["f2", "f1"] },
    };

    const canonical = canonicalFeatureUpdateIdempotencyBody(body);

    expect(body).toEqual({
      providers: ["z", "a"],
      dataset_keys: ["b", "a"],
      scope: { type: "feature_ids", feature_ids: ["f2", "f1"] },
    });
    expect(canonical).toEqual({
      providers: ["a", "z"],
      dataset_keys: ["a", "b"],
      scope: { type: "feature_ids", feature_ids: ["f1", "f2"] },
    });
  });

  it("create 결과는 replay, active reuse, 신규 순서로 분기한다", () => {
    expect(
      featureUpdateCreationStatus({
        idempotent_replay: true,
        reused_active_request: true,
      }),
    ).toBe("동일 요청 결과 재생");
    expect(
      featureUpdateCreationStatus({
        idempotent_replay: false,
        reused_active_request: true,
      }),
    ).toBe("기존 활성 요청 재사용");
    expect(
      featureUpdateCreationStatus({
        idempotent_replay: false,
        reused_active_request: false,
      }),
    ).toBe("새 요청 생성");
  });
});
