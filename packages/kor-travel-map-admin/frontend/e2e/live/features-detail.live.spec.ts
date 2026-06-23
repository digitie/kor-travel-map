import { test, expect } from "@playwright/test";

import * as F from "./_fixtures";

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
 *   - 컨테이너: `data-testid="feature-detail-view"` / `data-testid="feature-weather-panel"`
 *   - 헤더 dl 라벨: coord / sigungu / updated / provider
 *   - 섹션 타이틀: Sources / Issues / Overrides / History / Files / Raw / Nearby / Weather
 *   - Raw <details> summary: detail / raw_refs / urls / address
 *   - AdminShell 상수 헤딩(h1): "Feature detail"
 *
 * 실데이터라 feature 이름·행 텍스트·카운트는 변동이 크므로 단언하지 않는다.
 * 안정 landmark(testid/상수 헤딩/섹션 타이틀/URL)만 robust하게 본다.
 *
 * NOTE: Playwright는 Windows 호스트에서만 실행된다(라이브 검증은 Windows 런 필요).
 */

const TIMEOUT = { timeout: 15000 } as const;

// 상한 — fixture가 비거나 과다해도 안전하게.
const FEATURE_IDS = F.FEATURE_IDS.slice(0, 150);
const DEEPLINK_IDS = F.FEATURE_IDS.slice(0, 24);
const VIEWPORT_IDS = F.FEATURE_IDS.slice(0, 6);

// fixture가 비어도 최소 시나리오가 돌도록 하는 폴백 id(존재하지 않아도
// 상수 헤딩 "Feature detail"은 항상 렌더된다).
const FALLBACK_ID = "f_1156010100_p_e2eabc1234567890";

const SAMPLE_ID = FEATURE_IDS[0] ?? FALLBACK_ID;

// AdminShell이 항상 렌더하는 상수 헤딩(detail GET 성공/실패와 무관).
const SHELL_HEADING = "Feature detail";

// detail GET 성공 시 detail-view가 무조건 렌더하는 섹션 타이틀들.
const DETAIL_SECTIONS = [
  "Sources",
  "Issues",
  "Overrides",
  "History",
  "Files",
] as const;

// Raw <details> disclosure summary 텍스트.
const RAW_SUMMARIES = ["detail", "raw_refs", "urls", "address"] as const;

// 응답형 viewport(데스크탑/태블릿/모바일).
const VIEWPORTS: [string, number, number][] = [
  ["desktop-1280", 1280, 800],
  ["tablet-768", 768, 1024],
  ["mobile-390", 390, 844],
];

test.describe("features-detail LIVE — id별 상세 로드", () => {
  // FEATURE_IDS(150) 각각 1개씩: 상세 페이지 로드 + 핵심 landmark visible.
  for (const featureId of FEATURE_IDS) {
    test(`detail loads — ${featureId}`, async ({ page }) => {
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

      // weather 패널 landmark는 weather 성공/실패와 무관하게 렌더된다.
      await expect(page.getByTestId("feature-weather-panel")).toBeVisible(
        TIMEOUT,
      );
    });
  }
});

