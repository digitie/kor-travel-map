import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";

// 손으로 쓴 record shape 대신 **생성된 OpenAPI 스키마**에 바인딩한다(#308 리뷰).
// 백엔드 DTO가 바뀌면 mock factory가 타입 불일치로 컴파일 실패 → mock-실계약 drift 감지.
// 본 spec은 admin-ops.spec.ts의 /ops/providers smoke(T-217g)가 다루지 않는
// **깊이**(refresh policy PUT, client validation, recent-request/job 링크,
// cursor JSON, row→detail 재선택, empty/error 분기)만 추가한다.
type Meta = components["schemas"]["Meta"];
type OpsProviderDatasetSummary =
  components["schemas"]["OpsProviderDatasetSummary"];
type OpsProviderDatasetDetail =
  components["schemas"]["OpsProviderDatasetDetail"];
type OpsProviderDetailResponse =
  components["schemas"]["OpsProviderDetailResponse"];
type OpsProvidersResponse = components["schemas"]["OpsProvidersResponse"];
type OpsProviderSyncStateDetail =
  components["schemas"]["OpsProviderSyncStateDetail"];
type OpsProviderUpdateRequestSummary =
  components["schemas"]["OpsProviderUpdateRequestSummary"];
type ProviderRefreshPolicyRecord =
  components["schemas"]["ProviderRefreshPolicyRecord"];
type ProviderRefreshPolicyResponse =
  components["schemas"]["ProviderRefreshPolicyResponse"];
type ProviderRefreshPolicyUpsertRequest =
  components["schemas"]["ProviderRefreshPolicyUpsertRequest"];

const MOCK_NOW = "2026-06-08T00:00:00.000Z";
const KMA_PROVIDER = "python-kma-api";
const KMA_DATASET = "kma_weather_values";
const MOIS_PROVIDER = "python-mois-api";
const MOIS_DATASET = "mois_license_features_bulk";
const REQUEST_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const JOB_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";

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

function makeRefreshPolicy(
  overrides: Partial<ProviderRefreshPolicyRecord> = {},
): ProviderRefreshPolicyRecord {
  return {
    provider: KMA_PROVIDER,
    dataset_key: KMA_DATASET,
    source_kind: "openapi",
    targeted_policy: "allow_targeted",
    config_source: "db",
    enabled: true,
    max_concurrent: 1,
    system_interval_seconds: 3600,
    optimal_interval_seconds: null,
    min_interval_seconds: null,
    max_requests_per_minute: 30,
    max_requests_per_hour: null,
    max_requests_per_day: null,
    burst_size: null,
    rate_limit_source: {},
    created_at: MOCK_NOW,
    updated_at: "2026-06-08T00:30:00.000Z",
    ...overrides,
  };
}

function makeSyncState(
  overrides: Partial<OpsProviderSyncStateDetail> = {},
): OpsProviderSyncStateDetail {
  return {
    sync_scope: "default",
    status: "active",
    last_success_at: MOCK_NOW,
    last_failure_at: null,
    next_run_after: null,
    consecutive_failures: 0,
    cursor: {},
    ...overrides,
  };
}

function makeUpdateRequest(
  overrides: Partial<OpsProviderUpdateRequestSummary> = {},
): OpsProviderUpdateRequestSummary {
  return {
    request_id: REQUEST_ID,
    job_id: JOB_ID,
    dagster_run_id: null,
    status: "succeeded",
    run_mode: "queued",
    dry_run: false,
    status_url: `/v1/admin/feature-update-requests/${REQUEST_ID}`,
    created_at: MOCK_NOW,
    updated_at: MOCK_NOW,
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
    sync_states: [makeSyncState()],
    ...overrides,
  };
}

function makeProvidersResponse(
  items: OpsProviderDatasetSummary[],
): OpsProvidersResponse {
  return { data: { items }, meta: makeMeta("e2e-ops-providers") };
}

function makeDetailResponse(
  provider: string,
  datasets: OpsProviderDatasetDetail[],
): OpsProviderDetailResponse {
  return {
    data: { provider, datasets },
    meta: makeMeta("e2e-ops-provider-detail"),
  };
}

