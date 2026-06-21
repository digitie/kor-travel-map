import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";

/**
 * `/admin/feature-update-requests/[requestId]` 상세 — 액션/에러/실시간 depth spec
 * (T-AUDIT-0616, `docs/reports/e2e-scenario-coverage-2026-06-16.md` §1.3 후속).
 *
 * `feature-update-request-detail.spec.ts`(smoke + 버튼 가시성)와 **중복되지 않는**
 * 깊이 시나리오만 더한다:
 *  - cancel/run-now POST가 정확한 pathname·method·body로 단 1회 발사되는지(payload 단언)
 *  - run-now가 201을 반환해도 onSuccess invalidation → 상세 re-fetch가 도는지
 *  - failed/cancelled 같은 done 외 terminal 분기의 버튼 가시성
 *  - cancel/run-now mutation 실패(409)가 같은 destructive Alert를 띄우고 버튼이 잔존하는지
 *  - 새로고침(refetch) 버튼 / "목록" back-link
 *  - status 전환(running→done)이 자동 폴링 re-fetch로 반영되는지(WS 실시간 invalidation의
 *    deterministic 대체 — 아래 NOTE 참고)
 *
 * 패턴은 `admin-ops.spec.ts`/`feature-update-request-detail.spec.ts`와 동일하게
 * `**​/v1/admin/feature-update-requests/**`만 가로채고, 페이지 document·RSC·WS는 그대로
 * 통과시킨다. mock body는 모두 생성된 OpenAPI 타입에 바인딩해 계약 drift를 컴파일에서
 * 잡는다.
 *
 * WS 실시간 invalidation 직접 검증을 넣지 않은 이유: `useOpsLiveInvalidation`은
 * BASE_URL(`http://127.0.0.1:12701`)로 cross-origin WS를 연다(`live.ts` 35-46). 페이지는
 * 12705에서 서빙되므로 `page.routeWebSocket`로 mock하려면 cross-origin glob이 필요하고,
 * Windows 호스트 런에서만 실증 가능해 본 recon 시점엔 미검증이다. 대신
 * `useFeatureUpdateRequest`의 refetchInterval(`updateRequests.ts` 133-136 — status∈
 * {queued,running}일 때 2s 폴링)로 status 전환을 deterministic하게 검증한다. WS mock이
 * Windows 런에서 안정 동작함이 확인되면 routeWebSocket 시나리오로 승격 가능.
 *
 * NOTE: Playwright는 Windows 호스트에서만 실행된다(`playwright.config.ts`).
 */

type FeatureUpdateRequestRecord =
  components["schemas"]["FeatureUpdateRequestRecord"];
type FeatureUpdateRequestDetailResponse =
  components["schemas"]["FeatureUpdateRequestDetailResponse"];
type FeatureUpdateRequestCreateResponse =
  components["schemas"]["FeatureUpdateRequestCreateResponse"];
type FeatureUpdateRequestCancelRequest =
  components["schemas"]["FeatureUpdateRequestCancelRequest"];
type FeatureUpdateRequestRunNowRequest =
  components["schemas"]["FeatureUpdateRequestRunNowRequest"];
type Meta = components["schemas"]["Meta"];

const REQUEST_ID = "88888888-8888-4888-8888-888888888888";
const JOB_ID = "99999999-9999-4999-8999-999999999999";
const DETAIL_PATH = `/v1/admin/feature-update-requests/${REQUEST_ID}`;
const LIST_PATH = "/admin/feature-update-requests";

const meta: Meta = { duration_ms: 1, request_id: "e2e-fur-detail-actions" };

