import { afterEach, describe, expect, it, vi } from "vitest";

import { DomainIdempotencySubmissionMismatchError } from "./client";
import {
  adminFeaturesInBboxQueryKey,
  adminFeatureRequestZoom,
  adminFeaturesInBoundsPath,
  deleteAdminFeature,
  allowedPublicationStates,
  fetchAdminFeatureCorrectionBasis,
  isAdminFeatureClusterZoom,
  patchAdminFeature,
  type AdminFeaturesInBoundsParams,
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

function revisionResponse(
  rowRevision: number,
  entityTag: string,
  featureId = "feature-1",
): Response {
  return jsonResponse(
    { data: { feature_id: featureId, row_revision: rowRevision } },
    { entityTag },
  );
}

function detailResponse(
  rowRevision: number,
  featureId = "feature-1",
): Response {
  return jsonResponse({
    data: {
      feature: { feature_id: featureId, row_revision: rowRevision },
    },
    meta: {},
  });
}

function stubRandomUUID(keys: string[]) {
  const subtle = globalThis.crypto.subtle;
  const randomUUID = vi.fn(
    () => keys.shift() ?? "ffffffff-ffff-4fff-8fff-ffffffffffff",
  );
  vi.stubGlobal("crypto", { randomUUID, subtle });
  return randomUUID;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function params(
  overrides: Partial<AdminFeaturesInBoundsParams> = {},
): AdminFeaturesInBoundsParams {
  return {
    min_lon: 126.97,
    min_lat: 37.55,
    max_lon: 127.01,
    max_lat: 37.575,
    zoom: 14,
    ...overrides,
  };
}

describe("feature map tile selection", () => {
  it("admin viewport는 세 상태 축 반복 필터와 admin 경로를 사용한다", () => {
    const path = adminFeaturesInBoundsPath(
      {
        ...params(),
        zoom: 14,
        lifecycleStates: ["retired"],
        publicationStates: ["suppressed"],
        qualityStates: ["quarantined"],
        includeGeometry: true,
      },
      { clustered: false },
    );

    expect(path).toContain("/v1/admin/features/in-bounds?");
    expect(path).toContain("lifecycle_state=retired");
    expect(path).toContain("publication_state=suppressed");
    expect(path).toContain("quality_state=quarantined");
    expect(path).toContain("include_geometry=true");
    // items 모드에서도 zoom을 항상 전송한다(서버는 zoom>=14를 items로 해석 —
    // _resolve_admin_cluster_unit). 소비자가 요청의 zoom 문맥을 관측 가능해야 한다.
    expect(path).toContain("zoom=14");
  });

  it("items query key는 요청과 동일한 정수 zoom·raw bbox를 구분한다", () => {
    const options = { clustered: false };
    const zoom14Params = {
      ...params({ zoom: 14.1 }),
      zoom: 14.1,
    };
    const zoom14 = adminFeaturesInBboxQueryKey(zoom14Params, options);
    const sameIntegerZoom = adminFeaturesInBboxQueryKey(
      { ...zoom14Params, zoom: 14.9 },
      options,
    );
    const zoom15 = adminFeaturesInBboxQueryKey(
      { ...zoom14Params, zoom: 15 },
      options,
    );
    const shiftedBbox = adminFeaturesInBboxQueryKey(
      { ...zoom14Params, min_lon: zoom14Params.min_lon + 0.00001 },
      options,
    );

    expect(zoom14).toEqual(sameIntegerZoom);
    expect(zoom14).not.toEqual(zoom15);
    expect(zoom14).not.toEqual(shiftedBbox);
    expect(zoom14[6]).toBe(14);
  });

  it("query key는 delimiter가 포함된 filter 배열의 HTTP identity를 보존한다", () => {
    const options = { clustered: false };
    const baseParams = { ...params({ zoom: 14 }), zoom: 14 };
    const singleProvider = adminFeaturesInBboxQueryKey(
      { ...baseParams, provider: ["a,b"] },
      options,
    );
    const repeatedProviders = adminFeaturesInBboxQueryKey(
      { ...baseParams, provider: ["a", "b"] },
      options,
    );

    expect(singleProvider).not.toEqual(repeatedProviders);
    expect(singleProvider[8]).toEqual(["a,b"]);
    expect(repeatedProviders[8]).toEqual(["a", "b"]);
  });

  it("13.x zoom도 서버와 동일하게 cluster 모드로 판정한다", () => {
    expect(adminFeatureRequestZoom(13.9)).toBe(13);
    expect(isAdminFeatureClusterZoom(13.9)).toBe(true);
    expect(isAdminFeatureClusterZoom(14)).toBe(false);
  });

  it("admin cluster viewport는 zoom을 보내고 geometry payload는 요청하지 않는다", () => {
    const path = adminFeaturesInBoundsPath(
      {
        ...params({ zoom: 7 }),
        zoom: 7,
        publicationStates: ["draft"],
      },
      { clustered: true },
    );

    expect(path).toContain("publication_state=draft");
    expect(path).toContain("zoom=7");
    expect(path).not.toContain("include_geometry");
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

  it("legacy revision echo와 UUID detail을 하나의 canonical basis로 수렴한다", async () => {
    const featureId = "018f9b5e-5b66-7d0d-b24f-1029384756aa";
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(revisionResponse(7, '"7"', "feature-1"))
      .mockResolvedValueOnce(detailResponse(7, featureId));
    vi.stubGlobal("fetch", fetchMock);

    const basis = await fetchAdminFeatureCorrectionBasis(featureId);

    expect(basis).toMatchObject({
      entityTag: '"7"',
      featureId,
      rowRevision: 7,
    });
  });

  it("legacy 입력도 UUID detail을 canonical write basis로 수렴한다", async () => {
    const canonicalFeatureId = "018f9b5e-5b66-7d0d-b24f-1029384756aa";
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(revisionResponse(7, '"7"', "feature-1"))
      .mockResolvedValueOnce(detailResponse(7, canonicalFeatureId));
    vi.stubGlobal("fetch", fetchMock);

    const basis = await fetchAdminFeatureCorrectionBasis("feature-1");

    expect(basis.featureId).toBe(canonicalFeatureId);
    expect(basis.detail.data.feature.feature_id).toBe(canonicalFeatureId);
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

    await expect(fetchAdminFeatureCorrectionBasis("feature-1")).rejects.toThrow(
      "3회 연속 일치하지 않았습니다",
    );
    expect(fetchMock).toHaveBeenCalledTimes(6);
  });

  it("PATCH와 DELETE는 caller basis만 보내고 mutation 직전 revision을 다시 읽지 않는다", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockImplementation(async () =>
        jsonResponse({
          data: { request: { feature_id: "feature-1" } },
          meta: {},
        }),
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

  it("불명확한 PATCH 뒤 body가 바뀐 재시도는 새 side effect를 보내지 않는다", async () => {
    const randomUUID = stubRandomUUID(["89898989-8989-4989-8989-898989898989"]);
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(new Response("{}", { status: 503 }))
      .mockImplementation(async () =>
        jsonResponse({
          data: { request: { feature_id: "feature-1" } },
          meta: {},
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      patchAdminFeature("feature-1", '"4"', {
        reason: "original",
      }),
    ).rejects.toMatchObject({ status: 503 });
    await expect(
      patchAdminFeature("feature-1", '"4"', {
        reason: "changed",
      }),
    ).rejects.toBeInstanceOf(DomainIdempotencySubmissionMismatchError);
    await patchAdminFeature("feature-1", '"4"', {
      reason: "original",
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.map(([, init]) => init?.method)).toEqual([
      "PATCH",
      "PATCH",
    ]);
    expect(
      fetchMock.mock.calls.map(
        ([, init]) =>
          (init?.headers as Record<string, string>)["Idempotency-Key"],
      ),
    ).toEqual([
      "89898989-8989-4989-8989-898989898989",
      "89898989-8989-4989-8989-898989898989",
    ]);
    expect(randomUUID).toHaveBeenCalledTimes(1);
  });
});

describe("allowedPublicationStates", () => {
  it("retired feature에는 suppressed만 제시한다", () => {
    // `ck_features_state_tuple`이 `lifecycle='active' OR publication='suppressed'`를
    // 강제한다. retired에서 published/draft를 고를 수 있게 두면 운영자가 한 번의
    // 클릭으로 **반드시 실패하는** 요청을 보낸다.
    expect(allowedPublicationStates("retired")).toEqual(["suppressed"]);
  });

  it("active feature에는 세 축 값을 모두 제시한다", () => {
    expect([...allowedPublicationStates("active")]).toEqual([
      "draft",
      "published",
      "suppressed",
    ]);
  });
});
