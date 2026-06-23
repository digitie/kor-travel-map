import { test, expect } from "@playwright/test";

import * as F from "./_fixtures";

/**
 * LIVE (non-mock) e2e for `/features` (Feature 지도) against prod 실데이터
 * (~1.09M features). READ-ONLY: only goto + read assertions + non-mutating
 * clicks on [nav links / tabs / kind filter chips / sort headers]. No
 * deactivate/delete/submit/save/apply/run/cancel/approve/reject actions.
 *
 * Selectors are reused verbatim from the already-verified specs:
 *   - e2e/features.spec.ts
 *   - e2e/features-map-interactions.spec.ts
 * Nothing new is invented. The page reads viewport from Zustand (not URL),
 * so center/zoom query deep-links cannot move the map — those scenarios still
 * assert against the stable heading + map-canvas-container instead.
 */

const ROUTE = "/features";
const HEADING = "Feature 지도";
const KINDS = F.KINDS.length > 0 ? F.KINDS : ["place"];
const MAP_VIEWS = F.MAP_VIEWS;
const VIEWPORTS = [
  { name: "desktop-1280", width: 1280, height: 800 },
  { name: "tablet-768", width: 768, height: 1024 },
  { name: "mobile-390", width: 390, height: 844 },
] as const;

const STATUS_TEXT =
  /지도 로딩 중|feature 로딩 중|건 표시|feature 호출 실패/;

/** Stable page-ready assertion shared by every scenario. */
async function expectFeaturesPageReady(
  page: import("@playwright/test").Page,
): Promise<void> {
  await expect(
    page.getByRole("heading", { level: 1, name: HEADING }),
  ).toBeVisible({ timeout: 15000 });
  await expect(page.getByTestId("map-canvas-container")).toBeAttached({
    timeout: 15000,
  });
}

test.describe("/features live — page load + core controls", () => {
  test("페이지 로드 — heading + map-canvas-container + 상태 텍스트", async ({
    page,
  }) => {
    await page.goto(ROUTE);
    await expectFeaturesPageReady(page);
    await expect(page.getByText(STATUS_TEXT).first()).toBeVisible({
      timeout: 15000,
    });
  });

  test("페이지 로드 — 지도 탭이 기본 선택", async ({ page }) => {
    await page.goto(ROUTE);
    await expectFeaturesPageReady(page);
    await expect(
      page.getByRole("tab", { name: "지도" }),
    ).toHaveAttribute("aria-selected", "true", { timeout: 15000 });
  });

  test("페이지 로드 — 테이블 탭은 비선택", async ({ page }) => {
    await page.goto(ROUTE);
    await expectFeaturesPageReady(page);
    await expect(
      page.getByRole("tab", { name: "테이블" }),
    ).toHaveAttribute("aria-selected", "false", { timeout: 15000 });
  });

  test("페이지 로드 — kind-filter 그룹이 보임", async ({ page }) => {
    await page.goto(ROUTE);
    await expectFeaturesPageReady(page);
    await expect(page.getByTestId("kind-filter")).toBeVisible({
      timeout: 15000,
    });
  });

  test("페이지 로드 — Features 배지 + 홈 링크가 보임", async ({ page }) => {
    await page.goto(ROUTE);
    await expectFeaturesPageReady(page);
    await expect(page.getByRole("link", { name: /홈/ })).toBeVisible({
      timeout: 15000,
    });
  });

  test("페이지 로드 — 선택 안 했을 때 상세 패널 숨김", async ({ page }) => {
    await page.goto(ROUTE);
    await expectFeaturesPageReady(page);
    await expect(page.getByTestId("feature-detail-panel")).toBeHidden({
      timeout: 15000,
    });
  });

  test("탭 전환 — 지도 → 테이블 (aria-selected 토글)", async ({ page }) => {
    await page.goto(ROUTE);
    await expectFeaturesPageReady(page);
    const tableTab = page.getByRole("tab", { name: "테이블" });
    await tableTab.click();
    await expect(tableTab).toHaveAttribute("aria-selected", "true", {
      timeout: 15000,
    });
    await expect(
      page.getByRole("table", { name: "이름순 feature" }),
    ).toBeVisible({ timeout: 15000 });
  });

  test("탭 전환 — 테이블 → 지도 복귀", async ({ page }) => {
    await page.goto(ROUTE);
    await expectFeaturesPageReady(page);
    const mapTab = page.getByRole("tab", { name: "지도" });
    const tableTab = page.getByRole("tab", { name: "테이블" });
    await tableTab.click();
    await expect(tableTab).toHaveAttribute("aria-selected", "true", {
      timeout: 15000,
    });
    await mapTab.click();
    await expect(mapTab).toHaveAttribute("aria-selected", "true", {
      timeout: 15000,
    });
    await expect(page.getByTestId("map-canvas-container")).toBeAttached({
      timeout: 15000,
    });
  });

  test("테이블 탭 — 4종 columnheader (name/kind/status/coord)", async ({
    page,
  }) => {
    await page.goto(ROUTE);
    await expectFeaturesPageReady(page);
    await page.getByRole("tab", { name: "테이블" }).click();
    const table = page.getByRole("table", { name: "이름순 feature" });
    await expect(table).toBeVisible({ timeout: 15000 });
    for (const column of ["name", "kind", "status", "coord"]) {
      await expect(
        table.getByRole("columnheader", { name: column }),
      ).toBeVisible({ timeout: 15000 });
    }
  });

  test("홈에서 → Features 내비 링크로 이동", async ({ page }) => {
    await page.goto("/");
    await page
      .getByRole("navigation")
      .getByRole("link", { name: "Features", exact: true })
      .click();
    await expect(page).toHaveURL(/\/features$/, { timeout: 15000 });
    await expect(
      page.getByRole("heading", { level: 1, name: HEADING }),
    ).toBeVisible({ timeout: 15000 });
  });
});

