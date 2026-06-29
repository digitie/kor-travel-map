import { expect, test, type Locator, type Page, type Response } from "@playwright/test";

import * as F from "./_fixtures";
import type { components } from "../../src/api/types";

// LIVE (non-mock) e2e for /admin/features — USER-INPUT → API query param → data → UI
// round-trip. Read-only (GET-only list reads, no mutation): NOT gated, always runnable.
//
// This file DEEPENS e2e/live/features-list.live.spec.ts (issue #574). That spec only
// asserts the table container stays visible after each control change. Here we assert the
// stronger contract for each input:
//   1) the OUTGOING `GET /v1/admin/features` request carries the exact query param, AND
//   2) the live backend response body reflects it (rows filtered/ordered/paged), AND
//   3) the UI table re-renders to mirror that backend response.
//
// Surface + selectors are read verbatim from src/app/admin/features/admin-features-client.tsx
// and the list endpoint param names from src/api/features.ts (fetchAdminFeatures) +
// packages/kor-travel-map-api/.../routers/admin_features.py (list_features).
//   route                 /admin/features
//   h1 heading            "Admin features"            (AdminShell title)
//   search input          getByLabel("feature search")      → q=
//   kind select           getByLabel("feature kind")        → kind=  (repeated)
//   status select         getByLabel("feature status")      → status= (repeated, alias of feature_status)
//   sort select           getByLabel("feature sort")        → sort=
//   page size select      getByLabel("feature page size")   → page_size=
//   order buttons         getByRole("button", {name:"asc"|"desc"})  → order=
//   pagination buttons    getByRole("button", {name:"다음"|"첫 페이지"})  → cursor= (keyset)
//   table container       getByRole("table")  (DataTable)
//
// NOTE: there is NO category control in admin-features-client (category= exists only in the
// API/router, never wired to a UI input), so category is intentionally not exercised here.

type AdminFeaturesListResponse =
  components["schemas"]["AdminFeaturesListResponse"];
type AdminFeatureRecord = components["schemas"]["AdminFeatureRecord"];

type BrowserFetchResult<T> = {
  body: T | null;
  status: number;
  text: string;
};

const ROUTE = "/admin/features";
const HEADING = "Admin features";
const ADMIN_FEATURES_PATH = "/v1/admin/features";

const UI_TIMEOUT = 15_000;
const FLOW_TIMEOUT = 5 * 60 * 1000;
const T = { timeout: UI_TIMEOUT } as const;