test.describe("features-detail LIVE — 섹션/헤딩 깊이(샘플 id)", () => {
  // 첫 24개 id에서 핵심 섹션 타이틀이 detail-view scope 안에 모두 보이는지.
  for (const featureId of DEEPLINK_IDS) {
    test(`sections visible — ${featureId}`, async ({ page }) => {
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
  for (const featureId of DEEPLINK_IDS) {
    test(`header dl labels — ${featureId}`, async ({ page }) => {
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
  for (const featureId of DEEPLINK_IDS) {
    test(`raw disclosures — ${featureId}`, async ({ page }) => {
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

  // 우측 aside 패널들(Weather/Nearby/Raw 섹션 타이틀) 가시성.
  for (const featureId of DEEPLINK_IDS) {
    test(`aside panels — ${featureId}`, async ({ page }) => {
      await page.goto(`/features/${featureId}`);

      await expect(page.getByTestId("feature-detail-view")).toBeVisible(
        TIMEOUT,
      );

      const weatherPanel = page.getByTestId("feature-weather-panel");
      await expect(weatherPanel).toBeVisible(TIMEOUT);
      await expect(weatherPanel.getByText("Weather").first()).toBeVisible(
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
  for (const featureId of DEEPLINK_IDS.slice(0, 12)) {
    test(`raw_refs toggle — ${featureId}`, async ({ page }) => {
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
  // 상세 → 'Admin' 링크 클릭 시 /admin/features로 이동(GET 내비).
  test(`nav to admin features — ${SAMPLE_ID}`, async ({ page }) => {
    await page.goto(`/features/${SAMPLE_ID}`);
    await expect(page.getByTestId("feature-detail-view")).toBeVisible(TIMEOUT);

    await page.getByRole("link", { name: "Admin", exact: true }).click();
    await expect(page).toHaveURL(/\/admin\/features(?:$|[/?])/, TIMEOUT);
  });

  // 상세 → 'Changes' 링크 클릭 시 change-requests로 이동(GET 내비).
  test(`nav to change-requests — ${SAMPLE_ID}`, async ({ page }) => {
    await page.goto(`/features/${SAMPLE_ID}`);
    await expect(page.getByTestId("feature-detail-view")).toBeVisible(TIMEOUT);

    await page
      .getByRole("link", { name: "Changes", exact: true })
      .click();
    await expect(page).toHaveURL(/\/admin\/features\/change-requests/, TIMEOUT);
  });

  // 상세 → '지도' 링크 클릭 시 /features 지도로 이동(GET 내비).
  test(`nav to features map — ${SAMPLE_ID}`, async ({ page }) => {
    await page.goto(`/features/${SAMPLE_ID}`);
    await expect(page.getByTestId("feature-detail-view")).toBeVisible(TIMEOUT);

    await page.getByRole("link", { name: "지도", exact: true }).click();
    await expect(page).toHaveURL(/\/features(?:$|[/?])/, TIMEOUT);
  });
});

test.describe("features-detail LIVE — 딥링크 URL", () => {
  // 첫 24개 id에서 URL이 정확히 그 id로 끝나는지(딥링크 검증).
  for (const featureId of DEEPLINK_IDS) {
    test(`deeplink url — ${featureId}`, async ({ page }) => {
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
  for (const featureId of VIEWPORT_IDS) {
    for (const [vpName, width, height] of VIEWPORTS) {
      test(`viewport ${vpName} — ${featureId}`, async ({ page }) => {
        await page.setViewportSize({ width, height });
        await page.goto(`/features/${featureId}`);

        await expect(
          page.getByRole("heading", { name: SHELL_HEADING, level: 1 }),
        ).toBeVisible(TIMEOUT);
        await expect(page.getByTestId("feature-detail-view")).toBeVisible(
          TIMEOUT,
        );
        await expect(page.getByTestId("feature-weather-panel")).toBeVisible(
          TIMEOUT,
        );
      });
    }
  }
});

test.describe("features-detail LIVE — 고정 시나리오(fixture-독립)", () => {
  // fixture가 비어도 항상 도는 고정 시나리오 — 페이지 로드 + 컨트롤 + 반응형.
  test(`page load — ${SAMPLE_ID}`, async ({ page }) => {
    await page.goto(`/features/${SAMPLE_ID}`);
    await expect(
      page.getByRole("heading", { name: SHELL_HEADING, level: 1 }),
    ).toBeVisible(TIMEOUT);
  });

  test(`detail container present — ${SAMPLE_ID}`, async ({ page }) => {
    await page.goto(`/features/${SAMPLE_ID}`);
    await expect(page.getByTestId("feature-detail-view")).toBeVisible(TIMEOUT);
  });

  test(`weather panel present — ${SAMPLE_ID}`, async ({ page }) => {
    await page.goto(`/features/${SAMPLE_ID}`);
    await expect(page.getByTestId("feature-weather-panel")).toBeVisible(
      TIMEOUT,
    );
  });

  for (const [vpName, width, height] of VIEWPORTS) {
    test(`fixed viewport ${vpName} — ${SAMPLE_ID}`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      await page.goto(`/features/${SAMPLE_ID}`);
      await expect(
        page.getByRole("heading", { name: SHELL_HEADING, level: 1 }),
      ).toBeVisible(TIMEOUT);
    });
  }
});
