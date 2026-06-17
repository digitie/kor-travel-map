import { expect, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";

// 손으로 쓴 record shape 대신 **생성된 OpenAPI 스키마**에 바인딩한다(#308 리뷰).
// 백엔드 DTO가 바뀌면 mock factory가 타입 불일치로 컴파일 실패 → mock-실계약 drift 감지.
// admin-ops.spec.ts의 /admin/issues smoke(render + 필터 + manual_override 검증)는
// 그대로 두고, 여기서는 **미검증 깊이**만 추가한다:
//   (1) row/detail quick-action PATCH coverage,
//   (2) keyset cursor 페이지네이션,
//   (3) list/detail 500 error alert,
//   (4) severity badge + feature snapshot(지도 link gate, coord '없음').
type AdminIssueRecord = components["schemas"]["AdminIssueRecord"];
type AdminIssueFeatureSnapshot =
  components["schemas"]["AdminIssueFeatureSnapshot"];
type AdminIssueListResponse =
  components["schemas"]["AdminIssueListResponse"];
type AdminIssueDetailResponse =
  components["schemas"]["AdminIssueDetailResponse"];
type AdminIssueActionResponse =
  components["schemas"]["AdminIssueActionResponse"];
type AdminIssuePatchRequest =
  components["schemas"]["AdminIssuePatchRequest"];

const MOCK_NOW = "2026-06-08T00:00:00.000Z";
const ISSUE_ID = "issue-0000-1111-2222-3333-444455556666";
const FEATURE_ID = "python-kma-api::kma_weather_values::mock-feature-1";

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

function makeIssue(overrides: Partial<AdminIssueRecord> = {}): AdminIssueRecord {
  return {
    dataset_key: "kma_weather_values",
    detected_at: MOCK_NOW,
    feature_id: FEATURE_ID,
    issue_id: ISSUE_ID,
    message: "주소를 확인할 수 없습니다.",
    payload: { rule: "address-required" },
    provider: "python-kma-api",
    resolved_at: null,
    severity: "critical",
    source_record_key: "kma::station::108",
    status: "open",
    violation_type: "missing_address",
    ...overrides,
  };
}

function makeFeatureSnapshot(
  overrides: Partial<AdminIssueFeatureSnapshot> = {},
): AdminIssueFeatureSnapshot {
  return {
    address: { road: "서울특별시 중구 세종대로 110" },
    feature_id: FEATURE_ID,
    lat: 37.5665,
    legal_dong_code: null,
    lon: 126.978,
    road_address_management_no: null,
    sido_code: "11",
    sigungu_code: "11140",
    status: "active",
    ...overrides,
  };
}

function listResponse(
  items: AdminIssueRecord[],
  nextCursor: string | null,
  pageSize: number,
): AdminIssueListResponse {
  return {
    data: { items },
    meta: {
      duration_ms: 1,
      page: { next_cursor: nextCursor, page_size: pageSize, total: null },
      request_id: "e2e-issue-list",
    },
  };
}

function detailResponse(
  issue: AdminIssueRecord,
  feature: AdminIssueFeatureSnapshot | null,
): AdminIssueDetailResponse {
  return {
    data: { feature, issue },
    meta: { duration_ms: 1, request_id: "e2e-issue-detail" },
  };
}

function actionResponse(
  issue: AdminIssueRecord,
  feature: AdminIssueFeatureSnapshot | null = null,
): AdminIssueActionResponse {
  return {
    data: { feature, geocode_candidate: null, issue },
    meta: { duration_ms: 1, request_id: "e2e-issue-action" },
  };
}

const LIST_PATH = "/v1/admin/issues";
function isListPath(pathname: string) {
  return pathname === LIST_PATH;
}
function isDetailPath(pathname: string) {
  return pathname.startsWith(`${LIST_PATH}/`);
}

test.describe("admin/issues actions + pagination + errors", () => {
  test("row quick-actions + detail-panel actions fire the right PATCH mutation", async ({
    page,
  }) => {
    const issue = makeIssue({ violation_type: "missing_address" });
    const feature = makeFeatureSnapshot();
    const patchBodies: Array<{ issueId: string; body: AdminIssuePatchRequest }> =
      [];

    // glob `**/v1/admin/issues**`는 목록(`/v1/admin/issues`)과
    // 상세/PATCH(`/v1/admin/issues/<id>`)를 모두 잡는다 → method + pathname으로
    // 분기(admin-ops.spec 관용구). mutation onSuccess가 ['admin-issues']를
    // invalidate해 list GET이 재발사되므로 GET 핸들러는 멱등(closure list).
    await page.route("**/v1/admin/issues**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());

      if (request.method() === "GET" && isListPath(url.pathname)) {
        const pageSize = Number(url.searchParams.get("page_size") ?? 100);
        await fulfillJson(route, listResponse([issue], null, pageSize));
        return;
      }
      if (request.method() === "GET" && isDetailPath(url.pathname)) {
        await fulfillJson(route, detailResponse(issue, feature));
        return;
      }
      if (request.method() === "PATCH" && isDetailPath(url.pathname)) {
        const issueId = decodeURIComponent(url.pathname.split("/").at(-1) ?? "");
        const body = request.postDataJSON() as AdminIssuePatchRequest;
        patchBodies.push({ body, issueId });
        await fulfillJson(route, actionResponse(issue, feature));
        return;
      }
      throw new Error(`Unhandled issue route: ${request.method()} ${url}`);
    });

    await page.goto("/admin/issues");

    const row = page.getByRole("row", { name: /missing_address/ });
    await expect(row).toBeVisible();

    // ROW actions — 'resolve'/'ignore'는 row 액션 컬럼과 detail 패널 둘 다에
    // 있으므로(strict-mode 충돌) 반드시 row locator로 스코프한다.
    await row.getByRole("button", { name: "resolve" }).click();
    await expect.poll(() => patchBodies.length).toBe(1);
    expect(patchBodies[0].issueId).toBe(ISSUE_ID);
    expect(patchBodies[0].body).toMatchObject({
      action: "resolve",
      operator: "local-admin",
      prevent_provider_reactivation: true,
      reason: "admin-ui resolve",
    });

    await row.getByRole("button", { name: "ignore" }).click();
    await expect.poll(() => patchBodies.length).toBe(2);
    expect(patchBodies[1].body).toMatchObject({
      action: "ignore",
      reason: "admin-ui ignore",
    });

    // DETAIL actions — row 클릭 → detail 쿼리가 끝나 'Issue detail'이 뜬 뒤
    // detail-only 버튼(reopen/retry geocode/retry reverse/apply kraddr)만 사용한다.
    await row.click();
    await expect(page.getByText("Issue detail")).toBeVisible();

    const detailActions: Array<[string, AdminIssuePatchRequest["action"]]> = [
      ["reopen", "reopen"],
      ["retry geocode", "retry_geocode"],
      ["retry reverse", "retry_reverse_geocode"],
      ["apply kraddr", "apply_kor_travel_geo_address"],
    ];
    let expected = patchBodies.length;
    for (const [label, action] of detailActions) {
      await page.getByRole("button", { name: label }).click();
      expected += 1;
      await expect.poll(() => patchBodies.length).toBe(expected);
      expect(patchBodies[expected - 1].body).toMatchObject({
        action,
        operator: "local-admin",
        prevent_provider_reactivation: true,
        reason: `admin-ui ${action}`,
      });
    }
  });

  test("cursor pagination: 다음 advances cursor, 첫 페이지 resets, buttons gate on next_cursor", async ({
    page,
  }) => {
    const page1 = makeIssue({
      issue_id: "issue-page-1",
      violation_type: "page1_token",
    });
    const page2 = makeIssue({
      issue_id: "issue-page-2",
      violation_type: "page2_token",
    });
    let lastCursorParam: string | null = "(unset)";

    await page.route("**/v1/admin/issues**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (request.method() === "GET" && isListPath(url.pathname)) {
        const cursor = url.searchParams.get("cursor");
        lastCursorParam = cursor;
        const pageSize = Number(url.searchParams.get("page_size") ?? 100);
        if (cursor === "cursor-2") {
          await fulfillJson(route, listResponse([page2], null, pageSize));
          return;
        }
        await fulfillJson(route, listResponse([page1], "cursor-2", pageSize));
        return;
      }
      throw new Error(`Unhandled issue route: ${request.method()} ${url}`);
    });

    await page.goto("/admin/issues");
    await expect(page.getByText("Issue table")).toBeVisible();

    const firstBtn = page.getByRole("button", { name: "첫 페이지" });
    const nextBtn = page.getByRole("button", { name: "다음" });
    const page1Row = page.getByRole("row", { name: /page1_token/ });
    const page2Row = page.getByRole("row", { name: /page2_token/ });

    // 초기: cursor null → '첫 페이지' disabled, next_cursor 있음 → '다음' enabled.
    await expect(page1Row).toBeVisible();
    await expect(firstBtn).toBeDisabled();
    await expect(nextBtn).toBeEnabled();

    // '다음' → setCursor('cursor-2') → list GET이 ?cursor=cursor-2로 재발사.
    await nextBtn.click();
    await expect.poll(() => lastCursorParam).toBe("cursor-2");
    await expect(page2Row).toBeVisible();
    await expect(page1Row).toHaveCount(0);
    await expect(nextBtn).toBeDisabled();
    await expect(firstBtn).toBeEnabled();

    // '첫 페이지' → setCursor(null). KNOWN GOTCHA: 동일 queryKey + staleTime
    // 15s → react-query 캐시 적중으로 새 요청이 보장되지 않는다. UI 상태로만 단언.
    await firstBtn.click();
    await expect(page1Row).toBeVisible();
    await expect(page2Row).toHaveCount(0);
    await expect(firstBtn).toBeDisabled();
    await expect(nextBtn).toBeEnabled();
  });

  test("list-query 500 surfaces the top destructive alert", async ({ page }) => {
    await page.route("**/v1/admin/issues**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (request.method() === "GET" && isListPath(url.pathname)) {
        // 에러 경로: client.ts는 response.text()로 detail을 읽고 ApiClientError를
        // throw한다(스키마 파싱 없음). body shape은 무관 — 던져진 메시지만 단언.
        await fulfillJson(route, { detail: "boom" }, 500);
        return;
      }
      throw new Error(`Unhandled issue route: ${request.method()} ${url}`);
    });

    await page.goto("/admin/issues");

    const topAlert = page
      .getByRole("alert")
      .filter({ hasText: "admin issue 처리 실패" });
    await expect(topAlert).toBeVisible();
    await expect(topAlert).toContainText("실패 (HTTP 500)");
  });

  test("detail-query 500 surfaces the in-panel destructive alert", async ({
    page,
  }) => {
    const issue = makeIssue({ violation_type: "detail_err_token" });

    await page.route("**/v1/admin/issues**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (request.method() === "GET" && isListPath(url.pathname)) {
        const pageSize = Number(url.searchParams.get("page_size") ?? 100);
        await fulfillJson(route, listResponse([issue], null, pageSize));
        return;
      }
      if (request.method() === "GET" && isDetailPath(url.pathname)) {
        await fulfillJson(route, { detail: "boom" }, 500);
        return;
      }
      throw new Error(`Unhandled issue route: ${request.method()} ${url}`);
    });

    await page.goto("/admin/issues");

    const row = page.getByRole("row", { name: /detail_err_token/ });
    await expect(row).toBeVisible();
    await row.click();

    // detail card chrome('Issue detail')는 에러여도 렌더된다. in-panel alert는
    // AlertTitle 'issue 상세 조회 실패'로 top alert와 구분한다.
    await expect(page.getByText("Issue detail")).toBeVisible();
    await expect(page.getByText("issue 상세 조회 실패")).toBeVisible();
  });

  test("severity badge per row + feature snapshot 지도 link/coord gating", async ({
    page,
  }) => {
    const critical = makeIssue({
      feature_id: FEATURE_ID,
      issue_id: "issue-critical",
      severity: "critical",
      violation_type: "token_a",
    });
    const info = makeIssue({
      feature_id: null,
      issue_id: "issue-info",
      severity: "info",
      violation_type: "token_b",
    });

    await page.route("**/v1/admin/issues**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (request.method() === "GET" && isListPath(url.pathname)) {
        // status=open이 기본값이라 두 행 모두 open이어야 목록에 남는다.
        const pageSize = Number(url.searchParams.get("page_size") ?? 100);
        await fulfillJson(route, listResponse([critical, info], null, pageSize));
        return;
      }
      if (request.method() === "GET" && isDetailPath(url.pathname)) {
        const issueId = decodeURIComponent(url.pathname.split("/").at(-1) ?? "");
        if (issueId === "issue-info") {
          // feature_id 없는 이슈 → feature 스냅샷 없음.
          await fulfillJson(route, detailResponse(info, null));
          return;
        }
        // 기본: 좌표 없는 feature 스냅샷.
        await fulfillJson(
          route,
          detailResponse(
            critical,
            makeFeatureSnapshot({ lat: null, lon: null }),
          ),
        );
        return;
      }
      throw new Error(`Unhandled issue route: ${request.method()} ${url}`);
    });

    await page.goto("/admin/issues");

    // severity 'marker' = StatusBadge(맵 핀 아님). row로 스코프해 detail 패널의
    // severity badge와 충돌하지 않게 한다. issue_id('issue-critical'/'issue-info')가
    // severity 문자열을 substring으로 포함하므로 exact match로 severity badge만 집는다.
    const criticalRow = page.getByRole("row", { name: /token_a/ });
    const infoRow = page.getByRole("row", { name: /token_b/ });
    await expect(criticalRow.getByText("critical", { exact: true })).toBeVisible();
    await expect(infoRow.getByText("info", { exact: true })).toBeVisible();

    // feature_id 있는 이슈: 지도 link 노출 + feature snapshot, 좌표 null → '없음'.
    await criticalRow.click();
    await expect(page.getByText("Issue detail")).toBeVisible();
    await expect(page.getByRole("link", { name: "지도" })).toBeVisible();
    await expect(page.getByText("feature snapshot")).toBeVisible();
    await expect(page.getByText("없음")).toBeVisible();

    // feature_id 없는 이슈: 지도 link 없음 + snapshot 블록 없음.
    await infoRow.click();
    await expect(page.getByText("Issue detail")).toBeVisible();
    await expect(page.getByRole("link", { name: "지도" })).toHaveCount(0);
    await expect(page.getByText("feature snapshot")).toHaveCount(0);
  });

  test("feature snapshot renders coordinate when lon/lat are numbers", async ({
    page,
  }) => {
    const issue = makeIssue({ violation_type: "coord_token" });

    await page.route("**/v1/admin/issues**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (request.method() === "GET" && isListPath(url.pathname)) {
        const pageSize = Number(url.searchParams.get("page_size") ?? 100);
        await fulfillJson(route, listResponse([issue], null, pageSize));
        return;
      }
      if (request.method() === "GET" && isDetailPath(url.pathname)) {
        await fulfillJson(
          route,
          detailResponse(
            issue,
            makeFeatureSnapshot({ lat: 37.5665, lon: 126.978, status: "active" }),
          ),
        );
        return;
      }
      throw new Error(`Unhandled issue route: ${request.method()} ${url}`);
    });

    await page.goto("/admin/issues");
    const row = page.getByRole("row", { name: /coord_token/ });
    await expect(row).toBeVisible();
    await row.click();

    await expect(page.getByText("Issue detail")).toBeVisible();
    await expect(page.getByRole("link", { name: "지도" })).toBeVisible();
    // coord는 toFixed(5)로 표시(line 303).
    await expect(page.getByText("126.97800, 37.56650")).toBeVisible();
  });
});