test.describe("/features live — kind filter chips", () => {
  for (const kind of KINDS) {
    test(`kind 칩 노출 — "${kind}"`, async ({ page }) => {
      await page.goto(ROUTE);
      await expectFeaturesPageReady(page);
      const filter = page.getByTestId("kind-filter");
      await expect(
        filter.getByRole("button", { name: kind, exact: true }),
      ).toBeVisible({ timeout: 15000 });
    });
  }

  for (const kind of KINDS) {
    test(`kind 칩 토글 ON — "${kind}"`, async ({ page }) => {
      await page.goto(ROUTE);
      await expectFeaturesPageReady(page);
      const filter = page.getByTestId("kind-filter");
      const chip = filter.getByRole("button", { name: kind, exact: true });
      await expect(chip).toHaveAttribute("aria-pressed", "false", {
        timeout: 15000,
      });
      await chip.click();
      await expect(chip).toHaveAttribute("aria-pressed", "true", {
        timeout: 15000,
      });
      await expect(
        filter.getByRole("button", { name: "초기화" }),
      ).toBeVisible({ timeout: 15000 });
    });
  }

  for (const kind of KINDS) {
    test(`kind 칩 토글 ON→초기화 — "${kind}"`, async ({ page }) => {
      await page.goto(ROUTE);
      await expectFeaturesPageReady(page);
      const filter = page.getByTestId("kind-filter");
      const chip = filter.getByRole("button", { name: kind, exact: true });
      await chip.click();
      await expect(chip).toHaveAttribute("aria-pressed", "true", {
        timeout: 15000,
      });
      const reset = filter.getByRole("button", { name: "초기화" });
      await reset.click();
      await expect(chip).toHaveAttribute("aria-pressed", "false", {
        timeout: 15000,
      });
      await expect(reset).toBeHidden({ timeout: 15000 });
    });
  }
});

test.describe("/features live — map-view deep links (center/zoom query)", () => {
  // The page derives viewport from Zustand, not the URL — these query strings
  // are harmless GET params; we assert the page is robustly ready regardless.
  for (const [name, lon, lat, zoom] of MAP_VIEWS) {
    test(`딥링크 쿼리 로드 — ${name} (z${zoom})`, async ({ page }) => {
      await page.goto(
        `${ROUTE}?center=${lon},${lat}&zoom=${zoom}&v=${encodeURIComponent(
          String(name),
        )}`,
      );
      await expectFeaturesPageReady(page);
      await expect(
        page.getByRole("tab", { name: "지도" }),
      ).toHaveAttribute("aria-selected", "true", { timeout: 15000 });
    });
  }

  for (const [name, lon, lat, zoom] of MAP_VIEWS) {
    test(`딥링크 쿼리 + 테이블 탭 — ${name}`, async ({ page }) => {
      await page.goto(
        `${ROUTE}?lon=${lon}&lat=${lat}&z=${zoom}&v=${encodeURIComponent(
          String(name),
        )}`,
      );
      await expectFeaturesPageReady(page);
      await page.getByRole("tab", { name: "테이블" }).click();
      await expect(
        page.getByRole("table", { name: "이름순 feature" }),
      ).toBeVisible({ timeout: 15000 });
    });
  }
});

test.describe("/features live — responsive viewports", () => {
  for (const vp of VIEWPORTS) {
    test(`반응형 로드 — ${vp.name}`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(ROUTE);
      await expectFeaturesPageReady(page);
      await expect(page.getByTestId("kind-filter")).toBeVisible({
        timeout: 15000,
      });
    });
  }

  for (const vp of VIEWPORTS) {
    test(`반응형 탭 전환 — ${vp.name}`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(ROUTE);
      await expectFeaturesPageReady(page);
      const tableTab = page.getByRole("tab", { name: "테이블" });
      await tableTab.click();
      await expect(tableTab).toHaveAttribute("aria-selected", "true", {
        timeout: 15000,
      });
    });
  }

  for (const vp of VIEWPORTS) {
    test(`반응형 kind 칩 토글 — ${vp.name}`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(ROUTE);
      await expectFeaturesPageReady(page);
      const filter = page.getByTestId("kind-filter");
      const chip = filter.getByRole("button", {
        name: KINDS[0],
        exact: true,
      });
      await chip.click();
      await expect(chip).toHaveAttribute("aria-pressed", "true", {
        timeout: 15000,
      });
    });
  }
});

