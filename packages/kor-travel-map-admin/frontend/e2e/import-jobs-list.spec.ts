import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";

/**
 * `/ops/import-jobs` 목록 — route-mocked depth spec
 * (admin-ops.spec.ts의 `/v1/ops/import-jobs` smoke가 보지 않는 계약을 보강).
 *
 * 화면 route는 `/ops/import-jobs`지만 backend 목록 계약은 bare path
 * `/v1/ops/import-jobs`(trailing segment 없음)다. 따라서 detail spec의
 * `**​/v1/ops/import-jobs/**`(trailing slash) glob은 목록을 잡지 못한다 — 여기서는
 * `**​/v1/ops/import-jobs**`로 가로채고 url.pathname === "/v1/ops/import-jobs"
 * 분기로만 목록 GET을 처리한다. 페이지 document·RSC(_rsc)·WS·기타 경로는
 * route.continue() (admin-ops.spec.ts mockOfflineUploadMutations passthrough idiom).
 *
 * 모든 mock body는 생성 OpenAPI 타입(components["schemas"][...])에 바인딩 →
 * 백엔드 DTO drift 시 컴파일 실패.
 *
 * NOTE: Playwright는 Windows 호스트에서만 실행된다. 라이브 검증은 Windows 런 필요.
 *
 * BLOCKING REFRAME (recon §risks): ImportJobsClient에는 cursor 페이지네이션 UI가
 * 없다. useImportJobs(src/api/importJobs.ts)는 page_size:100 단일 useQuery이고
 * (useInfiniteQuery 아님, cursor 미설정) 컴포넌트는 jobs.data?.data.items만
 * 렌더하며 공용 DataTable에 pager가 없다 → next/prev 컨트롤이 없고 페이지는
 * meta.page.next_cursor를 읽지 않는다. 그래서 "next_cursor 따라가기"는 UI로
 * 노출되지 않으며, scenario 1은 페이지가 실제로 지키는 계약(목록 GET 1회,
 * page_size=100, cursor 파라미터 없음, next_cursor 무시)을 단언한다.
 */

type OpsImportJobRecord = components["schemas"]["OpsImportJobRecord"];
type OpsImportJobsListResponse =
  components["schemas"]["OpsImportJobsListResponse"];
type PageMeta = components["schemas"]["PageMeta"];

const LIST_PATH = "/v1/ops/import-jobs";

function makeJob(
  overrides: Partial<OpsImportJobRecord> = {},
): OpsImportJobRecord {
  return {
    created_at: "2026-06-08T00:00:00.000Z",
    current_stage: "load",
    error_message: null,
    finished_at: "2026-06-08T00:02:00.000Z",
    heartbeat_at: "2026-06-08T00:01:00.000Z",
    job_id: "job-a",
    kind: "provider_sync",
    links: [],
    load_batch_id: null,
    parent_job_id: null,
    payload: { provider: "python-visitkorea-api", dataset_key: "festival" },
    progress: 100,
    source_checksum: null,
    started_at: "2026-06-08T00:00:30.000Z",
    // recon §WS: 백그라운드 refetchInterval(2s)은 queued/running 행에서만 켜진다.
    // scenario 1의 "정확히 1회" 단언이 흔들리지 않도록 mock 행은 terminal 상태로 둔다.
    status: "done",
    status_url: `${LIST_PATH}/job-a`,
    ...overrides,
  };
}

