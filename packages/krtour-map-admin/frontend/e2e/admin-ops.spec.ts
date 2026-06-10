import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";

// 손으로 쓴 record shape 대신 **생성된 OpenAPI 스키마**에 바인딩한다(#308 리뷰).
// 백엔드 DTO가 바뀌면 mock factory가 타입 불일치로 컴파일 실패 → mock-실계약 drift 감지.
type OfflineUploadRecord = components["schemas"]["OfflineUploadRecord"];
type PoiCacheTargetRecord = components["schemas"]["PoiCacheTargetRecord"];
type AdminFeatureChangeRecord =
  components["schemas"]["AdminFeatureChangeRequestRecord"];
type AdminFeatureChangeListResponse =
  components["schemas"]["AdminFeatureChangeListResponse"];
type AdminFeatureChangeResponse =
  components["schemas"]["AdminFeatureChangeResponse"];
type AdminFeatureCreateRequest =
  components["schemas"]["AdminFeatureCreateRequest"];
type AdminFeaturePatchRequest =
  components["schemas"]["AdminFeaturePatchRequest"];
type AdminFeatureDeleteRequest =
  components["schemas"]["AdminFeatureDeleteRequest"];
type AdminFeatureReviewActionRequest =
  components["schemas"]["AdminFeatureReviewActionRequest"];
type AdminFeatureReviewMode = AdminFeatureChangeRecord["review_mode"];
type BackupRecord = components["schemas"]["BackupRecord"];

const MOCK_NOW = "2026-06-08T00:00:00.000Z";
const MOCK_REVIEWED_AT = "2026-06-08T00:10:00.000Z";
const OFFLINE_UPLOAD_ID = "11111111-1111-4111-8111-111111111111";
const OFFLINE_VALIDATION_JOB_ID = "22222222-2222-4222-8222-222222222222";
const OFFLINE_LOAD_JOB_ID = "33333333-3333-4333-8333-333333333333";
const OFFLINE_DAGSTER_RUN_ID = "dagster-run-offline-upload-001";
const POI_TARGET_ID = "44444444-4444-4444-8444-444444444444";
const FEATURE_CHANGE_ID = "55555555-5555-4555-8555-555555555555";
const MOCK_BACKUP_ID = "backup-20260608-000000";

function makeBackup(overrides: Partial<BackupRecord> = {}): BackupRecord {
  return {
    backup_id: MOCK_BACKUP_ID,
    byte_size: 1024,
    checksum_count: 3,
    components: { app_db: "ok", dagster_db: "ok" },
    created_at_utc: MOCK_NOW,
    databases: { app: "krtour_map", dagster: "krtour_map_dagster" },
    detail_url: `/v1/admin/backups/${MOCK_BACKUP_ID}`,
    manifest_status: "complete",
    mode: "cold",
    object_storage: {},
    path: `/var/backups/${MOCK_BACKUP_ID}`,
    restore_url: `/v1/admin/restore/${MOCK_BACKUP_ID}`,
    ...overrides,
  };
}

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
    load_url: `/v1/admin/offline-uploads/${OFFLINE_UPLOAD_ID}/load`,
    original_filename: "offline.csv",
    provider: "offline-test-provider",
    status: "uploaded",
    status_url: `/v1/admin/offline-uploads/${OFFLINE_UPLOAD_ID}`,
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
    status_url: "/v1/admin/poi-cache-targets/tripmate/mock-target-1",
    target_id: POI_TARGET_ID,
    target_key: "mock-target-1",
    update_enabled: true,
    updated_at: MOCK_NOW,
    ...overrides,
  };
}

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
    request_id: FEATURE_CHANGE_ID,
    requested_by: "local-admin",
    review_mode: "require_review",
    reviewed_at: null,
    reviewed_by: null,
    status: "pending",
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
    if (url.pathname === "/admin/offline-uploads" || url.searchParams.has("_rsc")) {
      await route.continue();
      return;
    }
    const uploadPath = `/v1/admin/offline-uploads/${OFFLINE_UPLOAD_ID}`;

    if (request.method() === "GET" && url.pathname === "/v1/admin/offline-uploads") {
      const status = url.searchParams.get("status");
      const items = status
        ? uploads.filter((item) => item.status === status)
        : uploads;
      await fulfillJson(route, {
        data: { items },
        meta: {
          duration_ms: 1,
          page: { page_size: 100, next_cursor: null, total: null },
          request_id: "e2e-offline-list",
        },
      });
      return;
    }

    if (request.method() === "POST" && url.pathname === "/v1/admin/offline-uploads") {
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
        status: "validated",
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
          job_status: "done",
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
          job_status: "done",
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
        status: "loading",
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
    if (url.pathname === "/admin/poi-cache-targets" || url.searchParams.has("_rsc")) {
      await route.continue();
      return;
    }
    const targetPath = "/v1/admin/poi-cache-targets/tripmate/mock-target-1";

    if (request.method() === "GET" && url.pathname === "/v1/admin/poi-cache-targets") {
      await fulfillJson(route, {
        data: { items: targets },
        meta: {
          duration_ms: 1,
          page: { page_size: 100, next_cursor: null, total: null },
          request_id: "e2e-poi-target-list",
        },
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
        target: {
          external_system: "tripmate",
          lat: 37.5665,
          lon: 126.978,
          target_key: "mock-target-1",
        },
      },
      meta: {
        duration_ms: 1,
        page: { page_size: 100, next_cursor: null, total: null },
        request_id: "e2e-nearby-target",
      },
    });
  });

  return requests;
}

