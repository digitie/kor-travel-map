import { test, expect } from "@playwright/test";

import {
  LIVE_FEATURE_SAMPLE_MAX,
  liveFeatureIdForSlot,
} from "./_live-feature-sample";

/**
 * LIVE (비-mock) e2e — `/features/[featureId]` 상세 (area key=features-detail).
 *
 * 백엔드는 prod 실데이터(약 1.09M features)다. 본 spec은 **read-only**: page.goto +
 * 읽기 assertion + 내비/탭/딥링크 클릭만 한다(POST/PUT/PATCH/DELETE를 유발하는
 * 버튼·폼 제출은 절대 하지 않는다).
 *
 * selector/route/heading은 mock 참조 spec(`e2e/feature-detail.spec.ts`,
 * `e2e/feature-detail-sections.spec.ts`)에서 이미 검증된 것만 재사용한다:
 *   - 라우트: `/features/{featureId}` (admin 상세 GET `/v1/admin/features/{id}` 호출)
 *   - 컨테이너: `data-testid="feature-detail-view"`
 *   - 헤더 dl 라벨: coord / sigungu / updated / provider
 *   - 섹션 타이틀: Sources / Issues / Overrides / History / Files / Raw / Nearby
 *   - 2026-10-01 ADR-105: Map은 weather 기능을 걷어냈다 — 상세에 Weather 패널
 *     (`feature-weather-panel`)이 **없어야** 한다(고정 시나리오에서 부재를 단언).
 *   - Raw <details> summary: detail / raw_refs / urls / address
 *   - AdminShell 상수 헤딩(h1): "Feature 상세"
 *
 * 실데이터라 feature 이름·행 텍스트·카운트는 변동이 크므로 단언하지 않는다.
 * 안정 landmark(testid/상수 헤딩/섹션 타이틀/URL)만 robust하게 본다.
 *
 * 대상 id: 고정 fixture(`_fixtures.ts` FEATURE_IDS)는 prod 재생성마다 전멸해 31건이
 * 404로 실패했다(2026-11-25 운영 e2e). 이제 실행 시점에 admin 목록 API에서 kind별
 * 공개·유효·활성 feature를 표집해(`_live-feature-sample.ts`) slot 번호로 쓴다 — 테스트
 * 제목은 slot(`sample #07`)이고 실제 id는 annotation(`feature_id`)으로 남는다.
 *
 * NOTE: Playwright는 Windows 호스트에서만 실행된다(라이브 검증은 Windows 런 필요).
 */

// 대용량 raw 페이로드를 JsonBlock으로 렌더하는 상세는 첫 페인트가 느릴 수 있어
// (대상 몇 건 15s 초과) 여유 타임아웃을 준다.
const TIMEOUT = { timeout: 30000 } as const;

// slot 수 — 표본 상한(kind 수 × kind당 25) 안에서. 표본이 slot보다 적으면 그 slot은 skip.
const DETAIL_SLOTS = Math.min(100, LIVE_FEATURE_SAMPLE_MAX);
const DEEPLINK_SLOTS = Math.min(24, DETAIL_SLOTS);
const VIEWPORT_SLOTS = Math.min(6, DETAIL_SLOTS);

function slots(count: number): number[] {
  return Array.from({ length: count }, (_, index) => index);
}

function slotName(slot: number): string {
  return `sample #${String(slot).padStart(2, "0")}`;
}

// AdminShell이 항상 렌더하는 상수 헤딩(detail GET 성공/실패와 무관).
const SHELL_HEADING = "Feature 상세";

// detail GET 성공 시 detail-view가 무조건 렌더하는 섹션 타이틀들.
// T-VN-36이 whole-row "History" 패널을 제거했다 — 남은 것은 notice 전용
// "Notice History"뿐이고, 그건 kind별이라 무조건 렌더가 아니다.
const DETAIL_SECTIONS = ["Sources", "Issues", "Overrides", "Files"] as const;

// Raw <details> disclosure summary 텍스트.
const RAW_SUMMARIES = ["detail", "raw_refs", "urls", "address"] as const;

// 응답형 viewport(데스크탑/태블릿/모바일).
const VIEWPORTS: [string, number, number][] = [
  ["desktop-1280", 1280, 800],
  ["tablet-768", 768, 1024],
  ["mobile-390", 390, 844],
];

test.describe("features-detail LIVE — id별 상세 로드", () => {
  // 운영 표본 slot 각각 1개씩: 상세 페이지 로드 + 핵심 landmark visible.
  for (const slot of slots(DETAIL_SLOTS)) {
    test(`detail loads — ${slotName(slot)}`, async ({ page }) => {
      const featureId = await liveFeatureIdForSlot(page, slot);
      await page.goto(`/features/${featureId}`);

      // 상수 헤딩은 detail GET 성공/실패와 무관하게 항상 보인다.
      await expect(
        page.getByRole("heading", { name: SHELL_HEADING, level: 1 }),
      ).toBeVisible(TIMEOUT);

      // prod 실데이터 id → 상세 GET 성공 → detail-view 컨테이너 렌더.
      const detailView = page.getByTestId("feature-detail-view");
      await expect(detailView).toBeVisible(TIMEOUT);

      // 헤더 좌측 — 원문 feature_id(font-mono)가 그대로 노출된다.
      await expect(detailView.getByText(featureId, { exact: true })).toBeVisible(
        TIMEOUT,
      );
    });
  }
});

