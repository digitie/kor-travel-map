import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";

// 손으로 쓴 record shape 대신 **생성된 OpenAPI 스키마**에 바인딩한다(#308 리뷰).
// 백엔드 DTO가 바뀌면 mock factory가 타입 불일치로 컴파일 실패 → mock-실계약 drift 감지.
type OfflineUploadRecord = components["schemas"]["OfflineUploadRecord"];
type PoiCacheTargetRecord = components["schemas"]["PoiCacheTargetRecord"];

const MOCK_NOW = "2026-06-08T00:00:00.000Z";
const OFFLINE_UPLOAD_ID = "11111111-1111-4111-8111-111111111111";
const OFFLINE_VALIDATION_JOB_ID = "22222222-2222-4222-8222-222222222222";
const OFFLINE_LOAD_JOB_ID = "33333333-3333-4333-8333-333333333333";
const OFFLINE_DAGSTER_RUN_ID = "dagster-run-offline-upload-001";
const POI_TARGET_ID = "44444444-4444-4444-8444-444444444444";

function makeOfflineUpload(
  overrides: Partial<OfflineUploadRecord> = {},
): OfflineUploadRecord {
  return {
    byte_size: 46,
    checksum_sha256:
      "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    created_at: MOCK_NOW,
    created_by: "local-admin",
    dataset_key: "offline_csv",
    detected_encoding: "utf-8",
    detected_format: "csv",
    load_job_id: null,
    load_url: `/admin/offline-uploads/${OFFLINE_UPLOAD_ID}/load`,
    original_filename: "offline.csv",
    provider: "offline-test-provider",
    state: "uploaded",
    status_url: `/admin/offline-uploads/${OFFLINE_UPLOAD_ID}`,
    storage_backend: "rustfs",
    storage_key: `offline-uploads/${OFFLINE_UPLOAD_ID}/offline.csv`,
    sync_scope: "default",
    updated_at: MOCK_NOW,
    upload_id: OFFLINE_UPLOAD_ID,
    validation_job_id: null,
    ...overrides,
  };
}