function makeUpdateRequest(
  overrides: Partial<FeatureUpdateRequestRecord> = {},
): FeatureUpdateRequestRecord {
  return {
    created_at: "2026-06-08T00:00:00.000Z",
    dagster_run_id: "dagster-run-fur-002",
    dataset_keys: ["festival_open_api"],
    dry_run: true,
    job_id: JOB_ID,
    // scope/matched_scope/policy mock 값에 'running'/'done'/'failed' 문자열을 넣지 않아
    // StatusBadge 텍스트 단언이 pre 블록과 충돌(strict mode)하지 않게 한다.
    matched_scope: { sido_code: "11" },
    operator: "local-admin",
    priority: 100,
    providers: ["python-visitkorea-api"],
    reason: "e2e",
    request_id: REQUEST_ID,
    run_mode: "queued",
    scope: { kind: "sido", sido_code: "11" },
    scope_type: "sido",
    status: "queued",
    update_policy: { mode: "upsert" },
    updated_at: "2026-06-08T00:05:00.000Z",
    ...overrides,
  };
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

type MockOptions = {
  /** 초기(첫 GET) status. */
  initialStatus?: string;
  /**
   * 단계 전환: WS/폴링 시나리오용. 지정하면 GET 호출 횟수가
   * `transitionAfterDetailCalls`를 넘은 시점부터 이 status를 반환한다.
   */
  transitionStatus?: string;
  transitionAfterDetailCalls?: number;
  shouldTransition?: () => boolean;
  /** cancel/run-now POST가 반환할 HTTP status(>=400이면 mutation 실패 분기). */
  mutationStatus?: number;
  /** mutation 실패 시 반환할 problem+json body(docs/architecture/rest-api.md §error). */
  mutationError?: {
    status: number;
    detail: string;
    code: string;
    request_id: string;
  };
};

type Calls = {
  detail: number;
  cancel: number;
  runNow: number;
  cancelBody: FeatureUpdateRequestCancelRequest | null;
  runNowBody: FeatureUpdateRequestRunNowRequest | null;
};

/**
 * 상세 GET / cancel / run-now를 한 핸들러로 가로챈다.
 *  - cancel/run-now POST의 method·pathname·body·횟수를 캡처
 *  - 성공(2xx) 시 status를 갈아끼워 후속 GET이 전환된 상태를 반환(가시성 변화 검증)
 *  - mutationStatus>=400이면 POST를 실패시켜 mutation error 분기를 트리거(status 미변경)
 *  - transitionStatus가 있으면 GET 횟수 기반으로 status를 단계 전환(폴링 검증)
 */
async function mockUpdateRequest(
  page: Page,
  options: MockOptions = {},
): Promise<Calls> {
  const calls: Calls = {
    detail: 0,
    cancel: 0,
    runNow: 0,
    cancelBody: null,
    runNowBody: null,
  };
  let status = options.initialStatus ?? "queued";
  const mutationStatus = options.mutationStatus ?? 0;
  const mutationFails = mutationStatus >= 400;

  await page.route(
    "**/v1/admin/feature-update-requests/**",
    async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const method = request.method();

      if (method === "POST" && url.pathname === `${DETAIL_PATH}/cancel`) {
        calls.cancel += 1;
        calls.cancelBody =
          request.postDataJSON() as FeatureUpdateRequestCancelRequest;
        if (mutationFails) {
          await fulfillJson(
            route,
            options.mutationError ?? {
              status: mutationStatus,
              detail: "request 상태가 cancel과 충돌합니다.",
              code: "feature_update_request_conflict",
              request_id: "e2e-cancel-409",
            },
            mutationStatus,
          );
          return;
        }
        status = "cancelled";
        const body: FeatureUpdateRequestCreateResponse = {
          data: makeUpdateRequest({ status }),
          meta,
        };
        await fulfillJson(route, body);
        return;
      }

      if (method === "POST" && url.pathname === `${DETAIL_PATH}/run-now`) {
        calls.runNow += 1;
        calls.runNowBody =
          request.postDataJSON() as FeatureUpdateRequestRunNowRequest;
        if (mutationFails) {
          await fulfillJson(
            route,
            options.mutationError ?? {
              status: mutationStatus,
              detail: "request 상태가 run-now와 충돌합니다.",
              code: "feature_update_request_conflict",
              request_id: "e2e-run-now-409",
            },
            mutationStatus,
          );
          return;
        }
        status = "running";
        const body: FeatureUpdateRequestCreateResponse = {
          data: makeUpdateRequest({ status, run_mode: "now" }),
          meta,
        };
        await fulfillJson(route, body, 201);
        return;
      }

      if (method === "GET" && url.pathname === DETAIL_PATH) {
        calls.detail += 1;
        let effectiveStatus = status;
        if (
          options.transitionStatus &&
          options.transitionAfterDetailCalls !== undefined &&
          (options.shouldTransition?.() ?? true) &&
          calls.detail > options.transitionAfterDetailCalls
        ) {
          status = options.transitionStatus;
          effectiveStatus = options.transitionStatus;
        }
        const body: FeatureUpdateRequestDetailResponse = {
          data: makeUpdateRequest({ status: effectiveStatus }),
          meta,
        };
        await fulfillJson(route, body);
        return;
      }

      await route.continue();
    },
  );

  return calls;
}