test.describe("features-detail LIVE — 섹션/헤딩 깊이(샘플 id)", () => {
  // 첫 24개 id에서 핵심 섹션 타이틀이 detail-view scope 안에 모두 보이는지.
  for (const slot of slots(DEEPLINK_SLOTS)) {
    test(`sections visible — ${slotName(slot)}`, async ({ page }) => {
      const featureId = await liveFeatureIdForSlot(page, slot);
      await page.goto(`/features/${featureId}`);

      const detailView = page.getByTestId("feature-detail-view");
      await expect(detailView).toBeVisible(TIMEOUT);

      for (const section of DETAIL_SECTIONS) {
        await expect(
          detailView.getByText(section, { exact: true }),
        ).toBeVisible(TIMEOUT);
      }
    });
  }

  // 헤더 dl 라벨(coord/sigungu/updated/provider)이 보이는지.
  for (const slot of slots(DEEPLINK_SLOTS)) {
    test(`header dl labels — ${slotName(slot)}`, async ({ page }) => {
      const featureId = await liveFeatureIdForSlot(page, slot);
      await page.goto(`/features/${featureId}`);

      const detailView = page.getByTestId("feature-detail-view");
      await expect(detailView).toBeVisible(TIMEOUT);

      for (const label of ["coord", "sigungu", "updated", "provider"]) {
        await expect(
          detailView.getByText(label, { exact: true }).first(),
        ).toBeVisible(TIMEOUT);
      }
    });
  }

  // Raw <details> disclosure summary(detail/raw_refs/urls/address) 가시성.
  for (const slot of slots(DEEPLINK_SLOTS)) {
    test(`raw disclosures — ${slotName(slot)}`, async ({ page }) => {
      const featureId = await liveFeatureIdForSlot(page, slot);
      await page.goto(`/features/${featureId}`);

      const detailView = page.getByTestId("feature-detail-view");
      await expect(detailView).toBeVisible(TIMEOUT);

      for (const summary of RAW_SUMMARIES) {
        await expect(
          detailView.getByText(summary, { exact: true }).first(),
        ).toBeVisible(TIMEOUT);
      }
    });
  }

  // 우측 aside 패널들(Nearby/Raw 섹션 타이틀) 가시성.
  for (const slot of slots(DEEPLINK_SLOTS)) {
    test(`aside panels — ${slotName(slot)}`, async ({ page }) => {
      const featureId = await liveFeatureIdForSlot(page, slot);
      await page.goto(`/features/${featureId}`);

      await expect(page.getByTestId("feature-detail-view")).toBeVisible(
        TIMEOUT,
      );

      for (const section of ["Nearby", "Raw"]) {
        await expect(
          page.getByText(section, { exact: true }).first(),
        ).toBeVisible(TIMEOUT);
      }
    });
  }
});

test.describe("features-detail LIVE — Raw disclosure 토글(read-only)", () => {
  // 닫힌 raw_refs/urls/address summary 클릭(GET만 유발하는 네이티브 <details> 토글).
  for (const slot of slots(Math.min(12, DEEPLINK_SLOTS))) {
    test(`raw_refs toggle — ${slotName(slot)}`, async ({ page }) => {
      const featureId = await liveFeatureIdForSlot(page, slot);
      await page.goto(`/features/${featureId}`);

      const detailView = page.getByTestId("feature-detail-view");
      await expect(detailView).toBeVisible(TIMEOUT);

      // raw_refs disclosure는 <details>(닫힘) — summary 클릭은 비파괴 토글.
      const rawRefsSummary = detailView
        .getByText("raw_refs", { exact: true })
        .first();
      await expect(rawRefsSummary).toBeVisible(TIMEOUT);
      await rawRefsSummary.click();

      // 토글 후에도 컨테이너는 그대로(POST 없음, 페이지 잔존).
      await expect(detailView).toBeVisible(TIMEOUT);
    });
  }
});

