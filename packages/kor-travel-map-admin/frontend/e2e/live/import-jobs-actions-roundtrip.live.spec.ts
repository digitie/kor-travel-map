import { expect, test, type Page, type Response } from "@playwright/test";

import type { components } from "../../src/api/types";

/**
 * LIVE (비-mock) e2e — `/ops/import-jobs` 목록·상세의 실제 라운드트립.
 *
 * 기존 `import-jobs.live.spec.ts`는 컨트롤 PRESENCE/타이핑(값 반영)·URL 시드·
 * 반응형만 본다(행 텍스트/카운트/응답 body는 단언하지 않음). 본 파일은 그 위에
 * 실 백엔드 라운드트립을 추가한다(중복 없음):
 *
 *  A1 (ungated, read-only): status/kind 필터 → 목록 GET 쿼리 파라미터(status/kind,
 *      page_size=100, cursor 없음) → backend가 필터한 응답 body(items.every) → UI 행
 *      반영(필터된 응답의 첫 job deeplink 가시).
 *  A2 (ungated, read-only): 목록에서 job deeplink 클릭 → 상세 GET + events GET →
 *      JobSummary 필드(job_id/kind/progress) + Events 서브테이블이 응답을 반영.
 *  B  (GATED + EXTRA flag): queued(=in-flight 작업 손실 없는 SAFE 대상) job의 cancel
 *      POST → 응답·상세 GET·UI가 cancelled 전이를 반영.
 *
 * 라운드트립 규칙은 gold-standard(admin-features-change-requests-write.live.spec.ts)를
 * 미러: 외부 액션 → waitForApiResponse(/api/proxy 경로) → 응답 body 단언 →
 * expect.poll(browserFetch) backend 재확인 → UI 반영. browserFetch/apiPath/
 * isApiResponse/waitForApiResponse 헬퍼는 gold-standard에서 verbatim 복사.
 *
 * 비파괴/안전: A1·A2는 GET만 유발한다. B(cancel)는 ops.import_jobs 행을 cancelled로
 * **되돌릴 수 없게(irreversible)** 전이시키므로 (1) write 게이트(E2E_ADMIN_WRITE 또는
 * E2E_IMPORT_JOB_WRITE)에 더해 (2) 별도 명시 플래그 E2E_IMPORT_JOB_CANCEL=1 을 추가로
 * 요구하고, (3) 아직 시작 안 된 `queued` job만 대상으로 한다(running은 진행 중인 import를
 * 죽이므로 제외). 대상 job이 없으면 skip. cancel은 un-cancel API가 없어 finally 복구가
 * 불가능하다 — 그래서 이중 게이트로만 실행한다.
 *
 * selector는 import-jobs-client.tsx / import-job-detail-client.tsx에서 검증된 것만
 * 사용한다(요약의 인용 라인 참조). NOTE: Playwright는 Windows 호스트에서만 실행된다.
 */

type OpsImportJobsListResponse =
  components["schemas"]["OpsImportJobsListResponse"];
type OpsImportJobResponse = components["schemas"]["OpsImportJobResponse"];
type OpsImportJobRecord = components["schemas"]["OpsImportJobRecord"];
type OpsImportJobEventsListResponse =
  components["schemas"]["OpsImportJobEventsListResponse"];
type OpsImportJobCancelRequest =
  components["schemas"]["OpsImportJobCancelRequest"];

type BrowserFetchResult<T> = {
  body: T | null;
  status: number;
  text: string;
};

const UI_TIMEOUT = 15_000;
const FLOW_TIMEOUT = 5 * 60 * 1000;
const T = { timeout: UI_TIMEOUT } as const;

const LIST_ROUTE = "/ops/import-jobs";
const LIST_API_PATH = "/v1/ops/import-jobs";