async function mockBackupOperations(page: Page) {
  const requests = { create: 0, restore: 0, swap: 0 };

  await page.route("**/admin/backups**", async (route) => {
    const request = route.request();
    if (request.resourceType() === "document") {
      await route.continue();
      return;
    }
    const url = new URL(request.url());
    if (url.pathname === "/admin/backups" || url.searchParams.has("_rsc")) {
      await route.continue();
      return;
    }

    if (request.method() === "GET" && url.pathname === "/v1/admin/backups") {
      await fulfillJson(route, {
        data: {
          backup_root: "/var/backups",
          command_enabled: false,
          items: [makeBackup()],
        },
        meta: { duration_ms: 1, request_id: "e2e-backup-list" },
      });
      return;
    }

    if (request.method() === "POST" && url.pathname === "/v1/admin/backups") {
      requests.create += 1;
      await fulfillJson(route, {
        data: {
          backup_id: MOCK_BACKUP_ID,
          message: "backup command planned",
          operation: "backup",
          status: "planned",
        },
        meta: { duration_ms: 1 },
      });
      return;
    }

    throw new Error(`Unhandled backups route: ${request.method()} ${url}`);
  });

  await page.route("**/admin/restore/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());

    if (url.pathname.endsWith("/swap")) {
      requests.swap += 1;
      await fulfillJson(route, {
        data: {
          backup_id: MOCK_BACKUP_ID,
          message: "swap command planned",
          operation: "swap",
          status: "planned",
        },
        meta: { duration_ms: 1 },
      });
      return;
    }

    requests.restore += 1;
    await fulfillJson(route, {
      data: {
        backup_id: MOCK_BACKUP_ID,
        message: "restore command planned",
        operation: "restore",
        status: "planned",
        restore_targets: {
          app_db: "krtour_map_staging",
          dagster_db: "krtour_map_dagster_staging",
          rustfs_volume: "rustfs_staging",
        },
      },
      meta: { duration_ms: 1 },
    });
  });

  return requests;
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

function applyFeatureChange(
  request: AdminFeatureChangeRecord,
  operator: string | null | undefined,
): AdminFeatureChangeRecord {
  return {
    ...request,
    applied_at: MOCK_REVIEWED_AT,
    reviewed_at: MOCK_REVIEWED_AT,
    reviewed_by: operator ?? "local-admin",
    status: "applied",
  };
}