test.describe("/admin/feature-update-requests/[requestId] actions", () => {
  test("cancel 액션 → POST /cancel body(error_message) + 호출 1회 + re-fetch", async ({
    page,
  }) => {
    const calls = await mockUpdateRequest(page, { initialStatus: "queued" });
    await page.goto(`/admin/feature-update-requests/${REQUEST_ID}`);

    const cancel = page.getByRole("button", { name: "cancel" });
    await expect(cancel).toBeVisible();
    const detailBefore = calls.detail;

    await cancel.click();

    // POST가 정확히 /cancel pathname으로 단 1회.
    await expect.poll(() => calls.cancel).toBe(1);
    // component(line 113-116)가 보내는 고정 error_message.
    const cancelBody: FeatureUpdateRequestCancelRequest | null = calls.cancelBody;
    expect(cancelBody).toMatchObject({
      error_message: "cancelled from feature update request detail",
    });
    // 성공 → status=cancelled(terminal) → cancel 버튼 사라짐 + 상세 re-fetch.
    await expect(cancel).toBeHidden();
    await expect.poll(() => calls.detail).toBeGreaterThan(detailBefore);
  });

  test("run-now 액션 → POST /run-now body(reason) + 201 처리 + 호출 1회", async ({
    page,
  }) => {
    const calls = await mockUpdateRequest(page, { initialStatus: "queued" });
    await page.goto(`/admin/feature-update-requests/${REQUEST_ID}`);

    const runNow = page.getByRole("button", { name: "run-now" });
    await expect(runNow).toBeVisible();
    const detailBefore = calls.detail;

    await runNow.click();

    await expect.poll(() => calls.runNow).toBe(1);
    // component(line 131)가 보내는 고정 reason.
    const runNowBody: FeatureUpdateRequestRunNowRequest | null =
      calls.runNowBody;
    expect(runNowBody).toMatchObject({
      reason: "run-now from detail view",
    });
    // 201 응답이어도 onSuccess invalidation → status=running → run-now 숨김 + re-fetch.
    await expect(runNow).toBeHidden();
    await expect.poll(() => calls.detail).toBeGreaterThan(detailBefore);
  });

  test("failed terminal — cancel 숨김, run-now 유지(재큐잉)", async ({
    page,
  }) => {
    await mockUpdateRequest(page, { initialStatus: "failed" });
    await page.goto(`/admin/feature-update-requests/${REQUEST_ID}`);

    await expect(
      page.getByRole("heading", { level: 1, name: "Feature update request" }),
    ).toBeVisible();
    // failed ∈ terminalStatuses(component line 26) → canCancel=false.
    await expect(page.getByRole("button", { name: "cancel" })).toBeHidden();
    // failed != running → canRunNow=true.
    await expect(page.getByRole("button", { name: "run-now" })).toBeVisible();
    // StatusBadge가 status 문자열 그대로 렌더(status-badge.tsx line 37).
    await expect(page.getByText("failed", { exact: true })).toBeVisible();
  });

  test("cancelled terminal — cancel 숨김, run-now는 재큐잉 가능", async ({
    page,
  }) => {
    await mockUpdateRequest(page, { initialStatus: "cancelled" });
    await page.goto(`/admin/feature-update-requests/${REQUEST_ID}`);

    await expect(
      page.getByRole("heading", { level: 1, name: "Feature update request" }),
    ).toBeVisible();
    // cancelled ∈ terminalStatuses → cancel 숨김.
    await expect(page.getByRole("button", { name: "cancel" })).toBeHidden();
    // cancelled != running → terminal이어도 run-now는 노출(재큐잉 허용).
    await expect(page.getByRole("button", { name: "run-now" })).toBeVisible();
  });

  test("cancel 실패(409) → request 조회 실패 alert + cancel 버튼 잔존", async ({
    page,
  }) => {
    const calls = await mockUpdateRequest(page, {
      initialStatus: "queued",
      mutationStatus: 409,
    });
    await page.goto(`/admin/feature-update-requests/${REQUEST_ID}`);

    const cancel = page.getByRole("button", { name: "cancel" });
    await expect(cancel).toBeVisible();

    await cancel.click();

    // cancelRequest.isError → 동일 destructive Alert(component line 78,80).
    await expect(page.getByText("request 조회 실패")).toBeVisible();
    await expect.poll(() => calls.cancel).toBe(1);
    // mutation 실패라 status 미변경(queued) → cancel 버튼은 계속 노출.
    await expect(cancel).toBeVisible();
  });

  test("run-now 실패(409) → request 조회 실패 alert + run-now 버튼 잔존", async ({
    page,
  }) => {
    const calls = await mockUpdateRequest(page, {
      initialStatus: "queued",
      mutationStatus: 409,
    });
    await page.goto(`/admin/feature-update-requests/${REQUEST_ID}`);

    const runNow = page.getByRole("button", { name: "run-now" });
    await expect(runNow).toBeVisible();

    await runNow.click();

    // runNow.isError → 동일 Alert(component line 78). cancel-error와 별개 분기.
    await expect(page.getByText("request 조회 실패")).toBeVisible();
    await expect.poll(() => calls.runNow).toBe(1);
    // mutation 실패라 status 미변경(queued) → run-now 버튼 잔존.
    await expect(runNow).toBeVisible();
  });

  test("새로고침 버튼 → 수동 refetch 발사", async ({ page }) => {
    // done(폴링 off)로 mock해 자동 refetchInterval과 수동 refetch 증가를 구분.
    const calls = await mockUpdateRequest(page, { initialStatus: "done" });
    await page.goto(`/admin/feature-update-requests/${REQUEST_ID}`);

    await expect(
      page.getByRole("heading", { level: 1, name: "Feature update request" }),
    ).toBeVisible();
    // 초기 GET이 끝나 화면이 그려질 때까지 대기 후 카운트 고정.
    await expect(page.getByText("done", { exact: true })).toBeVisible();
    const detailBefore = calls.detail;

    await page.getByRole("button", { name: "새로고침" }).click();

    // request.refetch() → 상세 GET 재호출(component line 62-70).
    await expect.poll(() => calls.detail).toBeGreaterThan(detailBefore);
  });

  test("목록 back-link → /admin/feature-update-requests href", async ({
    page,
  }) => {
    await mockUpdateRequest(page, { initialStatus: "queued" });
    await page.goto(`/admin/feature-update-requests/${REQUEST_ID}`);

    // "목록" 링크(component line 52-58, ArrowLeftIcon + "목록").
    await expect(page.getByRole("link", { name: "목록" })).toHaveAttribute(
      "href",
      LIST_PATH,
    );
  });

  test("폴링 re-fetch — running→done 전환이 자동 재조회로 반영", async ({
    page,
  }) => {
    // WS 실시간 invalidation의 deterministic 대체. refetchInterval(2s)이
    // status∈{queued,running}일 때 폴링하므로, 첫 GET=running 이후 다음 폴링에서
    // done을 반환하면 cancel 버튼이 사라진다(=재조회가 실제로 발생했다는 증거).
    let allowTransition = false;
    const calls = await mockUpdateRequest(page, {
      initialStatus: "running",
      transitionStatus: "done",
      transitionAfterDetailCalls: 1,
      shouldTransition: () => allowTransition,
    });
    await page.goto(`/admin/feature-update-requests/${REQUEST_ID}`);

    const cancel = page.getByRole("button", { name: "cancel" });
    // running → canCancel=true, canRunNow=false.
    await expect(cancel).toBeVisible();
    await expect(page.getByRole("button", { name: "run-now" })).toBeHidden();

    allowTransition = true;

    // 2s 폴링이 done을 반환 → terminal → cancel 사라지고 run-now 노출.
    // 전체 스위트 병렬 부하에서도 안정적이도록 타임아웃 여유를 둔다(2s 폴링 간격 +
    // 5s staleTime + 렌더; 단일 실행 ~3s, 부하 시 8s 근접해 flaky했음).
    await expect(cancel).toBeHidden({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: "run-now" })).toBeVisible();
    // 폴링이 최소 1회 추가 fetch.
    await expect.poll(() => calls.detail).toBeGreaterThanOrEqual(2);
  });
});
