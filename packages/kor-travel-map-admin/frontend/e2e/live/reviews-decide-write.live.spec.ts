import { expect, test, type Locator, type Page, type Response } from "@playwright/test";

import type { components } from "../../src/api/types";
import * as F from "./_fixtures";

// LIVE (non-mock) e2e for the dedup + enrichment review DECISION round-trip.
//
// PART A (NOT gated): read-input round-trip for both /admin/dedup-reviews and
//   /admin/enrichment-reviews — status / score-band / search / page-size /
//   pagination drive the list GET query string (asserted via waitForResponse on
//   the /api/proxy list path), the UI table/empty-state reflects it, and — when a
//   candidate row exists — clicking it opens the comparison dialog and the dialog
//   shows the two features/scores returned by the single-detail GET. PRESENCE
//   (dedup/enrichment) may be 0 in this env, so empty queues are handled
//   gracefully (assert empty-state, skip the row/dialog parts).
//
// PART B (GATED + IRREVERSIBLE): a real reject decision. dedup `set_dedup_review_
//   decision` / enrichment `decide_enrichment_review` flip the queue row to
//   `rejected` and CANNOT be undone via the UI/API. reject is the least-
//   destructive decision (no merge, no enrichment SourceLink applied), so it is
//   chosen over accept. PART B only runs with an EXPLICIT
//   `E2E_REVIEW_DECIDE=1` AND (`E2E_ADMIN_WRITE=1` or `E2E_REVIEW_WRITE=1`); at
//   runtime it queries for a PENDING candidate and `test.skip`s when none exist.

type DedupReviewListResponse = components["schemas"]["DedupReviewListResponse"];
type DedupReviewDetailResponse =
  components["schemas"]["DedupReviewDetailResponse"];
type DedupReviewDecisionResponse =
  components["schemas"]["DedupReviewDecisionResponse"];
type EnrichmentReviewListResponse =
  components["schemas"]["EnrichmentReviewListResponse"];
type EnrichmentReviewDetailResponse =
  components["schemas"]["EnrichmentReviewDetailResponse"];
type EnrichmentReviewDecisionResponse =
  components["schemas"]["EnrichmentReviewDecisionResponse"];
type AdminFeatureDetailResponse =
  components["schemas"]["AdminFeatureDetailResponse"];

type BrowserFetchResult<T> = {
  body: T | null;
  status: number;
  text: string;
};

const UI_TIMEOUT = 15_000;
const FLOW_TIMEOUT = 5 * 60 * 1000;
const T = { timeout: UI_TIMEOUT } as const;