const RUN_ID = `live-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

// terminal 상태 우선(필터 단언 중 status가 바뀌지 않게) → present 중 첫 매치.
const STATUS_PREFERENCE = [
  "done",
  "failed",
  "cancelled",
  "queued",
  "running",
] as const;

// write 게이트. cancel은 여기에 더해 EXTRA 플래그를 추가로 요구한다(아래).
const EXECUTE_WRITE =
  process.env.E2E_ADMIN_WRITE === "1" ||
  process.env.E2E_IMPORT_JOB_WRITE === "1";
// cancel은 irreversible → write 게이트 + 명시적 cancel 플래그 둘 다 있어야 실행.
const EXECUTE_CANCEL =
  EXECUTE_WRITE && process.env.E2E_IMPORT_JOB_CANCEL === "1";

test.describe.configure({ mode: "serial" });

// ── gold-standard verbatim helpers ──────────────────────────────────────────

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

// ── local helpers ────────────────────────────────────────────────────────────

/** import-jobs-client.tsx가 쓰는 lib/format.ts shortId(기본 size 12)와 동일 로직. */
function shortId(value: string, size = 12): string {
  return value.length > size ? `${value.slice(0, size)}...` : value;
}

/** 목록 GET 응답을 추가 query 술어로 좁혀 기다린다(필터 후속 GET 식별용). */
async function waitForListResponse(
  page: Page,
  predicate: (url: URL) => boolean,
): Promise<Response> {
  return page.waitForResponse(
    (response) =>
      isApiResponse(response, "GET", LIST_API_PATH) &&
      predicate(new URL(response.url())),
    { timeout: FLOW_TIMEOUT },
  );
}

/** 목록 페이지 로드 + 안정 landmark. */
async function gotoListReady(page: Page): Promise<void> {
  await page.goto(LIST_ROUTE);
  // import-jobs-client.tsx: AdminShell title="Import jobs" (line 186).
  await expect(
    page.getByRole("heading", { level: 1, name: "Import jobs" }),
  ).toBeVisible(T);
  // DataTable thead는 비어도 렌더 → columnheader "job"은 항상 존재.
  await expect(page.getByRole("columnheader", { name: "job" })).toBeVisible(T);
}

/** 직접 API 읽기(=browserFetch) — backend 정본 baseline. */
async function fetchJobs(
  page: Page,
  query: string,
): Promise<OpsImportJobsListResponse> {
  const res = await browserFetch<OpsImportJobsListResponse>(
    page,
    `${LIST_API_PATH}${query}`,
  );
  expect(res.status).toBe(200);
  expect(res.body).not.toBeNull();
  return res.body as OpsImportJobsListResponse;
}

// ── tests ─────────────────────────────────────────────────────────────────────

test.describe("/ops/import-jobs 실데이터 라운드트립", () => {
  test("A1: status·kind 필터가 목록 GET 쿼리 파라미터 + backend 결과 + UI 행에 반영된다", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    await gotoListReady(page);

    const baseline = await fetchJobs(page, "?page_size=100");
    const items = baseline.data.items;
    test.skip(items.length === 0, "import job이 없어 필터 라운드트립을 건너뜀");

    await test.step("status 필터 → status 파라미터 + status=X로 필터된 body + UI 행", async () => {
      const present = new Set(items.map((item) => item.status));
      const targetStatus =
        STATUS_PREFERENCE.find((status) => present.has(status)) ??
        items[0].status;

      // import-jobs-client.tsx: NativeSelect aria-label="status" (line 198).
      const statusRespP = waitForListResponse(
        page,
        (url) => url.searchParams.get("status") === targetStatus,
      );
      await page.getByLabel("status").selectOption(targetStatus);
      const statusResp = await statusRespP;

      // (1) API 파라미터 계약: status=X, page_size=100, cursor 없음(UI 미페이징).
      const statusUrl = new URL(statusResp.url());
      expect(statusUrl.searchParams.get("status")).toBe(targetStatus);
      expect(statusUrl.searchParams.get("page_size")).toBe("100");
      expect(statusUrl.searchParams.has("cursor")).toBe(false);

      // (2) backend가 실제로 status로 필터한다(SQL: status = :status, 정확일치).
      const filtered = (await statusResp.json()) as OpsImportJobsListResponse;
      const filteredItems = filtered.data.items;
      expect(filteredItems.length).toBeGreaterThan(0);
      expect(filteredItems.every((item) => item.status === targetStatus)).toBe(
        true,
      );

      // (3) UI 반영: 필터된 응답의 첫 job(created_at DESC, job_id DESC 정렬)이
      // 목록 첫 행 deeplink로 보인다. job 컬럼만 <Link>(line 81-87) → shortId가 접근명.
      const firstJobId = filteredItems[0].job_id;
      await expect(
        page.getByRole("link", { name: shortId(firstJobId) }).first(),
      ).toBeVisible(T);
      await expect(page.getByLabel("status")).toHaveValue(targetStatus, T);
    });

    await test.step("kind 필터 → kind 파라미터 + kind=X로 필터된 body + UI 행", async () => {
      const targetKind = items[0].kind;

      // status를 all로 되돌려 query를 kind 단독으로 만든다(every(kind) 단언 단순화).
      await page.getByLabel("status").selectOption("all");

      const kindRespP = waitForListResponse(
        page,
        (url) =>
          url.searchParams.get("kind") === targetKind &&
          !url.searchParams.has("status"),
      );
      // import-jobs-client.tsx: <Input placeholder="kind filter"> (line 212).
      await page.getByPlaceholder("kind filter").fill(targetKind);
      const kindResp = await kindRespP;

      const kindUrl = new URL(kindResp.url());
      expect(kindUrl.searchParams.get("kind")).toBe(targetKind);
      expect(kindUrl.searchParams.has("status")).toBe(false);

      const filtered = (await kindResp.json()) as OpsImportJobsListResponse;
      const filteredItems = filtered.data.items;
      expect(filteredItems.length).toBeGreaterThan(0);
      // SQL: kind = :kind (정확일치) → 모든 행 kind === targetKind.
      expect(filteredItems.every((item) => item.kind === targetKind)).toBe(true);

      const firstJobId = filteredItems[0].job_id;
      await expect(
        page.getByRole("link", { name: shortId(firstJobId) }).first(),
      ).toBeVisible(T);
      await expect(page.getByPlaceholder("kind filter")).toHaveValue(
        targetKind,
        T,
      );
    });
  });

  test("A2: 목록 deeplink 클릭이 상세/events API를 부르고 JobSummary·Events 서브테이블에 반영된다", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    await gotoListReady(page);

    const baseline = await fetchJobs(page, "?page_size=100");
    const items = baseline.data.items;
    test.skip(items.length === 0, "import job이 없어 상세 라운드트립을 건너뜀");

    const jobId = items[0].job_id;
    const detailApiPath = `${LIST_API_PATH}/${jobId}`;
    const eventsApiPath = `${LIST_API_PATH}/${jobId}/events`;

    // 클릭 직후 발생하는 상세 GET + events GET을 모두 캡처(클릭 전 promise 설정).
    const detailRespP = waitForApiResponse(page, "GET", detailApiPath);
    const eventsRespP = waitForApiResponse(page, "GET", eventsApiPath);

    // job 컬럼 <Link href=/ops/import-jobs/{job_id}> 텍스트 shortId(line 81-87) 클릭.
    await page.getByRole("link", { name: shortId(jobId) }).first().click();

    const detailResp = await detailRespP;
    expect(detailResp.status()).toBe(200);
    const detail = (await detailResp.json()) as OpsImportJobResponse;
    const record: OpsImportJobRecord = detail.data;
    expect(record.job_id).toBe(jobId);

    // import-job-detail-client.tsx: AdminShell title="Import job" (line 297).
    await expect(
      page.getByRole("heading", { level: 1, name: "Import job" }),
    ).toBeVisible(T);
    await expect(page).toHaveURL(
      new RegExp(`/ops/import-jobs/${jobId}$`),
      T,
    );

    await test.step("JobSummary 필드가 상세 응답을 반영한다", async () => {
      // FieldRow job_id <dd>는 job.job_id 전체를 렌더(line 160). 전체 jobId는
      // job_id 셀에만 정확히 일치(status_url/links는 부분일치라 exact에서 제외).
      await expect(page.getByText(jobId, { exact: true }).first()).toBeVisible(T);
      // 상단 progress Badge `{progress}%`(line 332).
      await expect(
        page.getByText(`${record.progress}%`, { exact: true }).first(),
      ).toBeVisible(T);
      // "Job" 카드 CardDescription = job.kind(line 156).
      await expect(page.getByText(record.kind).first()).toBeVisible(T);
    });

    await test.step("Events 서브테이블이 events 응답을 반영한다", async () => {
      const eventsResp = await eventsRespP;
      expect(eventsResp.status()).toBe(200);
      const events =
        (await eventsResp.json()) as OpsImportJobEventsListResponse;
      const eventItems = events.data.items;

      // Events 카드 타이틀(line 341)은 항상 렌더.
      await expect(page.getByText("Events", { exact: true })).toBeVisible(T);

      if (eventItems.length > 0) {
        // event 컬럼헤더(line 204-244): time/level/stage/code/message/payload.
        for (const column of ["time", "level", "code", "message"]) {
          await expect(
            page.getByRole("columnheader", { name: column, exact: true }),
          ).toBeVisible(T);
        }
        // 첫 event message가 행에 렌더(line 231-233).
        await expect(
          page.getByText(eventItems[0].message, { exact: true }).first(),
        ).toBeVisible(T);
      } else {
        // 빈 events → DataTable emptyMessage(line 376).
        await expect(page.getByText("event가 없습니다.")).toBeVisible(T);
      }
    });
  });

  test("B: queued job cancel POST가 cancelled 전이를 응답·상세 API·UI에 반영한다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_CANCEL,
      "cancel은 irreversible → E2E_IMPORT_JOB_CANCEL=1 + (E2E_ADMIN_WRITE|E2E_IMPORT_JOB_WRITE)=1 일 때만 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);
    await gotoListReady(page);

    // SAFE 대상: 아직 시작 안 된 queued만(running은 진행 중 import를 죽이므로 제외).
    const queued = await fetchJobs(page, "?status=queued&page_size=100");
    const queuedItems = queued.data.items;
    test.skip(
      queuedItems.length === 0,
      "cancel 가능한 queued job이 없어 건너뜀(running은 SAFE 대상에서 제외)",
    );

    const jobId = queuedItems[0].job_id;
    const detailApiPath = `${LIST_API_PATH}/${jobId}`;
    const cancelApiPath = `${LIST_API_PATH}/${jobId}/cancel`;
    const cancelReason = `live cancel ${RUN_ID}`;

    // 상세 진입(시작 상태 confirm) — 상세 GET이 queued를 반환하는지 본다.
    const detailRespP = waitForApiResponse(page, "GET", detailApiPath);
    await page.goto(`${LIST_ROUTE}/${jobId}`);
    const detailResp = await detailRespP;
    expect(detailResp.status()).toBe(200);
    const before = (await detailResp.json()) as OpsImportJobResponse;
    expect(before.data.status).toBe("queued");

    await expect(
      page.getByRole("heading", { level: 1, name: "Import job" }),
    ).toBeVisible(T);

    // import-job-detail-client.tsx: queued/running이면 canCancel → 버튼·입력 활성(line 392-407).
    const cancelButton = page.getByRole("button", { name: "cancel" });
    await expect(cancelButton).toBeEnabled(T);

    // <Input placeholder="reason">(line 396)에 reason 입력 → handleCancel은
    // body { operator:"admin-ui", reason: trim()||undefined }로 POST(line 258-264).
    await page.getByPlaceholder("reason").fill(cancelReason);

    const cancelRespP = waitForApiResponse(page, "POST", cancelApiPath);
    await cancelButton.click();
    const cancelResp = await cancelRespP;

    // (1) 요청 body(=UI 입력)가 그대로 전달됐는지.
    const sent =
      (cancelResp.request().postDataJSON() ?? {}) as OpsImportJobCancelRequest;
    expect(sent.operator).toBe("admin-ui");
    expect(sent.reason).toBe(cancelReason);

    // (2) 응답이 cancelled 전이(router line 752-769).
    expect(cancelResp.status()).toBe(200);
    const after = (await cancelResp.json()) as OpsImportJobResponse;
    expect(after.data.job_id).toBe(jobId);
    expect(after.data.status).toBe("cancelled");

    // (3) 성공 Alert(default variant → role=status, line 318-325).
    // AlertDescription은 status를 statusLabel()로 렌더하므로(line 322) cancelled →
    // "취소됨". (API body는 영어 "cancelled" 그대로 — 위 (2)에서 단언.)
    const successAlert = page
      .getByRole("status")
      .filter({ hasText: "cancel 요청됨" });
    await expect(successAlert).toBeVisible(T);
    await expect(successAlert).toContainText("취소됨");

    // (4) backend 재확인 — 상세 GET이 cancelled를 반환.
    await expect
      .poll(async () => {
        const res = await browserFetch<OpsImportJobResponse>(
          page,
          detailApiPath,
        );
        return res.body?.data.status ?? `http:${res.status}`;
      }, T)
      .toBe("cancelled");

    // (5) UI 반영: terminal이 되어 cancel 버튼 비활성 + Cancel 카드 desc "terminal"(line 388).
    await expect(cancelButton).toBeDisabled(T);
    await expect(page.getByText("terminal", { exact: true })).toBeVisible(T);

    // 복구 없음: cancel은 un-cancel API가 없는 단방향 전이다. 그래서 이 테스트는
    // 이중 게이트(write + E2E_IMPORT_JOB_CANCEL)와 queued-전용 대상으로만 실행되며,
    // finally 되돌림이 불가능함을 의도적으로 명시한다.
  });
});
