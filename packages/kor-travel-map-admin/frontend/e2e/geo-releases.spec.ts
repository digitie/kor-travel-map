import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";
import { bffApiPath } from "./bff-api-path";
import { installInertOpsLiveWebSocket } from "./ws-isolation";

// mock factory는 생성된 OpenAPI 스키마에 바인딩한다 — 백엔드 DTO가 바뀌면 컴파일이 깨진다.
type Schemas = components["schemas"];
type Plan = Schemas["GeoReleasePlanRecord"];
type Item = Schemas["GeoReleaseItemRecord"];
type Coverage = Schemas["GeoCoverageRecord"];
type ListResponse = Schemas["GeoReleaseListResponse"];
type DetailResponse = Schemas["GeoReleaseDetailResponse"];
type DetectResponse = Schemas["GeoReleaseDetectResponse"];
type Dataset = Schemas["GeoDatasetRecord"];

const ROUTE = "/admin/ops/geo-releases";
const TOKEN_A = `dd1-${"1".repeat(32)}`;
const TOKEN_B = `dd1-${"2".repeat(32)}`;
const META = { duration_ms: 1, request_id: "geo-release-e2e" };
const OBSERVED = "2026-10-16T03:00:00.000Z";

const CURRENT: Dataset = {
  version_token: `dv1-${"b".repeat(32)}`,
  data_token: TOKEN_B,
  activated_at: "2026-10-15T00:00:00.000Z",
  reference_months: { juso: "202609" },
};

function item(position: number, overrides: Partial<Item> = {}): Item {
  return {
    position,
    operation_key: "feature_place_krheritage_items_job",
    datasets: [
      { provider_dataset_id: 100 + position, provider: "python-krheritage-api", dataset_key: "krheritage_items" },
    ],
    run_config: null,
    launch_blocked_reason: null,
    attempt_seq: 1,
    state: "pending",
    state_reason: null,
    run_key: null,
    dagster_run_id: null,
    requested_at: null,
    ...overrides,
  };
}

function plan(planId: number, items: Item[], overrides: Partial<Plan> = {}): Plan {
  return {
    plan_id: planId,
    geo_data_token: TOKEN_B,
    plan_seq: 1,
    geo_version_token: CURRENT.version_token,
    activated_at: CURRENT.activated_at ?? null,
    reference_months: null,
    state: "running",
    residual_stale: null,
    sweep_started_at: null,
    observed_at: OBSERVED,
    completed_at: null,
    items,
    ...overrides,
  };
}

const COVERAGE: Coverage = {
  total_provider_with_coord: 35_754,
  stamped_current: 12_001,
  stamped_other: 20_500,
  unstamped: 3_253,
  not_called_by_kind: { place: 977, event: 3 },
  excluded_by_skip: 41,
  unstamped_non_provider: 7,
};

type Mock = {
  current: Dataset | null;
  status: ListResponse["data"]["current_status"];
  plans: Plan[];
  calls: string[];
};

async function fulfill(route: Route, body: unknown, status = 200) {
  await route.fulfill({ body: JSON.stringify(body), contentType: "application/json", status });
}

/** 상태를 들고 있는 mock — skip·detect·replan이 다음 GET에 반영된다. */
async function mockGeoReleases(page: Page, mock: Mock): Promise<void> {
  await page.route("**/api/proxy/v1/ops/geo-releases**", async (route) => {
    const request = route.request();
    const path = bffApiPath(request.url());
    mock.calls.push(`${request.method()} ${path}`);
    if (request.method() === "GET" && path === "/v1/ops/geo-releases") {
      const list: ListResponse = {
        data: {
          current: mock.current,
          current_status: mock.status,
          plans: mock.plans.map((value) => ({ ...value, items: [] })),
        },
        meta: META,
      };
      return fulfill(route, list);
    }
    if (request.method() === "POST" && path === "/v1/ops/geo-releases/detect") {
      const created = plan(9, [item(1)], { plan_seq: 1 });
      mock.plans = [created, ...mock.plans];
      const body: DetectResponse = {
        data: { outcome: "created", current: CURRENT, plan: created, superseded_plan_ids: [] },
        meta: META,
      };
      return fulfill(route, body);
    }
    const skip = path.match(/^\/v1\/ops\/geo-releases\/(\d+)\/items\/(\d+)\/skip$/);
    if (request.method() === "POST" && skip) {
      const [planId, position] = [Number(skip[1]), Number(skip[2])];
      mock.plans = mock.plans.map((value) =>
        value.plan_id !== planId
          ? value
          : {
              ...value,
              items: value.items.map((entry) =>
                entry.position === position
                  ? { ...entry, state: "skipped", state_reason: "operator" }
                  : entry,
              ),
            },
      );
    }
    const replan = path.match(/^\/v1\/ops\/geo-releases\/(\d+)\/replan$/);
    if (request.method() === "POST" && replan) {
      const source = mock.plans.find((value) => value.plan_id === Number(replan[1]));
      const next = plan(11, source?.items ?? [], { plan_seq: (source?.plan_seq ?? 1) + 1 });
      mock.plans = [next, ...mock.plans.map((value) => ({ ...value, state: "superseded" as const }))];
      const body: DetailResponse = { data: { plan: next, coverage: COVERAGE }, meta: META };
      return fulfill(route, body);
    }
    const detail = path.match(/^\/v1\/ops\/geo-releases\/(\d+)(?:\/items\/\d+\/skip)?$/);
    if (detail) {
      const found = mock.plans.find((value) => value.plan_id === Number(detail[1]));
      if (!found) return fulfill(route, { detail: "없는 계획" }, 404);
      const body: DetailResponse = { data: { plan: found, coverage: COVERAGE }, meta: META };
      return fulfill(route, body);
    }
    throw new Error(`unmocked geo-releases call: ${request.method()} ${path}`);
  });
}