test.describe("features-detail LIVE — 헤더 내비 링크(read-only nav)", () => {
  // 상세 → 상단 바 동작 'Feature 목록' 링크 클릭 시 /admin/features로 이동(GET 내비).
  // (옛 'Admin' 링크는 상단 바 동작 재편으로 'Feature 목록'이 됐다. 사이드바에도 같은
  // 이름의 nav 링크가 있으므로 상단 바 동작 영역으로 scope한다.)
  test(`nav to admin features — ${slotName(0)}`, async ({ page }) => {
    const sampleId = await liveFeatureIdForSlot(page, 0);
    await page.goto(`/features/${sampleId}`);
    await expect(page.getByTestId("feature-detail-view")).toBeVisible(TIMEOUT);

    await page
      .locator('[data-slot="map-shell-actions"]')
      .getByRole("link", { name: "Feature 목록", exact: true })
      .click();
    await expect(page).toHaveURL(/\/admin\/features(?:$|[/?])/, TIMEOUT);
  });

  // T-VN-36(0104)이 change-request 모델과 상세의 'Changes' 링크를 함께 제거했다.
  // 이동 대상 라우트 자체가 없으므로 해당 내비 테스트도 삭제한다.

  // 상세 → '지도' 링크 클릭 시 /features 지도로 이동(GET 내비).
  test(`nav to features map — ${slotName(0)}`, async ({ page }) => {
    const sampleId = await liveFeatureIdForSlot(page, 0);
    await page.goto(`/features/${sampleId}`);
    await expect(page.getByTestId("feature-detail-view")).toBeVisible(TIMEOUT);

    await page
      .locator('[data-slot="map-shell-actions"]')
      .getByRole("link", { name: "지도", exact: true })
      .click();
    await expect(page).toHaveURL(/\/features(?:$|[/?])/, TIMEOUT);
  });
});

test.describe("features-detail LIVE — 딥링크 URL", () => {
  // 첫 24개 id에서 URL이 정확히 그 id로 끝나는지(딥링크 검증).
  for (const slot of slots(DEEPLINK_SLOTS)) {
    test(`deeplink url — ${slotName(slot)}`, async ({ page }) => {
      const featureId = await liveFeatureIdForSlot(page, slot);
      await page.goto(`/features/${featureId}`);

      await expect(page).toHaveURL(
        new RegExp(`/features/${featureId}(?:$|[?#])`),
        TIMEOUT,
      );
      await expect(
        page.getByRole("heading", { name: SHELL_HEADING, level: 1 }),
      ).toBeVisible(TIMEOUT);
    });
  }
});

test.describe("features-detail LIVE — 반응형 viewport", () => {
  // viewport(1280/768/390) × 샘플 id 6개 교차 — 각 폭에서 상세 로드.
  for (const slot of slots(VIEWPORT_SLOTS)) {
    for (const [vpName, width, height] of VIEWPORTS) {
      test(`viewport ${vpName} — ${slotName(slot)}`, async ({ page }) => {
        const featureId = await liveFeatureIdForSlot(page, slot);
        await page.setViewportSize({ width, height });
        await page.goto(`/features/${featureId}`);

        await expect(
          page.getByRole("heading", { name: SHELL_HEADING, level: 1 }),
        ).toBeVisible(TIMEOUT);
        await expect(page.getByTestId("feature-detail-view")).toBeVisible(
          TIMEOUT,
        );
      });
    }
  }
});

test.describe("features-detail LIVE — 고정 시나리오(표본 slot 0)", () => {
  // 표본 첫 slot 고정 시나리오 — 페이지 로드 + 컨트롤 + 반응형.
  test(`page load — ${slotName(0)}`, async ({ page }) => {
    const sampleId = await liveFeatureIdForSlot(page, 0);
    await page.goto(`/features/${sampleId}`);
    await expect(
      page.getByRole("heading", { name: SHELL_HEADING, level: 1 }),
    ).toBeVisible(TIMEOUT);
  });

  test(`detail container present — ${slotName(0)}`, async ({ page }) => {
    const sampleId = await liveFeatureIdForSlot(page, 0);
    await page.goto(`/features/${sampleId}`);
    await expect(page.getByTestId("feature-detail-view")).toBeVisible(TIMEOUT);
  });

  // ADR-105: weather 패널은 사라졌다. 상세가 다 렌더된 **뒤에** 부재를 본다 —
  // 렌더 전 0건으로 공허하게 통과하지 않도록 detail-view 가시성을 먼저 기다린다.
  test(`weather panel absent — ${slotName(0)}`, async ({ page }) => {
    const sampleId = await liveFeatureIdForSlot(page, 0);
    await page.goto(`/features/${sampleId}`);
    await expect(page.getByTestId("feature-detail-view")).toBeVisible(TIMEOUT);
    await expect(page.getByTestId("feature-weather-panel")).toHaveCount(0);
  });

  for (const [vpName, width, height] of VIEWPORTS) {
    test(`fixed viewport ${vpName} — ${slotName(0)}`, async ({ page }) => {
      const sampleId = await liveFeatureIdForSlot(page, 0);
      await page.setViewportSize({ width, height });
      await page.goto(`/features/${sampleId}`);
      await expect(
        page.getByRole("heading", { name: SHELL_HEADING, level: 1 }),
      ).toBeVisible(TIMEOUT);
    });
  }
});
