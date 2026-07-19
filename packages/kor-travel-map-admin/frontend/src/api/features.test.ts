import { describe, expect, it } from "vitest";

import {
  adminFeaturesInBoundsPath,
  buildFeatureTiles,
  featureViewportQueryKey,
  type FeaturesInBboxParams,
} from "./features";

function params(overrides: Partial<FeaturesInBboxParams> = {}): FeaturesInBboxParams {
  return {
    min_lon: 126.97,
    min_lat: 37.55,
    max_lon: 127.01,
    max_lat: 37.575,
    page_size: 500,
    zoom: 14,
    ...overrides,
  };
}

describe("feature map tile selection", () => {
  it("admin viewport는 status 반복 필터와 admin 경로를 사용한다", () => {
    const path = adminFeaturesInBoundsPath(
      {
        ...params(),
        statuses: ["inactive", "hidden"],
        includeGeometry: true,
      },
      { clustered: false },
    );

    expect(path).toContain("/v1/admin/features/in-bounds?");
    expect(path).toContain("status=inactive");
    expect(path).toContain("status=hidden");
    expect(path).toContain("include_geometry=true");
    expect(path).not.toContain("zoom=");
  });

  it("admin cluster viewport는 zoom을 보내고 geometry payload는 요청하지 않는다", () => {
    const path = adminFeaturesInBoundsPath(
      { ...params({ zoom: 7 }), statuses: ["draft"] },
      { clustered: true },
    );

    expect(path).toContain("status=draft");
    expect(path).toContain("zoom=7");
    expect(path).not.toContain("include_geometry");
  });

  it("고zoom viewport를 최대 8개의 z13~z15 tile로 제한한다", () => {
    for (const zoom of [14, 15, 16]) {
      const scale = 2 ** (14 - zoom);
      const tiles = buildFeatureTiles(
        params({
          max_lon: 126.99 + 0.02 * scale,
          max_lat: 37.5625 + 0.0125 * scale,
          min_lon: 126.99 - 0.02 * scale,
          min_lat: 37.5625 - 0.0125 * scale,
          zoom,
        }),
      );

      expect(tiles.length).toBeGreaterThan(0);
      expect(tiles.length).toBeLessThanOrEqual(8);
      expect(tiles.every((tile) => tile.z >= 13 && tile.z <= 15)).toBe(true);
    }
  });

  it("z16의 작은 viewport는 z12 cap 대신 z15 tile을 사용한다", () => {
    const tiles = buildFeatureTiles(
      params({
        min_lon: 126.981,
        min_lat: 37.563,
        max_lon: 126.986,
        max_lat: 37.568,
        zoom: 16,
      }),
    );

    expect(tiles.length).toBeGreaterThan(0);
    expect(tiles.length).toBeLessThanOrEqual(8);
    expect(new Set(tiles.map((tile) => tile.z))).toEqual(new Set([15]));
  });

  it("같은 tile 집합이면 viewport 실수값이 달라도 outer query key를 재사용한다", () => {
    const first = params({
      min_lon: 126.981,
      min_lat: 37.563,
      max_lon: 126.986,
      max_lat: 37.568,
      zoom: 16,
    });
    const second = {
      ...first,
      min_lon: first.min_lon + 0.0001,
      min_lat: first.min_lat + 0.0001,
      max_lon: first.max_lon + 0.0001,
      max_lat: first.max_lat + 0.0001,
    };
    const firstTiles = buildFeatureTiles(first);
    const secondTiles = buildFeatureTiles(second);

    expect(secondTiles.map((tile) => tile.key)).toEqual(
      firstTiles.map((tile) => tile.key),
    );
    expect(featureViewportQueryKey(second, secondTiles)).toEqual(
      featureViewportQueryKey(first, firstTiles),
    );
    expect(featureViewportQueryKey(first, firstTiles)[2]).toBe("");
  });

  it("single-bbox fallback은 실제 viewport 서명으로 서로 구분한다", () => {
    const first = params();
    const second = { ...first, min_lon: first.min_lon + 0.02 };

    expect(featureViewportQueryKey(second, [])[2]).not.toBe(
      featureViewportQueryKey(first, [])[2],
    );
  });
});
