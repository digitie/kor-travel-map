import { test, expect } from "@playwright/test";
import * as F from "./_fixtures";

/**
 * LIVE (non-mock) misc smoke — prod 실데이터(1.09M features) 직격.
 *
 * 영역(key=misc): 홈(/), /admin/dagster, /etl, /admin/features/change-requests,
 * /admin/features/new. 모든 시나리오는 read-only(GET)만 — page.goto + 읽기 assertion +
 * 비파괴 click(nav 링크 / 탭 / kind·status 필터 / 페이지크기 select / 정렬 헤더 /
 * 페이지네이션) + 검색창 타이핑(GET 조회)에 한정한다. 제출/저장/적용/삭제/실행 류 버튼은
 * 절대 클릭하지 않는다.
 *
 * selector/route/heading은 home.spec / home-nav.spec / home-density-matrix.spec /
 * dagster.spec / etl.spec / change-requests-lifecycle.spec / features-new.spec /
 * admin-ops.spec에서 이미 검증된 것만 재사용한다.
 */

const TIMEOUT = { timeout: 15000 } as const;

// admin-shell nav 18행 — home-nav.spec NAV_ITEMS와 1:1.
const NAV_ITEMS: ReadonlyArray<{ label: string; href: string }> = [
  { label: "홈", href: "/" },
  { label: "Features", href: "/features" },
  { label: "Admin features", href: "/admin/features" },
  { label: "Feature changes", href: "/admin/features/change-requests" },
  { label: "Curated features", href: "/admin/curated-features" },
  { label: "Issues", href: "/admin/issues" },
  { label: "Import jobs", href: "/ops/import-jobs" },
  { label: "Providers", href: "/ops/providers" },
  { label: "Consistency", href: "/ops/consistency" },
  { label: "Logs", href: "/ops/logs" },
  { label: "Dedup reviews", href: "/admin/dedup-reviews" },
  { label: "Enrichment reviews", href: "/admin/enrichment-reviews" },
  { label: "Update requests", href: "/admin/feature-update-requests" },
  { label: "POI targets", href: "/admin/poi-cache-targets" },
  { label: "Offline uploads", href: "/admin/offline-uploads" },
  { label: "Backups", href: "/admin/backups" },
  { label: "Dagster", href: "/admin/dagster" },
  { label: "ETL preview", href: "/etl" },
];

const VIEWPORTS: ReadonlyArray<{ name: string; width: number; height: number }> =
  [
    { name: "desktop-1280", width: 1280, height: 800 },
    { name: "tablet-768", width: 768, height: 1024 },
    { name: "mobile-390", width: 390, height: 844 },
  ];

// 홈 metric/status 카드 제목 — home.spec 검증.
const HOME_METRIC_HEADINGS: ReadonlyArray<string> = [
  "Features",
  "Import jobs",
  "Dedup queue",
  "Issues",
  "서비스 상태",
  "Dedup pending",
];

// /admin/dagster 페이지 내부 heading — dagster.spec 검증.
const DAGSTER_HEADINGS: ReadonlyArray<string> = [
  "Code locations",
  "Recent runs",
  "Run detail",
  "Dagster webserver",
];

// /admin/features/new 폼 섹션 h2 — features-new.spec 검증.
const NEW_FEATURE_SECTIONS: ReadonlyArray<string> = [
  "좌표",
  "kor-travel-geo",
  "중복 후보",
  "기본 정보",
  "주소",
  "상세",
];

// change-requests 폼 label — admin-ops.spec 검증.
const CHANGE_REQUEST_LABELS: ReadonlyArray<string> = [
  "change action",
  "change feature id",
  "change reason",
  "change operator",
  "change kind",
  "change feature status",
  "change name",
  "change category",
  "change lon",
  "change lat",
  "change detail JSON",
  "change search",
  "change status",
  "change action filter",
  "change page size",
];

// change-requests columnheader — admin-ops.spec 검증.
const CHANGE_REQUEST_COLUMNS: ReadonlyArray<string> = [
  "request",
  "action/status",
  "feature",
  "review",
  "reason",
  "created",
  "actions",
];

// ─────────────────────────────────────────────────────────────────────────────
// 홈 (/) — shell, nav, metric/status 카드
// ─────────────────────────────────────────────────────────────────────────────

