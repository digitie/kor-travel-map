import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";
import { bffApiPath } from "./bff-api-path";
import { makePipelineCancellationResponse } from "./pipeline-cancellation-fixture";
import { installInertOpsLiveWebSocket } from "./ws-isolation";

/**
 * `/admin/features/update-requests/[requestId]` 상세 — 액션/에러/실시간 depth spec
 * (T-AUDIT-0616, `docs/reports/e2e-scenario-coverage-2026-06-16.md` §1.3 후속).
 *
 * `feature-update-request-detail.spec.ts`(smoke + 버튼 가시성)와 **중복되지 않는**
 * 깊이 시나리오만 더한다:
 *  - cancel/run-now POST가 정확한 pathname·method·body로 단 1회 발사되는지(payload 단언)
 *  - run-now가 원 요청을 바꾸지 않고 새 request_id를 반환·안내하는지
 *  - failed/cancelled 같은 done 외 terminal 분기의 버튼 가시성
 *  - cancel/run-now mutation 실패(409)가 액션별 Alert를 띄우고 버튼이 잔존하는지
 *  - 새로고침(refetch) 버튼 / "목록" back-link
 *  - status 전환(running→done)이 자동 폴링 re-fetch로 반영되는지(WS 실시간 invalidation의
 *    deterministic 대체 — 아래 NOTE 참고)
 *
 * 패턴은 `admin-ops.spec.ts`/`feature-update-request-detail.spec.ts`와 동일하게
 * `**​/v1/admin/features/update-requests/**`만 가로채고, 페이지 document·RSC·WS는 그대로
 * 통과시킨다. mock body는 모두 생성된 OpenAPI 타입에 바인딩해 계약 drift를 컴파일에서
 * 잡는다.
 *
 * WS 격리(#503): `useOpsLiveInvalidation`은 BASE_URL(`http://127.0.0.1:12701`)로
 * cross-origin WS를 연다(`live.ts`). 페이지는 12705에서 서빙되므로 `page.routeWebSocket`
 * cross-origin glob은 Windows 호스트 런에서만 실증 가능했다. 대신 `beforeEach`에서
 * `installInertOpsLiveWebSocket(page)`(`e2e/ws-isolation.ts`, origin-agnostic
 * addInitScript no-op 스텁)로 WS를 deterministic하게 inert로 만든다 — 라이브 백엔드
 * snapshot/update가 mock GET 버스트를 유발하지 않으므로 status 전환은 오롯이
 * `useFeatureUpdateRequest`의 refetchInterval(`updateRequests.ts` 133-136 — status∈
 * {queued,running}일 때 2s 폴링) 경로로만 검증된다.
 *
 * NOTE: Playwright는 Windows 호스트에서만 실행된다(`playwright.config.ts`).
 */

type FeatureUpdateRequestRecord =
  components["schemas"]["FeatureUpdateRequestRecord"];
type FeatureUpdateRequestDetailResponse =
  components["schemas"]["FeatureUpdateRequestDetailResponse"];
type FeatureUpdateRequestMutationResponse =
  components["schemas"]["FeatureUpdateRequestMutationResponse"];
type FeatureUpdateStatus = FeatureUpdateRequestRecord["status"];
type PipelineCancellationRequest =
  components["schemas"]["PipelineCancellationRequest"];
type FeatureUpdateRequestRunNowRequest =
  components["schemas"]["FeatureUpdateRequestRunNowRequest"];
type Meta = components["schemas"]["Meta"];

const REQUEST_ID = "88888888-8888-4888-8888-888888888888";
const NEW_REQUEST_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const JOB_ID = "99999999-9999-4999-8999-999999999999";
const NEW_JOB_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const DETAIL_PATH = `/v1/admin/features/update-requests/${REQUEST_ID}`;
const NEW_DETAIL_PATH = `/v1/admin/features/update-requests/${NEW_REQUEST_ID}`;
const LIST_PATH = "/admin/features/update-requests";

const meta: Meta = { duration_ms: 1, request_id: "e2e-fur-detail-actions" };

