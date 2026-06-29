import { expect, test, type Locator, type Page, type Response } from "@playwright/test";

import type { components } from "../../src/api/types";

type FeatureUpdateRequestCreateResponse =
  components["schemas"]["FeatureUpdateRequestCreateResponse"];
type FeatureUpdateRequestDetailResponse =
  components["schemas"]["FeatureUpdateRequestDetailResponse"];
type FeatureUpdateRequestListResponse =
  components["schemas"]["FeatureUpdateRequestListResponse"];

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
// SAFE 선택: 존재하지 않는 unique provider/dataset로 좁히면 center_radius scope여도
// 매칭되는 provider가 없어 Dagster job이 no-op가 된다(무거운 실 실행 방지). providers를
// 비워 두면 반경 내 "모든" provider refresh로 무거워질 수 있으므로 반드시 bogus 값을 준다.
const PROVIDER = `e2e_inert_provider_${RUN_ID}`;
const DATASET = `e2e_inert_dataset_${RUN_ID}`;
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

const LIST_PATH = "/v1/admin/feature-update-requests";

function detailPath(requestId: string): string {
  return `/v1/admin/feature-update-requests/${encodeURIComponent(requestId)}`;
}

function cancelPath(requestId: string): string {
  return `/v1/admin/feature-update-requests/${encodeURIComponent(requestId)}/cancel`;
}

function runNowPath(requestId: string): string {
  return `/v1/admin/feature-update-requests/${encodeURIComponent(requestId)}/run-now`;
}

async function readCreateResponse(
  response: Response,
): Promise<FeatureUpdateRequestCreateResponse> {
  // 라우터: @router.post("", ..., status_code=status.HTTP_201_CREATED) → 생성은 201.
  expect(response.status()).toBe(201);
  return (await response.json()) as FeatureUpdateRequestCreateResponse;
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
): Promise<BrowserFetchResult<FeatureUpdateRequestListResponse>> {
  const params = new URLSearchParams();
  params.set("provider", provider);
  if (statusFilter) params.set("status", statusFilter);
  params.set("page_size", "100");
  return browserFetch<FeatureUpdateRequestListResponse>(
    page,
    `${LIST_PATH}?${params.toString()}`,
  );
}

async function cancelByApi(page: Page, requestId: string): Promise<void> {
  // best-effort 정리: queued/running이면 cancel(200), terminal이면 409 → 무시.
  // 라우터: @router.post("/{request_id}/cancel", ...) → cancel_update_request.
  try {
    await browserFetch<FeatureUpdateRequestCreateResponse>(
      page,
      cancelPath(requestId),
      {
        method: "POST",
        body: { error_message: `${BASE_REASON} cleanup cancel` },
      },
    );
  } catch {
    // 페이지 컨텍스트 문제 등은 정리 단계이므로 삼킨다.
  }
}

async function gotoUpdateRequests(page: Page): Promise<void> {
  await page.goto("/admin/feature-update-requests");
  await expect(
    page.getByRole("heading", { level: 1, name: "Feature update requests" }),
  ).toBeVisible(T);
  await expect(page.getByLabel("lon", { exact: true })).toBeVisible(T);
  await expect(page.getByLabel("radius km", { exact: true })).toBeVisible(T);
  await expect(page.getByRole("button", { name: "요청 생성" })).toBeVisible(T);
}

function rowContaining(page: Page, text: string): Locator {
  return page.getByRole("row", { name: new RegExp(escapeRegExp(text)) });
}

// ─── DEEPEN helpers (above browserFetch/waitForApiResponse 등은 재사용) ────────
// 시나리오별 고유 provider/dataset 토큰 — list 필터가 jsonb @> 정확 멤버십이라
// 서로 다른 tag면 교차 매칭되지 않아 시나리오가 격리된다.
function inertProvider(tag: string): string {
  return `${PROVIDER}_${tag}`;
}

