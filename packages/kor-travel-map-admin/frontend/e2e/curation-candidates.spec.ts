import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";

type Candidate = components["schemas"]["AdminThemeCandidateView"];
type CandidateResponse = components["schemas"]["AdminThemeCandidateResponse"];
type CandidatePageResponse =
  components["schemas"]["AdminThemeCandidatePageResponse"];
type CandidateTransition =
  components["schemas"]["AdminThemeCandidateTransitionView"];
type CandidateTransitionPageResponse =
  components["schemas"]["AdminThemeCandidateTransitionPageResponse"];
type CandidateCommandResponse =
  components["schemas"]["ThemeCandidateCommandResponse"];
type Collection = components["schemas"]["AdminCurationCollectionView"];
type CollectionsResponse =
  components["schemas"]["AdminCurationCollectionsResponse"];
type Meta = components["schemas"]["Meta"];

const CANDIDATE_ID = "11111111-1111-4111-8111-111111111111";
const RULE_ID = "22222222-2222-4222-8222-222222222222";
const THEME_ID = "33333333-3333-4333-8333-333333333333";
const SOURCE_ID = "44444444-4444-4444-8444-444444444444";
const FEATURE_UUID = "55555555-5555-4555-8555-555555555555";
const COLLECTION_ID = "66666666-6666-4666-8666-666666666666";
const NOW = "2026-08-14T03:00:00.000Z";

function meta(requestId: string, withPage = false): Meta {
  return {
    duration_ms: 1,
    page: withPage
      ? { next_cursor: null, page_size: 50, total: 1 }
      : null,
    request_id: requestId,
  };
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType:
      status >= 400 ? "application/problem+json" : "application/json",
    status,
  });
}

function candidate(overrides: Partial<Candidate> = {}): Candidate {
  return {
    candidate_etag: '"3"',
    candidate_id: CANDIDATE_ID,
    candidate_input_hash: "a".repeat(64),
    candidate_revision: "3",
    created_at: NOW,
    disposition: "active",
    eligibility_present: true,
    feature_category: "01070300",
    feature_detail: { place: { description: "한강과 도심을 잇는 공원" } },
    feature_id: "mcst::tourism::yeouido",
    feature_kind: "place",
    feature_name: "여의도공원",
    feature_row_revision: "12",
    feature_uuid: FEATURE_UUID,
    lifecycle_state: "active",
    match_evidence: { confidence: 92, match_method: "exact" },
    proposal_summary: "서울 도심 산책 후보",
    proposal_title: "여의도공원 산책",
    provider_dataset_id: 701,
    publication_state: "published",
    quality_state: "valid",
    rank_score: "92.50",
    representation_etag: '"sha256:representation"',
    review_state: "open",
    rule_id: RULE_ID,
    rule_input_hash: "b".repeat(64),
    rule_row_revision: "4",
    source_entity_key: "mcst::tourism::yeouido",
    source_id: SOURCE_ID,
    source_name: "문화체육관광부 관광 후보",
    source_record_hash: "c".repeat(64),
    source_record_key: "mcst::tourism::yeouido::2026",
    theme_id: THEME_ID,
    theme_name: "도심 산책",
    theme_slug: "urban-walk",
    updated_at: NOW,
    ...overrides,
  };
}

function collection(): Collection {
  return {
    archived_at: null,
    collection_id: COLLECTION_ID,
    collection_key: "urban-walk-2026",
    command_etag: '"5"',
    created_at: NOW,
    created_by: "admin:e2e",
    dataset_key: null,
    description: "도심 산책 컬렉션",
    edition_key: "2026",
    item_count: 1,
    metadata: {},
    provider: null,
    provider_dataset_id: null,
    public_item_count: 1,
    row_revision: "5",
    source_id: null,
    source_name: null,
    source_url: null,
    status: "published",
    theme_group: "산책",
    theme_id: THEME_ID,
    theme_name: "도심 산책",
    theme_slug: "urban-walk",
    title: "2026 도심 산책",
    updated_at: NOW,
    updated_by: "admin:e2e",
    visibility: "public",
  };
}

function transition(): CandidateTransition {
  return {
    actor: "provider:mcst",
    candidate_id: CANDIDATE_ID,
    candidate_revision: "1",
    causation_ref: { generation_id: "1" },
    command_id: null,
    from_eligibility_present: null,
    from_review_state: null,
    generation_id: "1",
    occurred_at: NOW,
    reason_code: "provider_materialize",
    to_eligibility_present: true,
    to_review_state: "open",
    transition_id: "10",
    transition_kind: "eligibility_materialize",
  };
}

