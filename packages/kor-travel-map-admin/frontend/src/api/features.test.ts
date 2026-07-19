import { afterEach, describe, expect, it, vi } from "vitest";

import {
  adminFeaturesInBoundsPath,
  buildFeatureTiles,
  deleteAdminFeature,
  fetchAdminFeatureCorrectionBasis,
  featureSearchPath,
  featureViewportQueryKey,
  patchAdminFeature,
  type FeaturesInBboxParams,
} from "./features";

function jsonResponse(
  body: unknown,
  options: { entityTag?: string; status?: number } = {},
): Response {
  return new Response(JSON.stringify(body), {
    status: options.status ?? 200,
    headers: {
      "Content-Type": "application/json",
      ...(options.entityTag ? { ETag: options.entityTag } : {}),
    },
  });
}

function revisionResponse(rowRevision: number, entityTag: string): Response {
  return jsonResponse(
    { data: { feature_id: "feature-1", row_revision: rowRevision } },
    { entityTag },
  );
}

function detailResponse(rowRevision: number): Response {
  return jsonResponse({
    data: {
      feature: { feature_id: "feature-1", row_revision: rowRevision },
    },
    meta: {},
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

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
        zoom: 14,
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
      { ...params({ zoom: 7 }), zoom: 7, statuses: ["draft"] },
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

describe("feature search request contract", () => {
  it("COUNT opt-in 기본값을 false로 보내고 opaque cursor를 그대로 인코딩한다", () => {
    const path = featureSearchPath({
      q: "경복궁",
      kind: ["place", "event"],
      page_size: 25,
      cursor: "payload.signature",
    });
    const url = new URL(path, "http://localhost");

    expect(url.pathname).toBe("/v1/features/search");
    expect(url.searchParams.get("include_total")).toBe("false");
    expect(url.searchParams.getAll("kind")).toEqual(["place", "event"]);
    expect(url.searchParams.get("cursor")).toBe("payload.signature");
  });

  it("total이 필요한 화면만 include_total=true를 명시한다", () => {
    const path = featureSearchPath({
      min_lon: 126,
      min_lat: 37,
      max_lon: 128,
      max_lat: 38,
      include_total: true,
    });
    expect(new URL(path, "http://localhost").searchParams.get("include_total"))
      .toBe("true");
  });
});

describe("admin feature correction basis", () => {
  it("revision과 detail이 같은 시점일 때 raw ETag를 그대로 고정한다", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(revisionResponse(7, '"7"'))
      .mockResolvedValueOnce(detailResponse(7));
    vi.stubGlobal("fetch", fetchMock);

    const basis = await fetchAdminFeatureCorrectionBasis("feature-1");

    expect(basis).toMatchObject({
      entityTag: '"7"',
      featureId: "feature-1",
      rowRevision: 7,
    });
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toEqual([
      "/api/proxy/v1/admin/features/feature-1/revision",
      "/api/proxy/v1/admin/features/feature-1",
    ]);
  });

  it("revision과 detail 사이 경쟁 갱신은 제한 재조회 후 일치하는 basis만 반환한다", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(revisionResponse(7, '"7"'))
      .mockResolvedValueOnce(detailResponse(8))
      .mockResolvedValueOnce(revisionResponse(8, '"8"'))
      .mockResolvedValueOnce(detailResponse(8));
    vi.stubGlobal("fetch", fetchMock);

    const basis = await fetchAdminFeatureCorrectionBasis("feature-1");

    expect(basis.entityTag).toBe('"8"');
    expect(basis.rowRevision).toBe(8);
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it("revision과 detail이 계속 다르면 세 번만 읽고 쓰기 basis를 만들지 않는다", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(revisionResponse(1, '"1"'))
      .mockResolvedValueOnce(detailResponse(2))
      .mockResolvedValueOnce(revisionResponse(2, '"2"'))
      .mockResolvedValueOnce(detailResponse(3))
      .mockResolvedValueOnce(revisionResponse(3, '"3"'))
      .mockResolvedValueOnce(detailResponse(4));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      fetchAdminFeatureCorrectionBasis("feature-1"),
    ).rejects.toThrow("3회 연속 일치하지 않았습니다");
    expect(fetchMock).toHaveBeenCalledTimes(6);
  });

  it("PATCH와 DELETE는 caller basis만 보내고 mutation 직전 revision을 다시 읽지 않는다", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockImplementation(async () =>
        jsonResponse({ data: { request: { feature_id: "feature-1" } }, meta: {} }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await patchAdminFeature("feature-1", '"4"', {
      reason: "edit",
    });
    await deleteAdminFeature("feature-1", '"5"', {
      reason: "delete",
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toEqual([
      "/api/proxy/v1/admin/features/feature-1",
      "/api/proxy/v1/admin/features/feature-1",
    ]);
    expect(fetchMock.mock.calls.map(([, init]) => init?.method)).toEqual([
      "PATCH",
      "DELETE",
    ]);
    expect(fetchMock.mock.calls.map(([, init]) => init?.headers)).toEqual([
      expect.objectContaining({ "If-Match": '"4"' }),
      expect.objectContaining({ "If-Match": '"5"' }),
    ]);
  });
});