const RUN_ID = `live-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

// PART B gating: irreversible, default-skip. Requires E2E_REVIEW_DECIDE=1 AND a
// write gate (E2E_ADMIN_WRITE=1 or E2E_REVIEW_WRITE=1).
const EXECUTE_REVIEW_WRITE =
  process.env.E2E_ADMIN_WRITE === "1" || process.env.E2E_REVIEW_WRITE === "1";
const EXECUTE_REVIEW_DECIDE =
  process.env.E2E_REVIEW_DECIDE === "1" && EXECUTE_REVIEW_WRITE;
// ACCEPT는 reject보다 무겁다: dedup accept는 status 전이(데이터 미변경)지만,
// enrichment accept는 보관 SourceRecord를 복원해 ENRICHMENT SourceLink를 1차 feature에
// 적재(applied=true)하므로 비가역적으로 데이터를 바꾼다. 따라서 reject 게이트
// (E2E_REVIEW_DECIDE) 위에 EXTRA `E2E_REVIEW_ACCEPT=1`을 추가로 요구하고 기본 skip한다.
const EXECUTE_REVIEW_ACCEPT =
  process.env.E2E_REVIEW_ACCEPT === "1" && EXECUTE_REVIEW_DECIDE;

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

/**
 * `apiPath` ignores the query string (pathname only), so to assert the list GET
 * carries the right filter params we match the list pathname AND require every
 * expected search param to equal the given value.
 */
async function waitForListQuery(
  page: Page,
  listPath: string,
  expected: Record<string, string>,
  timeout = FLOW_TIMEOUT,
): Promise<Response> {
  return page.waitForResponse(
    (response) => {
      if (response.request().method() !== "GET") return false;
      if (apiPath(response) !== listPath) return false;
      const params = new URL(response.url()).searchParams;
      return Object.entries(expected).every(
        ([key, value]) => params.get(key) === value,
      );
    },
    { timeout },
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

interface Surface {
  key: "dedup" | "enrichment";
  route: string;
  heading: string;
  listPath: string;
  searchLabel: string;
  statusLabel: string;
  scoreLabel: string;
  pageSizeLabel: string;
  nextLabel: string;
  prevLabel: string;
  emptyMessage: string;
  dialogName: string;
  dialogTitle: string;
}

const DEDUP: Surface = {
  key: "dedup",
  route: "/admin/dedup-reviews",
  heading: "Dedup review",
  listPath: "/v1/admin/dedup-reviews",
  searchLabel: "dedup search",
  statusLabel: "dedup status",
  scoreLabel: "dedup score filter",
  pageSizeLabel: "dedup page size",
  nextLabel: "dedup 다음 페이지",
  prevLabel: "dedup 이전 페이지",
  emptyMessage: "dedup review가 없습니다.",
  dialogName: "dedup review detail",
  dialogTitle: "Dedup 상세 비교",
};

const ENRICHMENT: Surface = {
  key: "enrichment",
  route: "/admin/enrichment-reviews",
  heading: "Enrichment review",
  listPath: "/v1/admin/enrichment-reviews",
  searchLabel: "enrichment search",
  statusLabel: "enrichment status",
  scoreLabel: "enrichment score filter",
  pageSizeLabel: "enrichment page size",
  nextLabel: "다음 페이지",
  prevLabel: "이전 페이지",
  emptyMessage: "enrichment review가 없습니다.",
  dialogName: "enrichment review detail",
  dialogTitle: "Enrichment 상세 비교",
};

function detailPath(s: Surface, reviewId: string): string {
  return `${s.listPath}/${encodeURIComponent(reviewId)}`;
}

/** row locator by the rendered `shortId` (first 12 chars of review_id). */
function reviewRow(page: Page, reviewId: string): Locator {
  return page
    .locator("tbody tr")
    .filter({ hasText: reviewId.slice(0, 12) })
    .first();
}

/**
 * `status-badge.tsx`의 `statusLabel` 미러. #600에서 status 뱃지/`statusLabel(...)`로
 * 렌더되는 상태 텍스트가 한글화됐다 — 큐 행의 status 뱃지(`<StatusBadge>`)와 상세
 * 다이얼로그의 feature status(`statusLabel(feature.status)`)는 이제 한글로 노출되므로
 * "렌더된 텍스트"를 단언할 때 이 변환을 거친다. (API/DTO enum 값은 여전히 영문이라
 * 응답 body·쿼리·selectOption 단언에는 쓰지 않는다 — 화면 텍스트 단언 전용.)
 */
function koStatus(status: string): string {
  const map: Record<string, string> = {
    active: "활성",
    inactive: "비활성",
    deleted: "삭제됨",
    pending: "대기",
    accepted: "수락됨",
    rejected: "거절됨",
    merged: "병합됨",
    ignored: "무시됨",
  };
  return map[status.toLowerCase().replace(/-/g, "_")] ?? status;
}

async function expectEmptyOrTable(page: Page, s: Surface): Promise<void> {
  const empty = page.getByText(s.emptyMessage);
  if ((await empty.count()) > 0 && (await empty.first().isVisible())) {
    return;
  }
  await expect(page.getByRole("table").first()).toBeVisible(T);
}

async function gotoSurface(page: Page, s: Surface): Promise<void> {
  await page.goto(s.route);
  await expect(
    page.getByRole("heading", { level: 1, name: s.heading }),
  ).toBeVisible(T);
}

// ─── PART A: read-input round-trip (NOT gated) ──────────────────────────────

async function runReadRoundTrip(page: Page, s: Surface): Promise<void> {
  await gotoSurface(page, s);

  await test.step("필터/페이지 컨트롤이 노출된다", async () => {
    await expect(page.getByLabel(s.searchLabel)).toBeVisible(T);
    await expect(page.getByLabel(s.statusLabel)).toBeVisible(T);
    await expect(page.getByLabel(s.scoreLabel)).toBeVisible(T);
    await expect(page.getByLabel(s.pageSizeLabel)).toBeVisible(T);
  });

  await test.step("status 필터가 list GET status 쿼리에 반영된다", async () => {
    const wait = waitForListQuery(page, s.listPath, {
      status: "accepted",
      page: "1",
    });
    await page.getByLabel(s.statusLabel).selectOption("accepted");
    const response = await wait;
    expect(response.status()).toBe(200);
    await expectEmptyOrTable(page, s);
  });

  await test.step("score band 필터가 min_score/max_score 쿼리에 반영된다", async () => {
    const wait = waitForListQuery(page, s.listPath, {
      min_score: "70",
      max_score: "90",
    });
    await page.getByLabel(s.scoreLabel).selectOption("middle");
    expect((await wait).status()).toBe(200);
    await expectEmptyOrTable(page, s);
  });

  const term = F.SEARCH_TERMS[0];
  await test.step("검색어가 q 쿼리에 반영된다", async () => {
    const wait = waitForListQuery(page, s.listPath, { q: term });
    await page.getByLabel(s.searchLabel).fill(term);
    expect((await wait).status()).toBe(200);
    await expect(page.getByLabel(s.searchLabel)).toHaveValue(term, T);
    await expectEmptyOrTable(page, s);
  });

  let total = 0;
  await test.step("page size가 page_size 쿼리에 반영된다", async () => {
    const wait = waitForListQuery(page, s.listPath, { page_size: "25" });
    await page.getByLabel(s.pageSizeLabel).selectOption("25");
    const response = await wait;
    const body = (await response.json()) as
      | DedupReviewListResponse
      | EnrichmentReviewListResponse;
    total = body.meta.page?.total ?? 0;
    await expectEmptyOrTable(page, s);
  });

  await test.step("페이지네이션이 page 쿼리에 반영되거나 빈 큐에서 비활성이다", async () => {
    const nextBtn = page.getByLabel(s.nextLabel).first();
    if (total > 25) {
      const forward = waitForListQuery(page, s.listPath, {
        page: "2",
        page_size: "25",
      });
      await nextBtn.click();
      expect((await forward).status()).toBe(200);
      const back = waitForListQuery(page, s.listPath, {
        page: "1",
        page_size: "25",
      });
      await page.getByLabel(s.prevLabel).first().click();
      expect((await back).status()).toBe(200);
    } else {
      // empty/single-page queue (PRESENCE may be 0) → next is disabled.
      await expect(nextBtn).toBeDisabled(T);
    }
    await expectEmptyOrTable(page, s);
  });

  await test.step("후보가 있으면 행 클릭으로 상세 비교 다이얼로그를 검증한다", async () => {
    // fresh nav → 기본 status=pending(대부분 후보가 pending) 으로 노출.
    await gotoSurface(page, s);
    const pending = await browserFetch<
      DedupReviewListResponse | EnrichmentReviewListResponse
    >(page, `${s.listPath}?status=pending&page_size=5&page=1`);
    const items = pending.body?.data.items ?? [];
    if (items.length === 0) {
      // zero candidates → empty state, skip row/dialog (do not fail).
      await expect(page.getByText(s.emptyMessage)).toBeVisible(T);
      return;
    }

    // 실제 데이터 행이 렌더될 때까지 대기(skeleton/empty 행 클릭 방지).
    const firstId = items[0].review_id;
    const dataRow = reviewRow(page, firstId);
    await expect(dataRow).toBeVisible(T);

    const detailWait = page.waitForResponse(
      (response) =>
        response.request().method() === "GET" &&
        apiPath(response).startsWith(`${s.listPath}/`),
      { timeout: FLOW_TIMEOUT },
    );
    // review id 텍스트 셀을 클릭해 행 onRowClick → 다이얼로그를 연다. dedup은
    // enableRowSelection으로 첫 td가 체크박스(onClick stopPropagation)이고 actions
    // 셀도 stopPropagation 하므로, 위치 무관하게 review id 셀(전파 O)을 직접 클릭한다.
    await dataRow.getByText(firstId.slice(0, 12)).first().click();
    const detailResponse = await detailWait;
    expect(detailResponse.status()).toBe(200);

    const dialog = page.getByRole("dialog", { name: s.dialogName });
    await expect(dialog).toBeVisible(T);
    await expect(dialog.getByText(s.dialogTitle)).toBeVisible(T);

    if (s.key === "dedup") {
      const body = (await detailResponse.json()) as DedupReviewDetailResponse;
      // 비교 대상 두 feature(A/B) + 점수가 다이얼로그에 그대로 노출된다.
      await expect(dialog).toContainText(body.data.feature_a.feature_id);
      await expect(dialog).toContainText(body.data.feature_b.feature_id);
      await expect(dialog).toContainText(body.data.feature_a.name);
      await expect(dialog).toContainText(body.data.feature_b.name);
      await expect(dialog).toContainText(body.data.total_score.toFixed(1));
    } else {
      const body = (await detailResponse.json()) as EnrichmentReviewDetailResponse;
      // 1차 target(datagokr) + 2차 source(visitkorea) + 점수가 노출된다.
      await expect(dialog).toContainText(body.data.target.feature_id);
      await expect(dialog).toContainText(body.data.source.source_entity_id);
      // 다이얼로그는 target.name(ReviewFeatureDetailRecord.name)을 렌더한다 —
      // 상위 target_name(역정규화 필드)이 아닌, DOM에 실제 노출되는 값을 단언한다.
      await expect(dialog).toContainText(body.data.target.name);
      await expect(dialog).toContainText(body.data.name_score.toFixed(1));
    }

    await dialog.getByRole("button", { name: "닫기" }).click();
    await expect(dialog).toBeHidden(T);
  });
}

test.describe("dedup + enrichment reviews — read-input round-trip (ungated)", () => {
  test("dedup 목록 필터/페이지/상세 다이얼로그가 list·detail API와 왕복한다", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    await runReadRoundTrip(page, DEDUP);
  });

  test("enrichment 목록 필터/페이지/상세 다이얼로그가 list·detail API와 왕복한다", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    await runReadRoundTrip(page, ENRICHMENT);
  });
});

// ─── PART B: real reject decision (GATED, IRREVERSIBLE) ─────────────────────

test.describe("dedup + enrichment reviews — real reject decision (gated)", () => {
  test("[dedup] PENDING 후보를 reject하면 status·목록이 바뀌고 feature는 불변이다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_REVIEW_DECIDE,
      "E2E_REVIEW_DECIDE=1 + (E2E_ADMIN_WRITE|E2E_REVIEW_WRITE)=1일 때만 비가역 reject 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);
    test.info().annotations.push({ type: "run-id", description: RUN_ID });

    await gotoSurface(page, DEDUP);

    const pending = await browserFetch<DedupReviewListResponse>(
      page,
      `${DEDUP.listPath}?status=pending&page_size=1&page=1`,
    );
    const target = pending.body?.data.items?.[0];
    if (!target) {
      test.skip(true, "no pending dedup review candidate");
      return;
    }
    const reviewId = target.review_id;
    const featureAId = target.feature_a.feature_id;

    // baseline: 거절 후 feature 불변 확인을 위해 상세 snapshot 캡처.
    const before = await browserFetch<DedupReviewDetailResponse>(
      page,
      detailPath(DEDUP, reviewId),
    );
    expect(before.status).toBe(200);
    const beforeVersion = before.body?.data.feature_a.data_version ?? null;
    const beforeUpdatedAt = before.body?.data.feature_a.updated_at ?? null;

    // pending을 넓게(200) 노출해 대상 행을 화면에 띄운다.
    const sizeWait = waitForListQuery(page, DEDUP.listPath, {
      status: "pending",
      page_size: "200",
    });
    await page.getByLabel(DEDUP.pageSizeLabel).selectOption("200");
    await sizeWait;

    const row = reviewRow(page, reviewId);
    await expect(row).toBeVisible(T);

    // reject (비가역) — UI 버튼이 PATCH decision API를 호출한다.
    const decideWait = waitForApiResponse(
      page,
      "PATCH",
      detailPath(DEDUP, reviewId),
    );
    await row.getByRole("button", { name: "reject" }).click();
    const decideResponse = await decideWait;
    expect(decideResponse.status()).toBe(200);
    const decideBody =
      (await decideResponse.json()) as DedupReviewDecisionResponse;
    expect(decideBody.data).toMatchObject({
      review_id: reviewId,
      decision: "rejected",
      changed: true,
    });
    // reject는 merge가 아니므로 master/loser/merge 이동이 없다.
    expect(decideBody.data.master_feature_id ?? null).toBeNull();
    expect(decideBody.data.loser_feature_id ?? null).toBeNull();
    expect(decideBody.data.merge_id ?? null).toBeNull();

    // 백엔드 반영: 더 이상 pending 큐에 없다.
    await expect
      .poll(async () => {
        const after = await browserFetch<DedupReviewListResponse>(
          page,
          `${DEDUP.listPath}?status=pending&page_size=200&page=1`,
        );
        return (after.body?.data.items ?? []).some(
          (item) => item.review_id === reviewId,
        );
      }, T)
      .toBe(false);

    // 상세 status=rejected + feature(A) data_version/updated_at 불변.
    const after = await browserFetch<DedupReviewDetailResponse>(
      page,
      detailPath(DEDUP, reviewId),
    );
    expect(after.status).toBe(200);
    expect(after.body?.data.status).toBe("rejected");
    expect(after.body?.data.feature_a.data_version ?? null).toBe(beforeVersion);
    expect(after.body?.data.feature_a.updated_at ?? null).toBe(beforeUpdatedAt);

    // 추가 불변 확인: feature 자체는 삭제/병합되지 않았다.
    const feature = await browserFetch<AdminFeatureDetailResponse>(
      page,
      `/v1/admin/features/${encodeURIComponent(featureAId)}`,
    );
    if (feature.status === 200) {
      expect(["active", "inactive"]).toContain(
        feature.body?.data.feature.status,
      );
    }

    // UI 반영: pending 목록에서 행이 사라지고, rejected 필터에서 다시 보인다.
    await expect(
      page.locator("tbody tr").filter({ hasText: reviewId.slice(0, 12) }),
    ).toHaveCount(0, { timeout: UI_TIMEOUT });

    // rejected는 비가역이라 누적되므로 feature_id로 좁혀(placeholder "feature id, name")
    // 대상 review를 1페이지에 확실히 노출시킨다.
    await page.getByLabel(DEDUP.searchLabel).fill(featureAId);
    const rejectedWait = waitForListQuery(page, DEDUP.listPath, {
      status: "rejected",
      q: featureAId,
    });
    await page.getByLabel(DEDUP.statusLabel).selectOption("rejected");
    await rejectedWait;
    const rejectedRow = reviewRow(page, reviewId);
    await expect(rejectedRow).toBeVisible(T);
    await expect(rejectedRow).toContainText(koStatus("rejected"));
  });

  test("[enrichment] PENDING 후보를 reject하면 status·목록이 바뀌고 미적용(applied=false)이다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_REVIEW_DECIDE,
      "E2E_REVIEW_DECIDE=1 + (E2E_ADMIN_WRITE|E2E_REVIEW_WRITE)=1일 때만 비가역 reject 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);
    test.info().annotations.push({ type: "run-id", description: RUN_ID });

    await gotoSurface(page, ENRICHMENT);

    const pending = await browserFetch<EnrichmentReviewListResponse>(
      page,
      `${ENRICHMENT.listPath}?status=pending&page_size=1&page=1`,
    );
    const target = pending.body?.data.items?.[0];
    if (!target) {
      test.skip(true, "no pending enrichment review candidate");
      return;
    }
    const reviewId = target.review_id;
    const targetFeatureId = target.target_feature_id;

    // baseline: target feature snapshot(accept는 source link를 추가하므로 거절 후
    // sources 길이/version 불변을 확인한다).
    const before = await browserFetch<EnrichmentReviewDetailResponse>(
      page,
      detailPath(ENRICHMENT, reviewId),
    );
    expect(before.status).toBe(200);
    const beforeVersion = before.body?.data.target.data_version ?? null;
    const beforeSources = before.body?.data.target.sources.length ?? null;

    const sizeWait = waitForListQuery(page, ENRICHMENT.listPath, {
      status: "pending",
      page_size: "200",
    });
    await page.getByLabel(ENRICHMENT.pageSizeLabel).selectOption("200");
    await sizeWait;

    const row = reviewRow(page, reviewId);
    await expect(row).toBeVisible(T);

    const decideWait = waitForApiResponse(
      page,
      "PATCH",
      detailPath(ENRICHMENT, reviewId),
    );
    await row.getByRole("button", { name: "reject" }).click();
    const decideResponse = await decideWait;
    expect(decideResponse.status()).toBe(200);
    const decideBody =
      (await decideResponse.json()) as EnrichmentReviewDecisionResponse;
    expect(decideBody.data).toMatchObject({
      review_id: reviewId,
      decision: "rejected",
      changed: true,
      applied: false,
    });
    // reject는 enrichment SourceLink를 적재하지 않는다.
    expect(decideBody.data.source_links_inserted ?? 0).toBe(0);

    await expect
      .poll(async () => {
        const after = await browserFetch<EnrichmentReviewListResponse>(
          page,
          `${ENRICHMENT.listPath}?status=pending&page_size=200&page=1`,
        );
        return (after.body?.data.items ?? []).some(
          (item) => item.review_id === reviewId,
        );
      }, T)
      .toBe(false);

    // 상세 status=rejected + target feature(version/sources) 불변.
    const after = await browserFetch<EnrichmentReviewDetailResponse>(
      page,
      detailPath(ENRICHMENT, reviewId),
    );
    expect(after.status).toBe(200);
    expect(after.body?.data.status).toBe("rejected");
    expect(after.body?.data.target.data_version ?? null).toBe(beforeVersion);
    expect(after.body?.data.target.sources.length ?? null).toBe(beforeSources);

    // 추가 불변 확인: 1차 feature 자체는 삭제/병합되지 않았다.
    const feature = await browserFetch<AdminFeatureDetailResponse>(
      page,
      `/v1/admin/features/${encodeURIComponent(targetFeatureId)}`,
    );
    if (feature.status === 200) {
      expect(["active", "inactive"]).toContain(
        feature.body?.data.feature.status,
      );
    }

    // UI 반영: pending 목록에서 사라지고 rejected 필터에서 다시 보인다.
    await expect(
      page.locator("tbody tr").filter({ hasText: reviewId.slice(0, 12) }),
    ).toHaveCount(0, { timeout: UI_TIMEOUT });

    // rejected는 비가역이라 누적되므로 target feature_id로 좁혀(검색: review/target/source)
    // 대상 review를 1페이지에 확실히 노출시킨다.
    await page.getByLabel(ENRICHMENT.searchLabel).fill(targetFeatureId);
    const rejectedWait = waitForListQuery(page, ENRICHMENT.listPath, {
      status: "rejected",
      q: targetFeatureId,
    });
    await page.getByLabel(ENRICHMENT.statusLabel).selectOption("rejected");
    await rejectedWait;
    const rejectedRow = reviewRow(page, reviewId);
    await expect(rejectedRow).toBeVisible(T);
    await expect(rejectedRow).toContainText(koStatus("rejected"));
  });
});

// ─── shared helpers for the DEEPENED scenarios below ────────────────────────

/** client `formatDistance` 미러 — 다이얼로그 distance 텍스트 단언에 사용. */
function fmtDistance(value: number | null | undefined): string {
  if (typeof value !== "number") return "-";
  if (value >= 1000) return `${(value / 1000).toFixed(2)}km`;
  return `${value.toFixed(1)}m`;
}

/**
 * 첫/마지막 페이지 버튼 aria-label. dedup은 surface 접두사("dedup …")가 붙고
 * enrichment는 접두사 없이 노출된다(컴포넌트 aria-label 그대로).
 */
const FIRST_LAST: Record<Surface["key"], { first: string; last: string }> = {
  dedup: { first: "dedup 첫 페이지", last: "dedup 마지막 페이지" },
  enrichment: { first: "첫 페이지", last: "마지막 페이지" },
};

/** 큐 행을 클릭해 상세 비교 다이얼로그를 열고, 그 단일-detail GET 응답을 돌려준다. */
async function openDetailDialog(
  page: Page,
  s: Surface,
  reviewId: string,
): Promise<Response> {
  const row = reviewRow(page, reviewId);
  await expect(row).toBeVisible(T);
  const detailWait = page.waitForResponse(
    (response) =>
      response.request().method() === "GET" &&
      apiPath(response).startsWith(`${s.listPath}/`),
    { timeout: FLOW_TIMEOUT },
  );
  // review id 셀(전파 O)을 직접 클릭 — dedup 첫 td(체크박스)·actions 셀은
  // stopPropagation 하므로 onRowClick 이 안 열린다.
  await row.getByText(reviewId.slice(0, 12)).first().click();
  const detailResponse = await detailWait;
  expect(detailResponse.status()).toBe(200);
  await expect(page.getByRole("dialog", { name: s.dialogName })).toBeVisible(T);
  return detailResponse;
}

/** assertScoreBand 호출마다 고유 q 토큰을 만들어 캐시 충돌(아래 설명)을 피한다. */
let scoreBandSeq = 0;

/**
 * score band 옵션을 골라 list GET 의 min_score/max_score 쿼리가 기대대로
 * (값 present / 미설정 시 absent) 직렬화되는지 단언한다. `null`은 "쿼리에 없음".
 *
 * `useDedupReviews`/`useEnrichmentReviews`는 `queryKey:[…, params]` + `staleTime:
 * 15_000`이라, score band를 'all'(min/max 없음)로 되돌리면 queryKey가 초기
 * gotoSurface 로드와 완전히 동일해져 react-query가 캐시로 응답하고 네트워크 요청을
 * 보내지 않는다 → waitForResponse가 5분 hang. 그래서 호출마다 고유 q 토큰을 함께
 * 입력해 queryKey를 항상 새로 만들고, 응답 매칭도 그 토큰으로 핀한다(q는 deferred라
 * 토큰+score가 모두 반영된 최종 요청을 기다린다).
 */
async function assertScoreBand(
  page: Page,
  s: Surface,
  option: "high" | "low" | "all",
  expectMin: string | null,
  expectMax: string | null,
): Promise<void> {
  const token = `${RUN_ID}-sb-${(scoreBandSeq += 1)}`;
  const wait = page.waitForResponse(
    (response) => {
      if (response.request().method() !== "GET") return false;
      if (apiPath(response) !== s.listPath) return false;
      const params = new URL(response.url()).searchParams;
      if (params.get("q") !== token) return false;
      const minOk =
        expectMin === null
          ? !params.has("min_score")
          : params.get("min_score") === expectMin;
      const maxOk =
        expectMax === null
          ? !params.has("max_score")
          : params.get("max_score") === expectMax;
      return minOk && maxOk;
    },
    { timeout: FLOW_TIMEOUT },
  );
  await page.getByLabel(s.searchLabel).fill(token);
  await page.getByLabel(s.scoreLabel).selectOption(option);
  const response = await wait;
  expect(response.status()).toBe(200);
  await expectEmptyOrTable(page, s);
}

/** 깊은 페이지네이션: page_size=25 로 페이지 수를 키우고 마지막↔첫 점프를 검증한다. */
async function runDeepPagination(page: Page, s: Surface): Promise<void> {
  await gotoSurface(page, s);
  const labels = FIRST_LAST[s.key];
  const sizeWait = waitForListQuery(page, s.listPath, {
    page_size: "25",
    page: "1",
  });
  await page.getByLabel(s.pageSizeLabel).selectOption("25");
  const sizeResp = await sizeWait;
  const body = (await sizeResp.json()) as
    | DedupReviewListResponse
    | EnrichmentReviewListResponse;
  const total = body.meta.page?.total ?? 0;
  const lastBtn = page.getByLabel(labels.last).first();
  const firstBtn = page.getByLabel(labels.first).first();

  if (total > 25) {
    const totalPages = Math.max(1, Math.ceil(total / 25));
    const lastWait = waitForListQuery(page, s.listPath, {
      page: String(totalPages),
      page_size: "25",
    }, UI_TIMEOUT).catch(() => null);
    await lastBtn.click();
    const lastResp = await lastWait;
    if (lastResp) expect(lastResp.status()).toBe(200);
    // 마지막 페이지에서 '다음'/'마지막'은 비활성.
    await expect(page.getByLabel(s.nextLabel).first()).toBeDisabled(T);
    await expect(lastBtn).toBeDisabled(T);

    const firstWait = waitForListQuery(page, s.listPath, {
      page: "1",
      page_size: "25",
    }, UI_TIMEOUT).catch(() => null);
    await firstBtn.click();
    const firstResp = await firstWait;
    if (firstResp) expect(firstResp.status()).toBe(200);
    // 첫 페이지에서 '이전'/'첫'은 비활성.
    await expect(page.getByLabel(s.prevLabel).first()).toBeDisabled(T);
    await expect(firstBtn).toBeDisabled(T);
  } else {
    // 단일/빈 페이지(PRESENCE 0) → 첫/마지막 모두 비활성.
    await expect(lastBtn).toBeDisabled(T);
    await expect(firstBtn).toBeDisabled(T);
  }
  await expectEmptyOrTable(page, s);
}

// ─── PART A+: extra filters + score-band 경계 (NOT gated) ────────────────────

test.describe("dedup + enrichment reviews — 추가 필터 + score-band 경계 (ungated)", () => {
  test("[dedup] kind/provider/dataset/category 필터가 각각 list GET 쿼리에 반영된다", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    await gotoSurface(page, DEDUP);

    await test.step("kind 필터(NativeSelect)가 kind 쿼리에 반영된다", async () => {
      const wait = waitForListQuery(page, DEDUP.listPath, { kind: "place" });
      await page.getByLabel("dedup kind").selectOption("place");
      expect((await wait).status()).toBe(200);
      await expectEmptyOrTable(page, DEDUP);
    });

    await test.step("provider 필터가 provider 쿼리에 반영된다", async () => {
      const wait = waitForListQuery(page, DEDUP.listPath, {
        provider: "datagokr",
      });
      await page.getByLabel("dedup provider").fill("datagokr");
      expect((await wait).status()).toBe(200);
      await expect(page.getByLabel("dedup provider")).toHaveValue("datagokr", T);
      await expectEmptyOrTable(page, DEDUP);
    });

    await test.step("dataset 필터가 dataset_key 쿼리에 반영된다", async () => {
      const wait = waitForListQuery(page, DEDUP.listPath, {
        dataset_key: "vworld",
      });
      await page.getByLabel("dedup dataset").fill("vworld");
      expect((await wait).status()).toBe(200);
      await expectEmptyOrTable(page, DEDUP);
    });

    const categoryCode = F.CATEGORY_CODES[0];
    await test.step("category 필터가 category 쿼리에 반영된다", async () => {
      const wait = waitForListQuery(page, DEDUP.listPath, {
        category: categoryCode,
      });
      await page.getByLabel("dedup category").fill(categoryCode);
      expect((await wait).status()).toBe(200);
      await expectEmptyOrTable(page, DEDUP);
    });
  });

  test("[enrichment] provider 필터가 list GET provider 쿼리에 반영된다", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    await gotoSurface(page, ENRICHMENT);
    const wait = waitForListQuery(page, ENRICHMENT.listPath, {
      provider: "visitkorea",
    });
    await page.getByLabel("enrichment provider").fill("visitkorea");
    expect((await wait).status()).toBe(200);
    await expect(page.getByLabel("enrichment provider")).toHaveValue(
      "visitkorea",
      T,
    );
    await expectEmptyOrTable(page, ENRICHMENT);
  });

  test("[dedup] score band 경계(high/low/all)가 min_score/max_score 쿼리에 정확히 직렬화된다", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    await gotoSurface(page, DEDUP);
    // high = min 90 / max 없음, low = max 70 / min 없음, all = 둘 다 없음.
    await assertScoreBand(page, DEDUP, "high", "90", null);
    await assertScoreBand(page, DEDUP, "low", null, "70");
    await assertScoreBand(page, DEDUP, "all", null, null);
  });

  test("[enrichment] score band 경계(high/low/all)가 min_score/max_score 쿼리에 정확히 직렬화된다", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    await gotoSurface(page, ENRICHMENT);
    await assertScoreBand(page, ENRICHMENT, "high", "90", null);
    await assertScoreBand(page, ENRICHMENT, "low", null, "70");
    await assertScoreBand(page, ENRICHMENT, "all", null, null);
  });
});

// ─── PART A+: 깊은 페이지네이션 (NOT gated) ──────────────────────────────────

test.describe("dedup + enrichment reviews — 깊은 페이지네이션 (ungated)", () => {
  test("[dedup] 마지막/첫 페이지 점프가 page 쿼리에 반영되거나 빈 큐에서 비활성이다", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    await runDeepPagination(page, DEDUP);
  });

  test("[enrichment] 마지막/첫 페이지 점프가 page 쿼리에 반영되거나 빈 큐에서 비활성이다", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    await runDeepPagination(page, ENRICHMENT);
  });
});

// ─── PART A+: 상세 비교 다이얼로그 필드 단위 (NOT gated) ─────────────────────

test.describe("dedup + enrichment reviews — 상세 비교 다이얼로그 필드 단위 (ungated)", () => {
  test("[dedup] 후보가 있으면 두 feature를 id/name/kind/status/origin/점수/거리/좌표까지 비교한다", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    await gotoSurface(page, DEDUP);
    const pending = await browserFetch<DedupReviewListResponse>(
      page,
      `${DEDUP.listPath}?status=pending&page_size=5&page=1`,
    );
    const items = pending.body?.data.items ?? [];
    test.skip(items.length === 0, "no pending dedup candidate");

    const detailResponse = await openDetailDialog(
      page,
      DEDUP,
      items[0].review_id,
    );
    const body = (await detailResponse.json()) as DedupReviewDetailResponse;
    const dialog = page.getByRole("dialog", { name: DEDUP.dialogName });
    const a = body.data.feature_a;
    const b = body.data.feature_b;

    // 두 feature id/name 동시 노출.
    await expect(dialog).toContainText(a.feature_id);
    await expect(dialog).toContainText(b.feature_id);
    await expect(dialog).toContainText(a.name);
    await expect(dialog).toContainText(b.name);
    // 점수 4종(formatScore=toFixed(1)) + 거리(formatDistance).
    await expect(dialog).toContainText(body.data.total_score.toFixed(1));
    await expect(dialog).toContainText(body.data.name_score.toFixed(1));
    await expect(dialog).toContainText(body.data.spatial_score.toFixed(1));
    await expect(dialog).toContainText(body.data.category_score.toFixed(1));
    if (typeof body.data.distance_m === "number") {
      await expect(dialog).toContainText(fmtDistance(body.data.distance_m));
    }
    // feature 별 kind/status/origin(+category) 필드 노출.
    for (const f of [a, b]) {
      await expect(dialog).toContainText(f.kind);
      // status는 다이얼로그에서 statusLabel(feature.status)로 한글 렌더된다(#600).
      await expect(dialog).toContainText(koStatus(f.status));
      await expect(dialog).toContainText(f.data_origin);
      if (f.category) await expect(dialog).toContainText(f.category);
      // 좌표 — 숫자일 때만 toFixed(6)으로 노출.
      if (typeof f.lon === "number") {
        await expect(dialog).toContainText(f.lon.toFixed(6));
      }
      if (typeof f.lat === "number") {
        await expect(dialog).toContainText(f.lat.toFixed(6));
      }
    }

    await dialog.getByRole("button", { name: "닫기" }).click();
    await expect(dialog).toBeHidden(T);
  });

  test("[enrichment] 후보가 있으면 1차(datagokr)/2차(visitkorea)를 필드 단위로 비교하고 audit select가 동작한다", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    await gotoSurface(page, ENRICHMENT);
    const pending = await browserFetch<EnrichmentReviewListResponse>(
      page,
      `${ENRICHMENT.listPath}?status=pending&page_size=5&page=1`,
    );
    const items = pending.body?.data.items ?? [];
    test.skip(items.length === 0, "no pending enrichment candidate");

    const detailResponse = await openDetailDialog(
      page,
      ENRICHMENT,
      items[0].review_id,
    );
    const body = (await detailResponse.json()) as EnrichmentReviewDetailResponse;
    const dialog = page.getByRole("dialog", { name: ENRICHMENT.dialogName });
    const t = body.data.target;
    const src = body.data.source;

    // 1차 target: id/name/kind/status(+category/좌표).
    await expect(dialog).toContainText(t.feature_id);
    await expect(dialog).toContainText(t.name);
    await expect(dialog).toContainText(t.kind);
    // status는 다이얼로그에서 statusLabel(target.status)로 한글 렌더된다(#600).
    await expect(dialog).toContainText(koStatus(t.status));
    if (t.category) await expect(dialog).toContainText(t.category);
    if (typeof t.lon === "number") {
      await expect(dialog).toContainText(t.lon.toFixed(6));
    }
    if (typeof t.lat === "number") {
      await expect(dialog).toContainText(t.lat.toFixed(6));
    }
    // 2차 source: provider/entity/dataset/record(+address/좌표).
    await expect(dialog).toContainText(src.provider);
    await expect(dialog).toContainText(src.source_entity_id);
    await expect(dialog).toContainText(src.dataset_key);
    await expect(dialog).toContainText(src.source_record_key);
    if (src.raw_address) await expect(dialog).toContainText(src.raw_address);
    if (typeof src.raw_longitude === "number") {
      await expect(dialog).toContainText(src.raw_longitude.toFixed(6));
    }
    if (typeof src.raw_latitude === "number") {
      await expect(dialog).toContainText(src.raw_latitude.toFixed(6));
    }
    // 점수(name=toFixed(1), distance score=spatial_score) + 거리 + audit default.
    await expect(dialog).toContainText(body.data.name_score.toFixed(1));
    if (typeof body.data.spatial_score === "number") {
      await expect(dialog).toContainText(body.data.spatial_score.toFixed(1));
    }
    if (typeof body.data.distance_m === "number") {
      await expect(dialog).toContainText(fmtDistance(body.data.distance_m));
    }
    await expect(dialog).toContainText(body.data.default_detail_source);

    // audit source select(입력측 — 실제 API 효과는 gated accept 테스트에서 검증).
    const audit = dialog.getByLabel("enrichment detail source audit note");
    await expect(audit).toBeVisible(T);
    await audit.selectOption("visitkorea");
    await expect(audit).toHaveValue("visitkorea", T);

    await dialog.getByRole("button", { name: "닫기" }).click();
    await expect(dialog).toBeHidden(T);
  });
});

// ─── PART C: real accept decision (GATED, IRREVERSIBLE — applies effects) ────

test.describe("dedup + enrichment reviews — real accept decision (gated)", () => {
  test("[dedup] PENDING 후보를 accept하면 status=accepted로 바뀌고 merge/feature는 불변이다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_REVIEW_ACCEPT,
      "E2E_REVIEW_ACCEPT=1 + E2E_REVIEW_DECIDE=1 + (E2E_ADMIN_WRITE|E2E_REVIEW_WRITE)=1일 때만 비가역 accept 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);
    test.info().annotations.push({ type: "run-id", description: RUN_ID });

    await gotoSurface(page, DEDUP);

    const pending = await browserFetch<DedupReviewListResponse>(
      page,
      `${DEDUP.listPath}?status=pending&page_size=1&page=1`,
    );
    const target = pending.body?.data.items?.[0];
    if (!target) {
      test.skip(true, "no pending dedup review candidate");
      return;
    }
    const reviewId = target.review_id;
    const featureAId = target.feature_a.feature_id;

    // baseline: dedup accept(=상태 전이)는 feature를 바꾸지 않아야 한다.
    const before = await browserFetch<DedupReviewDetailResponse>(
      page,
      detailPath(DEDUP, reviewId),
    );
    expect(before.status).toBe(200);
    const beforeVersion = before.body?.data.feature_a.data_version ?? null;
    const beforeUpdatedAt = before.body?.data.feature_a.updated_at ?? null;

    const sizeWait = waitForListQuery(page, DEDUP.listPath, {
      status: "pending",
      page_size: "200",
    });
    await page.getByLabel(DEDUP.pageSizeLabel).selectOption("200");
    await sizeWait;

    const row = reviewRow(page, reviewId);
    await expect(row).toBeVisible(T);

    const decideWait = waitForApiResponse(
      page,
      "PATCH",
      detailPath(DEDUP, reviewId),
    );
    await row.getByRole("button", { name: "accept", exact: true }).click();
    const decideResponse = await decideWait;
    expect(decideResponse.status()).toBe(200);
    const decideBody =
      (await decideResponse.json()) as DedupReviewDecisionResponse;
    expect(decideBody.data).toMatchObject({
      review_id: reviewId,
      decision: "accepted",
      changed: true,
    });
    // accept는 merge가 아니므로 master/loser/merge 이동이 없다(merge와 구분되는 핵심).
    expect(decideBody.data.master_feature_id ?? null).toBeNull();
    expect(decideBody.data.loser_feature_id ?? null).toBeNull();
    expect(decideBody.data.merge_id ?? null).toBeNull();
    expect(decideBody.data.source_links_moved ?? 0).toBe(0);

    // 백엔드 반영: pending 큐에서 제거.
    await expect
      .poll(async () => {
        const after = await browserFetch<DedupReviewListResponse>(
          page,
          `${DEDUP.listPath}?status=pending&page_size=200&page=1`,
        );
        return (after.body?.data.items ?? []).some(
          (item) => item.review_id === reviewId,
        );
      }, T)
      .toBe(false);

    // 상세 status=accepted + feature(A) data_version/updated_at 불변.
    const after = await browserFetch<DedupReviewDetailResponse>(
      page,
      detailPath(DEDUP, reviewId),
    );
    expect(after.status).toBe(200);
    expect(after.body?.data.status).toBe("accepted");
    expect(after.body?.data.feature_a.data_version ?? null).toBe(beforeVersion);
    expect(after.body?.data.feature_a.updated_at ?? null).toBe(beforeUpdatedAt);

    const feature = await browserFetch<AdminFeatureDetailResponse>(
      page,
      `/v1/admin/features/${encodeURIComponent(featureAId)}`,
    );
    if (feature.status === 200) {
      expect(["active", "inactive"]).toContain(
        feature.body?.data.feature.status,
      );
    }

    // UI 반영: pending에서 사라지고 accepted 필터에서 재노출.
    await expect(
      page.locator("tbody tr").filter({ hasText: reviewId.slice(0, 12) }),
    ).toHaveCount(0, { timeout: UI_TIMEOUT });

    await page.getByLabel(DEDUP.searchLabel).fill(featureAId);
    const acceptedWait = waitForListQuery(page, DEDUP.listPath, {
      status: "accepted",
      q: featureAId,
    });
    await page.getByLabel(DEDUP.statusLabel).selectOption("accepted");
    await acceptedWait;
    const acceptedRow = reviewRow(page, reviewId);
    await expect(acceptedRow).toBeVisible(T);
    await expect(acceptedRow).toContainText(koStatus("accepted"));
  });

  test("[enrichment] PENDING 후보를 accept하면 applied=true·source link가 적재되고 detail_source는 audit_only로 기록된다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_REVIEW_ACCEPT,
      "E2E_REVIEW_ACCEPT=1 + E2E_REVIEW_DECIDE=1 + (E2E_ADMIN_WRITE|E2E_REVIEW_WRITE)=1일 때만 비가역 accept 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);
    test.info().annotations.push({ type: "run-id", description: RUN_ID });

    await gotoSurface(page, ENRICHMENT);

    const pending = await browserFetch<EnrichmentReviewListResponse>(
      page,
      `${ENRICHMENT.listPath}?status=pending&page_size=1&page=1`,
    );
    const target = pending.body?.data.items?.[0];
    if (!target) {
      test.skip(true, "no pending enrichment review candidate");
      return;
    }
    const reviewId = target.review_id;
    const targetFeatureId = target.target_feature_id;

    // baseline: accept는 1차 target에 enrichment source link를 추가하므로
    // sources 길이 증가/해당 provider 존재를 확인한다.
    const before = await browserFetch<EnrichmentReviewDetailResponse>(
      page,
      detailPath(ENRICHMENT, reviewId),
    );
    expect(before.status).toBe(200);
    const beforeSources = before.body?.data.target.sources.length ?? 0;
    const sourceProvider = before.body?.data.source.provider ?? null;

    // 큐 행을 화면에 띄우고 상세 다이얼로그로 진입 — audit select 입력을 함께 검증한다.
    const sizeWait = waitForListQuery(page, ENRICHMENT.listPath, {
      status: "pending",
      page_size: "200",
    });
    await page.getByLabel(ENRICHMENT.pageSizeLabel).selectOption("200");
    await sizeWait;

    await openDetailDialog(page, ENRICHMENT, reviewId);
    const dialog = page.getByRole("dialog", { name: ENRICHMENT.dialogName });
    // visitkorea는 항상 활성(target은 target_detail_available 의존) → 선택값을
    // accept body의 selected_detail_source로 전달한다.
    await dialog
      .getByLabel("enrichment detail source audit note")
      .selectOption("visitkorea");

    const decideWait = waitForApiResponse(
      page,
      "PATCH",
      detailPath(ENRICHMENT, reviewId),
    );
    await dialog.getByRole("button", { name: "accept", exact: true }).click();
    const decideResponse = await decideWait;
    expect(decideResponse.status()).toBe(200);
    const decideBody =
      (await decideResponse.json()) as EnrichmentReviewDecisionResponse;
    expect(decideBody.data).toMatchObject({
      review_id: reviewId,
      decision: "accepted",
      changed: true,
      applied: true,
    });
    // accept는 보관된 SourceRecord를 복원해 ENRICHMENT SourceLink를 적재한다.
    expect(
      (decideBody.data.source_links_inserted ?? 0) +
        (decideBody.data.source_links_updated ?? 0),
    ).toBeGreaterThanOrEqual(1);
    // 선택한 detail source는 데이터 변경 없이 audit_only marker로만 기록된다.
    expect(decideBody.data.selected_detail_source ?? null).toBe("visitkorea");
    expect(decideBody.data.detail_source_effect).toBe("audit_only");

    // 백엔드 반영: pending 큐에서 제거.
    await expect
      .poll(async () => {
        const after = await browserFetch<EnrichmentReviewListResponse>(
          page,
          `${ENRICHMENT.listPath}?status=pending&page_size=200&page=1`,
        );
        return (after.body?.data.items ?? []).some(
          (item) => item.review_id === reviewId,
        );
      }, T)
      .toBe(false);

    // 상세 status=accepted + target feature에 source link가 적재됐다.
    const after = await browserFetch<EnrichmentReviewDetailResponse>(
      page,
      detailPath(ENRICHMENT, reviewId),
    );
    expect(after.status).toBe(200);
    expect(after.body?.data.status).toBe("accepted");
    const afterSources = after.body?.data.target.sources ?? [];
    expect(afterSources.length).toBeGreaterThanOrEqual(beforeSources);
    if (sourceProvider) {
      expect(
        afterSources.some((link) => link.provider === sourceProvider),
      ).toBe(true);
    }

    const feature = await browserFetch<AdminFeatureDetailResponse>(
      page,
      `/v1/admin/features/${encodeURIComponent(targetFeatureId)}`,
    );
    if (feature.status === 200) {
      expect(["active", "inactive"]).toContain(
        feature.body?.data.feature.status,
      );
    }

    // UI 반영: 다이얼로그 닫고 pending에서 사라지고 accepted 필터에서 재노출.
    if (await dialog.isVisible()) {
      await dialog.getByRole("button", { name: "닫기" }).click();
    }
    await expect(
      page.locator("tbody tr").filter({ hasText: reviewId.slice(0, 12) }),
    ).toHaveCount(0, { timeout: UI_TIMEOUT });

    await page.getByLabel(ENRICHMENT.searchLabel).fill(targetFeatureId);
    const acceptedWait = waitForListQuery(page, ENRICHMENT.listPath, {
      status: "accepted",
      q: targetFeatureId,
    });
    await page.getByLabel(ENRICHMENT.statusLabel).selectOption("accepted");
    await acceptedWait;
    const acceptedRow = reviewRow(page, reviewId);
    await expect(acceptedRow).toBeVisible(T);
    await expect(acceptedRow).toContainText(koStatus("accepted"));
  });
});