function makePoiTarget(
  overrides: Partial<PoiCacheTargetRecord> = {},
): PoiCacheTargetRecord {
  return {
    coord: { lon: 126.978, lat: 37.5665 },
    coord_key: "126.978000:37.566500",
    coord_precision_digits: 6,
    created_at: MOCK_NOW,
    deleted_at: null,
    external_system: "tripmate",
    last_failed_at: null,
    last_refreshed_at: null,
    last_requested_at: null,
    last_seen_at: MOCK_NOW,
    metadata: {},
    name: "Mock target",
    nearby_url:
      "/features/nearby/by-target?external_system=tripmate&target_key=mock-target-1",
    next_eligible_refresh_at: null,
    provider_overrides: {},
    radius_km: 5,
    refresh_policy: "provider_default",
    scope_mode: "center_radius",
    status_url: "/admin/poi-cache-targets/tripmate/mock-target-1",
    target_id: POI_TARGET_ID,
    target_key: "mock-target-1",
    update_enabled: true,
    updated_at: MOCK_NOW,
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

async function mockOfflineUploadMutations(page: Page) {
  let upload = makeOfflineUpload();
  let uploads: OfflineUploadRecord[] = [];
  const requests = { create: 0, load: 0, preview: 0, validate: 0 };

  await page.route("**/admin/offline-uploads**", async (route) => {
    const request = route.request();
    if (request.resourceType() === "document") {
      await route.continue();
      return;
    }
    const url = new URL(request.url());
    const uploadPath = `/admin/offline-uploads/${OFFLINE_UPLOAD_ID}`;

    if (request.method() === "GET" && url.pathname === "/admin/offline-uploads") {
      const state = url.searchParams.get("state");
      const items = state
        ? uploads.filter((item) => item.state === state)
        : uploads;
      await fulfillJson(route, {
        data: { items, next_cursor: null },
        meta: { count: items.length, duration_ms: 1 },
      });
      return;
    }

    if (request.method() === "POST" && url.pathname === "/admin/offline-uploads") {
      requests.create += 1;
      expect(request.headers()["content-type"]).toContain("multipart/form-data");
      uploads = [upload];
      await fulfillJson(route, {
        data: upload,
        meta: {
          bucket: "krtour-uploads",
          content_type: "text/csv",
          duration_ms: 1,
          object_key: upload.storage_key,
        },
      });
      return;
    }

    if (request.method() === "GET" && url.pathname === uploadPath) {
      await fulfillJson(route, { data: upload, meta: { duration_ms: 1 } });
      return;
    }

    if (request.method() === "GET" && url.pathname === `${uploadPath}/preview`) {
      requests.preview += 1;
      await fulfillJson(route, {
        data: upload,
        meta: {
          bytes_read: upload.byte_size,
          checksum_sha256_actual: upload.checksum_sha256,
          delimiter: ",",
          duration_ms: 1,
          encoding: "utf-8",
          headers: ["name", "lon", "lat"],
          parsed_format: "csv",
          rows_sampled: 1,
          rows_total: 1,
          sample_rows: [
            { name: "Seoul Test POI", lon: "126.978", lat: "37.5665" },
          ],
        },
      });
      return;
    }

    if (request.method() === "POST" && url.pathname === `${uploadPath}/validate`) {
      requests.validate += 1;
      expect(request.postData()).toContain("column_mapping");
      upload = {
        ...upload,
        state: "validated",
        updated_at: "2026-06-08T00:01:00.000Z",
        validation_job_id: OFFLINE_VALIDATION_JOB_ID,
      };
      uploads = [upload];
      await fulfillJson(route, {
        data: upload,
        meta: {
          bytes_read: upload.byte_size,
          checksum_sha256_actual: upload.checksum_sha256,
          column_mapping: {
            address: "address",
            bjd_code: "bjd_code",
            category: "category",
            default_category: "02020101",
            default_marker_color: "P-01",
            default_marker_icon: "marker",
            default_place_kind: "offline_upload",
            lat: "lat",
            lon: "lon",
            name: "name",
            source_id: "source_id",
          },
          delimiter: ",",
          duration_ms: 1,
          encoding: "utf-8",
          error_rows: 0,
          headers: ["name", "lon", "lat"],
          issues: [],
          job_id: OFFLINE_VALIDATION_JOB_ID,
          job_state: "done",
          parsed_format: "csv",
          rows_sampled: 1,
          rows_total: 1,
          sample_rows: [
            { name: "Seoul Test POI", lon: "126.978", lat: "37.5665" },
          ],
          valid_rows: 1,
        },
      });
      return;
    }

    if (request.method() === "GET" && url.pathname === `${uploadPath}/validation`) {
      await fulfillJson(route, {
        data: upload,
        meta: {
          bytes_read: upload.byte_size,
          checksum_sha256_actual: upload.checksum_sha256,
          column_mapping: {
            lat: "lat",
            lon: "lon",
            name: "name",
          },
          delimiter: ",",
          duration_ms: 1,
          encoding: "utf-8",
          error_rows: 0,
          headers: ["name", "lon", "lat"],
          issues: [],
          job_id: OFFLINE_VALIDATION_JOB_ID,
          job_state: "done",
          parsed_format: "csv",
          rows_sampled: 1,
          rows_total: 1,
          sample_rows: [
            { name: "Seoul Test POI", lon: "126.978", lat: "37.5665" },
          ],
          valid_rows: 1,
        },
      });
      return;
    }

    if (request.method() === "POST" && url.pathname === `${uploadPath}/load`) {
      requests.load += 1;
      upload = {
        ...upload,
        load_job_id: OFFLINE_LOAD_JOB_ID,
        state: "loading",
        updated_at: "2026-06-08T00:02:00.000Z",
      };
      uploads = [upload];
      await fulfillJson(route, {
        data: upload,
        meta: {
          dagster_run_id: OFFLINE_DAGSTER_RUN_ID,
          dagster_status: "STARTED",
          duration_ms: 1,
        },
      });
      return;
    }

    throw new Error(`Unhandled offline upload route: ${request.method()} ${url}`);
  });

  return requests;
}

async function mockPoiCacheTargetMutations(page: Page) {
  let targets: PoiCacheTargetRecord[] = [];
  const requests = { delete: 0, nearby: 0, upsert: 0 };

  await page.route("**/admin/poi-cache-targets**", async (route) => {
    const request = route.request();
    if (request.resourceType() === "document") {
      await route.continue();
      return;
    }
    const url = new URL(request.url());
    const targetPath = "/admin/poi-cache-targets/tripmate/mock-target-1";

    if (request.method() === "GET" && url.pathname === "/admin/poi-cache-targets") {
      await fulfillJson(route, {
        data: { items: targets, next_cursor: null },
        meta: { count: targets.length, duration_ms: 1 },
      });
      return;
    }

    if (request.method() === "PUT" && url.pathname === targetPath) {
      requests.upsert += 1;
      expect(request.postDataJSON()).toMatchObject({
        coord: { lon: 126.978, lat: 37.5665 },
        name: "Mock target",
        on_conflict: "move",
        radius_km: 5,
        scope_mode: "center_radius",
      });
      const target = makePoiTarget();
      targets = [target];
      await fulfillJson(route, {
        data: target,
        meta: { duration_ms: 1 },
      });
      return;
    }

    if (request.method() === "DELETE" && url.pathname === targetPath) {
      requests.delete += 1;
      targets = [];
      await fulfillJson(route, {
        data: makePoiTarget({
          deleted_at: "2026-06-08T00:03:00.000Z",
          update_enabled: false,
          updated_at: "2026-06-08T00:03:00.000Z",
        }),
        meta: { duration_ms: 1 },
      });
      return;
    }

    throw new Error(`Unhandled POI cache target route: ${request.method()} ${url}`);
  });

  await page.route("**/v1/features/nearby/by-target**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    requests.nearby += 1;
    expect(url.searchParams.get("external_system")).toBe("tripmate");
    expect(url.searchParams.get("target_key")).toBe("mock-target-1");
    await fulfillJson(route, {
      data: {
        items: [
          {
            category: "02020101",
            distance_m: 42.5,
            feature_id: "mock-provider::mock-dataset::nearby-1",
            kind: "place",
            lat: 37.5667,
            lon: 126.9782,
            name: "Mock nearby feature",
            status: "active",
          },
        ],
        next_cursor: null,
        target: {
          external_system: "tripmate",
          lat: 37.5665,
          lon: 126.978,
          target_key: "mock-target-1",
        },
      },
      meta: { count: 1, duration_ms: 1 },
    });
  });

  return requests;
}

/**
 * 신규 admin/ops 화면 smoke.
 * API 결과 행 수보다 운영자가 사용할 표면(제목, 필터, 폼, 표)을 우선 검증한다.
 */
test.describe("admin/ops pages", () => {
  test("/ops/import-jobs", async ({ page }) => {
    await page.goto("/ops/import-jobs");

    await expect(
      page.getByRole("heading", { level: 1, name: "Import jobs" }),
    ).toBeVisible();
    await expect(page.getByLabel("state")).toBeVisible();
    await expect(page.getByPlaceholder("kind filter")).toBeVisible();
    for (const column of ["job", "kind", "state", "progress", "stage"]) {
      await expect(page.getByRole("columnheader", { name: column })).toBeVisible();
    }
  });

  test("/admin/features", async ({ page }) => {
    await page.goto("/admin/features");

    await expect(
      page.getByRole("heading", { level: 1, name: "Admin features" }),
    ).toBeVisible();
    await expect(page.getByLabel("feature search")).toBeVisible();
    await expect(page.getByLabel("feature kind")).toBeVisible();
    await expect(page.getByLabel("feature status")).toBeVisible();
    await expect(page.getByLabel("has issue")).toBeVisible();
    await expect(page.getByLabel("feature sort")).toBeVisible();
    await expect(page.getByLabel("feature page size")).toBeVisible();
    for (const column of [
      "feature",
      "kind/status",
      "provider",
      "issues",
      "coord/address",
      "updated",
      "actions",
    ]) {
      await expect(page.getByRole("columnheader", { name: column })).toBeVisible();
    }
    await expect(page.getByText("table에서 feature를 선택하면")).toBeVisible();
  });

  test("/admin/issues", async ({ page }) => {
    await page.goto("/admin/issues");

    await expect(
      page.getByRole("heading", { level: 1, name: "Admin issues" }),
    ).toBeVisible();
    await expect(page.getByLabel("issue search")).toBeVisible();
    await expect(page.getByLabel("issue status")).toBeVisible();
    await expect(page.getByLabel("issue severity")).toBeVisible();
    await expect(page.getByLabel("issue page size")).toBeVisible();
    await expect(page.getByLabel("issue type")).toBeVisible();
    await expect(page.getByLabel("issue provider")).toBeVisible();
    await expect(page.getByLabel("issue dataset")).toBeVisible();
    await expect(page.getByLabel("bbox")).toBeVisible();
    for (const column of [
      "issue",
      "severity",
      "status",
      "provider",
      "message",
      "feature",
      "detected",
      "actions",
    ]) {
      await expect(page.getByRole("columnheader", { name: column })).toBeVisible();
    }
    const firstIssue = page.getByRole("row").nth(1);
    if (await firstIssue.isVisible()) {
      await firstIssue.click();
      await expect(page.getByLabel("address JSON")).toBeVisible();
      await expect(page.getByLabel("manual lon")).toBeVisible();
      await expect(page.getByLabel("manual lat")).toBeVisible();
    } else {
      await expect(page.getByText("table에서 issue를 선택하면")).toBeVisible();
    }
  });

  test("/ops/consistency", async ({ page }) => {
    await page.goto("/ops/consistency");

    await expect(
      page.getByRole("heading", { level: 1, name: "Consistency" }),
    ).toBeVisible();
    await expect(page.getByText("Open issues")).toBeVisible();
    await expect(page.getByText("Reports")).toBeVisible();
    await expect(page.getByText("Integrity issues")).toBeVisible();
    await expect(page.getByLabel("issue status")).toBeVisible();
  });

  test("/ops/logs", async ({ page }) => {
    await page.goto("/ops/logs");

    await expect(page.getByRole("heading", { level: 1, name: "Logs" })).toBeVisible();
    await expect(page.getByLabel("log page size")).toBeVisible();
    await expect(page.getByRole("tab", { name: "System logs" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "API call logs" })).toBeVisible();
    await expect(page.getByLabel("system log search")).toBeVisible();
    await expect(page.getByLabel("system log level")).toBeVisible();
    await expect(page.getByLabel("system log source")).toBeVisible();
    for (const column of [
      "created",
      "level",
      "source",
      "event",
      "message",
      "request",
    ]) {
      await expect(page.getByRole("columnheader", { name: column })).toBeVisible();
    }
    await page.getByRole("tab", { name: "API call logs" }).click();
    await expect(page.getByRole("tab", { name: "API call logs" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(page.getByLabel("api log method")).toBeVisible();
    await expect(page.getByLabel("api log path")).toBeVisible();
    await expect(page.getByLabel("api log min status")).toBeVisible();
    for (const column of [
      "created",
      "method",
      "status",
      "duration",
      "path",
      "request",
      "error",
    ]) {
      await expect(page.getByRole("columnheader", { name: column })).toBeVisible();
    }
  });

  test("/admin/dedup-review", async ({ page }) => {
    await page.goto("/admin/dedup-review");

    await expect(
      page.getByRole("heading", { level: 1, name: "Dedup review" }),
    ).toBeVisible();
    await expect(page.getByLabel("dedup status")).toBeVisible();
    for (const column of ["review", "score", "feature A", "feature B", "actions"]) {
      await expect(page.getByRole("columnheader", { name: column })).toBeVisible();
    }
  });

  test("/admin/enrichment-review", async ({ page }) => {
    await page.goto("/admin/enrichment-review");

    await expect(
      page.getByRole("heading", { level: 1, name: "Enrichment review" }),
    ).toBeVisible();
    await expect(page.getByLabel("enrichment status")).toBeVisible();
    for (const column of [
      "review",
      "score",
      "1차 (datagokr)",
      "2차 (visitkorea)",
      "actions",
    ]) {
      await expect(page.getByRole("columnheader", { name: column })).toBeVisible();
    }
    // cursor 페이지네이션 컨트롤(#299).
    await expect(page.getByLabel("이전 페이지")).toBeVisible();
    await expect(page.getByLabel("다음 페이지")).toBeVisible();
  });

  test("/admin/feature-update-requests", async ({ page }) => {
    await page.goto("/admin/feature-update-requests");

    await expect(
      page.getByRole("heading", { level: 1, name: "Feature update requests" }),
    ).toBeVisible();
    await expect(page.getByText("새 요청")).toBeVisible();
    for (const label of ["lon", "lat", "radius km", "providers", "dataset keys"]) {
      await expect(page.getByLabel(label)).toBeVisible();
    }
    await expect(page.getByLabel("run mode")).toBeVisible();
    await expect(page.getByLabel("dry-run")).toBeChecked();
    await expect(page.getByLabel("request state")).toBeVisible();
  });

  test("/admin/poi-cache-targets", async ({ page }) => {
    await page.goto("/admin/poi-cache-targets");

    await expect(
      page.getByRole("heading", { level: 1, name: "POI cache targets" }),
    ).toBeVisible();
    await expect(page.getByText("Target upsert")).toBeVisible();
    for (const label of [
      "external system",
      "target key",
      "target name",
      "lon",
      "lat",
      "radius km",
    ]) {
      await expect(page.getByLabel(label)).toBeVisible();
    }
    await expect(page.getByLabel("scope mode")).toBeVisible();
    await expect(page.getByText("Nearby features")).toBeVisible();
  });

  test("/admin/poi-cache-targets mutation flow", async ({ page }) => {
    const requests = await mockPoiCacheTargetMutations(page);

    await page.goto("/admin/poi-cache-targets");
    await page.getByLabel("target key").fill("mock-target-1");
    await page.getByLabel("target name").fill("Mock target");
    await page.getByRole("button", { name: "저장" }).click();

    await expect.poll(() => requests.upsert).toBe(1);
    const targetRow = page.getByRole("row", { name: /Mock target/ });
    await expect(targetRow).toBeVisible();

    await targetRow.click();
    await expect(page.getByText("Mock nearby feature")).toBeVisible();
    await expect.poll(() => requests.nearby).toBeGreaterThanOrEqual(1);

    await targetRow.getByRole("button", { name: "삭제" }).click();
    await expect.poll(() => requests.delete).toBe(1);
    await expect(page.getByRole("row", { name: /Mock target/ })).toHaveCount(0);
  });

  test("/admin/offline-uploads", async ({ page }) => {
    await page.goto("/admin/offline-uploads");

    await expect(
      page.getByRole("heading", { level: 1, name: "Offline uploads" }),
    ).toBeVisible();
    await expect(page.getByText("파일 업로드")).toBeVisible();
    await expect(page.getByTestId("offline-upload-file-input")).toBeVisible();
    for (const label of ["provider", "dataset key", "sync scope", "created by"]) {
      await expect(page.getByLabel(label, { exact: true })).toBeVisible();
    }
    await expect(page.getByRole("button", { name: "업로드" })).toBeDisabled();
    await expect(page.getByText("CSV/TSV 업로드를 선택하면")).toBeVisible();
    await expect(page.getByLabel("offline upload state")).toBeVisible();
    await expect(page.getByLabel("provider filter")).toBeVisible();
    await expect(page.getByLabel("dataset filter")).toBeVisible();
    for (const column of [
      "upload",
      "state",
      "format",
      "provider/dataset",
      "file",
      "size",
      "updated",
      "actions",
    ]) {
      await expect(page.getByRole("columnheader", { name: column })).toBeVisible();
    }
  });

  test("/admin/offline-uploads mutation flow", async ({ page }) => {
    const requests = await mockOfflineUploadMutations(page);

    await page.goto("/admin/offline-uploads");
    await page.getByTestId("offline-upload-file-input").setInputFiles({
      buffer: Buffer.from("name,lon,lat\nSeoul Test POI,126.978,37.5665\n"),
      mimeType: "text/csv",
      name: "offline.csv",
    });
    await page.getByRole("button", { name: "업로드" }).click();

    await expect.poll(() => requests.create).toBe(1);
    await expect(page.getByText("업로드 완료")).toBeVisible();
    await expect(page.getByText("Seoul Test POI")).toBeVisible();
    await expect.poll(() => requests.preview).toBeGreaterThanOrEqual(1);

    await page.getByTestId("offline-upload-validate").click();
    await expect.poll(() => requests.validate).toBe(1);
    await expect(page.getByText("1 valid / 0 error")).toBeVisible();

    await page.getByLabel("offline upload state").selectOption("validated");
    const loadButton = page.getByTestId("offline-upload-load");
    await expect(loadButton).toBeEnabled();
    await loadButton.click();

    await expect.poll(() => requests.load).toBe(1);
    await expect(page.getByText("Dagster load 실행됨")).toBeVisible();
    await expect(page.getByText("STARTED")).toBeVisible();
  });
});
