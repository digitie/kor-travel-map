import { afterEach, describe, expect, it, vi } from "vitest";

import {
  fetchAllPublicCurationCollections,
  fetchAllPublicCurationGroups,
  filterPublicCurationGroupsToViewport,
  stabilizePublicCurationGroupsParams,
  type PublicCurationGroup,
  type PublicCurationItem,
  type PublicCurationGroupsResponse,
} from "./public-curations";

type FetchMock = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

function page(items: unknown[], nextCursor: string | null): Response {
  return new Response(
    JSON.stringify({
      data: { items },
      meta: { page: { page_size: 2, next_cursor: nextCursor } },
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

function group(
  featureId: string,
  itemIds: string[],
  { lon = 127, lat = 37 }: { lon?: number | null; lat?: number | null } = {},
): PublicCurationGroup {
  return {
    feature: {
      feature_id: featureId,
      name: featureId,
      kind: "place",
      category: "attraction",
      lon,
      lat,
      address: {},
      status: "active",
    },
    curations: itemIds.map((curationItemId): PublicCurationItem => ({
      address: {},
      address_hint: null,
      archived_at: null,
      collection_id: "collection-id",
      collection_key: "collection-key",
      created_at: "2026-07-13T00:00:00Z",
      curation_item_id: curationItemId,
      curation_relation: "primary_stop",
      dataset_key: "dataset-key",
      edition_key: "2025-2026",
      external_component_id: "primary",
      external_item_id: curationItemId,
      feature_category: "attraction",
      feature_id: featureId,
      feature_kind: "place",
      feature_name: featureId,
      item_summary: null,
      item_title: null,
      lat,
      lon,
      place_name: featureId,
      provider: "provider",
      reuse_policy: "allowed",
      sort_order: 0,
      source_name: "source",
      source_url: null,
      status: "included",
      theme_group: "official",
      theme_name: "theme",
      theme_slug: "theme",
      title: "title",
      updated_at: "2026-07-13T00:00:00Z",
    })),
    curation_count: itemIds.length,
  };
}

describe("public curation cursor accumulation", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("bbox와 필터를 유지하며 마지막 cursor까지 누적하고 Feature 중복을 병합한다", async () => {
    const fetchMock = vi
      .fn<FetchMock>()
      .mockResolvedValueOnce(page([group("feature-a", ["item-2023"])], "next+cursor"))
      .mockResolvedValueOnce(
        page(
          [
            group("feature-a", ["item-2025"]),
            group("feature-b", ["item-heritage"]),
          ],
          null,
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchAllPublicCurationGroups({
      theme_slug: "korea-tourism-100",
      edition_key: "2025-2026",
      provider: "mcst",
      q: "궁",
      min_lon: 126,
      min_lat: 36,
      max_lon: 128,
      max_lat: 38,
      page_size: 2,
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const firstUrl = String(fetchMock.mock.calls[0]?.[0]);
    const secondUrl = String(fetchMock.mock.calls[1]?.[0]);
    expect(firstUrl).toContain("/api/proxy/v1/curations?");
    expect(firstUrl).toContain("theme_slug=korea-tourism-100");
    expect(firstUrl).toContain("edition_key=2025-2026");
    expect(firstUrl).toContain("provider=mcst");
    expect(firstUrl).toContain("min_lon=126");
    expect(firstUrl).not.toContain("distinct_by_feature");
    expect(secondUrl).toContain("cursor=next%2Bcursor");
    expect(result.pages_loaded).toBe(2);
    expect(result.data.items).toHaveLength(2);
    expect(result.data.items[0]?.curations.map((item) => item.curation_item_id)).toEqual([
      "item-2023",
      "item-2025",
    ]);
    expect(result.data.items[0]?.curation_count).toBe(2);
    expect(result.meta.page?.next_cursor).toBeNull();
  });

  it("서버가 같은 cursor를 반복하면 무한 루프 대신 오류로 중단한다", async () => {
    const fetchMock = vi
      .fn<FetchMock>()
      .mockResolvedValueOnce(page([], "same"))
      .mockResolvedValueOnce(page([], "same"));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchAllPublicCurationGroups({ page_size: 2 })).rejects.toThrow(
      "같은 cursor",
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("공개 컬렉션도 500개 상한에서 자르지 않고 cursor를 끝까지 읽는다", async () => {
    const fetchMock = vi
      .fn<FetchMock>()
      .mockResolvedValueOnce(page([{ collection_id: "collection-a" }], "collections-2"))
      .mockResolvedValueOnce(page([{ collection_id: "collection-b" }], null));
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchAllPublicCurationCollections();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(String(fetchMock.mock.calls[1]?.[0])).toContain("cursor=collections-2");
    expect(result.data.items.map((item) => item.collection_id)).toEqual([
      "collection-a",
      "collection-b",
    ]);
  });
});

describe("public curation map bbox cache", () => {
  const base = {
    edition_key: "2025-2026",
    max_lat: 37.59,
    max_lon: 127.05,
    min_lat: 37.53,
    min_lon: 126.95,
    page_size: 500,
    theme_slug: "korea-tourism-100",
  };

  it("작은 pan은 동일한 padded bbox params를 사용한다", () => {
    const shifted = {
      ...base,
      max_lat: base.max_lat + 0.001,
      max_lon: base.max_lon + 0.002,
      min_lat: base.min_lat + 0.001,
      min_lon: base.min_lon + 0.002,
    };
    const stableBase = stabilizePublicCurationGroupsParams(base);
    const stableShifted = stabilizePublicCurationGroupsParams(shifted);

    expect(stableShifted).toEqual(stableBase);
    expect(stableBase.min_lon).toBeLessThanOrEqual(shifted.min_lon);
    expect(stableBase.min_lat).toBeLessThanOrEqual(shifted.min_lat);
    expect(stableBase.max_lon).toBeGreaterThanOrEqual(shifted.max_lon);
    expect(stableBase.max_lat).toBeGreaterThanOrEqual(shifted.max_lat);
  });

  it("동일 padded fetch를 재사용해도 각 viewport 결과와 total은 따로 자른다", () => {
    const shifted = {
      ...base,
      max_lat: base.max_lat + 0.001,
      max_lon: base.max_lon + 0.002,
      min_lat: base.min_lat + 0.001,
      min_lon: base.min_lon + 0.002,
    };
    expect(stabilizePublicCurationGroupsParams(shifted)).toEqual(
      stabilizePublicCurationGroupsParams(base),
    );
    const cached: PublicCurationGroupsResponse = {
      data: {
        items: [
          group("base-only", [], { lon: 126.951, lat: 37.55 }),
          group("both", [], { lon: 127, lat: 37.56 }),
          group("shifted-only", [], { lon: 127.051, lat: 37.57 }),
        ],
      },
      meta: {
        page: { next_cursor: null, page_size: 500, total: 3 },
      },
      pages_loaded: 1,
    };

    const baseResult = filterPublicCurationGroupsToViewport(cached, base);
    const shiftedResult = filterPublicCurationGroupsToViewport(cached, shifted);

    expect(baseResult.data.items.map((item) => item.feature.feature_id)).toEqual([
      "base-only",
      "both",
    ]);
    expect(shiftedResult.data.items.map((item) => item.feature.feature_id)).toEqual([
      "both",
      "shifted-only",
    ]);
    expect(baseResult.meta.page?.total).toBe(2);
    expect(shiftedResult.meta.page?.total).toBe(2);
    expect(cached.meta.page?.total).toBe(3);
  });

  it("viewport 경계 좌표는 포함하고 화면 밖 또는 좌표 없는 그룹은 제외한다", () => {
    const cached: PublicCurationGroupsResponse = {
      data: {
        items: [
          group("south-west-boundary", [], {
            lon: base.min_lon,
            lat: base.min_lat,
          }),
          group("north-east-boundary", [], {
            lon: base.max_lon,
            lat: base.max_lat,
          }),
          group("outside", [], { lon: base.max_lon + 0.000001, lat: 37.56 }),
          group("missing-coordinate", [], { lon: null, lat: null }),
        ],
      },
      meta: { page: { next_cursor: null, page_size: 500, total: 4 } },
      pages_loaded: 1,
    };

    const result = filterPublicCurationGroupsToViewport(cached, base);

    expect(result.data.items.map((item) => item.feature.feature_id)).toEqual([
      "south-west-boundary",
      "north-east-boundary",
    ]);
    expect(result.meta.page?.total).toBe(2);
  });

  it("padding 밖의 pan은 새 bbox params로 분리한다", () => {
    const shifted = {
      ...base,
      max_lon: base.max_lon + 0.04,
      min_lon: base.min_lon + 0.04,
    };

    expect(stabilizePublicCurationGroupsParams(shifted)).not.toEqual(
      stabilizePublicCurationGroupsParams(base),
    );
  });

  it("bbox가 없으면 필터 params를 그대로 보존한다", () => {
    const filters = { q: "궁", page_size: 500, provider: "mcst" };

    expect(stabilizePublicCurationGroupsParams(filters)).toBe(filters);
  });
});
