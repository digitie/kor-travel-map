import { afterEach, describe, expect, it, vi } from "vitest";

import {
  fetchAllPublicCurationCollections,
  fetchAllPublicCurationGroups,
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

function group(featureId: string, itemIds: string[]) {
  return {
    feature: {
      feature_id: featureId,
      name: featureId,
      kind: "place",
      category: "attraction",
      lon: 127,
      lat: 37,
      address: {},
      status: "active",
    },
    curations: itemIds.map((curationItemId) => ({
      curation_item_id: curationItemId,
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