test.describe("misc live — home (/)", () => {
  test("home shell H1 + navigation 렌더", async ({ page }) => {
    await page.goto("/");
    await expect(
      page.getByRole("heading", { level: 1, name: "운영 홈" }),
    ).toBeVisible(TIMEOUT);
    await expect(page.getByRole("navigation")).toBeVisible(TIMEOUT);
  });

  test("home nav 링크 정확히 18개", async ({ page }) => {
    await page.goto("/");
    const navigation = page.getByRole("navigation");
    await expect(navigation.getByRole("link")).toHaveCount(18, TIMEOUT);
  });

  test("home 새로고침 버튼 visible", async ({ page }) => {
    await page.goto("/");
    await expect(
      page.getByRole("button", { name: "새로고침" }),
    ).toBeVisible(TIMEOUT);
  });

  test("home service-backend / service-dagster 카드 visible", async ({
    page,
  }) => {
    await page.goto("/");
    await expect(page.getByTestId("service-backend")).toBeVisible(TIMEOUT);
    await expect(page.getByTestId("service-dagster")).toBeVisible(TIMEOUT);
  });

  test("home 최근 import jobs heading visible", async ({ page }) => {
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "최근 import jobs" }),
    ).toBeVisible(TIMEOUT);
  });

  // nav 링크 18개 각각: visible + href 정확.
  for (const item of NAV_ITEMS) {
    test(`home nav visible+href: ${item.label}`, async ({ page }) => {
      await page.goto("/");
      const link = page
        .getByRole("navigation")
        .getByRole("link", { name: item.label, exact: true });
      await expect(link).toBeVisible(TIMEOUT);
      await expect(link).toHaveAttribute("href", item.href, TIMEOUT);
    });

    test(`home nav internal path: ${item.label}`, async ({ page }) => {
      await page.goto("/");
      const link = page
        .getByRole("navigation")
        .getByRole("link", { name: item.label, exact: true });
      const href = await link.getAttribute("href");
      expect(href).toBe(item.href);
      expect(href?.startsWith("/")).toBe(true);
      expect(href).not.toContain("://");
    });
  }

  // metric/status 카드 제목 6개.
  for (const heading of HOME_METRIC_HEADINGS) {
    test(`home metric/status heading: ${heading}`, async ({ page }) => {
      await page.goto("/");
      await expect(
        page.getByRole("heading", { name: heading, exact: true }),
      ).toBeVisible(TIMEOUT);
    });
  }

  // viewport 교차 — shell 생존.
  for (const vp of VIEWPORTS) {
    test(`home viewport ${vp.name}: H1 생존`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto("/");
      await expect(
        page.getByRole("heading", { level: 1, name: "운영 홈" }),
      ).toBeVisible(TIMEOUT);
    });

    test(`home viewport ${vp.name}: nav 생존`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto("/");
      await expect(page.getByRole("navigation")).toBeVisible(TIMEOUT);
    });
  }

  // nav 클릭으로 각 목적지 이동 — URL만 단언(read-only 내비게이션).
  for (const item of NAV_ITEMS.filter((i) => i.href !== "/")) {
    test(`home nav click → URL ${item.href}`, async ({ page }) => {
      await page.goto("/");
      await page
        .getByRole("navigation")
        .getByRole("link", { name: item.label, exact: true })
        .click();
      await expect(page).toHaveURL(
        new RegExp(`${item.href}$`),
        TIMEOUT,
      );
    });
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// /admin/dagster — 임베드 요약
// ─────────────────────────────────────────────────────────────────────────────

test.describe("misc live — /admin/dagster", () => {
  test("dagster H1 운영 + Dagster 열기 링크", async ({ page }) => {
    await page.goto("/admin/dagster");
    await expect(
      page.getByRole("heading", { level: 1, name: "Dagster 운영" }),
    ).toBeVisible(TIMEOUT);
    await expect(
      page.getByRole("link", { name: /Dagster 열기/ }),
    ).toBeVisible(TIMEOUT);
  });

  test("dagster embed testid visible", async ({ page }) => {
    await page.goto("/admin/dagster");
    await expect(page.getByTestId("dagster-embed")).toBeVisible(TIMEOUT);
  });

  for (const heading of DAGSTER_HEADINGS) {
    test(`dagster heading: ${heading}`, async ({ page }) => {
      await page.goto("/admin/dagster");
      await expect(
        page.getByRole("heading", { name: heading }),
      ).toBeVisible(TIMEOUT);
    });
  }

  for (const vp of VIEWPORTS) {
    test(`dagster viewport ${vp.name}: H1 생존`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto("/admin/dagster");
      await expect(
        page.getByRole("heading", { level: 1, name: "Dagster 운영" }),
      ).toBeVisible(TIMEOUT);
    });
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// /etl — provider 드롭다운 로드 + 선택(비파괴 GET). Preview 실행은 클릭하지 않는다.
// ─────────────────────────────────────────────────────────────────────────────

const ETL_PROVIDERS: ReadonlyArray<string> = [
  "data.go.kr-standard",
  "python-kma-api",
  "python-krex-api",
  "python-opinet-api",
];

test.describe("misc live — /etl preview", () => {
  test("etl H1 visible", async ({ page }) => {
    await page.goto("/etl");
    await expect(
      page.getByRole("heading", { level: 1, name: "ETL preview" }),
    ).toBeVisible(TIMEOUT);
  });

  test("etl provider select 존재", async ({ page }) => {
    await page.goto("/etl");
    await expect(page.locator("main select").nth(0)).toBeVisible(TIMEOUT);
  });

  // provider 드롭다운에 각 provider option이 attached.
  for (const name of ETL_PROVIDERS) {
    test(`etl provider option attached: ${name}`, async ({ page }) => {
      await page.goto("/etl");
      const providerSelect = page.locator("main select").nth(0);
      await expect(
        providerSelect.locator("option", { hasText: name }),
      ).toBeAttached(TIMEOUT);
    });

    // provider 선택(select GET 조회) — 비파괴. dataset select가 그대로 노출되는지.
    test(`etl provider select → dataset select visible: ${name}`, async ({
      page,
    }) => {
      await page.goto("/etl");
      const selects = page.locator("main select");
      await expect(selects.nth(0)).toBeVisible(TIMEOUT);
      await selects.nth(0).selectOption(name);
      await expect(selects.nth(1)).toBeVisible(TIMEOUT);
    });
  }

  for (const vp of VIEWPORTS) {
    test(`etl viewport ${vp.name}: H1 생존`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto("/etl");
      await expect(
        page.getByRole("heading", { level: 1, name: "ETL preview" }),
      ).toBeVisible(TIMEOUT);
    });
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// /admin/features/change-requests — 빈/컨테이너, 필터, columnheader
// ─────────────────────────────────────────────────────────────────────────────

const CHANGE_STATUS_OPTIONS: ReadonlyArray<string> = [
  "all",
  "pending",
  "applied",
  "rejected",
];

const CHANGE_ACTION_FILTER_OPTIONS: ReadonlyArray<string> = [
  "add",
  "update",
  "delete",
];

test.describe("misc live — /admin/features/change-requests", () => {
  test("change-requests H1 + form heading", async ({ page }) => {
    await page.goto("/admin/features/change-requests");
    await expect(
      page.getByRole("heading", { level: 1, name: "Feature change requests" }),
    ).toBeVisible(TIMEOUT);
    await expect(page.getByText("Change request form")).toBeVisible(TIMEOUT);
  });

  test("change-requests 상세 placeholder visible", async ({ page }) => {
    await page.goto("/admin/features/change-requests");
    await expect(page.getByText("요청 행을 선택하면")).toBeVisible(TIMEOUT);
  });

  for (const label of CHANGE_REQUEST_LABELS) {
    test(`change-requests label visible: ${label}`, async ({ page }) => {
      await page.goto("/admin/features/change-requests");
      await expect(
        page.getByLabel(label, { exact: true }),
      ).toBeVisible(TIMEOUT);
    });
  }

  for (const column of CHANGE_REQUEST_COLUMNS) {
    test(`change-requests columnheader: ${column}`, async ({ page }) => {
      await page.goto("/admin/features/change-requests");
      await expect(
        page.getByRole("columnheader", { name: column }),
      ).toBeVisible(TIMEOUT);
    });
  }

  // status 필터 변경(GET 조회) — 컨테이너/H1 생존 확인(read-only).
  for (const status of CHANGE_STATUS_OPTIONS) {
    test(`change-requests status filter → ${status}`, async ({ page }) => {
      await page.goto("/admin/features/change-requests");
      await page
        .getByLabel("change status", { exact: true })
        .selectOption(status);
      await expect(
        page.getByRole("heading", {
          level: 1,
          name: "Feature change requests",
        }),
      ).toBeVisible(TIMEOUT);
    });
  }

  // action filter 변경(GET 조회).
  for (const action of CHANGE_ACTION_FILTER_OPTIONS) {
    test(`change-requests action filter → ${action}`, async ({ page }) => {
      await page.goto("/admin/features/change-requests");
      await page
        .getByLabel("change action filter", { exact: true })
        .selectOption(action);
      await expect(
        page.getByRole("heading", {
          level: 1,
          name: "Feature change requests",
        }),
      ).toBeVisible(TIMEOUT);
    });
  }

  // page size select 변경(GET 조회).
  for (const size of F.PAGE_SIZES) {
    test(`change-requests page size → ${size}`, async ({ page }) => {
      await page.goto("/admin/features/change-requests");
      await page
        .getByLabel("change page size", { exact: true })
        .selectOption(String(size));
      await expect(
        page.getByRole("heading", {
          level: 1,
          name: "Feature change requests",
        }),
      ).toBeVisible(TIMEOUT);
    });
  }

  // 검색창 타이핑(GET 조회 허용). 제출 버튼은 누르지 않는다.
  for (const term of F.SEARCH_TERMS.slice(0, 8)) {
    test(`change-requests search type: ${term}`, async ({ page }) => {
      await page.goto("/admin/features/change-requests");
      await page.getByLabel("change search").fill(term);
      await expect(
        page.getByRole("heading", {
          level: 1,
          name: "Feature change requests",
        }),
      ).toBeVisible(TIMEOUT);
    });
  }

  for (const vp of VIEWPORTS) {
    test(`change-requests viewport ${vp.name}: H1 생존`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto("/admin/features/change-requests");
      await expect(
        page.getByRole("heading", {
          level: 1,
          name: "Feature change requests",
        }),
      ).toBeVisible(TIMEOUT);
    });
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// /admin/features/new — 폼 렌더 + 클라이언트 검증 표면(제출 금지)
// ─────────────────────────────────────────────────────────────────────────────

test.describe("misc live — /admin/features/new", () => {
  test("new feature H1 + 제출 버튼 렌더", async ({ page }) => {
    await page.goto("/admin/features/new");
    await expect(
      page.getByRole("heading", { level: 1, name: "New feature" }),
    ).toBeVisible(TIMEOUT);
    await expect(
      page.getByRole("button", { name: "요청 생성" }),
    ).toBeVisible(TIMEOUT);
  });

  test("new feature 핵심 필드 visible", async ({ page }) => {
    await page.goto("/admin/features/new");
    await expect(
      page.getByLabel("name", { exact: true }),
    ).toBeVisible(TIMEOUT);
    await expect(page.getByLabel("lon", { exact: true })).toBeVisible(TIMEOUT);
    await expect(page.getByLabel("lat", { exact: true })).toBeVisible(TIMEOUT);
  });

  test("new feature category 기본값 01070300", async ({ page }) => {
    await page.goto("/admin/features/new");
    await expect(page.getByLabel("category", { exact: true })).toHaveValue(
      "01070300",
      TIMEOUT,
    );
  });

  test("new feature kind 기본값 place", async ({ page }) => {
    await page.goto("/admin/features/new");
    await expect(page.getByLabel("kind", { exact: true })).toHaveValue(
      "place",
      TIMEOUT,
    );
  });

  // 폼 섹션 h2 6개.
  for (const section of NEW_FEATURE_SECTIONS) {
    test(`new feature section h2: ${section}`, async ({ page }) => {
      await page.goto("/admin/features/new");
      await expect(
        page.getByRole("heading", { level: 2, name: section }),
      ).toBeVisible(TIMEOUT);
    });
  }

  for (const vp of VIEWPORTS) {
    test(`new feature viewport ${vp.name}: H1 생존`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto("/admin/features/new");
      await expect(
        page.getByRole("heading", { level: 1, name: "New feature" }),
      ).toBeVisible(TIMEOUT);
    });

    test(`new feature viewport ${vp.name}: name 필드 생존`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto("/admin/features/new");
      await expect(
        page.getByLabel("name", { exact: true }),
      ).toBeVisible(TIMEOUT);
    });
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// 딥링크 쿼리 — 홈 외 misc 목적지 직접 진입(read-only). URL+H1만 단언.
// ─────────────────────────────────────────────────────────────────────────────

const DEEPLINK_TARGETS: ReadonlyArray<{ href: string; h1: string }> = [
  { href: "/admin/dagster", h1: "Dagster 운영" },
  { href: "/etl", h1: "ETL preview" },
  {
    href: "/admin/features/change-requests",
    h1: "Feature change requests",
  },
  { href: "/admin/features/new", h1: "New feature" },
];

test.describe("misc live — deeplink targets", () => {
  for (const target of DEEPLINK_TARGETS) {
    test(`deeplink ${target.href} → H1 ${target.h1}`, async ({ page }) => {
      await page.goto(target.href);
      await expect(page).toHaveURL(new RegExp(`${target.href}$`), TIMEOUT);
      await expect(
        page.getByRole("heading", { level: 1, name: target.h1 }),
      ).toBeVisible(TIMEOUT);
    });

    // change-requests 검색어를 쿼리스트링 딥링크로 — GET 조회만, 컨테이너 생존.
    for (const term of F.SEARCH_TERMS.slice(0, 3)) {
      test(`deeplink ${target.href}?q=${term} → H1 생존`, async ({ page }) => {
        await page.goto(`${target.href}?q=${encodeURIComponent(term)}`);
        await expect(page).toHaveURL(new RegExp(`${target.href}`), TIMEOUT);
        await expect(
          page.getByRole("heading", { level: 1, name: target.h1 }),
        ).toBeVisible(TIMEOUT);
      });
    }
  }
});