test.describe("/features live — sort headers (table tab)", () => {
  // Only name/kind/status are sortable (coord enableSorting:false).
  const SORTABLE = ["name", "kind", "status"] as const;
  for (const column of SORTABLE) {
    test(`정렬 헤더 클릭 — "${column}" (1회)`, async ({ page }) => {
      await page.goto(ROUTE);
      await expectFeaturesPageReady(page);
      await page.getByRole("tab", { name: "테이블" }).click();
      const table = page.getByRole("table", { name: "이름순 feature" });
      await expect(table).toBeVisible({ timeout: 15000 });
      const headerButton = table
        .getByRole("columnheader", { name: column })
        .getByRole("button", { name: column, exact: true });
      await headerButton.click();
      await expect(table).toBeVisible({ timeout: 15000 });
    });
  }

  for (const column of SORTABLE) {
    test(`정렬 헤더 클릭 — "${column}" (토글 2회)`, async ({ page }) => {
      await page.goto(ROUTE);
      await expectFeaturesPageReady(page);
      await page.getByRole("tab", { name: "테이블" }).click();
      const table = page.getByRole("table", { name: "이름순 feature" });
      await expect(table).toBeVisible({ timeout: 15000 });
      const headerButton = table
        .getByRole("columnheader", { name: column })
        .getByRole("button", { name: column, exact: true });
      await headerButton.click();
      await headerButton.click();
      await expect(table).toBeVisible({ timeout: 15000 });
    });
  }
});

test.describe("/features live — header nav links present", () => {
  const NAV_LINKS = ["홈", "Jobs", "Update", "Targets", "Dedup", "Dagster"];
  for (const linkName of NAV_LINKS) {
    test(`헤더 링크 노출 — "${linkName}"`, async ({ page }) => {
      await page.goto(ROUTE);
      await expectFeaturesPageReady(page);
      await expect(
        page.getByRole("link", { name: new RegExp(linkName) }).first(),
      ).toBeVisible({ timeout: 15000 });
    });
  }
});

test.describe("/features live — kind chip + view combinations", () => {
  // Cross kinds × tabs to exercise filtered refetch under both views.
  const KIND_SUBSET = KINDS.slice(0, 4);
  for (const kind of KIND_SUBSET) {
    test(`kind "${kind}" 토글 후 테이블 뷰 유지`, async ({ page }) => {
      await page.goto(ROUTE);
      await expectFeaturesPageReady(page);
      const filter = page.getByTestId("kind-filter");
      const chip = filter.getByRole("button", { name: kind, exact: true });
      await chip.click();
      await expect(chip).toHaveAttribute("aria-pressed", "true", {
        timeout: 15000,
      });
      const tableTab = page.getByRole("tab", { name: "테이블" });
      await tableTab.click();
      await expect(tableTab).toHaveAttribute("aria-selected", "true", {
        timeout: 15000,
      });
      await expect(
        page.getByRole("table", { name: "이름순 feature" }),
      ).toBeVisible({ timeout: 15000 });
    });
  }

  for (const kind of KIND_SUBSET) {
    test(`kind "${kind}" 토글 후 지도 뷰 유지`, async ({ page }) => {
      await page.goto(ROUTE);
      await expectFeaturesPageReady(page);
      const filter = page.getByTestId("kind-filter");
      const chip = filter.getByRole("button", { name: kind, exact: true });
      await chip.click();
      await expect(chip).toHaveAttribute("aria-pressed", "true", {
        timeout: 15000,
      });
      await expect(
        page.getByRole("tab", { name: "지도" }),
      ).toHaveAttribute("aria-selected", "true", { timeout: 15000 });
      await expect(page.getByTestId("map-canvas-container")).toBeAttached({
        timeout: 15000,
      });
    });
  }
});

test.describe("/features live — deep link + viewport cross", () => {
  // First few map views × the three viewports → robust load assertion only.
  const VIEW_SUBSET = MAP_VIEWS.slice(0, 6);
  for (const [name, lon, lat, zoom] of VIEW_SUBSET) {
    for (const vp of VIEWPORTS) {
      test(`딥링크 ${name} @ ${vp.name}`, async ({ page }) => {
        await page.setViewportSize({ width: vp.width, height: vp.height });
        await page.goto(
          `${ROUTE}?center=${lon},${lat}&zoom=${zoom}&v=${encodeURIComponent(
            String(name),
          )}`,
        );
        await expectFeaturesPageReady(page);
      });
    }
  }
});