function makePolicyResponse(
  policy: ProviderRefreshPolicyRecord,
): ProviderRefreshPolicyResponse {
  return { data: policy, meta: makeMeta("e2e-policy-upsert") };
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

/**
 * `/v1/ops/providers`(목록) + `/v1/ops/providers/{provider}`(상세)를 같은 glob로
 * 잡되 `URL.pathname`으로 분기한다(T-217g idiom). 상세는 provider별 detail map에서
 * 꺼내 반환해 selectedDetail(dataset_key 매칭)이 항상 채워지게 한다.
 */
async function mockOpsProviders(
  page: Page,
  options: {
    items: OpsProviderDatasetSummary[];
    details?: Record<string, OpsProviderDatasetDetail[]>;
  },
) {
  const counts = { list: 0, detail: 0 };
  const detailPaths: string[] = [];

  await page.route("**/v1/ops/providers**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/v1/ops/providers") {
      counts.list += 1;
      await fulfillJson(route, makeProvidersResponse(options.items));
      return;
    }
    counts.detail += 1;
    detailPaths.push(url.pathname);
    const provider = decodeURIComponent(
      url.pathname.replace("/v1/ops/providers/", ""),
    );
    const datasets = options.details?.[provider] ?? [];
    await fulfillJson(route, makeDetailResponse(provider, datasets));
  });

  return { counts, detailPaths };
}

async function mockPolicyUpsert(page: Page) {
  const puts: { path: string; body: ProviderRefreshPolicyUpsertRequest }[] = [];

  await page.route(
    "**/v1/admin/provider-refresh-policies/**",
    async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (request.method() !== "PUT") {
        throw new Error(`Unexpected policy method: ${request.method()} ${url}`);
      }
      const body = request.postDataJSON() as ProviderRefreshPolicyUpsertRequest;
      puts.push({ path: url.pathname, body });
      // 응답 record는 보낸 body를 반영하되 record 필수 필드를 채워 contract를 맞춘다.
      await fulfillJson(
        route,
        makePolicyResponse(
          makeRefreshPolicy({
            provider: KMA_PROVIDER,
            dataset_key: KMA_DATASET,
            source_kind: body.source_kind,
            targeted_policy: body.targeted_policy,
            system_interval_seconds: body.system_interval_seconds ?? null,
            max_requests_per_minute: body.max_requests_per_minute ?? null,
            max_concurrent: body.max_concurrent,
            config_source: body.config_source,
            enabled: body.enabled,
            rate_limit_source: body.rate_limit_source ?? {},
          }),
        ),
      );
    },
  );

  return { puts };
}

