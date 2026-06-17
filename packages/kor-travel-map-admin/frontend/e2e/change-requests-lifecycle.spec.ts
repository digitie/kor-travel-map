import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";

// 손으로 쓴 record shape 대신 **생성된 OpenAPI 스키마**에 바인딩한다(#308 리뷰).
// 백엔드 DTO가 바뀌면 factory가 타입 불일치로 컴파일 실패 → mock-실계약 drift 감지.
// 이 spec은 admin-ops.spec.ts의 change-requests smoke/approve가 다루지 않는
// 나머지 깊이(reject 라이프사이클, 서버 4xx 에러 배너, 빈 목록, q 서버 필터)만 더한다.
type AdminFeatureChangeRecord =
  components["schemas"]["AdminFeatureChangeRequestRecord"];
type AdminFeatureChangeListResponse =
  components["schemas"]["AdminFeatureChangeListResponse"];
type AdminFeatureChangeResponse =
  components["schemas"]["AdminFeatureChangeResponse"];
type AdminFeatureReviewActionRequest =
  components["schemas"]["AdminFeatureReviewActionRequest"];
type AdminFeatureReviewMode = AdminFeatureChangeRecord["review_mode"];
type HTTPValidationError = components["schemas"]["HTTPValidationError"];

const MOCK_NOW = "2026-06-08T00:00:00.000Z";
const MOCK_REVIEWED_AT = "2026-06-08T00:10:00.000Z";

function makeFeatureChange(
  overrides: Partial<AdminFeatureChangeRecord> = {},
): AdminFeatureChangeRecord {
  return {
    action: "add",
    applied_at: null,
    created_at: MOCK_NOW,
    feature_id: "user_request::e2e::mock-feature",
    payload: {
      category: "01070300",
      kind: "place",
      name: "Mock pending feature",
    },
    reason: "운영 변경",
    request_id: "change-mock-1",
    requested_by: "local-admin",
    review_mode: "require_review",
    reviewed_at: null,
    reviewed_by: null,
    status: "pending",
    ...overrides,
  };
}

function featureChangeListResponse(
  items: AdminFeatureChangeRecord[],
  reviewMode: AdminFeatureReviewMode,
  limit: number,
): AdminFeatureChangeListResponse {
  return {
    data: { items, review_mode: reviewMode },
    meta: {
      duration_ms: 1,
      page: { page_size: limit, next_cursor: null, total: null },
      request_id: "e2e-feature-change-list",
    },
  };
}

function featureChangeResponse(
  request: AdminFeatureChangeRecord,
): AdminFeatureChangeResponse {
  return {
    data: { request },
    meta: { duration_ms: 1, request_id: "e2e-feature-change" },
  };
}