function makeUpdateRequest(
  overrides: Partial<FeatureUpdateRequestRecord> = {},
): FeatureUpdateRequestRecord {
  return {
    created_at: "2026-06-08T00:00:00.000Z",
    dagster_run_id: "dagster-run-fur-002",
    dataset_keys: ["festival_open_api"],
    error_message: null,
    finished_at: null,
    job_id: JOB_ID,
    // scope/matched_scope/policy mock 값에 'running'/'done'/'failed' 문자열을 넣지 않아
    // StatusBadge 텍스트 단언이 pre 블록과 충돌(strict mode)하지 않게 한다.
    matched_scope: { feature_count: 1, sigungu_codes: ["11110"] },
    operator: "e2e-authenticated-admin",
    priority: 100,
    providers: ["python-visitkorea-api"],
    reason: "e2e",
    request_id: REQUEST_ID,
    run_mode: "queued",
    scope: {
      type: "center_radius",
      center: { lon: 126.978, lat: 37.5665 },
      radius_km: 5,
    },
    scope_type: "center_radius",
    status: "queued",
    status_url: `/v1/admin/features/update-requests/${REQUEST_ID}`,
    started_at: null,
    update_policy: { mode: "refresh_existing" },
    generation: 1,
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
  initialStatus?: FeatureUpdateStatus;
  /**
   * 단계 전환: WS/폴링 시나리오용. 지정하면 GET 호출 횟수가
   * `transitionAfterDetailCalls`를 넘은 시점부터 이 status를 반환한다.
   */
  transitionStatus?: FeatureUpdateStatus;
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
  newDetail: number;
  cancel: number;
  runNow: number;
  cancelBody: PipelineCancellationRequest | null;
  runNowBody: FeatureUpdateRequestRunNowRequest | null;
  runNowRecord: FeatureUpdateRequestRecord | null;
};

/**
 * 상세 GET / cancel / run-now를 한 핸들러로 가로챈다.
 *  - cancel/run-now POST의 method·pathname·body·횟수를 캡처
 *  - cancel은 원 요청 상태를 바꾸고, run-now는 원 요청 불변 + 신규 요청 201을 반환
 *  - mutationStatus>=400이면 POST를 실패시켜 mutation error 분기를 트리거(status 미변경)
 *  - transitionStatus가 있으면 GET 횟수 기반으로 status를 단계 전환(폴링 검증)
 */
async function mockUpdateRequest(
  page: Page,
  options: MockOptions = {},
): Promise<Calls> {
  const calls: Calls = {
    detail: 0,
    newDetail: 0,
    cancel: 0,
    runNow: 0,
    cancelBody: null,
    runNowBody: null,
    runNowRecord: null,
  };
  let status = options.initialStatus ?? "queued";
  const mutationStatus = options.mutationStatus ?? 0;
  const mutationFails = mutationStatus >= 400;

  await page.route(
    "**/v1/admin/features/update-requests/**",
    async (route) => {
      const request = route.request();
      const pathname = bffApiPath(request.url());
      const method = request.method();

      if (method === "POST" && pathname === `${DETAIL_PATH}/cancel`) {
        calls.cancel += 1;
        calls.cancelBody =
          request.postDataJSON() as PipelineCancellationRequest;
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
        const body = makePipelineCancellationResponse({
          rootKind: "update_request",
          rootId: REQUEST_ID,
          initialStatus: "queued",
          reason: "cancelled from feature update request detail",
          members: [{ jobId: JOB_ID }],
        });
        await fulfillJson(route, body);
        return;
      }

      if (method === "POST" && pathname === `${DETAIL_PATH}/run-now`) {
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
        const runNowRecord = makeUpdateRequest({
          request_id: NEW_REQUEST_ID,
          job_id: NEW_JOB_ID,
          priority: calls.runNowBody?.priority ?? 100,
          reason: calls.runNowBody?.reason ?? `run-now from ${REQUEST_ID}`,
          run_mode: "now",
          status: "queued",
          status_url: `/v1/admin/features/update-requests/${NEW_REQUEST_ID}`,
        });
        calls.runNowRecord = runNowRecord;
        const body: FeatureUpdateRequestMutationResponse = {
          data: runNowRecord,
          meta,
        };
        await fulfillJson(route, body, 201);
        return;
      }

      if (method === "GET" && pathname === DETAIL_PATH) {
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

      if (method === "GET" && pathname === NEW_DETAIL_PATH) {
        calls.newDetail += 1;
        await fulfillJson(
          route,
          { detail: "run-now mutation cache miss" },
          500,
        );
        return;
      }

      await route.continue();
    },
  );

  return calls;
}

test.describe("/admin/features/update-requests/[requestId] actions", () => {
  // #503: 모든 시나리오에서 ops-live WS를 inert로 만들어 라이브 백엔드 snapshot/update가
  // mock GET 버스트를 유발하지 않게 한다(타이밍 단언 결정성 확보). page.goto 전에 적용.
  test.beforeEach(async ({ page }) => {
    await installInertOpsLiveWebSocket(page);
  });

  test("cancel 액션 → POST /cancel body(reason) + 호출 1회 + re-fetch", async ({
    page,
  }) => {
    const calls = await mockUpdateRequest(page, { initialStatus: "queued" });
    await page.goto(`/admin/features/update-requests/${REQUEST_ID}`);

    const cancel = page.getByRole("button", { name: "취소" });
    await expect(cancel).toBeVisible();
    const detailBefore = calls.detail;

    await cancel.click();

    // POST가 정확히 /cancel pathname으로 단 1회.
    await expect.poll(() => calls.cancel).toBe(1);
    // actor는 인증 context에서 정하고 UI는 reason만 전송한다.
    const cancelBody: PipelineCancellationRequest | null = calls.cancelBody;
    expect(cancelBody).toMatchObject({
      reason: "cancelled from feature update request detail",
    });
    const successAlert = page
      .getByRole("status")
      .filter({ hasText: "요청 취소 처리 결과" });
    await expect(successAlert).toContainText(REQUEST_ID);
    // 요청 lifecycle은 연결된 import job이 정본이므로 결과도 job 상태로 표현한다.
    await expect(successAlert).toContainText("연결 작업 상태 cancelled");
    await expect(successAlert).toContainText("취소 처리 상태 completed");
    // 성공 → status=cancelled(terminal) → cancel 버튼 사라짐 + 상세 re-fetch.
    await expect(cancel).toBeHidden();
    await expect.poll(() => calls.detail).toBeGreaterThan(detailBefore);
  });

  test("run-now 액션 → 원 요청 불변 + 새 request_id 안내", async ({
    page,
  }) => {
    const calls = await mockUpdateRequest(page, { initialStatus: "done" });
    await page.goto(`/admin/features/update-requests/${REQUEST_ID}`);

    const runNow = page.getByRole("button", { name: "즉시 실행" });
    await expect(runNow).toBeVisible();

    await runNow.click();

    await expect.poll(() => calls.runNow).toBe(1);
    // component(line 131)가 보내는 고정 reason.
    const runNowBody: FeatureUpdateRequestRunNowRequest | null =
      calls.runNowBody;
    expect(runNowBody).toMatchObject({
      reason: "run-now from detail view",
    });
    expect(runNowBody).not.toHaveProperty("operator");
    expect(calls.runNowRecord).toMatchObject({
      request_id: NEW_REQUEST_ID,
      job_id: NEW_JOB_ID,
      reason: "run-now from detail view",
      run_mode: "now",
    });
    expect(calls.runNowRecord?.job_id).not.toBe(JOB_ID);
    const successAlert = page
      .getByRole("status")
      .filter({ hasText: "즉시 실행 요청 생성 완료" });
    await expect(successAlert).toContainText("원본 요청은 변경되지 않았습니다.");
    const newRequestLink = successAlert.getByRole("link", {
      name: NEW_REQUEST_ID,
    });
    await expect(newRequestLink).toHaveAttribute(
      "href",
      `/admin/features/update-requests/${NEW_REQUEST_ID}`,
    );
    // 원 요청은 done 그대로라 즉시 실행 버튼과 완료 상태가 유지된다.
    await expect(runNow).toBeVisible();
    await expect(page.getByText("완료", { exact: true })).toBeVisible();

    await newRequestLink.click();
    await expect(page).toHaveURL(
      new RegExp(`/admin/features/update-requests/${NEW_REQUEST_ID}$`),
    );
    const newRequestSummary = page.locator("section").first();
    await expect(
      newRequestSummary.getByText(NEW_REQUEST_ID, { exact: true }),
    ).toBeVisible();
    await expect(
      newRequestSummary.getByText("now", { exact: true }),
    ).toBeVisible();
    await expect(
      newRequestSummary.getByText("대기", { exact: true }),
    ).toBeVisible();
    expect(calls.newDetail).toBe(0);
  });

  test("failed terminal — cancel 숨김, run-now 유지(재큐잉)", async ({
    page,
  }) => {
    await mockUpdateRequest(page, { initialStatus: "failed" });
    await page.goto(`/admin/features/update-requests/${REQUEST_ID}`);

    await expect(
      page.getByRole("heading", { level: 1, name: "갱신 요청 상세" }),
    ).toBeVisible();
    // failed ∈ terminalStatuses(component line 26) → canCancel=false.
    await expect(page.getByRole("button", { name: "취소" })).toBeHidden();
    // failed != running → canRunNow=true.
    await expect(page.getByRole("button", { name: "즉시 실행" })).toBeVisible();
    // StatusBadge가 status 문자열 그대로 렌더(status-badge.tsx line 37).
    await expect(page.getByText("실패", { exact: true })).toBeVisible();
  });

  test("cancelled terminal — cancel 숨김, run-now는 재큐잉 가능", async ({
    page,
  }) => {
    await mockUpdateRequest(page, { initialStatus: "cancelled" });
    await page.goto(`/admin/features/update-requests/${REQUEST_ID}`);

    await expect(
      page.getByRole("heading", { level: 1, name: "갱신 요청 상세" }),
    ).toBeVisible();
    // cancelled ∈ terminalStatuses → cancel 숨김.
    await expect(page.getByRole("button", { name: "취소" })).toBeHidden();
    // cancelled != running → terminal이어도 run-now는 노출(재큐잉 허용).
    await expect(page.getByRole("button", { name: "즉시 실행" })).toBeVisible();
  });

  test("cancel 실패(409) → 요청 취소 실패 alert + cancel 버튼 잔존", async ({
    page,
  }) => {
    const calls = await mockUpdateRequest(page, {
      initialStatus: "queued",
      mutationStatus: 409,
    });
    await page.goto(`/admin/features/update-requests/${REQUEST_ID}`);

    const cancel = page.getByRole("button", { name: "취소" });
    await expect(cancel).toBeVisible();

    await cancel.click();

    await expect(page.getByText("요청 취소 실패")).toBeVisible();
    await expect.poll(() => calls.cancel).toBe(1);
    // mutation 실패라 status 미변경(queued) → cancel 버튼은 계속 노출.
    await expect(cancel).toBeVisible();
  });

  test("run-now 실패(409) → 즉시 실행 생성 실패 alert + 버튼 잔존", async ({
    page,
  }) => {
    const calls = await mockUpdateRequest(page, {
      initialStatus: "queued",
      mutationStatus: 409,
    });
    await page.goto(`/admin/features/update-requests/${REQUEST_ID}`);

    const runNow = page.getByRole("button", { name: "즉시 실행" });
    await expect(runNow).toBeVisible();

    await runNow.click();

    await expect(page.getByText("즉시 실행 요청 생성 실패")).toBeVisible();
    await expect.poll(() => calls.runNow).toBe(1);
    // mutation 실패라 status 미변경(queued) → run-now 버튼 잔존.
    await expect(runNow).toBeVisible();
  });

  test("새로고침 버튼 → 수동 refetch 발사", async ({ page }) => {
    // done(폴링 off)로 mock해 자동 refetchInterval과 수동 refetch 증가를 구분.
    const calls = await mockUpdateRequest(page, { initialStatus: "done" });
    await page.goto(`/admin/features/update-requests/${REQUEST_ID}`);

    await expect(
      page.getByRole("heading", { level: 1, name: "갱신 요청 상세" }),
    ).toBeVisible();
    // 초기 GET이 끝나 화면이 그려질 때까지 대기 후 카운트 고정.
    await expect(page.getByText("완료", { exact: true })).toBeVisible();
    const detailBefore = calls.detail;

    await page.getByRole("button", { name: "새로고침" }).click();

    // request.refetch() → 상세 GET 재호출(component line 62-70).
    await expect.poll(() => calls.detail).toBeGreaterThan(detailBefore);
  });

  test("목록 back-link → /admin/features/update-requests href", async ({
    page,
  }) => {
    await mockUpdateRequest(page, { initialStatus: "queued" });
    await page.goto(`/admin/features/update-requests/${REQUEST_ID}`);

    // "목록" 링크(component line 52-58, ArrowLeftIcon + "목록").
    await expect(
      page.getByRole("link", { name: "목록", exact: true }),
    ).toHaveAttribute(
      "href",
      LIST_PATH,
    );
  });

  test("폴링 re-fetch — running→done 전환이 자동 재조회로 반영", async ({
    page,
  }) => {
    // WS는 beforeEach에서 inert(#503)라 status 전환은 refetchInterval 경로만으로
    // 검증된다(라이브 invalidation 잡음 없음). refetchInterval(2s)이
    // status∈{queued,running}일 때 폴링하므로, 첫 GET=running 이후 다음 폴링에서
    // done을 반환하면 cancel 버튼이 사라진다(=재조회가 실제로 발생했다는 증거).
    let allowTransition = false;
    const calls = await mockUpdateRequest(page, {
      initialStatus: "running",
      transitionStatus: "done",
      transitionAfterDetailCalls: 1,
      shouldTransition: () => allowTransition,
    });
    await page.goto(`/admin/features/update-requests/${REQUEST_ID}`);

    const cancel = page.getByRole("button", { name: "취소" });
    // running → canCancel=true, canRunNow=false.
    await expect(cancel).toBeVisible();
    await expect(page.getByRole("button", { name: "즉시 실행" })).toBeHidden();

    allowTransition = true;

    // 2s 폴링이 done을 반환 → terminal → cancel 사라지고 run-now 노출.
    // 전체 스위트 병렬 부하에서도 안정적이도록 타임아웃 여유를 둔다(2s 폴링 간격 +
    // 5s staleTime + 렌더; 단일 실행 ~3s, 부하 시 8s 근접해 flaky했음).
    await expect(cancel).toBeHidden({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: "즉시 실행" })).toBeVisible();
    // 폴링이 최소 1회 추가 fetch.
    await expect.poll(() => calls.detail).toBeGreaterThanOrEqual(2);
  });
});
