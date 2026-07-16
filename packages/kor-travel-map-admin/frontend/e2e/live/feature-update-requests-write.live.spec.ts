import { expect, test, type Locator, type Page, type Response } from "@playwright/test";

import type { components } from "../../src/api/types";

type FeatureUpdateRequestCreateResponse =
  components["schemas"]["FeatureUpdateRequestCreateResponse"];
type FeatureUpdateRequestDetailResponse =
  components["schemas"]["FeatureUpdateRequestDetailResponse"];
type FeatureUpdateRequestListResponse =
  components["schemas"]["FeatureUpdateRequestListResponse"];
type FeatureUpdateRequestMutationResponse =
  components["schemas"]["FeatureUpdateRequestMutationResponse"];
type PipelineCancellationResponse =
  components["schemas"]["PipelineCancellationResponse"];
type ScopeDispatchFeatureUpdateRequestRecord =
  FeatureUpdateRequestMutationResponse["data"] & {
    dispatch_requested_at: string | null;
  };

type BrowserFetchResult<T> = {
  body: T | null;
  status: number;
  text: string;
};

const UI_TIMEOUT = 15_000;
const FLOW_TIMEOUT = 5 * 60 * 1000;
const T = { timeout: UI_TIMEOUT } as const;

// 모든 생성 엔티티 식별자에 박아 parallel/재실행 충돌을 막는다.
const RUN_ID = `live-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
const RUN_STARTED_AT = new Date(Date.now() - 5_000).toISOString();
// SAFE 선택: legacy center_radius 폼은 target-selector dataset을 요청할 수 없으므로
// non-selector KMA pair를 쓰고, 한국 남서쪽 경계의 극소 반경으로 runner 부담을 낮춘다.
const SAFE_LON = "124.0001";
const SAFE_LAT = "33.0001";
const SAFE_RADIUS_KM = "0.1";
const PROVIDER = "python-kma-api";
const DATASET = "kma_mid_forecast";
const MULTI_DATASETS = [
  "kma_mid_forecast",
  "kma_weather_alerts",
] as const;
const BASE_REASON = `live ui e2e feature update ${RUN_ID}`;

// 메인 write flow 게이트(공통 E2E_ADMIN_WRITE 또는 surface 전용 E2E_FEATURE_UPDATE_WRITE).
const EXECUTE =
  process.env.E2E_ADMIN_WRITE === "1" ||
  process.env.E2E_FEATURE_UPDATE_WRITE === "1";
// run-now는 실제 Dagster runner를 깨우는 무거운 경로 → 별도 opt-in으로만.
const RUN_NOW = process.env.E2E_FEATURE_UPDATE_RUN === "1";

test.describe.configure({ mode: "serial" });

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function apiPath(response: Response): string {
  const pathname = new URL(response.url()).pathname;
  const path = pathname.startsWith("/api/proxy/")
    ? pathname.slice("/api/proxy".length)
    : pathname;
  return decodeURIComponent(path);
}

function isApiResponse(
  response: Response,
  method: string,
  path: string,
): boolean {
  return response.request().method() === method && apiPath(response) === path;
}

async function waitForApiResponse(
  page: Page,
  method: string,
  path: string,
): Promise<Response> {
  return page.waitForResponse(
    (response) => isApiResponse(response, method, decodeURIComponent(path)),
    { timeout: FLOW_TIMEOUT },
  );
}

async function browserFetch<T>(
  page: Page,
  path: string,
  options: { body?: unknown; method?: "GET" | "POST" | "PATCH" | "DELETE" } = {},
): Promise<BrowserFetchResult<T>> {
  return page.evaluate(
    async ({ body, method, path }) => {
      const response = await fetch(`/api/proxy${path}`, {
        method,
        headers: {
          Accept: "application/json",
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        credentials: "same-origin",
        cache: "no-store",
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      const text = await response.text();
      let parsed: unknown = null;
      try {
        parsed = text.length > 0 ? JSON.parse(text) : null;
      } catch {
        parsed = null;
      }
      return { body: parsed as T | null, status: response.status, text };
    },
    {
      body: options.body,
      method: options.method ?? "GET",
      path,
    },
  );
}

const LIST_PATH = "/v1/admin/features/update-requests";

function detailPath(requestId: string): string {
  return `/v1/admin/features/update-requests/${encodeURIComponent(requestId)}`;
}

function cancelPath(requestId: string): string {
  return `/v1/admin/features/update-requests/${encodeURIComponent(requestId)}/cancel`;
}

function runNowPath(requestId: string): string {
  return `/v1/admin/features/update-requests/${encodeURIComponent(requestId)}/run-now`;
}

async function readCreateResponse(
  response: Response,
): Promise<FeatureUpdateRequestCreateResponse> {
  // 라우터: @router.post("", ..., status_code=status.HTTP_201_CREATED) → 생성은 201.
  expect(response.status()).toBe(201);
  return (await response.json()) as FeatureUpdateRequestCreateResponse;
}

async function readMutationResponse(
  response: Response,
): Promise<FeatureUpdateRequestMutationResponse> {
  // run-now는 같은 canonical request/job의 즉시 dispatch 결과를 200으로 반환한다.
  expect(response.status()).toBe(200);
  return (await response.json()) as FeatureUpdateRequestMutationResponse;
}

async function fetchDetailByApi(
  page: Page,
  requestId: string,
): Promise<BrowserFetchResult<FeatureUpdateRequestDetailResponse>> {
  return browserFetch<FeatureUpdateRequestDetailResponse>(
    page,
    detailPath(requestId),
  );
}

async function fetchListByProviderApi(
  page: Page,
  provider: string,
  statusFilter?: string,
  datasetKey?: string,
): Promise<BrowserFetchResult<FeatureUpdateRequestListResponse>> {
  const params = new URLSearchParams();
  params.set("provider", provider);
  params.set("created_from", RUN_STARTED_AT);
  if (datasetKey) params.set("dataset_key", datasetKey);
  if (statusFilter) params.set("status", statusFilter);
  params.set("page_size", "100");
  return browserFetch<FeatureUpdateRequestListResponse>(
    page,
    `${LIST_PATH}?${params.toString()}`,
  );
}

async function cancelByApi(page: Page, requestId: string): Promise<void> {
  // best-effort 정리: queued/running이면 cancel(200), terminal이면 409 → 무시.
  // 라우터: @router.post("/{request_id}/cancel", ...) → C3d coordinator.
  try {
    await browserFetch<PipelineCancellationResponse>(
      page,
      cancelPath(requestId),
      {
        method: "POST",
        body: { reason: `${BASE_REASON} cleanup cancel` },
      },
    );
  } catch {
    // 페이지 컨텍스트 문제 등은 정리 단계이므로 삼킨다.
  }
}

async function gotoUpdateRequests(page: Page): Promise<void> {
  await page.goto("/admin/features/update-requests");
  await expect(
    page.getByRole("heading", { level: 1, name: "갱신 요청" }),
  ).toBeVisible(T);
  await expect(page.getByLabel("경도", { exact: true })).toBeVisible(T);
  await expect(page.getByLabel("반경(km)", { exact: true })).toBeVisible(T);
  // previewOnly가 기본 true이므로 초기 readiness는 실제 보이는 버튼으로 판정한다.
  await expect(page.getByRole("button", { name: "미리보기" })).toBeVisible(T);
}

async function selectProvider(page: Page, provider: string): Promise<void> {
  const combobox = page.getByRole("combobox", { name: "제공자" });
  await expect(combobox).toBeVisible(T);
  await expect(combobox).not.toContainText("불러오는 중", T);
  await combobox.click();
  await page.getByLabel("제공자 검색").fill(provider);
  await page.getByRole("option", { name: new RegExp(escapeRegExp(provider)) }).click();
  await expect(combobox).toContainText(provider);
}

function rowContaining(page: Page, text: string): Locator {
  return page.getByRole("row", { name: new RegExp(escapeRegExp(text)) });
}

function shortId(value: string, size = 12): string {
  return value.length > size ? `${value.slice(0, size)}...` : value;
}

function requestRowById(page: Page, requestId: string): Locator {
  return rowContaining(page, shortId(requestId));
}

// status select → 목록 GET을 query string까지 매칭해 "UI 선택 → API status param"을 증명.
async function waitForListStatusResponse(
  page: Page,
  statusValue: string,
): Promise<Response> {
  return page.waitForResponse(
    (response) => {
      if (response.request().method() !== "GET") return false;
      const url = new URL(response.url());
      const pathname = url.pathname.startsWith("/api/proxy/")
        ? url.pathname.slice("/api/proxy".length)
        : url.pathname;
      return (
        decodeURIComponent(pathname) === LIST_PATH &&
        url.searchParams.get("status") === statusValue
      );
    },
    { timeout: FLOW_TIMEOUT },
  );
}

type CreatedRequest = {
  create: FeatureUpdateRequestCreateResponse;
  requestId: string;
};

// UI 폼으로 SAFE refreshable provider/dataset queued 요청을 만들고 request_id를 돌려준다.
// 미리보기를 해제해 실제 row를 만들되, 좁은 scope라 실행 부담이 낮다.
async function createRefreshableQueuedRequest(
  page: Page,
  options: {
    provider: string;
    dataset: string;
    lon?: string;
    lat?: string;
    radiusKm?: string;
  },
): Promise<CreatedRequest> {
  await page.getByLabel("경도", { exact: true }).fill(options.lon ?? SAFE_LON);
  await page.getByLabel("위도", { exact: true }).fill(options.lat ?? SAFE_LAT);
  await page
    .getByLabel("반경(km)", { exact: true })
    .fill(options.radiusKm ?? SAFE_RADIUS_KM);
  await selectProvider(page, options.provider);
  await page.getByLabel("데이터셋 키", { exact: true }).fill(options.dataset);
  await page.getByLabel("실행 모드").selectOption("queued");
  await page.getByLabel(/미리보기/).uncheck();

  const responsePromise = waitForApiResponse(page, "POST", LIST_PATH);
  await page.getByRole("button", { name: "요청 생성" }).click();
  const create = await readCreateResponse(await responsePromise);
  const requestId = create.data.request_id ?? null;
  expect(requestId).not.toBeNull();
  return { create, requestId: requestId as string };
}

test.describe("/admin/features/update-requests live write workflow", () => {
  test("UI 폼으로 queued feature update request를 생성하고 목록/상세/백엔드에 반영된다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE,
      "E2E_FEATURE_UPDATE_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 update request write flow를 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    let requestId: string | null = null;
    let sourceJobId: string | null = null;

    try {
      await test.step("update request 폼/필터 표면을 확인한다", async () => {
        await gotoUpdateRequests(page);
        await expect(page.getByLabel("위도", { exact: true })).toBeVisible(T);
        await expect(
          page.getByRole("combobox", { name: "제공자" }),
        ).toBeVisible(T);
        await expect(page.getByLabel("데이터셋 키", { exact: true })).toBeVisible(T);
        await expect(page.getByLabel("실행 모드")).toBeVisible(T);
        await expect(page.getByLabel(/미리보기/)).toBeVisible(T);
        await expect(page.getByLabel("요청 상태 필터")).toBeVisible(T);
      });

      await test.step("미리보기를 끄고 SAFE provider/dataset로 queued 요청을 생성한다", async () => {
        await page.getByLabel("경도", { exact: true }).fill(SAFE_LON);
        await page.getByLabel("위도", { exact: true }).fill(SAFE_LAT);
        await page.getByLabel("반경(km)", { exact: true }).fill(SAFE_RADIUS_KM);
        await selectProvider(page, PROVIDER);
        await page.getByLabel("데이터셋 키", { exact: true }).fill(DATASET);
        await page.getByLabel("실행 모드").selectOption("queued");
        // 미리보기는 기본 checked → 실제 row를 만들기 위해 해제.
        await page.getByLabel(/미리보기/).uncheck();
        await expect(page.getByLabel(/미리보기/)).not.toBeChecked();

        const responsePromise = waitForApiResponse(page, "POST", LIST_PATH);
        await page.getByRole("button", { name: "요청 생성" }).click();
        const createResponse = await readCreateResponse(await responsePromise);

        requestId = createResponse.data.request_id ?? null;
        sourceJobId = createResponse.data.job_id;
        expect(requestId).not.toBeNull();
        // 생성 직후 응답(동기 캡처) — 레이스 없이 queued/center_radius/입력값을 단언.
        expect(createResponse.data).toMatchObject({
          scope_type: "center_radius",
          run_mode: "queued",
          status: "queued",
          result_kind: "request",
          job_id: expect.any(String),
        });
        expect(createResponse.data.providers).toContain(PROVIDER);
        expect(createResponse.data.dataset_keys).toContain(DATASET);
        expect(createResponse.data.scope).toMatchObject({ type: "center_radius" });
        expect(createResponse.data.generation).toBe(1);

        // 성공 피드백 alert: `{request_id} · {status}` (role=status).
        const successAlert = page
          .getByRole("status")
          .filter({ hasText: "요청 처리 완료" });
        await expect(successAlert).toBeVisible(T);
        await expect(successAlert).toContainText(requestId as string);
        // 성공 alert은 statusLabel(status)로 렌더 → "queued"가 한글 "대기"로 표시된다.
        await expect(successAlert).toContainText("대기");
      });

      await test.step("목록(all 필터)에 새 요청 행이 나타난다", async () => {
        // 폼/목록은 같은 페이지 — 생성 onSuccess가 목록 쿼리를 invalidate해 refetch한다.
        await page.getByLabel("요청 상태 필터").selectOption("all");
        const row = requestRowById(page, requestId as string);
        await expect(row).toBeVisible(T);
        await expect(row).toContainText(PROVIDER);
      });

      await test.step("행의 상세 링크로 이동해 requestId/scope를 확인한다", async () => {
        const row = requestRowById(page, requestId as string);
        // request 컬럼만 link(shortId) — job 컬럼은 '-' 텍스트, actions는 버튼.
        await row.getByRole("link").click();
        await expect(page).toHaveURL(
          new RegExp(
            `/admin/features/update-requests/${escapeRegExp(requestId as string)}$`,
          ),
          T,
        );
        await expect(
          page.getByRole("heading", {
            level: 1,
            name: "갱신 요청 상세",
            exact: true,
          }),
        ).toBeVisible(T);
        // 상세 헤더는 full requestId + scope_type/run_mode 배지를 렌더.
        await expect(
          page.getByText(requestId as string, { exact: true }),
        ).toBeVisible(T);
        await expect(page.getByText("center_radius").first()).toBeVisible(T);
        // status 배지: 생성 직후 queued. sensor가 빨리 집어가면 running일 수 있어
        // run_mode("queued") 배지가 항상 보이므로 페이지 렌더만 확인하고, 권위 있는
        // status 단언은 아래 API 폴링에서 한다.
        await expect(page.getByText("queued").first()).toBeVisible(T);
      });

      await test.step("백엔드 detail/list API가 제출한 provider/dataset로 row를 반환한다", async () => {
        // detail 조회 (envelope: data = FeatureUpdateRequestRecord).
        await expect
          .poll(
            async () => (await fetchDetailByApi(page, requestId as string)).status,
            T,
          )
          .toBe(200);
        const detail = await fetchDetailByApi(page, requestId as string);
        expect(detail.body?.data.request_id).toBe(requestId);
        expect(detail.body?.data.scope_type).toBe("center_radius");
        expect(detail.body?.data.providers).toContain(PROVIDER);
        expect(detail.body?.data.dataset_keys).toContain(DATASET);
        expect(detail.body?.data.scope).toMatchObject({ type: "center_radius" });
        expect(detail.body?.data.generation).toBeGreaterThanOrEqual(1);
        // queued로 생성된 row이며 무거운 실행을 강제하지 않았는지 확인.
        expect(detail.body?.data.run_mode).toBe("queued");
        expect(["queued", "running", "done"]).toContain(
          detail.body?.data.status,
        );

        // list 조회 (provider 필터로 우리 row 한정).
        const list = await fetchListByProviderApi(page, PROVIDER, undefined, DATASET);
        expect(list.status).toBe(200);
        const found = list.body?.data.items.find(
          (item) => item.request_id === requestId,
        );
        expect(found).toBeDefined();
        expect(found?.providers).toContain(PROVIDER);
        expect(found?.dataset_keys).toContain(DATASET);
      });

      if (RUN_NOW) {
        await test.step("run-now로 같은 request를 dispatch하고 status 전이를 폴링한다", async () => {
          const responsePromise = waitForApiResponse(
            page,
            "POST",
            runNowPath(requestId as string),
          );
          await page.getByRole("button", { name: "즉시 실행" }).click();
          const response = await responsePromise;
          expect(response.request().postDataJSON()).toEqual({});
          const runResponse = await readMutationResponse(response);
          expect(runResponse.data.request_id).toBe(requestId);
          expect(runResponse.data.job_id).toBe(sourceJobId);
          expect(runResponse.data.run_mode).toBe("queued");
          expect(runResponse.data.providers).toContain(PROVIDER);
          const dispatched =
            runResponse.data as ScopeDispatchFeatureUpdateRequestRecord;
          if (dispatched.status === "queued") {
            expect(dispatched.dispatch_requested_at).not.toBeNull();
          }
          const successAlert = page
            .getByRole("status")
            .filter({ hasText: "즉시 실행 요청 완료" });
          await expect(successAlert).toContainText(
            "기존 요청의 즉시 dispatch를 요청했습니다.",
          );
          await expect(
            successAlert.getByRole("link", { name: requestId as string }),
          ).toHaveAttribute(
            "href",
            `/admin/features/update-requests/${requestId as string}`,
          );

          // 같은 request_id의 dispatch intent를 Dagster sensor/job이 소비한다.
          await expect
            .poll(async () => {
              const res = await fetchDetailByApi(
                page,
                requestId as string,
              );
              return res.body?.data.status ?? `http:${res.status}`;
            }, { timeout: FLOW_TIMEOUT })
            .not.toBe("queued");
        });
      }
    } finally {
      // canonical request 하나만 존재한다. terminal이면 cleanup cancel 409를 무시한다.
      if (requestId) await cancelByApi(page, requestId);
    }
  });

  test("한 요청의 non-selector KMA 2종이 응답·목록·상세에 모두 반영된다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE,
      "E2E_FEATURE_UPDATE_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 write flow를 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    const [datasetA, datasetB] = MULTI_DATASETS;
    let requestId: string | null = null;

    try {
      await gotoUpdateRequests(page);

      await test.step("comma-separated KMA 2종으로 queued 요청을 생성한다", async () => {
        const created = await createRefreshableQueuedRequest(page, {
          provider: PROVIDER,
          dataset: `${datasetA},${datasetB}`,
        });
        requestId = created.requestId;
        // 생성 응답이 한 provider/두 dataset을 그대로 담는다(동기 캡처).
        expect(created.create.data.providers).toEqual([PROVIDER]);
        expect(created.create.data.dataset_keys).toEqual(
          expect.arrayContaining([datasetA, datasetB]),
        );
        expect(created.create.data.dataset_keys).toHaveLength(2);
        expect(created.create.data.status).toBe("queued");

        const successAlert = page
          .getByRole("status")
          .filter({ hasText: "요청 처리 완료" });
        await expect(successAlert).toBeVisible(T);
        await expect(successAlert).toContainText(requestId as string);
      });

      await test.step("목록 행이 provider와 request short id를 함께 노출한다", async () => {
        await page.getByLabel("요청 상태 필터").selectOption("all");
        const row = requestRowById(page, requestId as string);
        await expect(row).toBeVisible(T);
        await expect(row).toContainText(PROVIDER);
      });

      await test.step("detail/list API가 KMA 2종을 모두 반환한다", async () => {
        await expect
          .poll(
            async () =>
              (await fetchDetailByApi(page, requestId as string)).status,
            T,
          )
          .toBe(200);
        const detail = await fetchDetailByApi(page, requestId as string);
        expect(detail.body?.data.providers).toEqual([PROVIDER]);
        expect(detail.body?.data.dataset_keys).toEqual(
          expect.arrayContaining([datasetA, datasetB]),
        );

        // dataset_key 각각으로 필터해도 같은 row를 찾는다(@> 멤버십 매칭).
        for (const dataset of [datasetA, datasetB]) {
          const list = await fetchListByProviderApi(
            page,
            PROVIDER,
            undefined,
            dataset,
          );
          expect(list.status).toBe(200);
          const found = list.body?.data.items.find(
            (item) => item.request_id === requestId,
          );
          expect(found).toBeDefined();
        }
      });
    } finally {
      if (requestId) await cancelByApi(page, requestId);
    }
  });

  test("제공자 combobox multiple에서 검색·선택·해제가 동작한다", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);

    await gotoUpdateRequests(page);

    const combobox = page.getByRole("combobox", { name: "제공자" });
    await selectProvider(page, PROVIDER);
    await expect(combobox).toContainText(PROVIDER);

    await page.getByRole("button", { name: `${PROVIDER} 제거` }).click();
    await expect(combobox).not.toContainText(PROVIDER);
    await expect(combobox).toContainText("전체 제공자");
  });

  test("request status 필터가 status query param으로 내려가고 목록이 그에 맞게 좁혀진다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE,
      "E2E_FEATURE_UPDATE_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 write flow를 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    let requestId: string | null = null;

    try {
      await gotoUpdateRequests(page);

      await test.step("queued 요청을 하나 만든다", async () => {
        const created = await createRefreshableQueuedRequest(page, {
          provider: PROVIDER,
          dataset: DATASET,
        });
        requestId = created.requestId;
        expect(created.create.data.status).toBe("queued");
      });

      await test.step("all 필터에서 우리 row가 보인다", async () => {
        await page.getByLabel("요청 상태 필터").selectOption("all");
        const row = requestRowById(page, requestId as string);
        await expect(row).toBeVisible(T);
        await expect(row).toContainText(PROVIDER);

        const list = await fetchListByProviderApi(
          page,
          PROVIDER,
          undefined,
          DATASET,
        );
        expect(list.status).toBe(200);
        const found = list.body?.data.items.find(
          (item) => item.request_id === requestId,
        );
        expect(found).toBeDefined();
      });

      await test.step("failed 필터 선택 시 status=failed query가 나가고 우리 row는 사라진다", async () => {
        const responsePromise = waitForListStatusResponse(page, "failed");
        await page.getByLabel("요청 상태 필터").selectOption("failed");
        const response = await responsePromise;
        expect(new URL(response.url()).searchParams.get("status")).toBe(
          "failed",
        );

        await expect(requestRowById(page, requestId as string)).toHaveCount(0);

        const list = await fetchListByProviderApi(
          page,
          PROVIDER,
          "failed",
          DATASET,
        );
        expect(list.status).toBe(200);
        for (const item of list.body?.data.items ?? []) {
          expect(item.status).toBe("failed");
        }
        const found = list.body?.data.items.find(
          (item) => item.request_id === requestId,
        );
        expect(found).toBeUndefined();
      });

      await test.step("running 필터 선택 시 status=running query가 나가고 결과는 모두 running이다", async () => {
        const responsePromise = waitForListStatusResponse(page, "running");
        await page.getByLabel("요청 상태 필터").selectOption("running");
        const response = await responsePromise;
        expect(new URL(response.url()).searchParams.get("status")).toBe(
          "running",
        );

        const list = await fetchListByProviderApi(
          page,
          PROVIDER,
          "running",
          DATASET,
        );
        expect(list.status).toBe(200);
        for (const item of list.body?.data.items ?? []) {
          expect(item.status).toBe("running");
        }
      });
    } finally {
      if (requestId) await cancelByApi(page, requestId);
    }
  });

  test("상세 페이지가 제출한 scope/policy/run_mode를 API와 일치하게 깊이 렌더한다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE,
      "E2E_FEATURE_UPDATE_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 write flow를 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    const lon = "127.01234";
    const lat = "37.61234";
    const radiusKm = "0.1";
    let requestId: string | null = null;

    try {
      await gotoUpdateRequests(page);

      await test.step("구별되는 좌표/반경으로 queued 요청을 만든다", async () => {
        const created = await createRefreshableQueuedRequest(page, {
          provider: PROVIDER,
          dataset: DATASET,
          lon,
          lat,
          radiusKm,
        });
        requestId = created.requestId;
      });

      await test.step("행의 상세 링크로 이동한다", async () => {
        await page.getByLabel("요청 상태 필터").selectOption("all");
        const row = requestRowById(page, requestId as string);
        await expect(row).toBeVisible(T);
        await row.getByRole("link").click();
        await expect(page).toHaveURL(
          new RegExp(
            `/admin/features/update-requests/${escapeRegExp(
              requestId as string,
            )}$`,
          ),
          T,
        );
      });

      await test.step("API 상세 필드와 UI 렌더가 깊은 수준에서 일치한다", async () => {
        const detail = await fetchDetailByApi(page, requestId as string);
        expect(detail.status).toBe(200);
        const data = detail.body?.data;
        expect(data?.scope_type).toBe("center_radius");
        expect(data?.run_mode).toBe("queued");
        expect(data?.priority).toBe(50);
        expect(data).not.toHaveProperty("dry_run");
        expect(data?.job_id).toEqual(expect.any(String));
        expect(data?.providers).toContain(PROVIDER);
        expect(data?.dataset_keys).toContain(DATASET);
        // 폼이 update_policy 필드를 노출하지 않으므로 빈 객체로 저장된다.
        expect(data?.update_policy).toEqual({});
        expect(data?.scope).toMatchObject({
          type: "center_radius",
          center: { lon: Number(lon), lat: Number(lat) },
          radius_km: Number(radiusKm),
        });

        // 헤더: full requestId + scope_type 배지.
        await expect(
          page.getByText(requestId as string, { exact: true }),
        ).toBeVisible(T);
        await expect(page.getByText("center_radius").first()).toBeVisible(T);

        // Scope 카드 <pre>: 제출한 좌표가 JSON으로 그대로 보인다.
        // 같은 grid section의 첫 pre가 Scope(둘째가 Matched scope).
        const scopePre = page
          .locator("section")
          .filter({ hasText: "매칭된 스코프" })
          .locator("pre")
          .first();
        await expect(scopePre).toContainText(`"center_radius"`);
        await expect(scopePre).toContainText(lon);
        await expect(scopePre).toContainText(lat);

        // Policy <pre>: update_policy가 비어 있어 "{}".
        const policyPre = page
          .locator("section")
          .filter({ hasText: "정책" })
          .locator("pre");
        await expect(policyPre).toContainText("{}");
      });
    } finally {
      if (requestId) await cancelByApi(page, requestId);
    }
  });

  test("목록 actions의 cancel 버튼이 큐 요청을 cancelled로 전이시키고 UI에 반영된다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE,
      "E2E_FEATURE_UPDATE_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 write flow를 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    let requestId: string | null = null;
    let jobId: string | null = null;

    try {
      await gotoUpdateRequests(page);

      await test.step("queued 요청을 만든다", async () => {
        const created = await createRefreshableQueuedRequest(page, {
          provider: PROVIDER,
          dataset: DATASET,
        });
        requestId = created.requestId;
        jobId = created.create.data.job_id;
      });

      await test.step("queued row의 cancel 버튼이 POST /cancel을 호출하고 cancelled를 반환한다", async () => {
        await page.getByLabel("요청 상태 필터").selectOption("all");
        const row = requestRowById(page, requestId as string);
        await expect(row).toBeVisible(T);
        const cancelButton = row.getByRole("button", { name: "취소" });
        test.skip(
          (await cancelButton.count()) === 0,
          "sensor가 먼저 terminal status로 처리해 UI cancel 버튼이 사라짐",
        );

        const responsePromise = waitForApiResponse(
          page,
          "POST",
          cancelPath(requestId as string),
        );
        await cancelButton.click();
        const response = await responsePromise;
        expect(response.status()).toBe(200);
        const body = (await response.json()) as PipelineCancellationResponse;
        expect(body.data.root).toEqual({
          kind: "update_request",
          id: requestId,
        });
        expect(body.data.status).toBe("completed");
        expect(body.data.members).toContainEqual(
          expect.objectContaining({
            job_id: jobId,
            terminal_status: "cancelled",
          }),
        );
      });

      await test.step("백엔드 detail이 cancelled로 전이됐다", async () => {
        await expect
          .poll(async () => {
            const res = await fetchDetailByApi(page, requestId as string);
            return res.body?.data.status ?? `http:${res.status}`;
          }, T)
          .toBe("cancelled");
      });

      await test.step("cancelled 필터 목록에 row가 cancelled로 나타난다", async () => {
        await page.getByLabel("요청 상태 필터").selectOption("cancelled");
        const row = requestRowById(page, requestId as string);
        await expect(row).toBeVisible(T);
        // status 컬럼은 <StatusBadge>로 렌더 → "cancelled"가 한글 "취소됨"으로 표시된다.
        await expect(row).toContainText("취소됨");
      });
    } finally {
      // 이미 terminal(cancelled)이면 cleanup cancel은 409 → cancelByApi가 삼킨다.
      if (requestId) await cancelByApi(page, requestId);
    }
  });

  test("목록 actions의 run-now 버튼이 같은 canonical 요청을 dispatch한다", async ({
    page,
  }) => {
    test.skip(
      !(EXECUTE && RUN_NOW),
      "E2E_FEATURE_UPDATE_RUN=1과 write 플래그가 모두 켜졌을 때만 실제 Dagster run을 깨운다",
    );
    test.setTimeout(FLOW_TIMEOUT);

    let requestId: string | null = null;
    let sourceJobId: string | null = null;

    try {
      await gotoUpdateRequests(page);

      await test.step("queued 요청을 만든다", async () => {
        const created = await createRefreshableQueuedRequest(page, {
          provider: PROVIDER,
          dataset: DATASET,
        });
        requestId = created.requestId;
        sourceJobId = created.create.data.job_id;
      });

      await test.step("run-now 버튼이 기존 row를 200으로 dispatch한다", async () => {
        await page.getByLabel("요청 상태 필터").selectOption("all");
        const row = requestRowById(page, requestId as string);
        await expect(row).toBeVisible(T);

        const responsePromise = waitForApiResponse(
          page,
          "POST",
          runNowPath(requestId as string),
        );
        await row.getByRole("button", { name: "즉시 실행" }).click();
        const response = await responsePromise;
        expect(response.request().postDataJSON()).toEqual({});
        const runResponse = await readMutationResponse(response);
        expect(runResponse.data.request_id).toBe(requestId);
        expect(runResponse.data.job_id).toBe(sourceJobId);
        expect(runResponse.data.run_mode).toBe("queued");
        expect(runResponse.data.providers).toContain(PROVIDER);
        const dispatched =
          runResponse.data as ScopeDispatchFeatureUpdateRequestRecord;
        if (dispatched.status === "queued") {
          expect(dispatched.dispatch_requested_at).not.toBeNull();
        }
        const successAlert = page
          .getByRole("status")
          .filter({ hasText: "즉시 실행 요청 완료" });
        await expect(successAlert).toContainText(
          "기존 요청의 즉시 dispatch를 요청했습니다.",
        );
      });

      await test.step("같은 요청의 status가 queued를 벗어난다(runner 활성 전제)", async () => {
        await expect
          .poll(
            async () => {
              const res = await fetchDetailByApi(
                page,
                requestId as string,
              );
              return res.body?.data.status ?? `http:${res.status}`;
            },
            { timeout: FLOW_TIMEOUT },
          )
          .not.toBe("queued");
      });
    } finally {
      if (requestId) await cancelByApi(page, requestId);
    }
  });
});