test.describe("/ops/providers refresh policy depth", () => {
  test("policy edit fires PUT with coerced body and shows saved badge", async ({
    page,
  }) => {
    const item = makeOpsProviderDataset();
    const { counts } = await mockOpsProviders(page, {
      items: [item],
      details: { [KMA_PROVIDER]: [makeDatasetDetail({ refresh_policy: null })] },
    });
    const policy = await mockPolicyUpsert(page);

    await page.goto("/ops/providers");

    await expect(
      page.getByRole("heading", { level: 1, name: "Providers" }),
    ).toBeVisible();
    // 첫 행(kma)이 자동 선택되어 PolicyEditor가 빈 draft로 뜬다.
    await expect(page.getByText("Refresh policy")).toBeVisible();
    await expect.poll(() => counts.detail).toBeGreaterThanOrEqual(1);

    await page.getByLabel("targeted policy").selectOption("allow_targeted");
    await page.getByLabel("system interval sec").fill("3600");
    await page.getByLabel("requests / min").fill("30");

    await page.getByRole("button", { name: "저장" }).click();

    await expect.poll(() => policy.puts.length).toBe(1);
    expect(policy.puts[0].path).toBe(
      `/v1/admin/provider-refresh-policies/${KMA_PROVIDER}/${KMA_DATASET}`,
    );
    // buildPolicyBody: 빈 numeric → undefined(=JSON에서 생략), max_concurrent 기본 1,
    // rate_limit_source는 textarea seed `{}`에서 파싱.
    expect(policy.puts[0].body).toMatchObject({
      source_kind: "openapi",
      targeted_policy: "allow_targeted",
      system_interval_seconds: 3600,
      max_requests_per_minute: 30,
      max_concurrent: 1,
      config_source: "db",
      enabled: true,
      rate_limit_source: {},
    });
    expect(policy.puts[0].body.optimal_interval_seconds).toBeUndefined();
    expect(policy.puts[0].body.burst_size).toBeUndefined();

    // 200 후 saved Badge(updated_at → formatDateTime).
    await expect(page.getByText(/^saved /)).toBeVisible();
  });

  test("invalid positive-int field blocks PUT (client validation)", async ({
    page,
  }) => {
    const { counts } = await mockOpsProviders(page, {
      items: [makeOpsProviderDataset()],
      details: { [KMA_PROVIDER]: [makeDatasetDetail()] },
    });
    const policy = await mockPolicyUpsert(page);

    await page.goto("/ops/providers");
    await expect(page.getByText("Refresh policy")).toBeVisible();
    await expect.poll(() => counts.detail).toBeGreaterThanOrEqual(1);

    // 0은 양의 정수가 아니므로 optionalPositiveInt가 throw → 네트워크 호출 없음.
    await page.getByLabel("requests / hour").fill("0");
    await page.getByRole("button", { name: "저장" }).click();

    await expect(
      page.getByText("requests/hour 값은 양의 정수여야 합니다."),
    ).toBeVisible();
    await expect(
      page
        .getByRole("alert")
        .filter({ hasText: "policy 저장 실패" }),
    ).toBeVisible();
    await expect.poll(() => policy.puts.length).toBe(0);
  });

  test("rate_limit_source non-object JSON blocks PUT", async ({ page }) => {
    const { counts } = await mockOpsProviders(page, {
      items: [makeOpsProviderDataset()],
      details: { [KMA_PROVIDER]: [makeDatasetDetail()] },
    });
    const policy = await mockPolicyUpsert(page);

    await page.goto("/ops/providers");
    await expect(page.getByText("Refresh policy")).toBeVisible();
    await expect.poll(() => counts.detail).toBeGreaterThanOrEqual(1);

    // `[]`는 array(object 아님) → buildPolicyBody가 동기 throw → PUT 미발생.
    await page.getByLabel("rate limit source").fill("[]");
    await page.getByRole("button", { name: "저장" }).click();

    await expect(
      page.getByText("rate_limit_source 값은 JSON object여야 합니다."),
    ).toBeVisible();
    await expect(
      page.getByRole("alert").filter({ hasText: "policy 저장 실패" }),
    ).toBeVisible();
    await expect.poll(() => policy.puts.length).toBe(0);
  });

  test("recent update-request row renders request/job/detail links", async ({
    page,
  }) => {
    const detail = makeDatasetDetail({
      recent_update_requests: [makeUpdateRequest()],
    });
    await mockOpsProviders(page, {
      items: [makeOpsProviderDataset()],
      details: { [KMA_PROVIDER]: [detail] },
    });

    await page.goto("/ops/providers");
    await expect(page.getByText("Dataset detail")).toBeVisible();

    // recent-requests 테이블만 `job`/`link` 헤더로 한정(다른 테이블과 헤더 충돌 회피).
    const recentTable = page.getByRole("table").filter({
      has: page.getByRole("columnheader", { name: "job" }),
    });
    await expect(
      recentTable.getByRole("columnheader", { name: "link" }),
    ).toBeVisible();

    const requestRow = recentTable.getByRole("row", {
      name: new RegExp(REQUEST_ID.slice(0, 12)),
    });
    await expect(requestRow).toBeVisible();
    await expect(requestRow.getByRole("link", { name: "상세" })).toHaveAttribute(
      "href",
      `/admin/feature-update-requests/${REQUEST_ID}`,
    );
    await expect(
      requestRow.getByRole("link", { name: JOB_ID.slice(0, 12) }),
    ).toHaveAttribute("href", `/ops/import-jobs/${JOB_ID}`);
  });

  test("sync_state cursor JSON renders in Cursor block", async ({ page }) => {
    const detail = makeDatasetDetail({
      sync_states: [
        makeSyncState({
          cursor: { last_id: "abc123", updated_at: "2026-06-08T00:00:00Z" },
        }),
      ],
    });
    await mockOpsProviders(page, {
      items: [makeOpsProviderDataset()],
      details: { [KMA_PROVIDER]: [detail] },
    });

    await page.goto("/ops/providers");
    // Cursor 카드 + JSON.stringify(cursor, null, 2) 직렬화 확인.
    await expect(page.getByText("Cursor")).toBeVisible();
    await expect(page.getByText(/"last_id": "abc123"/)).toBeVisible();
  });

  test("row click re-selects dataset and re-keys detail/policy panels", async ({
    page,
  }) => {
    const kma = makeOpsProviderDataset();
    const mois = makeOpsProviderDataset({
      provider: MOIS_PROVIDER,
      dataset_key: MOIS_DATASET,
      last_failure_at: "2026-06-10T02:00:00.000Z",
      consecutive_failures: 3,
    });
    const { detailPaths } = await mockOpsProviders(page, {
      items: [kma, mois],
      details: {
        [KMA_PROVIDER]: [makeDatasetDetail()],
        [MOIS_PROVIDER]: [
          makeDatasetDetail({
            provider: MOIS_PROVIDER,
            dataset_key: MOIS_DATASET,
          }),
        ],
      },
    });

    await page.goto("/ops/providers");

    // 로드 시 items[0](kma)가 자동 선택 → detail/policy 패널 mono subheading.
    await expect(
      page.getByText(`${KMA_PROVIDER}/${KMA_DATASET}`).first(),
    ).toBeVisible();

    // freshness 테이블의 mois 행 클릭(아이콘 detail 버튼 대신 row click = house idiom).
    const freshnessTable = page.getByRole("table").filter({
      has: page.getByRole("columnheader", { name: "policy" }),
    });
    await freshnessTable.getByRole("row", { name: /python-mois-api/ }).click();

    // 상세 GET이 mois로 발화(URL-encoded provider 세그먼트).
    await expect
      .poll(() => detailPaths.some((p) => p.includes(MOIS_PROVIDER)))
      .toBe(true);
    // 패널이 provider/dataset 키로 remount → mono subheading 갱신.
    await expect(
      page.getByText(`${MOIS_PROVIDER}/${MOIS_DATASET}`).first(),
    ).toBeVisible();
  });

  test("empty providers list shows empty table and no-selection placeholder", async ({
    page,
  }) => {
    const { counts } = await mockOpsProviders(page, { items: [] });

    await page.goto("/ops/providers");

    await expect(
      page.getByRole("heading", { level: 1, name: "Providers" }),
    ).toBeVisible();
    await expect(
      page.getByText("provider ops row가 없습니다."),
    ).toBeVisible();
    // items=[] → activeSelection=null → 우측 placeholder, detail/policy 미렌더.
    await expect(
      page.getByText("선택된 provider dataset이 없습니다."),
    ).toBeVisible();
    await expect(page.getByText("0 providers")).toBeVisible();
    await expect(page.getByText("failing 0")).toBeVisible();
    // useOpsProvider는 provider null이면 disabled → 상세 GET 미발생.
    await expect.poll(() => counts.detail).toBe(0);
  });

  test("provider list fetch error shows destructive alert", async ({ page }) => {
    await page.route("**/v1/ops/providers**", async (route) => {
      await fulfillJson(
        route,
        {
          type: "about:blank",
          title: "Internal Server Error",
          status: 500,
          detail: "provider freshness 조회 중 오류",
        },
        500,
      );
    });

    await page.goto("/ops/providers");

    // AdminShell 헤딩은 error 분기 밖이라 항상 렌더.
    await expect(
      page.getByRole("heading", { level: 1, name: "Providers" }),
    ).toBeVisible();
    const alert = page
      .getByRole("alert")
      .filter({ hasText: "provider 조회 실패" });
    await expect(alert).toBeVisible();
    // ApiClientError 메시지는 path/detail을 포함 → HTTP 500 substring만 단언.
    await expect(alert).toContainText(/HTTP 500/);
  });
});
