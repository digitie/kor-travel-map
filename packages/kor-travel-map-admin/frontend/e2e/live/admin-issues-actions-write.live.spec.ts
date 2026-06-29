import { expect, test, type Locator, type Page, type Response } from "@playwright/test";

import type { components } from "../../src/api/types";

type AdminIssueListResponse = components["schemas"]["AdminIssueListResponse"];
type AdminIssueDetailResponse =
  components["schemas"]["AdminIssueDetailResponse"];
type AdminIssueActionResponse =
  components["schemas"]["AdminIssueActionResponse"];
type AdminIssuePatchRequest = components["schemas"]["AdminIssuePatchRequest"];

type BrowserFetchResult<T> = {
  body: T | null;
  status: number;
  text: string;
};

const UI_TIMEOUT = 15_000;
const FLOW_TIMEOUT = 5 * 60 * 1000;
const T = { timeout: UI_TIMEOUT } as const;

const RUN_ID = `live-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
// resolve/reopen은 ops.data_integrity_violations의 status만 바꾸는 가역 전이라
// E2E_ADMIN_WRITE/E2E_ISSUES_WRITE 일반 게이트만으로 충분하다(kor-travel-geo·feature
// 주소를 건드리는 retry_*/apply_*/manual_override는 비가역이라 여기서 다루지 않음).
const EXECUTE_ISSUES_WRITE =
  process.env.E2E_ADMIN_WRITE === "1" || process.env.E2E_ISSUES_WRITE === "1";

// admin/issues는 backend status query가 Literal[open,acknowledged,resolved,ignored].
// "all"은 backend에 보내면 422이고, UI는 "all"을 status param 생략(=default open)으로
// 매핑한다. 그래서 read probe는 절대 ?status=all을 보내지 않는다.
const PROBE_STATUSES = ["open", "resolved", "ignored", "acknowledged"] as const;

// status-badge.tsx의 statusLabel()이 status/severity enum을 한글 배지 텍스트로
// 렌더한다(StatusBadge — admin-issues-client.tsx line 210/211/459/465). 그래서
// UI-표시(렌더 텍스트) 단언은 한글 라벨로 비교해야 한다. API/DTO enum 값은 영어
// 그대로이므로 query param·selectOption·PATCH 응답 단언은 영어를 유지한다.
// 여기 등장하는 값(status open/acknowledged/resolved/ignored + severity
// info/warning/error/critical)만 매핑하고, 미매핑 값은 statusLabel과 동일하게
// 원문을 그대로 돌려준다.
const STATUS_KO: Record<string, string> = {
  open: "열림",
  acknowledged: "확인됨",
  resolved: "해결됨",
  ignored: "무시됨",
  info: "정보",
  warning: "경고",
  error: "오류",
  critical: "심각",
};
function statusKo(value: string): string {
  return STATUS_KO[value.toLowerCase()] ?? value;
}

test.describe.configure({ mode: "serial" });

// ── gold-standard 헬퍼 그대로 복사 (admin-features-change-requests-write.live.spec.ts) ──

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

// ── /admin/issues 전용 헬퍼 ─────────────────────────────────────────────────

function issuePath(issueId: string): string {
  return `/v1/admin/issues/${encodeURIComponent(issueId)}`;
}

// /admin/issues 목록 GET 중 expected query param을 모두 만족하는 응답을 기다린다.
// apiPath는 query를 떼므로 path는 "/v1/admin/issues"만 비교하고 param은 URL에서 직접 읽는다.
function waitForIssuesQuery(
  page: Page,
  expected: Record<string, string>,
): Promise<Response> {
  return page.waitForResponse(
    (response) => {
      if (response.request().method() !== "GET") return false;
      if (apiPath(response) !== "/v1/admin/issues") return false;
      const params = new URL(response.url()).searchParams;
      return Object.entries(expected).every(
        ([key, value]) => params.get(key) === value,
      );
    },
    { timeout: FLOW_TIMEOUT },
  );
}

// detail GET(/v1/admin/issues/{id})은 list(/v1/admin/issues)와 trailing slash로 구분된다.
function waitForIssueDetailGet(page: Page): Promise<Response> {
  return page.waitForResponse(
    (response) =>
      response.request().method() === "GET" &&
      apiPath(response).startsWith("/v1/admin/issues/"),
    { timeout: FLOW_TIMEOUT },
  );
}

async function fetchIssuesList(
  page: Page,
  query: string,
): Promise<BrowserFetchResult<AdminIssueListResponse>> {
  return browserFetch<AdminIssueListResponse>(
    page,
    `/v1/admin/issues${query}`,
  );
}

async function fetchIssueDetail(
  page: Page,
  issueId: string,
): Promise<BrowserFetchResult<AdminIssueDetailResponse>> {
  return browserFetch<AdminIssueDetailResponse>(page, issuePath(issueId));
}

async function readActionResponse(
  response: Response,
): Promise<AdminIssueActionResponse> {
  expect(response.status()).toBe(200);
  return (await response.json()) as AdminIssueActionResponse;
}

// 상세 카드: "Issue detail" 헤더를 감싼 최단 rounded-lg 컨테이너(컴포넌트 line 182).
// 같은 카드 안에 status/severity badge·violation_type·message·조치 버튼이 모두 있어
// 행(table)의 동일 텍스트와 충돌하지 않게 스코프한다.
function issueDetailCard(page: Page): Locator {
  return page
    .getByText("Issue detail", { exact: true })
    .locator("xpath=ancestor::div[contains(@class,'rounded-lg')][1]");
}

async function gotoAdminIssues(page: Page): Promise<void> {
  await page.goto("/admin/issues");
  await expect(
    page.getByRole("heading", { level: 1, name: "Admin issues" }),
  ).toBeVisible(T);
  await expect(page.getByText("Issue table")).toBeVisible(T);
}

async function expectIssuesTableOrEmpty(page: Page): Promise<void> {
  // PRESENCE.issues=0(prod 스냅샷)일 수 있어 행 존재를 강제하지 않는다.
  // DataTable emptyMessage 또는 table 랜드마크 중 하나만 보이면 통과.
  const empty = page.getByText("issue가 없습니다.");
  if ((await empty.count()) > 0 && (await empty.first().isVisible())) {
    return;
  }
  await expect(page.getByRole("table").first()).toBeVisible(T);
}

test.describe("/admin/issues live read + reversible status write", () => {
  // ── 시나리오 A1 (게이트 없음): 필터/페이지네이션 → GET 쿼리 파라미터 → 표/empty ──
  test("A1: 이슈 목록 필터/페이지네이션이 GET 쿼리 파라미터로 전달되고 표/empty-state가 유지된다", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    await gotoAdminIssues(page);

    await test.step("status 필터 → ?status=resolved", async () => {
      const wait = waitForIssuesQuery(page, { status: "resolved" });
      await page.getByLabel("issue status").selectOption("resolved");
      expect((await wait).status()).toBe(200);
      await expectIssuesTableOrEmpty(page);
    });

    await test.step("severity 필터 → ?severity=critical", async () => {
      const wait = waitForIssuesQuery(page, { severity: "critical" });
      await page.getByLabel("issue severity").selectOption("critical");
      expect((await wait).status()).toBe(200);
      await expectIssuesTableOrEmpty(page);
    });

    await test.step("issue_type 입력 → ?issue_type=missing_address", async () => {
      const wait = waitForIssuesQuery(page, { issue_type: "missing_address" });
      await page.getByLabel("issue type").fill("missing_address");
      expect((await wait).status()).toBe(200);
    });

    await test.step("provider 입력 → ?provider=python-kma-api", async () => {
      const wait = waitForIssuesQuery(page, { provider: "python-kma-api" });
      await page.getByLabel("issue provider").fill("python-kma-api");
      expect((await wait).status()).toBe(200);
    });

    await test.step("dataset_key 입력 → ?dataset_key=kma_weather_values", async () => {
      const wait = waitForIssuesQuery(page, {
        dataset_key: "kma_weather_values",
      });
      await page.getByLabel("issue dataset").fill("kma_weather_values");
      expect((await wait).status()).toBe(200);
    });

    await test.step("page size 선택 → ?page_size=25", async () => {
      const wait = waitForIssuesQuery(page, { page_size: "25" });
      await page.getByLabel("issue page size").selectOption("25");
      expect((await wait).status()).toBe(200);
      await expectIssuesTableOrEmpty(page);
    });

    await test.step("search 입력 → ?q= (deferred)", async () => {
      const term = "공원";
      const wait = waitForIssuesQuery(page, { q: term });
      await page.getByLabel("issue search").fill(term);
      expect((await wait).status()).toBe(200);
      await expectIssuesTableOrEmpty(page);
    });

    await test.step("bbox 입력 → ?min_lon/min_lat/max_lon/max_lat", async () => {
      const wait = waitForIssuesQuery(page, {
        min_lon: "126",
        min_lat: "37",
        max_lon: "127",
        max_lat: "38",
      });
      await page.getByLabel("bbox").fill("126,37,127,38");
      expect((await wait).status()).toBe(200);
      await expectIssuesTableOrEmpty(page);
    });

    await test.step("keyset 페이지네이션 컨트롤이 next_cursor와 일치한다", async () => {
      // 필터 누적 상태를 버리고 default(open, size 100)로 재로드.
      await gotoAdminIssues(page);
      const list = await fetchIssuesList(page, "?page_size=100");
      expect(list.status).toBe(200);
      const nextCursor = list.body?.meta.page?.next_cursor ?? null;

      const firstBtn = page.getByRole("button", { name: "첫 페이지" });
      const nextBtn = page.getByRole("button", { name: "다음" });
      await expect(firstBtn).toBeVisible(T);
      await expect(nextBtn).toBeVisible(T);
      // 초기 cursor=null → '첫 페이지' 비활성.
      await expect(firstBtn).toBeDisabled();

      if (nextCursor) {
        await expect(nextBtn).toBeEnabled();
        const wait = waitForIssuesQuery(page, { cursor: nextCursor });
        await nextBtn.click();
        expect((await wait).status()).toBe(200);
        await expect(firstBtn).toBeEnabled();
        await expectIssuesTableOrEmpty(page);
      } else {
        // next_cursor 없음 → '다음' 비활성(빈 큐 또는 페이지 1개).
        await expect(nextBtn).toBeDisabled();
      }
    });
  });

  // ── 시나리오 A2 (게이트 없음): 행 클릭 → detail API → UI 상세 필드 반영 ──
  test("A2: 이슈 행을 열면 detail API 응답과 UI 상세 필드가 일치한다", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    await gotoAdminIssues(page);

    // 어떤 status에든 이슈가 있으면 그 status로 UI를 몰아 상세를 연다.
    let probed: string | null = null;
    for (const status of PROBE_STATUSES) {
      const list = await fetchIssuesList(page, `?status=${status}&page_size=50`);
      expect(list.status).toBe(200);
      if ((list.body?.data.items.length ?? 0) > 0) {
        probed = status;
        break;
      }
    }

    if (probed === null) {
      // 모든 status가 비어있음 → 빈 큐 empty-state만 단언(상세 round-trip 불가).
      await expect(page.getByText("issue가 없습니다.")).toBeVisible(T);
      return;
    }

    if (probed !== "open") {
      const wait = waitForIssuesQuery(page, { status: probed });
      await page.getByLabel("issue status").selectOption(probed);
      await wait;
    }

    const firstRow = page.locator("tbody tr").first();
    await expect(firstRow).toBeVisible(T);

    const detailWait = waitForIssueDetailGet(page);
    await firstRow.click();
    const detailResponse = await detailWait;
    expect(detailResponse.status()).toBe(200);
    const issue = ((await detailResponse.json()) as AdminIssueDetailResponse).data
      .issue;

    // UI 상세 카드가 detail API의 핵심 필드를 그대로 반영한다.
    const detailCard = issueDetailCard(page);
    await expect(detailCard).toBeVisible(T);
    await expect(detailCard).toContainText(issue.issue_id);
    await expect(detailCard).toContainText(issue.violation_type);
    // status/severity는 StatusBadge가 한글로 렌더 → 한글 라벨로 단언.
    await expect(detailCard).toContainText(statusKo(issue.status));
    await expect(detailCard).toContainText(statusKo(issue.severity));
    if (issue.message.trim().length > 0) {
      await expect(detailCard).toContainText(issue.message);
    }
  });

  // ── 시나리오 B (게이트): open 이슈를 resolve → API/백엔드/UI 반영 → finally에서 reopen 원복 ──
  test("B: open 이슈를 UI에서 resolve하면 API/백엔드/UI에 반영되고 finally에서 reopen으로 원복한다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_ISSUES_WRITE,
      "E2E_ISSUES_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 issue status write flow를 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    let reopenIssueId: string | null = null;
    let originalStatus: string | null = null;

    try {
      await gotoAdminIssues(page);

      // 런타임에 처리할 open 이슈가 있는지 확인. 없으면 skip.
      const openList = await fetchIssuesList(page, "?status=open&page_size=50");
      expect(openList.status).toBe(200);
      const openCount = openList.body?.data.items.length ?? 0;
      test.skip(
        openCount === 0,
        "처리할 open 이슈가 없어 issue status write 시나리오를 건너뜀",
      );

      // default view(status=open)의 첫 행을 선택해 상세를 열고, 실제 대상 이슈를
      // detail GET 응답으로 확정한다(목록/상세 ordering 가정에 의존하지 않음).
      const firstRow = page.locator("tbody tr").first();
      await expect(firstRow).toBeVisible(T);
      const detailWait = waitForIssueDetailGet(page);
      await firstRow.click();
      const detailResponse = await detailWait;
      expect(detailResponse.status()).toBe(200);
      const targetIssue = ((await detailResponse.json()) as AdminIssueDetailResponse)
        .data.issue;
      reopenIssueId = targetIssue.issue_id;
      originalStatus = targetIssue.status;
      expect(originalStatus).toBe("open");

      // UI 상세 헤더가 선택된 이슈의 full issue_id를 노출(행은 shortId만 노출).
      // shortId(id,12)는 12자 이하 id를 그대로 렌더하므로 page 전역 exact match는
      // 행 셀과 충돌할 수 있다 → 상세 카드로 스코프해 헤더의 full id만 단언.
      await expect(
        issueDetailCard(page).getByText(targetIssue.issue_id, { exact: true }),
      ).toBeVisible(T);

      // 행 quick-action 'resolve' 클릭 → PATCH가 발사되고 status=resolved를 돌려준다.
      const patchWait = waitForApiResponse(page, "PATCH", issuePath(targetIssue.issue_id));
      await firstRow.getByRole("button", { name: "resolve" }).click();
      const patch = await readActionResponse(await patchWait);
      expect(patch.data.issue.issue_id).toBe(targetIssue.issue_id);
      expect(patch.data.issue.status).toBe("resolved");

      // 백엔드 반영: detail API를 다시 읽어 status=resolved를 확인.
      await expect
        .poll(async () => {
          const detail = await fetchIssueDetail(page, targetIssue.issue_id);
          return detail.body?.data.issue.status ?? `http:${detail.status}`;
        }, T)
        .toBe("resolved");

      // UI 반영: 선택 유지된 상세 카드가 resolve 후 '해결됨'(resolved) 한글 badge로
      // 갱신된다(StatusBadge → statusLabel). exact 매치는 status 배지에만 걸린다.
      const detailCard = issueDetailCard(page);
      await expect(
        detailCard.getByText(statusKo("resolved"), { exact: true }),
      ).toBeVisible(T);
    } finally {
      // 원복: open이던 이슈를 reopen으로 되돌린다(status만 가역 전이).
      if (reopenIssueId && originalStatus === "open") {
        const revertBody: AdminIssuePatchRequest = {
          action: "reopen",
          operator: "local-admin",
          reason: `${RUN_ID} revert reopen`,
          prevent_provider_reactivation: true,
        };
        await browserFetch<AdminIssueActionResponse>(
          page,
          issuePath(reopenIssueId),
          { body: revertBody, method: "PATCH" },
        );
      }
    }
  });
});