// read-only spec — nothing is created, so RUN_ID is only a per-run trace tag (no entity
// collisions / no cleanup possible). kept per repo convention for parallel re-run hygiene.
const RUN_ID = `live-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

const SEARCH_TERMS = F.SEARCH_TERMS.slice(0, 3); // ["공원","공항","도서관"]
const KIND = F.KINDS_PRESENT[0] ?? "place"; // kind guaranteed present in prod data
const PAGE_SIZE = F.PAGE_SIZES[0]; // 25
const ALL_STATUSES = [
  "active",
  "inactive",
  "hidden",
  "broken",
  "deleted",
] as const;

test.describe.configure({ mode: "serial" });

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

type ListCapture = {
  params: URLSearchParams;
  body: AdminFeaturesListResponse;
};

/**
 * Register a waitForResponse on `GET /v1/admin/features` (proxy-stripped) matching `predicate`
 * over the OUTGOING query params, run `action` to trigger it, then return the request's
 * query params + the parsed live response body. This is the input→param→data half of the
 * round-trip; the UI half is asserted by the caller against the returned body.
 */
async function captureList(
  page: Page,
  action: () => Promise<unknown>,
  predicate: (params: URLSearchParams) => boolean,
): Promise<ListCapture> {
  const responsePromise = page.waitForResponse(
    (response) =>
      response.status() === 200 &&
      isApiResponse(response, "GET", ADMIN_FEATURES_PATH) &&
      predicate(new URL(response.url()).searchParams),
    { timeout: FLOW_TIMEOUT },
  );
  await action();
  const response = await responsePromise;
  const body = (await response.json()) as AdminFeaturesListResponse;
  return { params: new URL(response.url()).searchParams, body };
}

async function expectListReady(page: Page): Promise<void> {
  await expect(page.getByRole("heading", { name: HEADING })).toBeVisible(T);
  await expect(page.getByRole("table")).toBeVisible(T);
}

/** DataTable renders a header <tr> (row 0) then body rows; row index 1 is the first data row. */
function firstDataRow(page: Page): Locator {
  return page.getByRole("row").nth(1);
}

/**
 * UI half of the round-trip: the rendered table must mirror the live response `body`. When the
 * query returns rows, items[0] (the server's first row, manualSorting preserves order) must show
 * up as the first data row; when empty, the empty-state message renders.
 */
async function expectTableReflectsBody(
  page: Page,
  body: AdminFeaturesListResponse,
): Promise<void> {
  const first = body.data.items[0];
  if (!first) {
    await expect(page.getByText("feature가 없습니다.")).toBeVisible(T);
    return;
  }
  const firstName = first.name.trim();
  if (firstName.length === 0) {
    await expect(firstDataRow(page)).toBeVisible(T);
    return;
  }
  await expect(firstDataRow(page)).toContainText(firstName, T);
}

// admin-features-client.tsx SORT_OPTIONS와 동일한 7종 (NativeSelect aria-label="feature sort").
type SortColumn =
  | "name"
  | "updated_at"
  | "created_at"
  | "kind"
  | "status"
  | "provider"
  | "issue_count";

/**
 * 시간 컬럼(updated_at/created_at)은 ISO 문자열이라 사전순=시간순이다. DB collation에
 * 의존하지 않고, 응답 페이지가 해당 방향으로 단조 정렬됐는지(asc=비감소, desc=비증가) 검증한다.
 */
function isMonotonicByTime(
  items: readonly AdminFeatureRecord[],
  field: "created_at" | "updated_at",
  order: "asc" | "desc",
): boolean {
  for (let i = 1; i < items.length; i += 1) {
    const prev = items[i - 1][field];
    const curr = items[i][field];
    if (order === "asc" ? prev > curr : prev < curr) {
      return false;
    }
  }
  return true;
}

test.describe("admin/features live — input → query param → data → UI round-trip", () => {
  for (const term of SEARCH_TERMS) {
    test(`검색어 "${term}" 입력이 q 파라미터로 나가고 결과 행이 응답을 반영한다`, async ({
      page,
    }) => {
      test.setTimeout(FLOW_TIMEOUT);
      test.info().annotations.push({ type: "run_id", description: RUN_ID });

      await page.goto(ROUTE);
      await expectListReady(page);

      // typing into the search box issues a GET list query carrying q=<term>.
      const { params, body } = await captureList(
        page,
        () => page.getByLabel("feature search").fill(term),
        (p) => p.get("q") === term,
      );

      // (1) outgoing request carries the search param.
      expect(params.get("q")).toBe(term);
      // (2) backend responded (rows for the term, possibly empty — both are valid live states).
      expect(Array.isArray(body.data.items)).toBe(true);
      // (3) UI reflects: search box holds the term and the table mirrors the response body.
      await expect(page.getByLabel("feature search")).toHaveValue(term);
      await expectTableReflectsBody(page, body);
    });
  }

  test(`kind 필터 "${KIND}" 선택이 kind 파라미터로 나가고 백엔드/행이 해당 kind만 반영한다`, async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    test.info().annotations.push({ type: "run_id", description: RUN_ID });

    await page.goto(ROUTE);
    await expectListReady(page);

    const { params, body } = await captureList(
      page,
      () => page.getByLabel("feature kind").selectOption(KIND),
      (p) => p.getAll("kind").includes(KIND),
    );

    // (1) outgoing request carries a single kind= param.
    expect(params.getAll("kind")).toEqual([KIND]);
    await expect(page.getByLabel("feature kind")).toHaveValue(KIND);

    // (2) every row in the live response is the selected kind.
    for (const item of body.data.items) {
      expect(item.kind).toBe(KIND);
    }
    // (3) UI reflects: first row renders and shows the kind badge.
    await expectTableReflectsBody(page, body);
    if (body.data.items[0]) {
      await expect(firstDataRow(page)).toContainText(KIND, T);
    }

    // Independent backend read (not the UI-driven request) confirms the kind= param semantics.
    await expect
      .poll(async () => {
        const res = await browserFetch<AdminFeaturesListResponse>(
          page,
          `${ADMIN_FEATURES_PATH}?kind=${encodeURIComponent(
            KIND,
          )}&status=active&page_size=25&sort=name&order=asc`,
        );
        const items = res.body?.data.items ?? [];
        return items.length > 0 && items.every((item) => item.kind === KIND);
      }, T)
      .toBe(true);
  });

  test("status 필터 변경(all / 단일)이 status 파라미터로 나가고 행이 반영된다", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    test.info().annotations.push({ type: "run_id", description: RUN_ID });

    await page.goto(ROUTE);
    await expectListReady(page);

    // "all" → 5종 status가 반복 파라미터로 전송된다.
    const all = await captureList(
      page,
      () => page.getByLabel("feature status").selectOption("all"),
      (p) => p.getAll("status").length >= ALL_STATUSES.length,
    );
    expect(new Set(all.params.getAll("status"))).toEqual(new Set(ALL_STATUSES));
    await expect(page.getByLabel("feature status")).toHaveValue("all");
    await expectTableReflectsBody(page, all.body);

    // 단일 "inactive" → 단일 status 파라미터, 백엔드 행은 모두 inactive(또는 빈 결과).
    const inactive = await captureList(
      page,
      () => page.getByLabel("feature status").selectOption("inactive"),
      (p) => p.getAll("status").length === 1 && p.get("status") === "inactive",
    );
    expect(inactive.params.getAll("status")).toEqual(["inactive"]);
    await expect(page.getByLabel("feature status")).toHaveValue("inactive");
    for (const item of inactive.body.data.items) {
      expect(item.status).toBe("inactive");
    }
    await expectTableReflectsBody(page, inactive.body);
  });

  test("sort 필드 / asc·desc order 변경이 sort·order 파라미터로 나가고 첫 행 정렬이 바뀐다", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    test.info().annotations.push({ type: "run_id", description: RUN_ID });

    // 기본 정렬(sort=name, order=asc, cursor 없음) 첫 로드 — 기준 첫 행 캡처.
    const asc = await captureList(
      page,
      () => page.goto(ROUTE),
      (p) =>
        p.get("sort") === "name" &&
        p.get("order") === "asc" &&
        p.get("cursor") === null,
    );
    await expectListReady(page);
    expect(asc.params.get("sort")).toBe("name");
    expect(asc.params.get("order")).toBe("asc");
    const ascFirst = asc.body.data.items[0]?.feature_id;
    expect(ascFirst).toBeTruthy();

    // order=desc 토글 → order 파라미터가 desc로 나가고, 정렬 범위 반대 끝이라 첫 행이 달라진다.
    const desc = await captureList(
      page,
      () => page.getByRole("button", { name: "desc" }).click(),
      (p) => p.get("order") === "desc" && p.get("sort") === "name",
    );
    expect(desc.params.get("order")).toBe("desc");
    const descFirst = desc.body.data.items[0]?.feature_id;
    expect(descFirst).toBeTruthy();
    expect(descFirst).not.toBe(ascFirst);
    await expectTableReflectsBody(page, desc.body);

    // sort=updated_at 선택 → sort 파라미터가 바뀌고 UI/응답이 재정렬된다.
    const updated = await captureList(
      page,
      () => page.getByLabel("feature sort").selectOption("updated_at"),
      (p) => p.get("sort") === "updated_at",
    );
    expect(updated.params.get("sort")).toBe("updated_at");
    await expect(page.getByLabel("feature sort")).toHaveValue("updated_at");
    await expectTableReflectsBody(page, updated.body);
  });

  test("page size 변경과 다음 페이지 이동이 page_size·cursor 파라미터로 나가고 행 집합이 바뀐다", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    test.info().annotations.push({ type: "run_id", description: RUN_ID });

    await page.goto(ROUTE);
    await expectListReady(page);

    // page size를 25로 변경 → page_size 파라미터 반영, cursor 리셋(첫 페이지).
    const sized = await captureList(
      page,
      () => page.getByLabel("feature page size").selectOption(String(PAGE_SIZE)),
      (p) => p.get("page_size") === String(PAGE_SIZE) && p.get("cursor") === null,
    );
    expect(sized.params.get("page_size")).toBe(String(PAGE_SIZE));
    await expect(page.getByLabel("feature page size")).toHaveValue(
      String(PAGE_SIZE),
    );
    const page1First = sized.body.data.items[0]?.feature_id;
    expect(page1First).toBeTruthy();
    // prod(1.09M)에서 첫 페이지에는 next_cursor가 존재한다.
    const nextCursor = sized.body.meta.page?.next_cursor ?? null;
    expect(nextCursor).toBeTruthy();

    // 이동 전: 첫 페이지 버튼 비활성(pageIndex<=1).
    await expect(
      page.getByRole("button", { name: "첫 페이지" }),
    ).toBeDisabled(T);

    // 다음 클릭 → cursor 파라미터가 실려 나가고 다음 페이지 행으로 바뀐다.
    const page2 = await captureList(
      page,
      () => page.getByRole("button", { name: "다음" }).click(),
      (p) =>
        (p.get("cursor") ?? "").length > 0 &&
        p.get("page_size") === String(PAGE_SIZE),
    );
    const cursorSent = page2.params.get("cursor");
    expect(cursorSent).toBeTruthy();
    // 다음 요청의 cursor는 1페이지 응답의 next_cursor와 동일하다(keyset 연속성).
    expect(cursorSent).toBe(nextCursor);
    const page2First = page2.body.data.items[0]?.feature_id;
    expect(page2First).toBeTruthy();
    // (2) 백엔드 데이터: 다음 페이지 첫 행은 1페이지 첫 행과 다르다.
    expect(page2First).not.toBe(page1First);

    // (3) UI 반영: 이동 후 첫 페이지 버튼 활성 + 테이블이 2페이지 응답을 미러링.
    await expect(page.getByRole("button", { name: "첫 페이지" })).toBeEnabled(T);
    await expectTableReflectsBody(page, page2.body);
  });

  test("has issue 필터(issue only / no issue / all)가 has_issue 파라미터로 나가고 행이 반영된다", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    test.info().annotations.push({ type: "run_id", description: RUN_ID });

    await page.goto(ROUTE);
    await expectListReady(page);

    // "no issue" → has_issue=false. 응답의 모든 행은 issue_count===0.
    const noIssue = await captureList(
      page,
      () => page.getByLabel("has issue").selectOption("no"),
      (p) => p.get("has_issue") === "false",
    );
    expect(noIssue.params.get("has_issue")).toBe("false");
    await expect(page.getByLabel("has issue")).toHaveValue("no");
    for (const item of noIssue.body.data.items) {
      expect(item.issue_count).toBe(0);
    }
    await expectTableReflectsBody(page, noIssue.body);

    // "issue only" → has_issue=true. 응답이 있으면 모든 행 issue_count>0
    // (prod 스냅샷엔 issue feature가 없어 보통 빈 결과 — 빈 상태도 유효한 round-trip).
    const issueOnly = await captureList(
      page,
      () => page.getByLabel("has issue").selectOption("yes"),
      (p) => p.get("has_issue") === "true",
    );
    expect(issueOnly.params.get("has_issue")).toBe("true");
    await expect(page.getByLabel("has issue")).toHaveValue("yes");
    for (const item of issueOnly.body.data.items) {
      expect(item.issue_count).toBeGreaterThan(0);
    }
    await expectTableReflectsBody(page, issueOnly.body);

    // "all" → has_issue 파라미터 자체가 빠진다(undefined → 직렬화에서 제외).
    const allIssues = await captureList(
      page,
      () => page.getByLabel("has issue").selectOption("all"),
      (p) => !p.has("has_issue") && p.get("sort") === "name",
    );
    expect(allIssues.params.has("has_issue")).toBe(false);
    await expect(page.getByLabel("has issue")).toHaveValue("all");
    await expectTableReflectsBody(page, allIssues.body);

    // 독립 backend 읽기로 has_issue=false 의미(모든 행 issue 0)를 재확인한다.
    await expect
      .poll(async () => {
        const res = await browserFetch<AdminFeaturesListResponse>(
          page,
          `${ADMIN_FEATURES_PATH}?has_issue=false&status=active&page_size=25&sort=name&order=asc`,
        );
        const items = res.body?.data.items ?? [];
        return res.status === 200 && items.every((item) => item.issue_count === 0);
      }, T)
      .toBe(true);
  });

  test("sort 7개 컬럼 × asc·desc가 sort·order 파라미터로 나가고 응답/UI 정렬이 반영된다", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    test.info().annotations.push({ type: "run_id", description: RUN_ID });

    // 초기 로드: sort=name, order=asc (component 기본값). 컬럼별 asc 기준값 확보.
    const captured = new Map<string, AdminFeaturesListResponse>();
    const initial = await captureList(
      page,
      () => page.goto(ROUTE),
      (p) =>
        p.get("sort") === "name" &&
        p.get("order") === "asc" &&
        p.get("cursor") === null,
    );
    await expectListReady(page);
    expect(initial.params.get("sort")).toBe("name");
    expect(initial.params.get("order")).toBe("asc");
    captured.set("name|asc", initial.body);

    // snake 전이: 각 단계는 sort(select) 또는 order(button) 중 하나만 바꿔 항상 새 요청을 유발한다.
    // 이로써 7컬럼 × {asc,desc} 14개 (sort,order) 조합을 빠짐없이 캡처한다.
    type SortStep = {
      sort: SortColumn;
      order: "asc" | "desc";
      control: "sort" | "order";
    };
    const steps: SortStep[] = [
      { control: "order", order: "desc", sort: "name" },
      { control: "sort", order: "desc", sort: "updated_at" },
      { control: "order", order: "asc", sort: "updated_at" },
      { control: "sort", order: "asc", sort: "created_at" },
      { control: "order", order: "desc", sort: "created_at" },
      { control: "sort", order: "desc", sort: "kind" },
      { control: "order", order: "asc", sort: "kind" },
      { control: "sort", order: "asc", sort: "status" },
      { control: "order", order: "desc", sort: "status" },
      { control: "sort", order: "desc", sort: "provider" },
      { control: "order", order: "asc", sort: "provider" },
      { control: "sort", order: "asc", sort: "issue_count" },
      { control: "order", order: "desc", sort: "issue_count" },
    ];

    for (const step of steps) {
      const action =
        step.control === "sort"
          ? () => page.getByLabel("feature sort").selectOption(step.sort)
          : () => page.getByRole("button", { name: step.order }).click();
      const result = await captureList(
        page,
        action,
        (p) => p.get("sort") === step.sort && p.get("order") === step.order,
      );
      // (1) 파라미터: sort·order가 정확히 실려 나간다.
      expect(result.params.get("sort")).toBe(step.sort);
      expect(result.params.get("order")).toBe(step.order);
      // (UI) sort select는 현재 정렬 컬럼을 미러링한다.
      await expect(page.getByLabel("feature sort")).toHaveValue(step.sort);
      // (2) 시간 컬럼은 응답 페이지가 해당 방향으로 단조 정렬돼 있다.
      if (step.sort === "updated_at" || step.sort === "created_at") {
        expect(
          isMonotonicByTime(result.body.data.items, step.sort, step.order),
        ).toBe(true);
      }
      // (3) UI: 테이블 첫 행이 응답 첫 행을 미러링한다.
      await expectTableReflectsBody(page, result.body);
      captured.set(`${step.sort}|${step.order}`, result.body);
    }

    // 값이 고르게 분포한 컬럼(name·updated_at·created_at)은 asc/desc 첫 행이 실제로 뒤집힌다
    // (order 파라미터가 결과 집합을 진짜로 바꾼다는 증거). kind/status/provider/issue_count는
    // prod 스냅샷에서 동률(전부 place/active/null/0)이라 첫 행 차이를 단정하지 않는다.
    for (const col of ["name", "updated_at", "created_at"] as const) {
      const ascFirst = captured.get(`${col}|asc`)?.data.items[0]?.feature_id;
      const descFirst = captured.get(`${col}|desc`)?.data.items[0]?.feature_id;
      expect(ascFirst).toBeTruthy();
      expect(descFirst).toBeTruthy();
      expect(ascFirst).not.toBe(descFirst);
    }
  });

  test("검색+kind+status 복합 필터가 한 요청에 q·kind·status 파라미터를 모두 싣고 행이 모두 만족한다", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    test.info().annotations.push({ type: "run_id", description: RUN_ID });

    const term = SEARCH_TERMS[0] ?? "공원";
    await page.goto(ROUTE);
    await expectListReady(page);

    // 검색어 입력(이 시점 status=active 기본). kind=place 선택이 q + kind=[place] +
    // status=[active]를 한 요청에 함께 싣는다.
    await page.getByLabel("feature search").fill(term);
    const combined = await captureList(
      page,
      () => page.getByLabel("feature kind").selectOption(KIND),
      (p) =>
        p.get("q") === term &&
        p.getAll("kind").includes(KIND) &&
        p.getAll("status").includes("active"),
    );
    expect(combined.params.get("q")).toBe(term);
    expect(combined.params.getAll("kind")).toEqual([KIND]);
    expect(combined.params.getAll("status")).toEqual(["active"]);
    // 모든 행이 세 필터를 동시에 만족한다(kind=place AND status=active).
    for (const item of combined.body.data.items) {
      expect(item.kind).toBe(KIND);
      expect(item.status).toBe("active");
    }
    await expect(page.getByLabel("feature search")).toHaveValue(term);
    await expect(page.getByLabel("feature kind")).toHaveValue(KIND);
    await expect(page.getByLabel("feature status")).toHaveValue("active");
    await expectTableReflectsBody(page, combined.body);

    // status를 all로 바꾸면 q+kind는 유지되고 status만 5종으로 확장된다(다중 필터 합성 유지).
    const widened = await captureList(
      page,
      () => page.getByLabel("feature status").selectOption("all"),
      (p) =>
        p.get("q") === term &&
        p.getAll("kind").includes(KIND) &&
        p.getAll("status").length >= ALL_STATUSES.length,
    );
    expect(widened.params.get("q")).toBe(term);
    expect(widened.params.getAll("kind")).toEqual([KIND]);
    expect(new Set(widened.params.getAll("status"))).toEqual(
      new Set(ALL_STATUSES),
    );
    for (const item of widened.body.data.items) {
      expect(item.kind).toBe(KIND);
    }
    await expectTableReflectsBody(page, widened.body);
  });

  test("page size 5개 값 각각이 page_size 파라미터로 나가고 응답 행 수가 상한을 지킨다", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    test.info().annotations.push({ type: "run_id", description: RUN_ID });

    await page.goto(ROUTE);
    await expectListReady(page);

    // 기본 50에서 출발 → 인접 값이 항상 달라지도록 25→100→200→500→50 순회(전 값 커버).
    for (const size of [25, 100, 200, 500, 50] as const) {
      const sized = await captureList(
        page,
        () =>
          page.getByLabel("feature page size").selectOption(String(size)),
        (p) => p.get("page_size") === String(size) && p.get("cursor") === null,
      );
      // (1) page_size 파라미터가 선택값으로 나간다.
      expect(sized.params.get("page_size")).toBe(String(size));
      // (UI) page size select가 선택값을 미러링한다.
      await expect(page.getByLabel("feature page size")).toHaveValue(
        String(size),
      );
      // (2) 백엔드: 응답 행 수는 page_size 상한을 넘지 않는다.
      expect(sized.body.data.items.length).toBeLessThanOrEqual(size);
      // (3) UI: 테이블 첫 행이 응답을 미러링한다.
      await expectTableReflectsBody(page, sized.body);
    }
  });

  test("깊은 페이지네이션: 다음을 반복하면 cursor가 이어지고 페이지마다 첫 행이 달라진다", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    test.info().annotations.push({ type: "run_id", description: RUN_ID });

    await page.goto(ROUTE);
    await expectListReady(page);

    // page_size=25 (cursor 리셋) → 1페이지 캡처.
    const page1 = await captureList(
      page,
      () => page.getByLabel("feature page size").selectOption("25"),
      (p) => p.get("page_size") === "25" && p.get("cursor") === null,
    );
    const id1 = page1.body.data.items[0]?.feature_id;
    expect(id1).toBeTruthy();
    const cursor1 = page1.body.meta.page?.next_cursor ?? null;
    expect(cursor1).toBeTruthy();

    // 다음 → 2페이지. 보낸 cursor는 1페이지 next_cursor와 동일(keyset 연속성).
    const page2 = await captureList(
      page,
      () => page.getByRole("button", { name: "다음" }).click(),
      (p) => p.get("cursor") === cursor1 && p.get("page_size") === "25",
    );
    expect(page2.params.get("cursor")).toBe(cursor1);
    const id2 = page2.body.data.items[0]?.feature_id;
    expect(id2).toBeTruthy();
    const cursor2 = page2.body.meta.page?.next_cursor ?? null;
    expect(cursor2).toBeTruthy();
    await expectTableReflectsBody(page, page2.body);

    // 다음 → 3페이지(더 깊이). 보낸 cursor는 2페이지 next_cursor와 동일.
    const page3 = await captureList(
      page,
      () => page.getByRole("button", { name: "다음" }).click(),
      (p) => p.get("cursor") === cursor2 && p.get("page_size") === "25",
    );
    expect(page3.params.get("cursor")).toBe(cursor2);
    const id3 = page3.body.data.items[0]?.feature_id;
    expect(id3).toBeTruthy();
    await expectTableReflectsBody(page, page3.body);

    // (2) 백엔드: 세 페이지의 첫 행 id가 모두 다르다(연속 전진, 중복 없음).
    expect(new Set([id1, id2, id3]).size).toBe(3);
    // (3) UI: 3페이지에서 첫 페이지 버튼은 활성 상태다.
    await expect(page.getByRole("button", { name: "첫 페이지" })).toBeEnabled(T);
  });
});
