import { expect, test, type Locator, type Page, type Response } from "@playwright/test";

import type { components } from "../../src/api/types";
import * as F from "./_fixtures";

type AdminFeatureChangeResponse =
  components["schemas"]["AdminFeatureChangeResponse"];
type AdminFeatureDeactivateResponse =
  components["schemas"]["AdminFeatureDeactivateResponse"];
type AdminFeatureDetailResponse =
  components["schemas"]["AdminFeatureDetailResponse"];
type FeatureDetailEnvelopeResponse =
  components["schemas"]["FeatureDetailEnvelopeResponse"];

type BrowserFetchResult<T> = {
  body: T | null;
  status: number;
  text: string;
};

const UI_TIMEOUT = 15_000;
const FLOW_TIMEOUT = 5 * 60 * 1000;
const T = { timeout: UI_TIMEOUT } as const;

const RUN_ID = `live-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
const FEATURE_ID = `user_request::e2e_admin_features::${RUN_ID}`;
const CREATE_NAME = `E2E Admin Feature ${RUN_ID}`;
const UPDATED_NAME = `E2E Admin Feature ${RUN_ID} updated`;
const REJECTED_NAME = `E2E Admin Feature ${RUN_ID} rejected`;
const BASE_REASON = `live ui e2e admin features ${RUN_ID}`;
const EXECUTE_ADMIN_FEATURES_WRITE =
  process.env.E2E_ADMIN_WRITE === "1" ||
  process.env.E2E_ADMIN_FEATURES_WRITE === "1";
const CHANGE_FORM_STATUSES = ["draft", "active", "inactive", "hidden"] as const;
const CHANGE_FORM_KINDS = ["place", "event"] as const;

test.describe.configure({ mode: "serial" });

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function fieldText(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return "";
}

function coordText(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toFixed(6)
    : "";
}

function dateTimeLocalText(value: unknown): string {
  const text = fieldText(value);
  if (text.length === 0) return "";
  const match = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/.exec(text);
  return match ? `${match[1]}T${match[2]}` : text;
}

function recordField(
  value: Record<string, unknown>,
  key: string,
): unknown {
  return value[key];
}

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

function adminFeaturePath(featureId: string): string {
  return `/v1/admin/features/${encodeURIComponent(featureId)}`;
}

function publicFeaturePath(featureId: string): string {
  return `/v1/features/${encodeURIComponent(featureId)}`;
}

function changeApprovePath(requestId: string): string {
  return `/v1/admin/features/change-requests/${encodeURIComponent(
    requestId,
  )}/approve`;
}

function changeRejectPath(requestId: string): string {
  return `/v1/admin/features/change-requests/${encodeURIComponent(
    requestId,
  )}/reject`;
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

async function readChangeResponse(
  response: Response,
): Promise<AdminFeatureChangeResponse> {
  expect(response.status()).toBe(200);
  return (await response.json()) as AdminFeatureChangeResponse;
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

async function fetchAdminFeature(
  page: Page,
  featureId: string,
): Promise<BrowserFetchResult<AdminFeatureDetailResponse>> {
  return browserFetch<AdminFeatureDetailResponse>(
    page,
    adminFeaturePath(featureId),
  );
}

async function fetchPublicFeature(
  page: Page,
  featureId: string,
): Promise<BrowserFetchResult<FeatureDetailEnvelopeResponse>> {
  return browserFetch<FeatureDetailEnvelopeResponse>(
    page,
    publicFeaturePath(featureId),
  );
}

async function expectAdminFeature(
  page: Page,
  featureId: string,
): Promise<AdminFeatureDetailResponse> {
  const response = await fetchAdminFeature(page, featureId);
  expect(response.status).toBe(200);
  expect(response.body).not.toBeNull();
  return response.body as AdminFeatureDetailResponse;
}

async function expectPublicFeature(
  page: Page,
  featureId: string,
): Promise<FeatureDetailEnvelopeResponse> {
  const response = await fetchPublicFeature(page, featureId);
  expect(response.status).toBe(200);
  expect(response.body).not.toBeNull();
  return response.body as FeatureDetailEnvelopeResponse;
}

async function expectOptionalFieldValue(
  page: Page,
  label: string,
  value: unknown,
): Promise<void> {
  const locator = page.getByLabel(label, { exact: true });
  await expect(locator).toBeVisible(T);
  const expected = fieldText(value);
  if (expected.length > 0) {
    await expect(locator).toHaveValue(expected);
  }
}

async function expectFeaturePrefillLoaded(
  page: Page,
  featureId: string,
): Promise<void> {
  const response = await expectAdminFeature(page, featureId);
  const feature = response.data.feature;
  const address = feature.address;
  const detail = feature.detail;
  const urls = feature.urls;

  await expect(page.getByText("데이터 로드됨")).toBeVisible(T);
  await expect(page.getByLabel("change feature id")).toHaveValue(featureId);
  await expect(page.getByLabel("change name")).toHaveValue(feature.name);
  await expect(page.getByLabel("change category")).toHaveValue(feature.category);

  if (CHANGE_FORM_KINDS.includes(feature.kind as (typeof CHANGE_FORM_KINDS)[number])) {
    await expect(page.getByLabel("change kind", { exact: true })).toHaveValue(
      feature.kind,
    );
  }
  if (
    CHANGE_FORM_STATUSES.includes(
      feature.status as (typeof CHANGE_FORM_STATUSES)[number],
    )
  ) {
    await expect(
      page.getByLabel("change feature status", { exact: true }),
    ).toHaveValue(feature.status);
  }

  const lon = coordText(feature.lon);
  const lat = coordText(feature.lat);
  if (lon.length > 0) {
    await expect(page.getByLabel("change lon")).toHaveValue(lon);
  }
  if (lat.length > 0) {
    await expect(page.getByLabel("change lat")).toHaveValue(lat);
  }

  await expectOptionalFieldValue(page, "change marker icon", feature.marker_icon);
  await expectOptionalFieldValue(page, "change marker color", feature.marker_color);
  await expectOptionalFieldValue(page, "change sigungu code", feature.sigungu_code);
  await expectOptionalFieldValue(
    page,
    "change parent feature id",
    feature.parent_feature_id,
  );
  await expectOptionalFieldValue(
    page,
    "change sibling group id",
    feature.sibling_group_id,
  );
  await expectOptionalFieldValue(
    page,
    "change coord precision digits",
    feature.coord_precision_digits,
  );

  await expectOptionalFieldValue(page, "change road address", recordField(address, "road"));
  await expectOptionalFieldValue(page, "change legal address", recordField(address, "legal"));
  await expectOptionalFieldValue(page, "change admin address", recordField(address, "admin"));
  await expectOptionalFieldValue(
    page,
    "change sido code",
    feature.sido_code ?? recordField(address, "sido_code"),
  );
  await expectOptionalFieldValue(
    page,
    "change legal dong code",
    feature.legal_dong_code ??
      recordField(address, "bjd_code") ??
      recordField(address, "legal_dong_code"),
  );
  await expectOptionalFieldValue(
    page,
    "change admin dong code",
    feature.admin_dong_code ?? recordField(address, "admin_dong_code"),
  );
  await expectOptionalFieldValue(
    page,
    "change road name code",
    feature.road_name_code ?? recordField(address, "road_name_code"),
  );
  await expectOptionalFieldValue(
    page,
    "change road address management no",
    feature.road_address_management_no ??
      recordField(address, "road_address_management_no"),
  );

  await expectOptionalFieldValue(page, "change phone", recordField(detail, "phone"));
  await expectOptionalFieldValue(
    page,
    "change place kind",
    recordField(detail, "place_kind"),
  );
  await expectOptionalFieldValue(
    page,
    "change homepage url",
    recordField(urls, "homepage"),
  );
  await expectOptionalFieldValue(page, "change source url", recordField(urls, "source"));

  if (feature.kind === "event") {
    await expectOptionalFieldValue(
      page,
      "change event status",
      recordField(detail, "event_status"),
    );
    const startDate = dateTimeLocalText(recordField(detail, "starts_at"));
    const endDate = dateTimeLocalText(recordField(detail, "ends_at"));
    await expect(page.getByLabel("change event start", { exact: true })).toBeVisible(
      T,
    );
    await expect(page.getByLabel("change event end", { exact: true })).toBeVisible(
      T,
    );
    if (startDate.length > 0) {
      await expect(page.getByLabel("change event start", { exact: true })).toHaveValue(
        startDate,
      );
    }
    if (endDate.length > 0) {
      await expect(page.getByLabel("change event end", { exact: true })).toHaveValue(
        endDate,
      );
    }
    await expectOptionalFieldValue(
      page,
      "change organizer",
      recordField(detail, "organizer"),
    );
    await expectOptionalFieldValue(page, "change venue", recordField(detail, "venue"));
  }
}

async function expectChangeRequestsReady(page: Page): Promise<void> {
  await expect(
    page.getByRole("heading", { level: 1, name: "Feature 변경" }),
  ).toBeVisible(T);
  await expect(page.getByText("Feature 변경 요청")).toBeVisible(T);
}

async function expectChangeReviewsReady(page: Page): Promise<void> {
  await expect(
    page.getByRole("heading", { level: 1, name: "Feature 검수" }),
  ).toBeVisible(T);
  await expect(page.getByRole("table")).toBeVisible(T);
  await expect(page.getByText("요청 행을 선택하면")).toBeVisible(T);
}

async function gotoChangeRequests(page: Page): Promise<void> {
  await page.goto("/admin/features/change-requests");
  await expectChangeRequestsReady(page);
}

async function gotoChangeReviews(page: Page): Promise<void> {
  await page.goto("/admin/features/change-reviews");
  await expectChangeReviewsReady(page);
}

async function expectAdminFeaturesReady(page: Page): Promise<void> {
  await expect(
    page.getByRole("heading", { level: 1, name: "Feature 목록" }),
  ).toBeVisible(T);
  await expect(page.getByRole("table")).toBeVisible(T);
}

async function gotoAdminFeatures(page: Page): Promise<void> {
  await page.goto("/admin/features");
  await expectAdminFeaturesReady(page);
}

async function setChangeFilters(
  page: Page,
  options: {
    action?: "all" | "add" | "update" | "delete";
    q?: string;
    status?: "all" | "pending" | "applied" | "rejected";
  },
): Promise<void> {
  if (options.status) {
    await page
      .getByLabel("change status", { exact: true })
      .selectOption(options.status);
  }
  if (options.action) {
    await page.getByLabel("change action filter").selectOption(options.action);
  }
  if (options.q !== undefined) {
    await page.getByLabel("change search").fill(options.q);
  }
}

function rowContaining(page: Page, text: string): Locator {
  return page.getByRole("row", {
    name: new RegExp(escapeRegExp(text)),
  });
}

async function selectPreferredOption(
  select: Locator,
  preferredValue: string,
): Promise<string> {
  await expect
    .poll(async () => select.locator("option").count(), T)
    .toBeGreaterThan(0);
  const values = await select.locator("option").evaluateAll((options) =>
    options
      .map((option) => (option as HTMLOptionElement).value)
      .filter((value) => value.length > 0),
  );
  const value = values.includes(preferredValue) ? preferredValue : values[0];
  expect(value).toBeDefined();
  await select.selectOption(value);
  return value;
}

async function longPressAtCenter(page: Page, locator: Locator): Promise<void> {
  const box = await locator.boundingBox();
  expect(box).not.toBeNull();
  if (!box) return;
  const point = {
    x: box.x + box.width / 2,
    y: box.y + box.height / 2,
  };
  await locator.evaluate((node, currentPoint) => {
    node.dispatchEvent(
      new PointerEvent("pointerdown", {
        bubbles: true,
        cancelable: true,
        clientX: currentPoint.x,
        clientY: currentPoint.y,
        isPrimary: true,
        pointerId: 31,
        pointerType: "touch",
      }),
    );
  }, point);
  await page.waitForTimeout(700);
  await locator.evaluate((node, currentPoint) => {
    node.dispatchEvent(
      new PointerEvent("pointerup", {
        bubbles: true,
        cancelable: true,
        clientX: currentPoint.x,
        clientY: currentPoint.y,
        isPrimary: true,
        pointerId: 31,
        pointerType: "touch",
      }),
    );
  }, point);
}

function changeRequestDetail(page: Page): Locator {
  return page.locator("aside").filter({ hasText: "Request detail" });
}

async function approveVisibleRequest(
  page: Page,
  row: Locator,
  requestId: string,
): Promise<AdminFeatureChangeResponse> {
  const responsePromise = waitForApiResponse(
    page,
    "POST",
    decodeURIComponent(changeApprovePath(requestId)),
  );
  await row.getByRole("button", { name: "approve" }).click();
  return readChangeResponse(await responsePromise);
}

async function rejectVisibleRequest(
  page: Page,
  row: Locator,
  requestId: string,
): Promise<AdminFeatureChangeResponse> {
  const responsePromise = waitForApiResponse(
    page,
    "POST",
    decodeURIComponent(changeRejectPath(requestId)),
  );
  await row.getByRole("button", { name: "reject" }).click();
  return readChangeResponse(await responsePromise);
}

async function rejectChangeRequestByApi(
  page: Page,
  requestId: string,
): Promise<void> {
  await browserFetch<AdminFeatureChangeResponse>(
    page,
    changeRejectPath(requestId),
    {
      body: { operator: "local-admin", reason: `${BASE_REASON} cleanup reject` },
      method: "POST",
    },
  );
}

async function approveChangeRequestByApi(
  page: Page,
  requestId: string,
): Promise<void> {
  await browserFetch<AdminFeatureChangeResponse>(
    page,
    changeApprovePath(requestId),
    {
      body: { operator: "local-admin", reason: `${BASE_REASON} cleanup approve` },
      method: "POST",
    },
  );
}

async function cleanupFeatureByApi(
  page: Page,
  featureId: string,
  deleteRequestId: string | null,
): Promise<void> {
  if (deleteRequestId) {
    await approveChangeRequestByApi(page, deleteRequestId);
  }

  const current = await fetchAdminFeature(page, featureId);
  if (current.status !== 200 || current.body?.data.feature.status === "deleted") {
    return;
  }

  const deleteResponse = await browserFetch<AdminFeatureChangeResponse>(
    page,
    adminFeaturePath(featureId),
    {
      body: { operator: "local-admin", reason: `${BASE_REASON} cleanup delete` },
      method: "DELETE",
    },
  );
  const request = deleteResponse.body?.data.request;
  if (deleteResponse.status === 200 && request?.status === "pending") {
    await approveChangeRequestByApi(page, request.request_id);
  }
}

test.describe("/admin/features + feature change requests live write workflow", () => {
  test("change request edit UI exposes catalog dropdowns, sigungu lookup, map dialog, and admin detail prefill", async ({
    page,
  }) => {
    test.setTimeout(90_000);

    await test.step("change request 폼의 dropdown 계약을 확인한다", async () => {
      await gotoChangeRequests(page);
      await expect(page.getByLabel("change action", { exact: true })).toBeVisible(T);
      await expect(page.getByLabel("change category")).toBeVisible(T);
      await expect(page.getByLabel("change marker icon")).toBeVisible(T);
      await expect(page.getByLabel("change marker color")).toBeVisible(T);
      await expect(page.getByRole("button", { name: "위치 편집" })).toBeVisible(T);

      await selectPreferredOption(page.getByLabel("change category"), "01070300");
      await page.getByLabel("change marker icon").selectOption("museum");
      await page.getByLabel("change marker color").selectOption("P-02");
      await expect(page.getByLabel("change marker color")).toHaveValue("P-02");
    });

    await test.step("sigungu_code 입력이 geocoder 후보와 실제 코드 표시를 갱신한다", async () => {
      await page.getByLabel("change sigungu code").fill("11680");
      await expect(
        page
          .getByText(/서울특별시 강남구.*11680|11680.*서울특별시 강남구/)
          .first(),
      ).toBeVisible({ timeout: 30_000 });

      await page.getByLabel("change sigungu code").fill("강남");
      await expect(
        page
          .getByText(/서울특별시 강남구.*11680|11680.*서울특별시 강남구/)
          .first(),
      ).toBeVisible({ timeout: 30_000 });
    });

    await test.step("위치/마커 다이얼로그가 취소/적용과 모바일 오래누르기 선택을 제공한다", async () => {
      await page.getByLabel("change lon").fill("126.978000");
      await page.getByLabel("change lat").fill("37.566500");
      await page.getByLabel("change sigungu code").fill("");
      await page.getByRole("button", { name: "위치 편집" }).click();
      const dialog = page.getByRole("dialog", { name: "위치/마커 편집" });
      await expect(dialog).toBeVisible(T);
      const map = dialog.getByTestId("feature-change-location-map");
      await expect(map).toBeVisible(T);
      await map.locator("canvas").first().waitFor({ state: "visible" });
      await dialog.getByLabel("marker_icon", { exact: true }).selectOption("park");
      await dialog.getByLabel("marker_color", { exact: true }).selectOption("P-03");
      await expect(dialog.getByLabel("marker_color", { exact: true })).toHaveValue(
        "P-03",
      );
      await dialog.getByLabel("lon", { exact: true }).fill("127.123456");
      const firstMapBox = await map.boundingBox();
      expect(firstMapBox).not.toBeNull();
      if (firstMapBox) {
        await page.mouse.click(
          firstMapBox.x + firstMapBox.width / 2,
          firstMapBox.y + firstMapBox.height / 2,
          { button: "right" },
        );
      }
      await dialog.getByRole("button", { name: "취소" }).click();
      await expect(dialog).toHaveCount(0);
      await expect(page.getByLabel("change lon")).toHaveValue("126.978000");
      await expect(page.getByLabel("change marker icon")).toHaveValue("museum");
      await expect(page.getByLabel("change marker color")).toHaveValue("P-02");

      await page.getByRole("button", { name: "위치 편집" }).click();
      await expect(dialog).toBeVisible(T);
      await map.locator("canvas").first().waitFor({ state: "visible" });
      await dialog.getByLabel("marker_icon", { exact: true }).selectOption("park");
      await dialog.getByLabel("marker_color", { exact: true }).selectOption("P-03");
      await expect(dialog.getByLabel("marker_color", { exact: true })).toHaveValue(
        "P-03",
      );

      await longPressAtCenter(page, map);
      await expect
        .poll(
          async () =>
            dialog.getByLabel("sigungu_code", { exact: true }).inputValue(),
          { timeout: 30_000 },
        )
        .toMatch(/^\d{5}$/);
      await expect(dialog.getByText(/· \d{5}/).first()).toBeVisible(T);
      await dialog.getByRole("button", { name: "적용" }).click();
      await expect(dialog).toHaveCount(0);
      await expect(page.getByLabel("change marker icon")).toHaveValue("park");
      await expect(page.getByLabel("change marker color")).toHaveValue("P-03");
      await expect
        .poll(async () => page.getByLabel("change sigungu code").inputValue(), T)
        .toMatch(/^\d{5}$/);
    });

    await test.step("admin features detail의 편집 링크가 change request prefill로 이어진다", async () => {
      const sampleFeatureId = F.FEATURE_IDS[0];
      test.skip(!sampleFeatureId, "live fixture FEATURE_IDS가 비어 있어 prefill 링크를 확인할 수 없음");
      await gotoAdminFeatures(page);
      await page.getByLabel("feature search").fill(sampleFeatureId);
      const row = rowContaining(page, sampleFeatureId.slice(0, 18));
      await expect(row).toBeVisible(T);
      await row.getByRole("button", { name: "preview" }).click();
      await expect(page.getByText(sampleFeatureId, { exact: true })).toBeVisible(T);

      await page.getByRole("link", { name: "편집" }).click();
      await expect(page).toHaveURL(/\/admin\/features\/change-requests\?.*action=update/, T);
      await expect(page.getByLabel("change action", { exact: true })).toHaveValue(
        "update",
      );
      await expectFeaturePrefillLoaded(page, sampleFeatureId);
    });

    await test.step("feature 상세 페이지의 수정 링크도 change request prefill을 로드한다", async () => {
      const sampleFeatureId = F.FEATURE_IDS[0];
      test.skip(!sampleFeatureId, "live fixture FEATURE_IDS가 비어 있어 prefill 링크를 확인할 수 없음");
      await page.goto(`/features/${encodeURIComponent(sampleFeatureId)}`);
      await expect(
        page.getByRole("heading", { level: 1, name: "Feature 상세" }),
      ).toBeVisible(T);
      await expect(page.getByTestId("feature-detail-view")).toBeVisible(T);

      await page.getByRole("link", { name: "수정" }).click();
      await expect(page).toHaveURL(/\/admin\/features\/change-requests\?.*action=update/, T);
      await expect(page.getByLabel("change action", { exact: true })).toHaveValue(
        "update",
      );
      await expectFeaturePrefillLoaded(page, sampleFeatureId);
    });
  });

  test("새 작성, 승인, 목록/상세 반영, 수정 승인/거절, 비활성화, 삭제 승인까지 실제 서비스에 반영된다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_ADMIN_FEATURES_WRITE,
      "E2E_ADMIN_FEATURES_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 feature write flow를 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    let addRequestId: string | null = null;
    let addApproved = false;
    let updateRequestId: string | null = null;
    let rejectedUpdateRequestId: string | null = null;
    let deleteRequestId: string | null = null;
    let deleted = false;

    try {
      await test.step("change request 화면의 읽기/필터/폼 표면을 확인한다", async () => {
        await gotoChangeRequests(page);
        await expect(page.getByLabel("change action", { exact: true })).toBeVisible(T);
        await expect(page.getByLabel("change feature id", { exact: true })).toBeVisible(T);
        await expect(page.getByLabel("change reason", { exact: true })).toBeVisible(T);
        await expect(page.getByLabel("change operator", { exact: true })).toBeVisible(T);
        await expect(page.getByLabel("change name", { exact: true })).toBeVisible(T);
        await expect(page.getByLabel("change category", { exact: true })).toBeVisible(T);
        await expect(page.getByLabel("change lon", { exact: true })).toBeVisible(T);
        await expect(page.getByLabel("change lat", { exact: true })).toBeVisible(T);
        await expect(page.getByLabel("change parent feature id", { exact: true })).toBeVisible(T);
        await expect(page.getByLabel("change sibling group id", { exact: true })).toBeVisible(T);
        await expect(page.getByLabel("change coord precision digits", { exact: true })).toBeVisible(T);
        await expect(page.getByLabel("change road address", { exact: true })).toBeVisible(T);
        await expect(page.getByLabel("change legal address", { exact: true })).toBeVisible(T);
        await expect(page.getByLabel("change admin address", { exact: true })).toBeVisible(T);
        await expect(page.getByLabel("change sido code", { exact: true })).toBeVisible(T);
        await expect(page.getByLabel("change legal dong code", { exact: true })).toBeVisible(T);
        await expect(page.getByLabel("change admin dong code", { exact: true })).toBeVisible(T);
        await expect(page.getByLabel("change road name code", { exact: true })).toBeVisible(T);
        await expect(
          page.getByLabel("change road address management no", { exact: true }),
        ).toBeVisible(T);
        await expect(page.getByLabel("change phone", { exact: true })).toBeVisible(T);
        await expect(page.getByLabel("change place kind", { exact: true })).toBeVisible(T);
        await expect(page.getByLabel("change homepage url", { exact: true })).toBeVisible(T);
        await expect(page.getByLabel("change source url", { exact: true })).toBeVisible(T);
        await expect(page.getByLabel("change detail JSON", { exact: true })).toBeVisible(T);
        await expect(page.getByLabel("change urls JSON", { exact: true })).toBeVisible(T);
        await expect(page.getByLabel("change address JSON", { exact: true })).toBeVisible(T);

        await gotoChangeReviews(page);
        await expect(page.getByText("review mode")).toBeVisible(T);
        await expect(page.getByText("require_review")).toBeVisible(T);
        await page.getByLabel("change page size").selectOption("25");
        await expect(page.getByLabel("change page size")).toHaveValue("25");
        await page.getByLabel("change action filter").selectOption("all");
        await page.getByLabel("change status", { exact: true }).selectOption("all");
        await expect(page.getByRole("table")).toBeVisible(T);
      });

      await test.step("/admin/features/new에서 실제 add change request를 생성한다", async () => {
        await page.goto("/admin/features/new");
        await expect(
          page.getByRole("heading", { level: 1, name: "새 피처" }),
        ).toBeVisible(T);

        await page.getByLabel("이름", { exact: true }).fill(CREATE_NAME);
        await page.getByLabel("카테고리", { exact: true }).fill("01070300");
        await page.getByLabel("경도", { exact: true }).fill("126.97841");
        await page.getByLabel("위도", { exact: true }).fill("37.56668");
        await page.getByLabel("marker_icon").fill("marker");
        await page.getByLabel("marker_color").fill("P-01");
        await page.getByLabel("사유", { exact: true }).fill(`${BASE_REASON} add`);
        await page.getByLabel("운영자").fill("local-admin");
        await page.getByLabel("feature_id").fill(FEATURE_ID);
        await page.getByLabel("idempotency_key").fill(`${RUN_ID}-add`);
        await page.getByLabel("도로", { exact: true }).fill("서울특별시 중구 세종대로 110");
        await page.getByLabel("legal", { exact: true }).fill("서울특별시 중구 태평로1가");
        await page.getByLabel("관리자", { exact: true }).fill("서울특별시 중구 명동");
        await page.getByLabel("sigungu_code").fill("11140");
        await page.getByLabel("sido_code").fill("11");
        await page.getByLabel("place_kind").fill("e2e-place");
        await page.getByLabel("전화").fill("02-0000-0000");
        await page.getByLabel("홈페이지").fill("https://example.invalid/e2e");
        await page.getByLabel("소스").fill("https://example.invalid/source");
        await page
          .getByLabel("detail extra JSON")
          .fill(JSON.stringify({ e2e_phase: "create", run_id: RUN_ID }));
        await page
          .getByLabel("urls extra JSON")
          .fill(JSON.stringify({ ticket: "https://example.invalid/ticket" }));

        const responsePromise = waitForApiResponse(
          page,
          "POST",
          "/v1/admin/features",
        );
        await page.getByRole("button", { name: "요청 생성" }).click();
        const createResponse = await readChangeResponse(await responsePromise);
        addRequestId = createResponse.data.request.request_id;

        expect(createResponse.data.request).toMatchObject({
          action: "add",
          feature_id: FEATURE_ID,
          review_mode: "require_review",
          status: "pending",
        });
        expect(createResponse.data.request.payload).toMatchObject({
          category: "01070300",
          kind: "place",
          name: CREATE_NAME,
          status: "active",
        });

        const successAlert = page
          .getByRole("status")
          .filter({ hasText: "변경 요청 생성됨" });
        await expect(successAlert).toBeVisible(T);
        await expect(page.getByRole("heading", { name: "생성 요청" })).toBeVisible(T);
      });

      await test.step("pending add 요청을 검색, 상세 확인, 승인한다", async () => {
        expect(addRequestId).not.toBeNull();
        await gotoChangeReviews(page);
        await setChangeFilters(page, {
          action: "add",
          q: `${BASE_REASON} add`,
          status: "pending",
        });

        const row = rowContaining(page, CREATE_NAME);
        await expect(row).toBeVisible(T);
        await row.click();
        const detail = changeRequestDetail(page);
        await expect(detail).toContainText(addRequestId as string);
        await expect(detail).toContainText(FEATURE_ID);
        await expect(detail).toContainText(CREATE_NAME);

        const approveResponse = await approveVisibleRequest(
          page,
          row,
          addRequestId as string,
        );
        expect(approveResponse.data.request.status).toBe("applied");
        addApproved = true;
        await expect(detail).toContainText(/applied|적용/);

        await expect
          .poll(async () => {
            const response = await fetchAdminFeature(page, FEATURE_ID);
            return response.body?.data.feature.status ?? `http:${response.status}`;
          }, T)
          .toBe("active");

        const adminDetail = await expectAdminFeature(page, FEATURE_ID);
        expect(adminDetail.data.feature).toMatchObject({
          category: "01070300",
          feature_id: FEATURE_ID,
          kind: "place",
          name: CREATE_NAME,
          status: "active",
        });

        const publicDetail = await expectPublicFeature(page, FEATURE_ID);
        expect(publicDetail.data).toMatchObject({
          feature_id: FEATURE_ID,
          name: CREATE_NAME,
          status: "active",
        });
      });

      await test.step("admin features 목록에서 검색, 필터, preview, detail 링크를 확인한다", async () => {
        await gotoAdminFeatures(page);
        await page.getByLabel("feature search").fill(CREATE_NAME);
        await page.getByLabel("feature kind").selectOption("place");
        await page.getByLabel("feature status").selectOption("active");
        await page.getByLabel("has issue").selectOption("all");
        await page.getByLabel("feature sort").selectOption("updated_at");
        await page.getByRole("button", { name: "desc" }).click();

        const row = rowContaining(page, CREATE_NAME);
        await expect(row).toBeVisible(T);
        await expect(row).toContainText(/active|활성/);
        await expect(row).toContainText("place");
        await expect(row).toContainText("01070300");

        await row.getByRole("button", { name: "preview" }).click();
        await expect(page.getByText("Feature 상세").last()).toBeVisible(T);
        await expect(page.getByText(CREATE_NAME).last()).toBeVisible(T);

        await row.getByRole("link", { name: "detail" }).click();
        await expect(page).toHaveURL(
          new RegExp(`/features/${escapeRegExp(encodeURIComponent(FEATURE_ID))}$`),
          T,
        );
        await expect(
          page.getByRole("heading", { level: 1, name: "Feature 상세" }),
        ).toBeVisible(T);
        await expect(page.getByText(FEATURE_ID, { exact: true })).toBeVisible(T);
      });

      await test.step("update change request를 생성하고 승인 후 서비스 상세가 갱신된다", async () => {
        await gotoChangeRequests(page);
        await page.getByLabel("change action", { exact: true }).selectOption("update");
        await page.getByLabel("change feature id").fill(FEATURE_ID);
        await page.getByLabel("change reason").fill(`${BASE_REASON} update`);
        await page.getByLabel("change name").fill(UPDATED_NAME);
        await page.getByLabel("change category").selectOption("01070400");
        await page.getByLabel("change lon").fill("126.97891");
        await page.getByLabel("change lat").fill("37.56718");
        await page.getByLabel("change marker color").selectOption("P-02");
        await page
          .getByLabel("change detail JSON")
          .fill(JSON.stringify({ e2e_phase: "update", run_id: RUN_ID }));
        await page
          .getByLabel("change urls JSON")
          .fill(JSON.stringify({ homepage: "https://example.invalid/updated" }));

        const responsePromise = waitForApiResponse(
          page,
          "PATCH",
          decodeURIComponent(adminFeaturePath(FEATURE_ID)),
        );
        await page.getByRole("button", { name: "요청 생성" }).click();
        const updateResponse = await readChangeResponse(await responsePromise);
        updateRequestId = updateResponse.data.request.request_id;
        expect(updateResponse.data.request).toMatchObject({
          action: "update",
          feature_id: FEATURE_ID,
          status: "pending",
        });

        await gotoChangeReviews(page);
        await setChangeFilters(page, {
          action: "update",
          q: `${BASE_REASON} update`,
          status: "pending",
        });
        const row = rowContaining(page, UPDATED_NAME);
        await expect(row).toBeVisible(T);
        const approveResponse = await approveVisibleRequest(
          page,
          row,
          updateRequestId,
        );
        expect(approveResponse.data.request.status).toBe("applied");

        await expect
          .poll(async () => {
            const response = await fetchAdminFeature(page, FEATURE_ID);
            return response.body?.data.feature.name ?? `http:${response.status}`;
          }, T)
          .toBe(UPDATED_NAME);

        const adminDetail = await expectAdminFeature(page, FEATURE_ID);
        expect(adminDetail.data.feature).toMatchObject({
          category: "01070400",
          marker_color: "P-02",
          name: UPDATED_NAME,
          status: "active",
        });
        expect(adminDetail.data.feature.detail).toMatchObject({
          e2e_phase: "update",
          run_id: RUN_ID,
        });

        const publicDetail = await expectPublicFeature(page, FEATURE_ID);
        expect(publicDetail.data).toMatchObject({
          category: "01070400",
          name: UPDATED_NAME,
          status: "active",
        });
      });

      await test.step("update change request를 거절하면 실제 feature 값은 바뀌지 않는다", async () => {
        await gotoChangeRequests(page);
        await page.getByLabel("change action", { exact: true }).selectOption("update");
        await page.getByLabel("change feature id").fill(FEATURE_ID);
        await page.getByLabel("change reason").fill(`${BASE_REASON} reject`);
        await page.getByLabel("change name").fill(REJECTED_NAME);
        await page.getByLabel("change category").selectOption("01070300");

        const responsePromise = waitForApiResponse(
          page,
          "PATCH",
          decodeURIComponent(adminFeaturePath(FEATURE_ID)),
        );
        await page.getByRole("button", { name: "요청 생성" }).click();
        const rejectCandidate = await readChangeResponse(await responsePromise);
        rejectedUpdateRequestId = rejectCandidate.data.request.request_id;
        expect(rejectCandidate.data.request.status).toBe("pending");

        await gotoChangeReviews(page);
        await setChangeFilters(page, {
          action: "update",
          q: `${BASE_REASON} reject`,
          status: "pending",
        });
        const row = rowContaining(page, REJECTED_NAME);
        await expect(row).toBeVisible(T);
        const rejectResponse = await rejectVisibleRequest(
          page,
          row,
          rejectedUpdateRequestId,
        );
        expect(rejectResponse.data.request.status).toBe("rejected");

        await setChangeFilters(page, {
          action: "update",
          q: FEATURE_ID,
          status: "rejected",
        });
        const rejectedRow = rowContaining(page, "rejected");
        await expect(rejectedRow).toBeVisible(T);
        await expect(rejectedRow).toContainText(/rejected|반려/);

        const adminDetail = await expectAdminFeature(page, FEATURE_ID);
        expect(adminDetail.data.feature.name).toBe(UPDATED_NAME);
        expect(adminDetail.data.feature.category).toBe("01070400");
      });

      await test.step("admin features 목록 deactivate 버튼이 실제 inactive 상태를 만든다", async () => {
        await gotoAdminFeatures(page);
        await page.getByLabel("feature search").fill(UPDATED_NAME);
        await page.getByLabel("feature status").selectOption("active");

        const row = rowContaining(page, UPDATED_NAME);
        await expect(row).toBeVisible(T);

        page.once("dialog", (dialog) => void dialog.accept());
        const responsePromise = waitForApiResponse(
          page,
          "POST",
          `${decodeURIComponent(adminFeaturePath(FEATURE_ID))}/deactivate`,
        );
        await row.getByRole("button", { name: "deactivate" }).click();
        const response = await responsePromise;
        expect(response.status()).toBe(200);
        const body = (await response.json()) as AdminFeatureDeactivateResponse;
        expect(body.data).toMatchObject({
          feature_id: FEATURE_ID,
          status: "inactive",
        });

        await expect
          .poll(async () => {
            const detail = await fetchAdminFeature(page, FEATURE_ID);
            return detail.body?.data.feature.status ?? `http:${detail.status}`;
          }, T)
          .toBe("inactive");

        await page.getByLabel("feature status").selectOption("inactive");
        const inactiveRow = rowContaining(page, UPDATED_NAME);
        await expect(inactiveRow).toBeVisible(T);
        await expect(inactiveRow).toContainText(/inactive|비활성/);
      });

      await test.step("delete change request를 생성, 승인하고 public 상세에서 제거를 확인한다", async () => {
        await gotoChangeRequests(page);
        await page.getByLabel("change action", { exact: true }).selectOption("delete");
        await page.getByLabel("change feature id").fill(FEATURE_ID);
        await page.getByLabel("change reason").fill(`${BASE_REASON} delete`);

        const responsePromise = waitForApiResponse(
          page,
          "DELETE",
          decodeURIComponent(adminFeaturePath(FEATURE_ID)),
        );
        await page.getByRole("button", { name: "요청 생성" }).click();
        const deleteResponse = await readChangeResponse(await responsePromise);
        deleteRequestId = deleteResponse.data.request.request_id;
        expect(deleteResponse.data.request).toMatchObject({
          action: "delete",
          feature_id: FEATURE_ID,
          status: "pending",
        });

        await gotoChangeReviews(page);
        await setChangeFilters(page, {
          action: "delete",
          q: `${BASE_REASON} delete`,
          status: "pending",
        });
        const row = rowContaining(page, `${BASE_REASON} delete`);
        await expect(row).toBeVisible(T);
        const approveResponse = await approveVisibleRequest(
          page,
          row,
          deleteRequestId,
        );
        expect(approveResponse.data.request.status).toBe("applied");
        deleted = true;

        await expect
          .poll(async () => {
            const detail = await fetchAdminFeature(page, FEATURE_ID);
            return detail.body?.data.feature.status ?? `http:${detail.status}`;
          }, T)
          .toBe("deleted");

        const deletedAdminDetail = await expectAdminFeature(page, FEATURE_ID);
        expect(deletedAdminDetail.data.feature.deleted_at).not.toBeNull();
        expect(deletedAdminDetail.data.feature.user_deleted_at).not.toBeNull();

        await expect
          .poll(async () => {
            const detail = await fetchPublicFeature(page, FEATURE_ID);
            return detail.status;
          }, T)
          .toBe(404);

        await setChangeFilters(page, {
          action: "delete",
          q: `${BASE_REASON} delete`,
          status: "applied",
        });
        const appliedDeleteRow = rowContaining(page, `${BASE_REASON} delete`);
        await expect(appliedDeleteRow).toBeVisible(T);
        await expect(appliedDeleteRow).toContainText(/applied|적용|반영됨/);
      });
    } finally {
      if (!addApproved && addRequestId) {
        await rejectChangeRequestByApi(page, addRequestId);
      }
      if (updateRequestId) {
        await rejectChangeRequestByApi(page, updateRequestId);
      }
      if (rejectedUpdateRequestId) {
        await rejectChangeRequestByApi(page, rejectedUpdateRequestId);
      }
      if (!deleted) {
        await cleanupFeatureByApi(page, FEATURE_ID, deleteRequestId);
      }
    }
  });
});