function runningPlan(): Plan {
  return plan(7, [
    item(1),
    item(2, {
      operation_key: "feature_place_mois_licenses_job",
      datasets: [{ provider_dataset_id: 30, provider: "python-mois-api", dataset_key: "mois_license_features_bulk" }],
      launch_blocked_reason: "replay_not_launchable_before_t_gr_08",
    }),
    item(3, {
      operation_key: "feature_place_standard_museums_job",
      run_config: { resources: { standard_museums: { config: { source_mode: "replay" } } } },
      state: "done",
      dagster_run_id: "0b7f5a8e-1111-4222-8333-444455556666",
      run_key: `geo_release/${TOKEN_B}/1/feature_place_standard_museums_job/3/1`,
    }),
  ]);
}

test.describe(`${ROUTE} (T-GR-06)`, () => {
  test.beforeEach(async ({ page }) => {
    await installInertOpsLiveWebSocket(page);
    // 구체 route가 우선 — 처리되지 않은 REST는 이 guard가 잡아 backend 독립성을 강제한다.
    await page.route("**/api/proxy/v1/**", (route) => {
      const request = route.request();
      throw new Error(`Unmocked REST call: ${request.method()} ${bffApiPath(request.url())}`);
    });
  });

  test("커버리지 게이지 수치가 API 응답과 일치한다", async ({ page }) => {
    const mock: Mock = { current: CURRENT, status: "ok", plans: [runningPlan()], calls: [] };
    await mockGeoReleases(page, mock);
    await page.goto(ROUTE);

    await expect(page.getByRole("heading", { level: 1, name: "geo 릴리스" })).toBeVisible();
    await expect(page.getByTestId("geo-coverage-ratio")).toHaveText("12,001 / 35,754 (33.6%)");
    const meter = page.getByRole("meter", { name: "현재 토큰 커버리지" });
    await expect(meter).toHaveAttribute("aria-valuenow", "33.6");
    for (const [testId, value] of [
      ["geo-coverage-stamped-other", "20,500"],
      ["geo-coverage-unstamped", "3,253"],
      ["geo-coverage-not-called", "980"],
      ["geo-coverage-excluded", "41"],
      ["geo-coverage-non-provider", "7"],
    ] as const) {
      await expect(page.getByTestId(testId)).toContainText(value);
    }
    await expect(page.getByTestId("geo-coverage-not-called")).toContainText("place 977 · event 3");
    await page.screenshot({ fullPage: true, path: test.info().outputPath("geo-releases-desktop.png") });
    // 현재 토큰은 정상 — 빨간 상태가 없다.
    await expect(page.getByTestId("geo-release-skip-reason")).toHaveCount(0);
    // run 링크는 Dagster run id로 간다.
    await expect(
      page.getByTestId("geo-release-item-3").getByRole("link", { name: "0b7f5a8e" }),
    ).toHaveAttribute("href", /\/runs\/0b7f5a8e-1111-4222-8333-444455556666$/);
  });

  test("항목 건너뛰기 → 확인 → 배지가 건너뜀이 된다", async ({ page }) => {
    const mock: Mock = { current: CURRENT, status: "ok", plans: [runningPlan()], calls: [] };
    await mockGeoReleases(page, mock);
    await page.goto(ROUTE);

    const row = page.getByTestId("geo-release-item-1");
    await expect(row).toContainText("대기");
    await row.getByRole("button", { name: "항목 1 건너뛰기" }).click();
    await page
      .getByRole("alertdialog")
      .getByRole("button", { name: "건너뛰기", exact: true })
      .click();
    await expect(row).toContainText("건너뜀");
    await expect(row).toContainText("운영자 건너뜀");
    await expect(row.getByRole("button", { name: "항목 1 건너뛰기" })).toHaveCount(0);
    expect(mock.calls.filter((call) => call === "POST /v1/ops/geo-releases/7/items/1/skip")).toHaveLength(1);
    // 끝난 항목에는 건너뛰기가 없다.
    await expect(
      page.getByTestId("geo-release-item-3").getByRole("button", { name: /건너뛰기/ }),
    ).toHaveCount(0);
  });

  test("MOIS 항목은 기존 차단 사유를 그대로 보이지 않고 수동 실행 안내를 보인다", async ({ page }) => {
    const mock: Mock = { current: CURRENT, status: "ok", plans: [runningPlan()], calls: [] };
    await mockGeoReleases(page, mock);
    await page.goto(ROUTE);

    const mois = page.getByTestId("geo-release-item-2");
    await expect(mois).toContainText("수동 실행 후 skip 필요");
    await expect(mois).not.toContainText("replay_not_launchable_before_t_gr_08");
    await expect(page.getByTestId("geo-release-item-1")).not.toContainText("수동 실행 후 skip 필요");
  });

  test("지금 감지 → /detect 정확히 1회, 새 계획 행이 보인다", async ({ page }) => {
    const mock: Mock = { current: CURRENT, status: "ok", plans: [], calls: [] };
    await mockGeoReleases(page, mock);
    await page.goto(ROUTE);
    await expect(page.getByText("계획이 없습니다.")).toBeVisible();

    await page.getByRole("button", { name: "지금 감지" }).click();
    await expect(page.getByTestId("geo-release-detect-outcome")).toContainText("새 계획을 만들었다");
    await expect(page.getByTestId("geo-release-plan-9")).toBeVisible();
    await expect(page.getByTestId("geo-release-plan-9")).toContainText("#9 · seq 1");
    expect(mock.calls.filter((call) => call === "POST /v1/ops/geo-releases/detect")).toHaveLength(1);
  });

  test("data_token 없음 → 빨간 상태 + 센서 Skip 사유", async ({ page }) => {
    const mock: Mock = {
      current: { ...CURRENT, data_token: null },
      status: "no_token",
      plans: [plan(5, [], { state: "baseline", geo_data_token: TOKEN_A })],
      calls: [],
    };
    await mockGeoReleases(page, mock);
    await page.goto(ROUTE);

    const alert = page.getByRole("alert").filter({ hasText: "계획을 만들 수 없음" });
    await expect(alert).toBeVisible();
    await expect(page.getByTestId("geo-release-skip-reason")).toHaveText(
      "센서 Skip 사유: geo data_token 없음 — 지문 backfill/복구 필요",
    );
    await expect(page.getByText("data_token 없음", { exact: true })).toBeVisible();
    // 기준선 계획은 다시 계획할 수 없다.
    await expect(page.getByRole("button", { name: "다시 계획" })).toHaveCount(0);
  });

  test("다시 계획은 확인 뒤 한 번만 보낸다", async ({ page }) => {
    const mock: Mock = { current: CURRENT, status: "ok", plans: [runningPlan()], calls: [] };
    await mockGeoReleases(page, mock);
    await page.goto(ROUTE);

    await page.getByRole("button", { name: "다시 계획" }).click();
    const dialog = page.getByRole("alertdialog");
    await dialog.getByRole("button", { name: "취소" }).click();
    // 닫힘 애니메이션 동안 dialog의 같은 이름 버튼이 남아 있다 — 사라진 뒤 다시 연다.
    await expect(dialog).toHaveCount(0);
    expect(mock.calls.filter((call) => call.endsWith("/replan"))).toHaveLength(0);

    await page.getByRole("button", { name: "다시 계획" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "다시 계획" }).click();
    await expect(page.getByTestId("geo-release-plan-11")).toBeVisible();
    expect(mock.calls.filter((call) => call === "POST /v1/ops/geo-releases/7/replan")).toHaveLength(1);
  });

  test("모바일 375px — 가로 스크롤 없이 핵심 영역이 보인다", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    const mock: Mock = { current: CURRENT, status: "ok", plans: [runningPlan()], calls: [] };
    await mockGeoReleases(page, mock);
    await page.goto(ROUTE);

    await expect(page.getByRole("heading", { level: 1, name: "geo 릴리스" })).toBeVisible();
    await expect(page.getByRole("button", { name: "지금 감지" })).toBeVisible();
    await expect(page.getByTestId("geo-coverage-ratio")).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
    // 시각 점검용 증거(실패 판정 아님).
    await page.screenshot({ fullPage: true, path: test.info().outputPath("geo-releases-375.png") });
  });
});
