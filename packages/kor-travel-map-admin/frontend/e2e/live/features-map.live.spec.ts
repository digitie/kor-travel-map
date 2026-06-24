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

/**
 * 실제 지도 RENDER 검증 (#501).
 *
 * 위의 `expectFeaturesPageReady`는 heading + map-canvas-container "attached"만 본다 —
 * 컨테이너가 0×0이거나 캔버스가 빈(blank) 상태여도 통과한다. 본 describe는 지도가
 * 실제로 그려졌음을 확인하는 별도 시나리오를 더한다:
 *  - 컨테이너 visible + boundingBox width/height > 0
 *  - maplibre 캔버스가 blank가 아님(스크린샷 색 분산 휴리스틱, 관대한 임계치)
 *  - 적어도 1개의 `.maplibregl-marker`(feature 점 또는 클러스터)가 존재
 *  - 클러스터 클릭이 zoom을 증가시킴(getClusterExpansionZoom → easeTo → onMoveEnd가
 *    Zustand viewport 갱신 → DOM의 "z N.N" 텍스트 증가)
 *
 * 라이브 렌더 + 타일 fetch는 본질적으로 타이밍 의존이라 flaky를 제한하려 retries=1,
 * 넉넉한 timeout, 관대한 분산 임계치를 쓴다. WS는 read-only 화면이라 별도 격리 불필요.
 */
const CANVAS_SELECTOR = ".maplibregl-canvas";
const MARKER_SELECTOR = ".maplibregl-marker";
const CLUSTER_SELECTOR = '.maplibregl-marker[aria-label^="feature 클러스터"]';

/** "center … · z 6.5" 텍스트에서 z 숫자를 읽는다(DOM이 viewport.zoom을 렌더). */
async function readZoom(
  page: import("@playwright/test").Page,
): Promise<number | null> {
  const text = await page.getByText(/center .*· z\s/).first().textContent();
  const match = text?.match(/z\s*([\d.]+)/);
  return match ? Number(match[1]) : null;
}

/**
 * 캔버스 스크린샷이 단색(blank)이 아님을 본다. PNG 바이트 분포가 거의 단일 값이면
 * blank로 간주. 라이브 타일/마커 색이 섞이므로 충분한 분산이 있어야 정상.
 * 임계치는 관대하게 — 8종 이상의 서로 다른 바이트 값이면 non-blank로 판정한다.
 */
function looksNonBlank(png: Buffer): boolean {
  const distinct = new Set<number>();
  // PNG 헤더(첫 ~100B) 이후를 듬성듬성 샘플링(성능). 데이터가 한 값에 몰리면 blank.
  for (let i = 128; i < png.length; i += 97) {
    distinct.add(png[i]);
    if (distinct.size >= 8) return true;
  }
  return distinct.size >= 8;
}

test.describe("/features live — map render verification", () => {
  // 라이브 렌더는 타이밍 의존 → flaky 제한용 retries=1.
  test.describe.configure({ retries: 1 });

  test("컨테이너 visible + boundingBox > 0 + 비-blank 캔버스", async ({
    page,
  }) => {
    await page.goto(ROUTE);
    await expectFeaturesPageReady(page);

    const container = page.getByTestId("map-canvas-container");
    await expect(container).toBeVisible({ timeout: 20000 });

    const box = await container.boundingBox();
    expect(box, "map-canvas-container는 측정 가능한 boundingBox를 가져야 함").not.toBeNull();
    expect(box!.width).toBeGreaterThan(0);
    expect(box!.height).toBeGreaterThan(0);

    // maplibre 캔버스가 부착되고 크기가 잡힐 때까지 대기.
    const canvas = page.locator(CANVAS_SELECTOR).first();
    await expect(canvas).toBeVisible({ timeout: 20000 });
    const canvasBox = await canvas.boundingBox();
    expect(canvasBox!.width).toBeGreaterThan(0);
    expect(canvasBox!.height).toBeGreaterThan(0);

    // 타일/마커가 칠해질 시간을 준 뒤 스크린샷(blank 방지). 분산이 충분해야 한다.
    const shot = await canvas.screenshot({ timeout: 20000 });
    expect(
      looksNonBlank(shot),
      "캔버스 스크린샷이 단색(blank)이면 안 됨 — 타일/마커가 렌더돼야 함",
    ).toBe(true);
  });

  test("적어도 1개의 maplibre 마커(점/클러스터)가 렌더됨", async ({ page }) => {
    await page.goto(ROUTE);
    await expectFeaturesPageReady(page);

    // 라이브 데이터(~1.09M)면 기본 뷰(전국 근처)에 클러스터/점 마커가 나타난다.
    await expect(page.locator(MARKER_SELECTOR).first()).toBeVisible({
      timeout: 30000,
    });
    expect(await page.locator(MARKER_SELECTOR).count()).toBeGreaterThan(0);
  });

  test("클러스터 클릭 → zoom 증가(z 텍스트 상승)", async ({ page }) => {
    await page.goto(ROUTE);
    await expectFeaturesPageReady(page);

    // 클러스터가 나타날 때까지 대기(점만 보이는 고배율 초기 뷰면 클러스터가 없을 수 있어
    // 명시적으로 클러스터 마커를 기다린다).
    const cluster = page.locator(CLUSTER_SELECTOR).first();
    await expect(cluster).toBeVisible({ timeout: 30000 });

    const zoomBefore = await readZoom(page);
    expect(zoomBefore, "초기 zoom(z 텍스트)을 읽을 수 있어야 함").not.toBeNull();

    await cluster.click();

    // getClusterExpansionZoom → easeTo → onMoveEnd → Zustand viewport 갱신 → DOM z 상승.
    // easeTo 애니메이션 + moveend 디바운스 여유로 넉넉한 timeout.
    await expect
      .poll(async () => (await readZoom(page)) ?? -1, { timeout: 20000 })
      .toBeGreaterThan(zoomBefore!);
  });
});
