import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";
import { installInertOpsLiveWebSocket } from "./ws-isolation";

// 이번 세션 admin UI 작업의 live UI e2e (route-mock; live n150에서 실행):
//   - #608: Refresh policy 폼 — 소스 종류는 read-only(자동), rate-limit은 기본값 사전 채움
//   - i18n: /ops/providers 등 우선 페이지가 한국어 라벨/필드 설명으로 표기
// providers-refresh-policy.spec.ts idiom(OpsProviders mock + pathname 분기).

type Meta = components["schemas"]["Meta"];
type OpsProviderDatasetSummary =
  components["schemas"]["OpsProviderDatasetSummary"];
type OpsProviderDatasetDetail =
  components["schemas"]["OpsProviderDatasetDetail"];
type OpsProviderDetailResponse =
  components["schemas"]["OpsProviderDetailResponse"];
type OpsProvidersResponse = components["schemas"]["OpsProvidersResponse"];

const KMA_PROVIDER = "python-kma-api";
const KMA_DATASET = "kma_ultra_short_grid";
const MOCK_NOW = "2026-06-29T00:00:00.000Z";

function makeMeta(requestId: string): Meta {
  return { duration_ms: 1, request_id: requestId };
}

function makeOpsProviderDataset(
  overrides: Partial<OpsProviderDatasetSummary> = {},
): OpsProviderDatasetSummary {
  return {
    provider: KMA_PROVIDER,
    dataset_key: KMA_DATASET,
    sync_scope: "default",
    status: "active",
    last_success_at: MOCK_NOW,
    last_failure_at: null,
    next_run_after: null,
    consecutive_failures: 0,
    links: [],
    refresh_policy: null,
    ...overrides,
  };
}

function makeDatasetDetail(
  overrides: Partial<OpsProviderDatasetDetail> = {},
): OpsProviderDatasetDetail {
  return {
    provider: KMA_PROVIDER,
    dataset_key: KMA_DATASET,
    links: [],
    recent_update_requests: [],
    refresh_policy: null,
    sync_states: [],
    ...overrides,
  };
}

function makeProvidersResponse(
  items: OpsProviderDatasetSummary[],
): OpsProvidersResponse {
  return { data: { items }, meta: makeMeta("e2e-session-ops-providers") };
}

function makeDetailResponse(
  provider: string,
  datasets: OpsProviderDatasetDetail[],
): OpsProviderDetailResponse {
  return {
    data: { provider, datasets },
    meta: makeMeta("e2e-session-ops-provider-detail"),
  };
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

async function mockOpsProviders(
  page: Page,
  options: {
    items: OpsProviderDatasetSummary[];
    details?: Record<string, OpsProviderDatasetDetail[]>;
  },
) {
  await page.route("**/v1/ops/providers**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/v1/ops/providers") {
      await fulfillJson(route, makeProvidersResponse(options.items));
      return;
    }
    const provider = decodeURIComponent(
      url.pathname.replace("/v1/ops/providers/", ""),
    );
    const datasets = options.details?.[provider] ?? [];
    await fulfillJson(route, makeDetailResponse(provider, datasets));
  });
}

test.describe("/ops/providers — Refresh policy 기본값 + 한국어 (#608)", () => {
  test.beforeEach(async ({ page }) => {
    await installInertOpsLiveWebSocket(page);
  });

  test("신규 정책: 소스 종류 read-only(자동) + rate-limit 기본값 사전 채움", async ({
    page,
  }) => {
    await mockOpsProviders(page, {
      items: [makeOpsProviderDataset({ refresh_policy: null })],
      details: {
        [KMA_PROVIDER]: [makeDatasetDetail({ refresh_policy: null })],
      },
    });
    await page.goto("/ops/providers");

    // 폼이 렌더되면 소스 종류 필드가 보인다 — read-only(사람이 고르는 드롭다운 아님).
    const sourceKind = page.getByLabel("소스 종류");
    await expect(sourceKind).toBeVisible();
    await expect(sourceKind).not.toBeEditable();

    // rate-limit·동시·버스트 기본값이 비어 있지 않고 보수적 기본값으로 채워져 있다.
    await expect(page.getByLabel("분당 요청 수")).toHaveValue("60");
    await expect(page.getByLabel("시간당 요청 수")).toHaveValue("1000");
    await expect(page.getByLabel("일일 요청 수")).toHaveValue("10000");
    await expect(page.getByLabel("최대 동시 실행")).toHaveValue("1");
    await expect(page.getByLabel("버스트 크기")).toHaveValue("10");
  });

  test("providers 페이지 폼 라벨·필드 설명이 한국어로 표기된다", async ({
    page,
  }) => {
    await mockOpsProviders(page, {
      items: [makeOpsProviderDataset({ refresh_policy: null })],
      details: {
        [KMA_PROVIDER]: [makeDatasetDetail({ refresh_policy: null })],
      },
    });
    await page.goto("/ops/providers");

    // 우선 페이지(providers) 한국어 라벨 + 한 문장 필드 설명(hint).
    for (const label of [
      "소스 종류",
      "타깃 갱신 정책",
      "분당 요청 수",
      "시간당 요청 수",
      "일일 요청 수",
      "최대 동시 실행",
      "버스트 크기",
    ]) {
      await expect(page.getByText(label, { exact: false }).first()).toBeVisible();
    }
    // 필드 설명(hint) 한국어 — 일일 요청 수 설명 문장.
    await expect(
      page.getByText("하루 동안 보낼 수 있는 최대 요청 수", { exact: false }),
    ).toBeVisible();
  });
});