function httpValidationError(): HTTPValidationError {
  return {
    detail: [
      {
        loc: ["body", "name"],
        msg: "field required",
        type: "value_error.missing",
      },
    ],
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
 * 목록 GET + reject/approve mutation을 in-memory 상태로 처리하는 self-contained
 * helper. admin-ops.spec.ts의 mockFeatureChangeMutations idiom을 그대로 옮기되,
 * 이 spec이 실제로 행사하는 분기(list + reject + approve)만 남긴다.
 */
async function mockChangeList(
  page: Page,
  options: {
    initial?: AdminFeatureChangeRecord[];
    reviewMode?: AdminFeatureReviewMode;
  } = {},
) {
  const reviewMode = options.reviewMode ?? "require_review";
  let changes = [...(options.initial ?? [])];
  const requests = {
    approve: 0,
    list: 0,
    reject: 0,
    lastListQ: null as string | null,
    reviewBodies: [] as AdminFeatureReviewActionRequest[],
  };

  function filteredChanges(url: URL) {
    const statuses = new Set(url.searchParams.getAll("status"));
    const actions = new Set(url.searchParams.getAll("action"));
    const q = (url.searchParams.get("q") ?? "").toLowerCase();
    return changes.filter((item) => {
      const name =
        typeof item.payload.name === "string"
          ? item.payload.name.toLowerCase()
          : "";
      return (
        (statuses.size === 0 || statuses.has(item.status)) &&
        (actions.size === 0 || actions.has(item.action)) &&
        (q.length === 0 ||
          item.request_id.toLowerCase().includes(q) ||
          item.feature_id.toLowerCase().includes(q) ||
          (item.reason ?? "").toLowerCase().includes(q) ||
          name.includes(q))
      );
    });
  }

  function storeChange(request: AdminFeatureChangeRecord) {
    changes = [
      request,
      ...changes.filter((item) => item.request_id !== request.request_id),
    ];
    return request;
  }

  await page.route("**/v1/admin/features**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());

    if (
      request.method() === "GET" &&
      url.pathname === "/v1/admin/features/change-requests"
    ) {
      requests.list += 1;
      requests.lastListQ = url.searchParams.get("q");
      await fulfillJson(
        route,
        featureChangeListResponse(
          filteredChanges(url),
          reviewMode,
          Number(url.searchParams.get("page_size") ?? 100),
        ),
      );
      return;
    }

    if (request.method() === "POST" && url.pathname.endsWith("/reject")) {
      requests.reject += 1;
      const body = request.postDataJSON() as AdminFeatureReviewActionRequest;
      requests.reviewBodies.push(body);
      const requestId = url.pathname.split("/").at(-2);
      const target = changes.find((item) => item.request_id === requestId);
      if (!target) {
        await fulfillJson(route, { detail: "not found" }, 404);
        return;
      }
      const updated = storeChange({
        ...target,
        reviewed_at: MOCK_REVIEWED_AT,
        reviewed_by: body.operator ?? "local-admin",
        status: "rejected",
      });
      await fulfillJson(route, featureChangeResponse(updated));
      return;
    }

    if (request.method() === "POST" && url.pathname.endsWith("/approve")) {
      requests.approve += 1;
      const body = request.postDataJSON() as AdminFeatureReviewActionRequest;
      requests.reviewBodies.push(body);
      const requestId = url.pathname.split("/").at(-2);
      const target = changes.find((item) => item.request_id === requestId);
      if (!target) {
        await fulfillJson(route, { detail: "not found" }, 404);
        return;
      }
      const updated = storeChange({
        ...target,
        applied_at: MOCK_REVIEWED_AT,
        reviewed_at: MOCK_REVIEWED_AT,
        reviewed_by: body.operator ?? "local-admin",
        status: "applied",
      });
      await fulfillJson(route, featureChangeResponse(updated));
      return;
    }

    throw new Error(`Unhandled feature change route: ${request.method()} ${url}`);
  });

  return requests;
}

test.describe("admin feature change-requests lifecycle", () => {
  test("reject flips a pending row to rejected and clears its action buttons", async ({
    page,
  }) => {
    const requests = await mockChangeList(page, {
      initial: [
        makeFeatureChange({
          feature_id: "feature-pending-1",
          payload: {
            category: "01070300",
            kind: "place",
            name: "Mock pending feature",
          },
          reason: "검토 필요",
          request_id: "change-pending-1",
        }),
      ],
    });

    await page.goto("/admin/features/change-requests");
    // 기본 마운트 status 필터는 'pending'(useState 초기값). reject 후 행이 pending을
    // 벗어나도 보이도록 'all'로 바꾼다(approve-workflow idiom과 동일).
    await page.getByLabel("change status", { exact: true }).selectOption("all");

    const pendingRow = page.getByRole("row", { name: /Mock pending feature/ });
    await expect(pendingRow).toBeVisible();

    // 행 선택 → 상세 aside에 request_id 노출(approve-workflow와 동일 idiom).
    await pendingRow.click();
    await expect(
      page.locator("aside").getByText("change-pending-1"),
    ).toBeVisible();

    await pendingRow.getByRole("button", { name: "reject" }).click();

    await expect.poll(() => requests.reject).toBe(1);
    expect(requests.reviewBodies[0]).toMatchObject({
      operator: "local-admin",
      reason: "admin-ui reject",
    });

    // StatusBadge는 raw status 문자열을 텍스트로 렌더한다.
    await expect(pendingRow.getByText("rejected")).toBeVisible();
    // status !== 'pending'이면 actions 셀은 버튼 대신 '완료' 텍스트만 렌더한다.
    await expect(
      pendingRow.getByRole("button", { name: "approve" }),
    ).toHaveCount(0);
    await expect(
      pendingRow.getByRole("button", { name: "reject" }),
    ).toHaveCount(0);
  });

  test("approve 409 conflict surfaces the destructive error alert", async ({
    page,
  }) => {
    const pendingRecord = makeFeatureChange({
      feature_id: "feature-pending-1",
      payload: {
        category: "01070300",
        kind: "place",
        name: "Mock pending feature",
      },
      reason: "검토 필요",
      request_id: "change-pending-1",
    });
    let approveCount = 0;

    await page.route("**/v1/admin/features**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());

      if (
        request.method() === "GET" &&
        url.pathname === "/v1/admin/features/change-requests"
      ) {
        await fulfillJson(
          route,
          featureChangeListResponse([pendingRecord], "require_review", 100),
        );
        return;
      }

      if (request.method() === "POST" && url.pathname.endsWith("/approve")) {
        approveCount += 1;
        await route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({ detail: "request already applied" }),
        });
        return;
      }

      throw new Error(`Unhandled route: ${request.method()} ${url}`);
    });

    await page.goto("/admin/features/change-requests");

    // 기본 'pending' 필터가 이 행을 그대로 보여주므로 selectOption 불필요.
    const pendingRow = page.getByRole("row", { name: /Mock pending feature/ });
    await expect(pendingRow).toBeVisible();
    await pendingRow.getByRole("button", { name: "approve" }).click();

    await expect.poll(() => approveCount).toBe(1);

    // destructive Alert는 role='alert'으로 해석된다.
    const alert = page
      .getByRole("alert")
      .filter({ hasText: "feature change 처리 실패" });
    await expect(alert).toBeVisible();
    // client.ts 에러 포맷 'POST <path> 실패 (HTTP 409) <detail>' → mutationError.message.
    await expect(alert).toContainText("HTTP 409");

    // approve가 적용되지 않았으므로 행은 여전히 pending + approve 버튼 유지.
    // STRICT-MODE: 행 안에는 'pending'이 status StatusBadge 외에도 feature name
    // ("Mock pending feature") 등 여러 곳에 substring으로 등장한다. status가
    // 'pending'으로 남았음만 단언하려면 StatusBadge가 렌더한 정확한 텍스트
    // 노드만 노린다 → exact 매칭으로 name 셀의 substring을 배제한다.
    await expect(
      pendingRow.getByText("pending", { exact: true }),
    ).toBeVisible();
    await expect(
      pendingRow.getByRole("button", { name: "approve" }),
    ).toBeVisible();
  });

  test("create 422 validation error surfaces the destructive error alert", async ({
    page,
  }) => {
    let postCount = 0;

    await page.route("**/v1/admin/features**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());

      if (
        request.method() === "GET" &&
        url.pathname === "/v1/admin/features/change-requests"
      ) {
        await fulfillJson(
          route,
          featureChangeListResponse([], "require_review", 100),
        );
        return;
      }

      if (
        request.method() === "POST" &&
        url.pathname === "/v1/admin/features"
      ) {
        postCount += 1;
        await route.fulfill({
          status: 422,
          contentType: "application/json",
          body: JSON.stringify(httpValidationError()),
        });
        return;
      }

      throw new Error(`Unhandled route: ${request.method()} ${url}`);
    });

    await page.goto("/admin/features/change-requests");

    // 폼을 VALID하게 채워 buildCreatePayload가 throw하지 않고 네트워크까지 도달하게 한다
    // (client-side guard 경로가 server 4xx를 가리지 않도록). category는 '01070300' 기본값,
    // action은 'add' 기본값.
    await page.getByLabel("change name", { exact: true }).fill("Server reject");
    await page.getByLabel("change reason", { exact: true }).fill("서버 거절");
    await page.getByRole("button", { name: "요청 생성" }).click();

    // 요청이 실제로 클라이언트를 떠났음을 확인(client-side guard 경로가 아님을 증명).
    await expect.poll(() => postCount).toBe(1);

    const alert = page
      .getByRole("alert")
      .filter({ hasText: "feature change 처리 실패" });
    await expect(alert).toBeVisible();
    // formError는 null(buildCreatePayload 성공) → mutationError.message가 렌더된다.
    await expect(alert).toContainText("HTTP 422");
  });

  test("empty list renders the DataTable empty message without crashing", async ({
    page,
  }) => {
    await page.route("**/v1/admin/features**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());

      if (
        request.method() === "GET" &&
        url.pathname === "/v1/admin/features/change-requests"
      ) {
        await fulfillJson(
          route,
          featureChangeListResponse([], "require_review", 100),
        );
        return;
      }

      throw new Error(`Unhandled route: ${request.method()} ${url}`);
    });

    await page.goto("/admin/features/change-requests");

    // DataTable emptyMessage prop.
    await expect(
      page.getByText("feature change request가 없습니다."),
    ).toBeVisible();
    // 데이터 행 0개 확인.
    await expect(page.getByRole("row", { name: /Mock|feature-/ })).toHaveCount(
      0,
    );
    // 상세 패널 placeholder(ChangeRequestDetail null 분기).
    await expect(page.getByText("요청 행을 선택하면")).toBeVisible();
  });

  test("q search server-filters the list (query carries q, row count shrinks)", async ({
    page,
  }) => {
    const requests = await mockChangeList(page, {
      initial: [
        makeFeatureChange({
          feature_id: "feature-alpha",
          payload: { category: "01070300", kind: "place", name: "Alpha feature" },
          reason: "r1",
          request_id: "change-alpha",
        }),
        makeFeatureChange({
          feature_id: "feature-beta",
          payload: { category: "01070300", kind: "place", name: "Beta feature" },
          reason: "r2",
          request_id: "change-beta",
        }),
      ],
    });

    await page.goto("/admin/features/change-requests");
    // 두 seed 행 모두 pending → 'all'로 바꿔 baseline 노출.
    await page.getByLabel("change status", { exact: true }).selectOption("all");

    const alphaRow = page.getByRole("row", { name: /Alpha feature/ });
    const betaRow = page.getByRole("row", { name: /Beta feature/ });
    await expect(alphaRow).toBeVisible();
    await expect(betaRow).toBeVisible();

    // q는 useDeferredValue(q.trim())로 debounce → q='alpha' 쿼리가 새로 발사된다.
    await page.getByLabel("change search").fill("alpha");

    await expect(alphaRow).toBeVisible();
    await expect(betaRow).toHaveCount(0);

    // 요청이 q를 실어 보냈는지 기록된 쿼리 파라미터로 검증(refetch count 아님 —
    // staleTime 15s 때문에 동일 파라미터는 캐시될 수 있음).
    await expect.poll(() => requests.lastListQ).toBe("alpha");
  });
});