async function mockFeatureChangeMutations(
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
    create: 0,
    delete: 0,
    list: 0,
    patch: 0,
    reject: 0,
    createBodies: [] as AdminFeatureCreateRequest[],
    deleteBodies: [] as AdminFeatureDeleteRequest[],
    patchBodies: [] as AdminFeaturePatchRequest[],
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

  function changeStateForWrite(request: AdminFeatureChangeRecord) {
    return reviewMode === "immediate"
      ? applyFeatureChange(request, request.requested_by)
      : request;
  }

  await page.route("**/admin/features**", async (route) => {
    const request = route.request();
    if (request.resourceType() === "document") {
      await route.continue();
      return;
    }
    const url = new URL(request.url());
    if (url.port === "9012") {
      await route.continue();
      return;
    }

    if (
      request.method() === "GET" &&
      url.pathname === "/v1/admin/features/change-requests"
    ) {
      requests.list += 1;
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

    if (
      request.method() === "POST" &&
      url.pathname.endsWith("/approve")
    ) {
      requests.approve += 1;
      const body = request.postDataJSON() as AdminFeatureReviewActionRequest;
      requests.reviewBodies.push(body);
      const requestId = url.pathname.split("/").at(-2);
      const target = changes.find((item) => item.request_id === requestId);
      if (!target) {
        await fulfillJson(route, { detail: "not found" }, 404);
        return;
      }
      const updated = storeChange(applyFeatureChange(target, body.operator));
      await fulfillJson(route, featureChangeResponse(updated));
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

    if (request.method() === "POST" && url.pathname === "/v1/admin/features") {
      requests.create += 1;
      const body = request.postDataJSON() as AdminFeatureCreateRequest;
      requests.createBodies.push(body);
      const created = storeChange(
        changeStateForWrite(
          makeFeatureChange({
            feature_id: body.feature_id ?? "user_request::e2e::created-feature",
            payload: { ...body },
            reason: body.reason,
            request_id: `change-create-${requests.create}`,
            requested_by: body.operator ?? "local-admin",
            review_mode: reviewMode,
          }),
        ),
      );
      await fulfillJson(route, featureChangeResponse(created));
      return;
    }

    if (
      request.method() === "PATCH" &&
      url.pathname.startsWith("/v1/admin/features/")
    ) {
      requests.patch += 1;
      const body = request.postDataJSON() as AdminFeaturePatchRequest;
      requests.patchBodies.push(body);
      const featureId = decodeURIComponent(url.pathname.split("/").at(-1) ?? "");
      const updated = storeChange(
        changeStateForWrite(
          makeFeatureChange({
            action: "update",
            feature_id: featureId,
            payload: { feature_id: featureId, ...body },
            reason: body.reason,
            request_id: `change-update-${requests.patch}`,
            requested_by: body.operator ?? "local-admin",
            review_mode: reviewMode,
          }),
        ),
      );
      await fulfillJson(route, featureChangeResponse(updated));
      return;
    }

    if (
      request.method() === "DELETE" &&
      url.pathname.startsWith("/v1/admin/features/")
    ) {
      requests.delete += 1;
      const body = request.postDataJSON() as AdminFeatureDeleteRequest;
      requests.deleteBodies.push(body);
      const featureId = decodeURIComponent(url.pathname.split("/").at(-1) ?? "");
      const deleted = storeChange(
        changeStateForWrite(
          makeFeatureChange({
            action: "delete",
            feature_id: featureId,
            payload: { deleted: true, feature_id: featureId, status: "hidden" },
            reason: body.reason,
            request_id: `change-delete-${requests.delete}`,
            requested_by: body.operator ?? "local-admin",
            review_mode: reviewMode,
          }),
        ),
      );
      await fulfillJson(route, featureChangeResponse(deleted));
      return;
    }

    throw new Error(`Unhandled feature change route: ${request.method()} ${url}`);
  });

  return requests;
}

/**
 * 신규 admin/ops 화면 smoke.
 * API 결과 행 수보다 운영자가 사용할 표면(제목, 필터, 폼, 표)을 우선 검증한다.
 */
test.describe("admin/ops pages", () => {
  test("/v1/ops/import-jobs", async ({ page }) => {
    await page.goto("/ops/import-jobs");

    await expect(
      page.getByRole("heading", { level: 1, name: "Import jobs" }),
    ).toBeVisible();
    await expect(page.getByLabel("status")).toBeVisible();
    await expect(page.getByPlaceholder("kind filter")).toBeVisible();
    for (const column of ["job", "kind", "status", "progress", "stage"]) {
      await expect(page.getByRole("columnheader", { name: column })).toBeVisible();
    }
  });

  test("/v1/admin/features", async ({ page }) => {
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

  test("/v1/admin/features/change-requests", async ({ page }) => {
    await page.goto("/admin/features/change-requests");

    await expect(
      page.getByRole("heading", { level: 1, name: "Feature change requests" }),
    ).toBeVisible();
    await expect(page.getByText("Change request form")).toBeVisible();
    for (const label of [
      "change action",
      "change feature id",
      "change reason",
      "change operator",
      "change kind",
      "change feature status",
      "change name",
      "change category",
      "change lon",
      "change lat",
      "change detail JSON",
      "change search",
      "change status",
      "change action filter",
      "change page size",
    ]) {
      await expect(page.getByLabel(label, { exact: true })).toBeVisible();
    }
    for (const column of [
      "request",
      "action/status",
      "feature",
      "review",
      "reason",
      "created",
      "actions",
    ]) {
      await expect(page.getByRole("columnheader", { name: column })).toBeVisible();
    }
    await expect(page.getByText("요청 행을 선택하면")).toBeVisible();
  });

  test("/v1/admin/features/change-requests validation (T-218d)", async ({
    page,
  }) => {
    await page.goto("/admin/features/change-requests");

    // 필수값을 채우되 detail JSON에 object가 아닌 배열을 넣어 클라이언트 검증 실패 유도.
    await page.getByLabel("change name", { exact: true }).fill("Neg test");
    await page.getByLabel("change reason", { exact: true }).fill("음성 경로");
    await page.getByLabel("change detail JSON", { exact: true }).fill("[]");
    await page.getByRole("button", { name: "요청 생성" }).click();

    // buildCreatePayload가 동기적으로 throw → 네트워크 호출 없이 formError 배너 노출.
    await expect(
      page.getByText("detail는 JSON object여야 합니다."),
    ).toBeVisible();
  });

  test("/v1/admin/features/change-requests approve workflow", async ({ page }) => {
    const requests = await mockFeatureChangeMutations(page, {
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
    await page.getByLabel("change status", { exact: true }).selectOption("all");

    const pendingRow = page.getByRole("row", { name: /Mock pending feature/ });
    await expect(pendingRow).toBeVisible();
    await pendingRow.click();
    await expect(page.locator("aside").getByText("change-pending-1")).toBeVisible();

    await pendingRow.getByRole("button", { name: "approve" }).click();

    await expect.poll(() => requests.approve).toBe(1);
    expect(requests.reviewBodies[0]).toMatchObject({
      operator: "local-admin",
      reason: "admin-ui approve",
    });
    await expect(pendingRow.getByText("applied")).toBeVisible();
    await expect(pendingRow.getByRole("button", { name: "approve" })).toHaveCount(
      0,
    );
  });

  test("/v1/admin/features/change-requests immediate create workflow", async ({
    page,
  }) => {
    const requests = await mockFeatureChangeMutations(page, {
      reviewMode: "immediate",
    });

    await page.goto("/admin/features/change-requests");
    await expect(page.getByText("immediate").first()).toBeVisible();

    await page.getByLabel("change name", { exact: true }).fill("Immediate feature");
    await page.getByLabel("change reason", { exact: true }).fill("즉시 적용");
    await page.getByLabel("change lon", { exact: true }).fill("126.978");
    await page.getByLabel("change lat", { exact: true }).fill("37.5665");
    await page.getByRole("button", { name: "요청 생성" }).click();

    await expect.poll(() => requests.create).toBe(1);
    expect(requests.createBodies[0]).toMatchObject({
      coord: { lon: 126.978, lat: 37.5665 },
      name: "Immediate feature",
      reason: "즉시 적용",
    });

    await page.getByLabel("change status", { exact: true }).selectOption("all");
    const createdRow = page.getByRole("row", { name: /Immediate feature/ });
    await expect(createdRow).toBeVisible();
    await expect(createdRow.getByText("applied")).toBeVisible();
  });

  test("/v1/admin/features/change-requests update/delete workflow", async ({
    page,
  }) => {
    const requests = await mockFeatureChangeMutations(page);

    await page.goto("/admin/features/change-requests");
    await page.getByLabel("change status", { exact: true }).selectOption("all");

    await page.getByLabel("change action", { exact: true }).selectOption("update");
    await page
      .getByLabel("change feature id", { exact: true })
      .fill("feature-update-1");
    await page.getByLabel("change reason", { exact: true }).fill("이름 수정");
    await page.getByLabel("change name", { exact: true }).fill("Updated feature");
    await page.getByRole("button", { name: "요청 생성" }).click();

    await expect.poll(() => requests.patch).toBe(1);
    expect(requests.patchBodies[0]).toMatchObject({
      name: "Updated feature",
      reason: "이름 수정",
    });
    await expect(page.getByRole("row", { name: /Updated feature/ })).toBeVisible();

    await page.getByLabel("change action", { exact: true }).selectOption("delete");
    await page
      .getByLabel("change feature id", { exact: true })
      .fill("feature-delete-1");
    await page.getByLabel("change reason", { exact: true }).fill("soft delete");
    await page.getByRole("button", { name: "요청 생성" }).click();

    await expect.poll(() => requests.delete).toBe(1);
    expect(requests.deleteBodies[0]).toMatchObject({
      operator: "local-admin",
      reason: "soft delete",
    });

    const deleteRow = page.getByRole("row", { name: /feature-delete-1/ });
    await expect(deleteRow).toBeVisible();
    await deleteRow.getByRole("button", { name: "approve" }).click();
    await expect.poll(() => requests.approve).toBe(1);
    await expect(deleteRow.getByText("applied")).toBeVisible();
    await expect(deleteRow.getByText("완료")).toBeVisible();

    await page
      .getByLabel("change action filter", { exact: true })
      .selectOption("delete");
    await expect(deleteRow).toBeVisible();
    await expect(page.getByRole("row", { name: /Updated feature/ })).toHaveCount(
      0,
    );
  });

  test("/v1/admin/issues", async ({ page }) => {
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
      const addressJson = page.getByLabel("address JSON");
      await expect(addressJson).toBeVisible();
      await expect(page.getByLabel("manual lon")).toBeVisible();
      await expect(page.getByLabel("manual lat")).toBeVisible();

      // T-218b-3: 빈 입력으로 manual override → 클라이언트 검증 에러 + 포커스(서버 미호출).
      await page.getByRole("button", { name: "manual override" }).click();
      await expect(
        page.getByText("address JSON 또는 lon/lat 중 하나는 필요합니다."),
      ).toBeVisible();
      await expect(addressJson).toHaveAttribute("aria-invalid", "true");
      await expect(addressJson).toBeFocused();
    } else {
      await expect(page.getByText("table에서 issue를 선택하면")).toBeVisible();
    }
  });

  test("/v1/ops/consistency", async ({ page }) => {
    await page.goto("/ops/consistency");

    await expect(
      page.getByRole("heading", { level: 1, name: "Consistency" }),
    ).toBeVisible();
    await expect(page.getByText("Open issues")).toBeVisible();
    await expect(page.getByText("Reports")).toBeVisible();
    await expect(page.getByText("Integrity issues")).toBeVisible();
    await expect(page.getByLabel("issue status")).toBeVisible();
  });

  test("/v1/ops/logs", async ({ page }) => {
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

  test("/v1/admin/dedup-reviews", async ({ page }) => {
    await page.goto("/admin/dedup-reviews");

    await expect(
      page.getByRole("heading", { level: 1, name: "Dedup review" }),
    ).toBeVisible();
    await expect(page.getByLabel("dedup status")).toBeVisible();
    for (const column of ["review", "score", "feature A", "feature B", "actions"]) {
      await expect(page.getByRole("columnheader", { name: column })).toBeVisible();
    }
  });

  test("/v1/admin/enrichment-reviews", async ({ page }) => {
    await page.goto("/admin/enrichment-reviews");

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

  test("/v1/admin/feature-update-requests", async ({ page }) => {
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
    await expect(page.getByLabel("request status")).toBeVisible();

    // T-218b: lon을 비우고 생성 → 클라이언트 검증 에러 + 포커스(네트워크 호출 전 차단).
    const lon = page.getByLabel("lon");
    await lon.fill("");
    await page.getByRole("button", { name: "요청 생성" }).click();
    await expect(lon).toHaveAttribute("aria-invalid", "true");
    await expect(lon).toBeFocused();
    await expect(page.getByText("경도(lon)는 필수입니다.")).toBeVisible();
  });

  test("/v1/admin/poi-cache-targets", async ({ page }) => {
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

  test("/v1/admin/poi-cache-targets mutation flow", async ({ page }) => {
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

  test("/v1/admin/poi-cache-targets validation (T-218b a11y)", async ({ page }) => {
    const requests = await mockPoiCacheTargetMutations(page);

    await page.goto("/admin/poi-cache-targets");

    // target_key가 비어있는 상태로 저장 → 클라이언트 검증 에러(서버 미호출).
    await page.getByRole("button", { name: "저장" }).click();

    const targetKey = page.getByLabel("target key");
    await expect(targetKey).toHaveAttribute("aria-invalid", "true");
    await expect(targetKey).toBeFocused();
    await expect(page.getByText("target_key는 필수입니다.")).toBeVisible();
    expect(requests.upsert).toBe(0);

    // 채우면 에러가 사라지고 정상 제출.
    await targetKey.fill("mock-target-1");
    await page.getByLabel("target name").fill("Mock target");
    await page.getByRole("button", { name: "저장" }).click();
    await expect.poll(() => requests.upsert).toBe(1);
    await expect(targetKey).not.toHaveAttribute("aria-invalid", "true");
    await expect(page.getByText("target_key는 필수입니다.")).toHaveCount(0);
  });

  test("/v1/admin/offline-uploads", async ({ page }) => {
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
    await expect(page.getByLabel("offline upload status")).toBeVisible();
    await expect(page.getByLabel("provider filter")).toBeVisible();
    await expect(page.getByLabel("dataset filter")).toBeVisible();
    for (const column of [
      "upload",
      "status",
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

  test("/v1/admin/offline-uploads mutation flow", async ({ page }) => {
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

    await page.getByLabel("offline upload status").selectOption("validated");
    const loadButton = page.getByTestId("offline-upload-load");
    await expect(loadButton).toBeEnabled();
    await loadButton.click();

    await expect.poll(() => requests.load).toBe(1);
    await expect(page.getByText("Dagster load 실행됨")).toBeVisible();
    await expect(page.getByText("STARTED")).toBeVisible();
  });

  test("/v1/admin/backups", async ({ page }) => {
    await mockBackupOperations(page);

    await page.goto("/admin/backups");

    await expect(
      page.getByRole("heading", { level: 1, name: "Backups" }),
    ).toBeVisible();
    for (const column of ["backup", "created", "status", "size", "action"]) {
      await expect(page.getByRole("columnheader", { name: column })).toBeVisible();
    }
    // 목록 + manifest 상세(선택 없음 시 첫 행을 detail로 노출)
    await expect(page.getByText("1 artifacts")).toBeVisible();
    await expect(page.getByText(MOCK_BACKUP_ID).first()).toBeVisible();
  });

  test("/v1/admin/backups operations (T-218c)", async ({ page }) => {
    const requests = await mockBackupOperations(page);

    await page.goto("/admin/backups");
    await expect(
      page.getByRole("row", { name: new RegExp(MOCK_BACKUP_ID.slice(0, 12)) }),
    ).toBeVisible();

    // 백업 command plan 생성
    await page.getByRole("button", { name: "백업" }).click();
    await expect.poll(() => requests.create).toBe(1);
    await expect(page.getByText("backup command planned")).toBeVisible();

    // restore command plan (staging target)
    await page.getByRole("button", { name: "Restore" }).first().click();
    await expect.poll(() => requests.restore).toBe(1);
    await expect(page.getByText("restore command planned")).toBeVisible();
    await expect(page.getByText("krtour_map_staging")).toBeVisible();

    // hot-swap command plan
    await page.getByRole("button", { name: "Swap" }).first().click();
    await expect.poll(() => requests.swap).toBe(1);
    await expect(page.getByText("swap command planned")).toBeVisible();
  });
});