function commandResponse(
  state: "promoted" | "rejected",
): CandidateCommandResponse {
  return {
    data: {
      candidate_id: CANDIDATE_ID,
      candidate_revision: "4",
      curation_item_id:
        state === "promoted" ? "77777777-7777-4777-8777-777777777777" : null,
      curation_item_revision: state === "promoted" ? "1" : null,
      transition_id: state === "promoted" ? "11" : "12",
    },
    meta: meta(`e2e-candidate-${state}`),
  };
}

async function installCandidateRoutes(
  page: Page,
  options: { rejectStatus?: number } = {},
) {
  let current = candidate();
  const requests = {
    detailGets: 0,
    promote: 0,
    reject: 0,
  };

  await page.route("**/api/proxy/v1/admin/curations**", (route) => {
    const response: CollectionsResponse = {
      data: { items: [collection()] },
      meta: meta("e2e-candidate-collections", true),
    };
    return fulfillJson(route, response);
  });
  await page.route(
    "**/api/proxy/v1/admin/theme-feature-candidates**",
    async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname.replace("/api/proxy", "");
      if (request.method() === "POST" && path.endsWith("/promote")) {
        requests.promote += 1;
        expect(request.headers()["if-match"]).toBe('"3"');
        expect(request.headers()["idempotency-key"]).toMatch(
          /^[0-9a-f-]{36}$/,
        );
        const body = request.postDataJSON() as Record<string, unknown>;
        expect(body.collection_id).toBe(COLLECTION_ID);
        expect(body.collection_revision).toBe("5");
        current = candidate({
          candidate_etag: '"4"',
          candidate_revision: "4",
          review_state: "promoted",
        });
        return fulfillJson(route, commandResponse("promoted"));
      }
      if (request.method() === "POST" && path.endsWith("/reject")) {
        requests.reject += 1;
        expect(request.headers()["if-match"]).toBe('"3"');
        if (options.rejectStatus) {
          return fulfillJson(
            route,
            {
              code: "PRECONDITION_FAILED",
              detail: "candidate revision changed",
              errors: [],
              request_id: "e2e-candidate-stale",
              status: options.rejectStatus,
              title: "Precondition failed",
              type: "https://kor-travel-map/errors/precondition-failed",
            },
            options.rejectStatus,
          );
        }
        current = candidate({
          candidate_etag: '"4"',
          candidate_revision: "4",
          review_state: "rejected",
        });
        return fulfillJson(route, commandResponse("rejected"));
      }
      if (path.endsWith("/transitions")) {
        const response: CandidateTransitionPageResponse = {
          data: { items: [transition()] },
          meta: meta("e2e-candidate-transitions", true),
        };
        return fulfillJson(route, response);
      }
      if (path.endsWith(`/${CANDIDATE_ID}`)) {
        requests.detailGets += 1;
        const response: CandidateResponse = {
          data: current,
          meta: meta("e2e-candidate-detail"),
        };
        return fulfillJson(route, response);
      }
      const response: CandidatePageResponse = {
        data: { items: [current] },
        meta: meta("e2e-candidate-list", true),
      };
      return fulfillJson(route, response);
    },
  );
  return requests;
}

test.describe("큐레이션 후보 검토", () => {
  test("현재 CAS로 후보를 canonical collection에 승격한다", async ({ page }) => {
    const requests = await installCandidateRoutes(page);
    await page.goto("/admin/curations/candidates");

    await expect(page.getByRole("heading", { name: "큐레이션 후보 검토" })).toBeVisible();
    await page.getByText("여의도공원 산책", { exact: true }).click();
    await expect(page.getByText("immutable candidate transition timeline입니다.")).toBeVisible();
    await expect(page.getByText("provider:mcst")).toBeVisible();

    await page.getByRole("button", { name: "승격 확정" }).click();

    await expect(
      page.getByText("후보를 canonical collection item으로 승격했습니다."),
    ).toBeVisible();
    expect(requests.promote).toBe(1);
  });

  test("stale CAS는 자동 재시도하지 않고 명시적 reload를 요구한다", async ({ page }) => {
    const requests = await installCandidateRoutes(page, { rejectStatus: 412 });
    await page.goto("/admin/curations/candidates");
    await page.getByText("여의도공원 산책", { exact: true }).click();

    await page.getByRole("button", { name: "거절 확정" }).click();

    await expect(
      page.getByText(
        "후보 또는 컬렉션이 다른 작업으로 변경되었습니다. 현재 상태를 다시 불러온 뒤 판단하세요.",
      ),
    ).toBeVisible();
    expect(requests.reject).toBe(1);
    const detailGetsBeforeReload = requests.detailGets;

    await page.getByRole("button", { name: "현재 상태 다시 불러오기" }).click();
    await expect.poll(() => requests.detailGets).toBeGreaterThan(detailGetsBeforeReload);
    expect(requests.reject).toBe(1);
  });
});
