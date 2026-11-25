import { expect, test, type Page } from "@playwright/test";

import type { components } from "../../src/api/types";
import { KINDS_PRESENT } from "./_fixtures";

type AdminFeaturesListResponse =
  components["schemas"]["AdminFeaturesListResponse"];

/**
 * 운영 데이터에서 **지금 존재하는** feature id를 런타임에 표집한다.
 *
 * 왜: `_fixtures.ts`의 `FEATURE_IDS`는 특정 시점 prod 스냅샷이라 전면 재생성 때마다
 * 전멸한다(2026-08-05 1차, 2026-11-25 운영 e2e에서 `features-detail` 31건 404). 상세
 * 화면이 "id별로 로드된다"를 보려면 id가 살아 있어야 하므로, 고정 목록 대신 실행 시점의
 * admin 목록 API에서 고른다 — 재생성과 무관하게 유효하다.
 *
 * 표본: prod에 있는 kind(`KINDS_PRESENT`)별로 공개·유효·활성 행을 이름순으로 최대
 * `PER_KIND * 2`건씩 읽어 round-robin으로 섞고 `LIVE_FEATURE_SAMPLE_MAX`건에서 자른다(앞쪽
 * slot에도 여러 kind가 오게, 행이 적은 kind의 빈자리는 다른 kind가 채운다 — 2026-11-25
 * 운영 재실행에서 한 kind가 비어 slot 25개가 skip됐다). 읽기 전용 GET만 쓴다.
 * 워커 안에서는 한 번만 조회하고 재사용한다(실패하면 다음 호출이 다시 시도).
 */
const PER_KIND = 25;

let cached: Promise<string[]> | null = null;

export const LIVE_FEATURE_SAMPLE_MAX = PER_KIND * KINDS_PRESENT.length;

async function fetchSample(page: Page): Promise<string[]> {
  // kind별 조회는 차례로 — 1M행 prod에 동시 질의를 몰지 않는다.
  const perKind: string[][] = [];
  for (const kind of KINDS_PRESENT) {
    const params = new URLSearchParams({
      kind,
      lifecycle_state: "active",
      publication_state: "published",
      quality_state: "valid",
      page_size: String(PER_KIND * 2),
      sort: "name",
      order: "asc",
    });
    // page.request는 브라우저 context의 세션 쿠키·baseURL을 공유한다.
    const response = await page.request.get(
      `/api/proxy/v1/admin/features?${params.toString()}`,
    );
    expect(
      response.status(),
      `GET /v1/admin/features kind=${kind} (표본 조회)`,
    ).toBe(200);
    const body = (await response.json()) as AdminFeaturesListResponse;
    perKind.push(body.data.items.map((item) => item.feature_id));
  }
  const merged: string[] = [];
  for (let index = 0; index < PER_KIND * 2; index += 1) {
    for (const ids of perKind) {
      const id = ids[index];
      if (id !== undefined) merged.push(id);
    }
  }
  const unique = [...new Set(merged)].slice(0, LIVE_FEATURE_SAMPLE_MAX);
  expect(
    unique.length,
    "운영 active·published·valid feature 표본이 비면 상세 스펙을 검증할 수 없다",
  ).toBeGreaterThan(0);
  return unique;
}

/** 워커 단위로 캐시된 운영 feature id 표본. */
export function liveFeatureSample(page: Page): Promise<string[]> {
  if (cached === null) {
    cached = fetchSample(page).catch((error: unknown) => {
      cached = null;
      throw error;
    });
  }
  return cached;
}

/**
 * slot 번호의 표본 id. 표본이 slot보다 적으면(운영 데이터가 적은 kind 등) 그 테스트는
 * skip한다 — 실패가 아니라 "검증할 대상이 없음"이다. 실제 id는 annotation으로 남긴다.
 */
export async function liveFeatureIdForSlot(
  page: Page,
  slot: number,
): Promise<string> {
  if (cached === null) {
    // 첫 호출은 kind별 목록 조회(prod 1M행)가 끼므로 그 테스트에 여유를 더 준다.
    test.setTimeout(test.info().timeout + 60_000);
  }
  const ids = await liveFeatureSample(page);
  test.skip(
    slot >= ids.length,
    `운영 feature 표본이 ${ids.length}건뿐이라 slot #${slot}은 대상이 없음`,
  );
  const featureId = ids[slot];
  test.info().annotations.push({ type: "feature_id", description: featureId });
  return featureId;
}