function makeListResponse(
  items: OpsImportJobRecord[],
  page: PageMeta,
  requestId = "e2e-import-jobs-list",
): OpsImportJobsListResponse {
  return {
    data: { items },
    meta: { duration_ms: 1, page, request_id: requestId },
  };
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

/**
 * 목록 GET만 mock한다. bare path(`/v1/ops/import-jobs`)인 GET만 응답하고, 페이지
 * document·_rsc prefetch·WS upgrade·`/v1/ops/metrics` 등 그 외 요청은
 * route.continue() 한다. 가로챈 모든 목록 GET의 searchParams를 push해 호출자가
 * 쿼리 계약을 검사할 수 있게 한다.
 */
async function mockImportJobsList(
  page: Page,
  options: {
    items?: OpsImportJobRecord[];
    pageMeta?: PageMeta;
    status?: number;
    errorBody?: unknown;
  } = {},
) {
  const listQueries: URLSearchParams[] = [];
  const items = options.items ?? [makeJob()];
  const pageMeta: PageMeta = options.pageMeta ?? {
    next_cursor: null,
    page_size: 100,
    total: null,
  };

  await page.route("**/v1/ops/import-jobs**", async (route) => {
    const request = route.request();
    if (request.resourceType() === "document") {
      await route.continue();
      return;
    }
    const url = new URL(request.url());
    // bare 목록 경로 GET이 아니면(=문서·RSC·WS·다른 v1 경로) 통과시킨다.
    if (
      request.method() !== "GET" ||
      url.pathname !== LIST_PATH ||
      url.searchParams.has("_rsc")
    ) {
      await route.continue();
      return;
    }
    listQueries.push(url.searchParams);
    if (options.status && options.status >= 400) {
      // client.ts는 비-OK 응답에서 response.text()를 ApiClientError 메시지에 그대로
      // 임베드한다(JSON envelope 아님) — 문자열/JSON 무관하게 메시지에 노출된다.
      await fulfillJson(
        route,
        options.errorBody ?? { detail: "import job store unavailable" },
        options.status,
      );
      return;
    }
    await fulfillJson(route, makeListResponse(items, pageMeta));
  });

  return {
    listQueries,
    lastListQuery: () => listQueries.at(-1),
  };
}

test.describe("/ops/import-jobs list", () => {
  test("cursor 무시 — page_size=100, next_cursor 후속 요청(cursor) 없음", async ({
    page,
  }) => {
    // RISK NOTE: 이 테스트는 페이지가 의도적으로 페이지네이션하지 않음을 단언한다.
    // 나중에 실제 cursor "다음 페이지" 컨트롤이 추가되면 이 시나리오는 그 컨트롤을
    // 클릭하고 후속 GET에 cursor=CURSOR_PAGE2가 실리는지 검사하도록 재작성해야 한다.
    const mock = await mockImportJobsList(page, {
      items: [makeJob({ job_id: "job-a" }), makeJob({ job_id: "job-b" })],
      pageMeta: { next_cursor: "CURSOR_PAGE2", page_size: 100, total: null },
    });

    await page.goto("/ops/import-jobs");

    await expect(
      page.getByRole("heading", { level: 1, name: "Import jobs" }),
    ).toBeVisible();
    // 행이 그려진 뒤(테이블 준비) 행 수를 단언한다.
    await expect(page.getByRole("columnheader", { name: "job" })).toBeVisible();
    await expect(page.getByRole("link", { name: "job-a" })).toBeVisible();

    // 페이지가 목록을 폴링/리페치할 수 있어 정확한 GET 횟수는 단언하지 않는다.
    // 핵심 계약: non-null next_cursor가 cursor 후속 요청을 부르지 않는다 — 어떤
    // list GET도 cursor를 싣지 않고(페이지는 meta.page.next_cursor를 안 읽음) 모두
    // page_size=100이다.
    await expect.poll(() => mock.listQueries.length).toBeGreaterThanOrEqual(1);
    expect(
      mock.listQueries.every((q) => q.get("page_size") === "100"),
    ).toBe(true);
    expect(mock.listQueries.some((q) => q.has("cursor"))).toBe(false);

    // header row + 2 data rows = 3. next_cursor 뒤의 2페이지 항목은 안 가져온다.
    await expect(page.getByRole("row")).toHaveCount(3);
  });

  test("empty list — DataTable emptyMessage + 헤더 유지", async ({ page }) => {
    await mockImportJobsList(page, {
      items: [],
      pageMeta: { next_cursor: null, page_size: 100, total: 0 },
    });

    await page.goto("/ops/import-jobs");

    await expect(
      page.getByRole("heading", { level: 1, name: "Import jobs" }),
    ).toBeVisible();
    // import-jobs-client.tsx의 emptyMessage prop 문자열 그대로.
    await expect(page.getByText("import job이 없습니다.")).toBeVisible();
    // DataTable은 비어도 thead를 렌더한다.
    await expect(page.getByRole("columnheader", { name: "job" })).toBeVisible();
    // 빈 목록에는 row deeplink가 없다 — admin-shell nav의 role=link와 충돌하지
    // 않도록 테이블 영역으로 한정한다.
    await expect(page.getByRole("table").getByRole("link")).toHaveCount(0);
  });

  test("list error — destructive alert(role=alert) + ApiClientError 메시지", async ({
    page,
  }) => {
    await mockImportJobsList(page, { status: 500 });

    await page.goto("/ops/import-jobs");

    await expect(
      page.getByRole("heading", { level: 1, name: "Import jobs" }),
    ).toBeVisible();
    // variant="destructive" Alert만 role=alert (default는 role=status — Wave 1).
    // 다른 alert와 충돌하지 않도록 AlertTitle 텍스트로 한정한다.
    await expect(
      page.getByRole("alert").filter({ hasText: "import job 조회 실패" }),
    ).toBeVisible();
    // AlertDescription은 jobs.error.message — ApiClientError가 HTTP status를 임베드.
    await expect(page.getByText(/실패 \(HTTP 500\)/)).toBeVisible();
    // 에러 시 jobs.data는 undefined → items=[] → empty message도 같이 보인다
    // (페이지는 DataTable.isError를 wiring하지 않음, top-level Alert만 렌더).
    await expect(page.getByText("import job이 없습니다.")).toBeVisible();
    // NOTE: react-query retry 횟수는 시간 기반이라 flaky → UI(alert)만 단언한다.
  });

  test("load_batch_id + parent_job_id 필터가 목록 쿼리 파라미터에 반영", async ({
    page,
  }) => {
    const mock = await mockImportJobsList(page, {
      items: [makeJob({ job_id: "job-a" })],
    });

    await page.goto("/ops/import-jobs");
    await expect(page.getByRole("columnheader", { name: "job" })).toBeVisible();

    // fetchImportJobs는 loadBatchId.trim()이 비어있지 않을 때만 load_batch_id 전송.
    await page.getByPlaceholder("load_batch_id").fill("batch-77");
    await expect
      .poll(() => mock.lastListQuery()?.get("load_batch_id"))
      .toBe("batch-77");

    await page.getByPlaceholder("parent_job_id").fill("parent-9");
    await expect
      .poll(() => mock.lastListQuery()?.get("parent_job_id"))
      .toBe("parent-9");

    // 두 useState 필터가 하나의 query 객체로 합쳐진다(queryKey 변경 → refetch).
    await expect
      .poll(() => {
        const q = mock.lastListQuery();
        return `${q?.get("load_batch_id")}|${q?.get("parent_job_id")}`;
      })
      .toBe("batch-77|parent-9");

    // 비우면(trim → undefined) 파라미터가 빠진다.
    // CACHE NOTE: useImportJobs는 staleTime=5_000이라, parent_job_id만 비우면
    // queryKey가 {load_batch_id:"batch-77", parent_job_id:undefined}로 앞서 fetch한
    // (load_batch_id만 채웠던) 쿼리와 동일해져 react-query가 캐시 hit → 새 GET이
    // 안 나가고 lastListQuery()는 직전(parent-9) 쿼리에 머문다. 그래서 parent를
    // 비우는 동시에 load_batch_id를 새 값으로 바꿔 한 번도 fetch된 적 없는 queryKey를
    // 만들어 실제 네트워크 GET을 강제하고, 그 GET이 parent_job_id를 생략하는지 본다.
    await page.getByPlaceholder("load_batch_id").fill("batch-88");
    await page.getByPlaceholder("parent_job_id").fill("");
    await expect
      .poll(() => {
        const q = mock.lastListQuery();
        return `${q?.get("load_batch_id")}|${q?.has("parent_job_id")}`;
      })
      .toBe("batch-88|false");

    // status 'all'은 생략, 'running'은 status 파라미터로 매핑.
    await page.getByLabel("status").selectOption("running");
    await expect.poll(() => mock.lastListQuery()?.get("status")).toBe("running");

    // RISK NOTE: 제어 Input에 debounce가 없어 키 입력마다 queryKey가 바뀔 수 있다 →
    // 고정 호출 횟수가 아니라 마지막 캡처 쿼리 값을 expect.poll로 단언한다.
  });

  test("URL 초기 필터가 컨트롤과 첫 쿼리를 시드한다", async ({ page }) => {
    const mock = await mockImportJobsList(page, {
      items: [makeJob({ job_id: "job-a" })],
    });

    // mock 라우트는 goto 전에 등록되어야 한다.
    await page.goto(
      "/ops/import-jobs?status=failed&kind=provider_sync&load_batch_id=batch-1&parent_job_id=parent-1",
    );

    // 컨트롤이 URL 값을 반영(page.tsx → initialFilters → useState 시드).
    await expect(page.getByLabel("status")).toHaveValue("failed");
    await expect(page.getByPlaceholder("kind filter")).toHaveValue(
      "provider_sync",
    );
    await expect(page.getByPlaceholder("load_batch_id")).toHaveValue("batch-1");
    await expect(page.getByPlaceholder("parent_job_id")).toHaveValue("parent-1");

    // 첫 목록 GET이 4개 필터를 모두 싣는다.
    await expect
      .poll(() => {
        const q = mock.lastListQuery();
        return [
          q?.get("status"),
          q?.get("kind"),
          q?.get("load_batch_id"),
          q?.get("parent_job_id"),
        ].join(",");
      })
      .toBe("failed,provider_sync,batch-1,parent-1");
  });

  test("URL status가 union 밖이면 'all'로 폴백 + status 파라미터 생략", async ({
    page,
  }) => {
    // statuses.includes 가드: 모르는 status는 'all'로 떨어진다(import-jobs-client.tsx).
    const mock = await mockImportJobsList(page, {
      items: [makeJob({ job_id: "job-a" })],
    });

    await page.goto("/ops/import-jobs?status=bogus");

    await expect(page.getByLabel("status")).toHaveValue("all");
    // 'all' → status 미전송. 첫 쿼리에 status 파라미터가 없어야 한다.
    await expect(page.getByRole("columnheader", { name: "job" })).toBeVisible();
    await expect.poll(() => mock.lastListQuery()?.has("status")).toBe(false);
  });

  test("row job cell → /ops/import-jobs/[jobId] deeplink href", async ({
    page,
  }) => {
    await mockImportJobsList(page, {
      items: [
        makeJob({
          job_id: "job-a",
          load_batch_id: "batch-xyz",
          parent_job_id: null,
        }),
        makeJob({ job_id: "job-b" }),
      ],
    });

    await page.goto("/ops/import-jobs");

    // job cell은 <Link href={`/ops/import-jobs/${encodeURIComponent(job_id)}`}> +
    // 텍스트 shortId(job_id)(len<=12면 verbatim) + onClick stopPropagation.
    // "job-a"는 encodeURIComponent no-op이라 href가 평문 그대로.
    await expect(page.getByRole("link", { name: "job-a" })).toHaveAttribute(
      "href",
      "/ops/import-jobs/job-a",
    );

    // batch/parent 컬럼이 실제로 존재함을 가볍게 corroborate(admin-ops 5-col smoke
    // 너머): load_batch_id는 shortId, parent_job_id null은 '-'.
    const row = page.getByRole("row", { name: /job-a/ });
    await expect(row.getByText("batch-xyz")).toBeVisible();
    await expect(row.getByText("-", { exact: true })).toBeVisible();

    // NOTE: detail 페이지로 클릭+네비게이션하지 않는다 — 상세 route는 자체 GET +
    // events + WS를 발생시키고(여기서 미mock) import-job-detail.spec.ts가 이미
    // 커버한다. href 속성만 단언한다.
  });

  test("slash 포함 job_id deeplink는 encodeURIComponent 인코딩된다", async ({
    page,
  }) => {
    await mockImportJobsList(page, {
      items: [makeJob({ job_id: "a/b" })],
    });

    await page.goto("/ops/import-jobs");

    // shortId("a/b")는 len<=12라 verbatim → link 이름은 "a/b", href는 a%2Fb.
    await expect(page.getByRole("link", { name: "a/b" })).toHaveAttribute(
      "href",
      "/ops/import-jobs/a%2Fb",
    );
  });
});