function inertDataset(tag: string): string {
  return `${DATASET}_${tag}`;
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

// UI 폼으로 SAFE(bogus provider/dataset) queued 요청을 만들고 request_id를 돌려준다.
// dry-run을 해제해 실제 row를 만들되, bogus provider라 Dagster job은 no-op가 된다.
async function createInertQueuedRequest(
  page: Page,
  options: {
    provider: string;
    dataset: string;
    lon?: string;
    lat?: string;
    radiusKm?: string;
  },
): Promise<CreatedRequest> {
  await page.getByLabel("lon", { exact: true }).fill(options.lon ?? "126.9780");
  await page.getByLabel("lat", { exact: true }).fill(options.lat ?? "37.5665");
  await page
    .getByLabel("radius km", { exact: true })
    .fill(options.radiusKm ?? "5");
  await page.getByLabel("providers", { exact: true }).fill(options.provider);
  await page.getByLabel("dataset keys", { exact: true }).fill(options.dataset);
  await page.getByLabel("run mode").selectOption("queued");
  await page.getByLabel("dry-run").uncheck();

  const responsePromise = waitForApiResponse(page, "POST", LIST_PATH);
  await page.getByRole("button", { name: "요청 생성" }).click();
  const create = await readCreateResponse(await responsePromise);
  const requestId = create.data.request_id ?? null;
  expect(requestId).not.toBeNull();
  return { create, requestId: requestId as string };
}

test.describe("/admin/feature-update-requests live write workflow", () => {
  test("UI 폼으로 queued feature update request를 생성하고 목록/상세/백엔드에 반영된다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE,
      "E2E_FEATURE_UPDATE_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 update request write flow를 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    let requestId: string | null = null;
    let runNowRequestId: string | null = null;

    try {
      await test.step("update request 폼/필터 표면을 확인한다", async () => {
        await gotoUpdateRequests(page);
        await expect(page.getByLabel("lat", { exact: true })).toBeVisible(T);
        await expect(page.getByLabel("providers", { exact: true })).toBeVisible(T);
        await expect(page.getByLabel("dataset keys", { exact: true })).toBeVisible(T);
        await expect(page.getByLabel("run mode")).toBeVisible(T);
        await expect(page.getByLabel("dry-run")).toBeVisible(T);
        await expect(page.getByLabel("request status")).toBeVisible(T);
      });

      await test.step("dry-run을 끄고 SAFE provider/dataset로 queued 요청을 생성한다", async () => {
        // 기본 center_radius(서울) 좌표 + bogus provider/dataset로 inert queued 요청 생성.
        await page.getByLabel("lon", { exact: true }).fill("126.9780");
        await page.getByLabel("lat", { exact: true }).fill("37.5665");
        await page.getByLabel("radius km", { exact: true }).fill("5");
        await page.getByLabel("providers", { exact: true }).fill(PROVIDER);
        await page.getByLabel("dataset keys", { exact: true }).fill(DATASET);
        await page.getByLabel("run mode").selectOption("queued");
        // dry-run 체크박스는 기본 checked → 실제 row를 만들기 위해 해제.
        await page.getByLabel("dry-run").uncheck();
        await expect(page.getByLabel("dry-run")).not.toBeChecked();

        const responsePromise = waitForApiResponse(page, "POST", LIST_PATH);
        await page.getByRole("button", { name: "요청 생성" }).click();
        const createResponse = await readCreateResponse(await responsePromise);

        requestId = createResponse.data.request_id ?? null;
        expect(requestId).not.toBeNull();
        // 생성 직후 응답(동기 캡처) — 레이스 없이 queued/center_radius/입력값을 단언.
        expect(createResponse.data).toMatchObject({
          scope_type: "center_radius",
          run_mode: "queued",
          status: "queued",
          dry_run: false,
        });
        expect(createResponse.data.providers).toContain(PROVIDER);
        expect(createResponse.data.dataset_keys).toContain(DATASET);
        expect(createResponse.data.scope).toMatchObject({ type: "center_radius" });

        // 성공 피드백 alert: `{request_id} · {status}` (role=status).
        const successAlert = page
          .getByRole("status")
          .filter({ hasText: "요청 처리 완료" });
        await expect(successAlert).toBeVisible(T);
        await expect(successAlert).toContainText(requestId as string);
        await expect(successAlert).toContainText("queued");
      });

      await test.step("목록(queued 필터)에 새 요청 행이 나타난다", async () => {
        // 폼/목록은 같은 페이지 — 생성 onSuccess가 목록 쿼리를 invalidate해 refetch한다.
        await page.getByLabel("request status").selectOption("queued");
        const row = rowContaining(page, PROVIDER);
        await expect(row).toBeVisible(T);
        await expect(row).toContainText("queued");
      });

      await test.step("행의 상세 링크로 이동해 requestId/scope를 확인한다", async () => {
        const row = rowContaining(page, PROVIDER);
        // request 컬럼만 link(shortId) — job 컬럼은 '-' 텍스트, actions는 버튼.
        await row.getByRole("link").click();
        await expect(page).toHaveURL(
          new RegExp(
            `/admin/feature-update-requests/${escapeRegExp(requestId as string)}$`,
          ),
          T,
        );
        await expect(
          page.getByRole("heading", {
            level: 1,
            name: "Feature update request",
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
        // queued로 생성된 row이며 무거운 실행을 강제하지 않았는지 확인.
        expect(detail.body?.data.run_mode).toBe("queued");
        expect(["queued", "running", "done"]).toContain(
          detail.body?.data.status,
        );

        // list 조회 (provider 필터로 우리 row 한정).
        const list = await fetchListByProviderApi(page, PROVIDER);
        expect(list.status).toBe(200);
        const found = list.body?.data.items.find(
          (item) => item.request_id === requestId,
        );
        expect(found).toBeDefined();
        expect(found?.providers).toContain(PROVIDER);
        expect(found?.dataset_keys).toContain(DATASET);
      });

      if (RUN_NOW) {
        await test.step("run-now로 재큐잉하고 새 request의 status 전이를 폴링한다", async () => {
          // 상세 페이지의 run-now 버튼 → run_mode=now로 신규 row를 enqueue(201).
          // 새 request_id는 응답에서만 얻을 수 있어 waitForApiResponse로 캡처한다.
          const responsePromise = waitForApiResponse(
            page,
            "POST",
            runNowPath(requestId as string),
          );
          await page.getByRole("button", { name: "run-now" }).click();
          const runResponse = await readCreateResponse(await responsePromise);
          runNowRequestId = runResponse.data.request_id ?? null;
          expect(runNowRequestId).not.toBeNull();
          expect(runResponse.data.run_mode).toBe("now");
          expect(runResponse.data.providers).toContain(PROVIDER);

          // run_mode=now도 실제 실행은 Dagster sensor/job이 맡는다(라우터 docstring).
          // E2E_FEATURE_UPDATE_RUN opt-in은 runner가 활성이라는 전제 → queued를 벗어남.
          await expect
            .poll(async () => {
              const res = await fetchDetailByApi(
                page,
                runNowRequestId as string,
              );
              return res.body?.data.status ?? `http:${res.status}`;
            }, { timeout: FLOW_TIMEOUT })
            .not.toBe("queued");
        });
      }
    } finally {
      // 생성한 모든 request를 API로 cancel(있을 때만). terminal이면 409 → 무시.
      for (const id of [runNowRequestId, requestId]) {
        if (id) {
          await cancelByApi(page, id);
        }
      }
    }
  });

  test("한 요청에 다중 provider/dataset_keys를 넣으면 응답·목록·상세에 모두 반영된다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE,
      "E2E_FEATURE_UPDATE_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 write flow를 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    const providerA = inertProvider("multi_a");
    const providerB = inertProvider("multi_b");
    const datasetA = inertDataset("multi_1");
    const datasetB = inertDataset("multi_2");
    const datasetC = inertDataset("multi_3");
    let requestId: string | null = null;

    try {
      await gotoUpdateRequests(page);

      await test.step("comma-separated 다중 provider/dataset로 queued 요청을 생성한다", async () => {
        const created = await createInertQueuedRequest(page, {
          provider: `${providerA},${providerB}`,
          dataset: `${datasetA},${datasetB},${datasetC}`,
        });
        requestId = created.requestId;
        // 생성 응답이 두 provider/세 dataset을 그대로 담는다(동기 캡처).
        expect(created.create.data.providers).toEqual(
          expect.arrayContaining([providerA, providerB]),
        );
        expect(created.create.data.providers).toHaveLength(2);
        expect(created.create.data.dataset_keys).toEqual(
          expect.arrayContaining([datasetA, datasetB, datasetC]),
        );
        expect(created.create.data.dataset_keys).toHaveLength(3);
        expect(created.create.data.status).toBe("queued");

        const successAlert = page
          .getByRole("status")
          .filter({ hasText: "요청 처리 완료" });
        await expect(successAlert).toBeVisible(T);
        await expect(successAlert).toContainText(requestId as string);
      });

      await test.step("목록 행이 두 provider를 함께 노출한다", async () => {
        const row = rowContaining(page, providerA);
        await expect(row).toBeVisible(T);
        await expect(row).toContainText(providerB);
      });

      await test.step("detail/list API가 다중 provider/dataset를 모두 반환한다", async () => {
        await expect
          .poll(
            async () =>
              (await fetchDetailByApi(page, requestId as string)).status,
            T,
          )
          .toBe(200);
        const detail = await fetchDetailByApi(page, requestId as string);
        expect(detail.body?.data.providers).toEqual(
          expect.arrayContaining([providerA, providerB]),
        );
        expect(detail.body?.data.dataset_keys).toEqual(
          expect.arrayContaining([datasetA, datasetB, datasetC]),
        );

        // providerA, providerB 각각으로 필터해도 같은 row를 찾는다(@> 멤버십 매칭).
        for (const provider of [providerA, providerB]) {
          const list = await fetchListByProviderApi(page, provider);
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

  test("provider 개수 제한(>32)을 위반하면 422가 표면화되고 백엔드에 아무것도 쌓이지 않는다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE,
      "E2E_FEATURE_UPDATE_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 write flow를 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    // 라우터: providers list max_length=MAX_PROVIDER_FILTERS(32) → 33개면 서버 422.
    const badBase = inertProvider("bad");
    const tooManyProviders = [...Array(33).keys()].map(
      (index) => `${badBase}_${index}`,
    );

    await gotoUpdateRequests(page);

    await test.step("33개 provider로 요청하면 POST가 422로 거절된다", async () => {
      await page
        .getByLabel("providers", { exact: true })
        .fill(tooManyProviders.join(","));
      const responsePromise = waitForApiResponse(page, "POST", LIST_PATH);
      await page.getByRole("button", { name: "요청 생성" }).click();
      const response = await responsePromise;
      expect(response.status()).toBe(422);
    });

    await test.step("UI에 생성 실패 alert이 뜨고 성공 alert은 없다", async () => {
      // destructive alert = role=alert (alert.tsx: variant=destructive → role=alert).
      await expect(
        page.getByRole("alert").filter({ hasText: "요청 생성 실패" }),
      ).toBeVisible(T);
      await expect(
        page.getByRole("status").filter({ hasText: "요청 처리 완료" }),
      ).toHaveCount(0);
    });

    await test.step("백엔드 목록에 해당 provider row가 없다(영속 안 됨)", async () => {
      const list = await fetchListByProviderApi(page, `${badBase}_0`);
      expect(list.status).toBe(200);
      expect(list.body?.data.items ?? []).toHaveLength(0);
    });
  });

  test("request status 필터가 status query param으로 내려가고 목록이 그에 맞게 좁혀진다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE,
      "E2E_FEATURE_UPDATE_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 write flow를 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    const provider = inertProvider("filter");
    const dataset = inertDataset("filter");
    let requestId: string | null = null;

    try {
      await gotoUpdateRequests(page);

      await test.step("queued 요청을 하나 만든다", async () => {
        const created = await createInertQueuedRequest(page, { provider, dataset });
        requestId = created.requestId;
        expect(created.create.data.status).toBe("queued");
      });

      await test.step("queued 필터에서 우리 row가 보이고 API도 queued만 반환한다", async () => {
        await page.getByLabel("request status").selectOption("queued");
        const row = rowContaining(page, provider);
        await expect(row).toBeVisible(T);
        await expect(row).toContainText("queued");

        const list = await fetchListByProviderApi(page, provider, "queued");
        expect(list.status).toBe(200);
        const found = list.body?.data.items.find(
          (item) => item.request_id === requestId,
        );
        expect(found).toBeDefined();
        expect(found?.status).toBe("queued");
      });

      await test.step("done 필터 선택 시 status=done query가 나가고 우리 row는 사라진다", async () => {
        const responsePromise = waitForListStatusResponse(page, "done");
        await page.getByLabel("request status").selectOption("done");
        const response = await responsePromise;
        expect(new URL(response.url()).searchParams.get("status")).toBe("done");

        // queued row는 done 목록에서 빠진다(UI 반영).
        await expect(rowContaining(page, provider)).toHaveCount(0);

        const list = await fetchListByProviderApi(page, provider, "done");
        expect(list.status).toBe(200);
        const found = list.body?.data.items.find(
          (item) => item.request_id === requestId,
        );
        expect(found).toBeUndefined();
      });

      await test.step("running 필터 선택 시 status=running query가 나가고 결과는 모두 running이다", async () => {
        const responsePromise = waitForListStatusResponse(page, "running");
        await page.getByLabel("request status").selectOption("running");
        const response = await responsePromise;
        expect(new URL(response.url()).searchParams.get("status")).toBe(
          "running",
        );

        const list = await fetchListByProviderApi(page, provider, "running");
        expect(list.status).toBe(200);
        for (const item of list.body?.data.items ?? []) {
          expect(item.status).toBe("running");
        }
        const found = (list.body?.data.items ?? []).find(
          (item) => item.request_id === requestId,
        );
        expect(found).toBeUndefined();
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

    const provider = inertProvider("detail");
    const dataset = inertDataset("detail");
    const lon = "127.01234";
    const lat = "37.61234";
    const radiusKm = "3";
    let requestId: string | null = null;

    try {
      await gotoUpdateRequests(page);

      await test.step("구별되는 좌표/반경으로 queued 요청을 만든다", async () => {
        const created = await createInertQueuedRequest(page, {
          provider,
          dataset,
          lon,
          lat,
          radiusKm,
        });
        requestId = created.requestId;
      });

      await test.step("행의 상세 링크로 이동한다", async () => {
        const row = rowContaining(page, provider);
        await expect(row).toBeVisible(T);
        await row.getByRole("link").click();
        await expect(page).toHaveURL(
          new RegExp(
            `/admin/feature-update-requests/${escapeRegExp(
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
        expect(data?.dry_run).toBe(false);
        expect(data?.providers).toContain(provider);
        expect(data?.dataset_keys).toContain(dataset);
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
          .filter({ hasText: "Matched scope" })
          .locator("pre")
          .first();
        await expect(scopePre).toContainText(`"center_radius"`);
        await expect(scopePre).toContainText(lon);
        await expect(scopePre).toContainText(lat);

        // Policy <pre>: update_policy가 비어 있어 "{}".
        const policyPre = page
          .locator("section")
          .filter({ hasText: "Policy" })
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

    const provider = inertProvider("cancel");
    const dataset = inertDataset("cancel");
    let requestId: string | null = null;

    try {
      await gotoUpdateRequests(page);

      await test.step("queued 요청을 만든다", async () => {
        const created = await createInertQueuedRequest(page, { provider, dataset });
        requestId = created.requestId;
      });

      await test.step("queued row의 cancel 버튼이 POST /cancel을 호출하고 cancelled를 반환한다", async () => {
        await page.getByLabel("request status").selectOption("queued");
        const row = rowContaining(page, provider);
        await expect(row).toBeVisible(T);

        const responsePromise = waitForApiResponse(
          page,
          "POST",
          cancelPath(requestId as string),
        );
        await row.getByRole("button", { name: "cancel" }).click();
        const response = await responsePromise;
        expect(response.status()).toBe(200);
        const body =
          (await response.json()) as FeatureUpdateRequestCreateResponse;
        expect(body.data.request_id).toBe(requestId);
        expect(body.data.status).toBe("cancelled");
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
        await page.getByLabel("request status").selectOption("cancelled");
        const row = rowContaining(page, provider);
        await expect(row).toBeVisible(T);
        await expect(row).toContainText("cancelled");
      });
    } finally {
      // 이미 terminal(cancelled)이면 cleanup cancel은 409 → cancelByApi가 삼킨다.
      if (requestId) await cancelByApi(page, requestId);
    }
  });

  test("목록 actions의 run-now 버튼이 run_mode=now로 재큐잉하고 status가 전이된다", async ({
    page,
  }) => {
    test.skip(
      !(EXECUTE && RUN_NOW),
      "E2E_FEATURE_UPDATE_RUN=1과 write 플래그가 모두 켜졌을 때만 실제 Dagster run을 깨운다",
    );
    test.setTimeout(FLOW_TIMEOUT);

    const provider = inertProvider("runnow");
    const dataset = inertDataset("runnow");
    let requestId: string | null = null;
    let runNowRequestId: string | null = null;

    try {
      await gotoUpdateRequests(page);

      await test.step("queued 요청을 만든다", async () => {
        const created = await createInertQueuedRequest(page, { provider, dataset });
        requestId = created.requestId;
      });

      await test.step("run-now 버튼이 run_mode=now 신규 row를 201로 enqueue한다", async () => {
        await page.getByLabel("request status").selectOption("queued");
        const row = rowContaining(page, provider);
        await expect(row).toBeVisible(T);

        const responsePromise = waitForApiResponse(
          page,
          "POST",
          runNowPath(requestId as string),
        );
        await row.getByRole("button", { name: "run-now" }).click();
        const runResponse = await readCreateResponse(await responsePromise);
        runNowRequestId = runResponse.data.request_id ?? null;
        expect(runNowRequestId).not.toBeNull();
        expect(runNowRequestId).not.toBe(requestId);
        expect(runResponse.data.run_mode).toBe("now");
        expect(runResponse.data.providers).toContain(provider);
      });

      await test.step("새 now 요청의 status가 queued를 벗어난다(runner 활성 전제)", async () => {
        await expect
          .poll(
            async () => {
              const res = await fetchDetailByApi(
                page,
                runNowRequestId as string,
              );
              return res.body?.data.status ?? `http:${res.status}`;
            },
            { timeout: FLOW_TIMEOUT },
          )
          .not.toBe("queued");
      });
    } finally {
      for (const id of [runNowRequestId, requestId]) {
        if (id) await cancelByApi(page, id);
      }
    }
  });
});
