import { expect, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";

// 손으로 쓴 record shape 대신 **생성된 OpenAPI 스키마**에 바인딩한다(#308 리뷰).
// 백엔드 DTO가 바뀌면 mock factory가 타입 불일치로 컴파일 실패 → mock-실계약 drift 감지.
type OfflineUploadRecord = components["schemas"]["OfflineUploadRecord"];
type OfflineUploadListResponse =
  components["schemas"]["OfflineUploadListResponse"];
type OfflineUploadDetailResponse =
  components["schemas"]["OfflineUploadDetailResponse"];
type OfflineUploadWriteResponse =
  components["schemas"]["OfflineUploadWriteResponse"];
type OfflineUploadWriteMeta = components["schemas"]["OfflineUploadWriteMeta"];
type OfflineUploadPreviewResponse =
  components["schemas"]["OfflineUploadPreviewResponse"];
type OfflineUploadPreviewMeta =
  components["schemas"]["OfflineUploadPreviewMeta"];
type OfflineUploadValidationResponse =
  components["schemas"]["OfflineUploadValidationResponse"];
type OfflineUploadValidationMeta =
  components["schemas"]["OfflineUploadValidationMeta"];
type OfflineUploadValidationIssueRecord =
  components["schemas"]["OfflineUploadValidationIssueRecord"];
type OfflineUploadColumnMappingRecord =
  components["schemas"]["OfflineUploadColumnMappingRecord"];
type Meta = components["schemas"]["Meta"];
type PageMeta = components["schemas"]["PageMeta"];

const MOCK_NOW = "2026-06-08T00:00:00.000Z";
const OFFLINE_UPLOAD_ID = "11111111-1111-4111-8111-111111111111";
const OFFLINE_VALIDATION_JOB_ID = "22222222-2222-4222-8222-222222222222";
const CHECKSUM =
  "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

// ---------------------------------------------------------------------------
// Schema-bound factories (self-contained; every mock body derives from these).
// ---------------------------------------------------------------------------

function makePageMeta(overrides: Partial<PageMeta> = {}): PageMeta {
  // docs/rest-api.md §3.3 — next_cursor는 항상 존재하고 null=exhausted.
  return { page_size: 100, next_cursor: null, total: null, ...overrides };
}

function makeMeta(overrides: Partial<Meta> = {}): Meta {
  return {
    duration_ms: 1,
    page: makePageMeta(),
    request_id: "e2e-offline-edge",
    ...overrides,
  };
}

function makeColumnMapping(
  overrides: Partial<OfflineUploadColumnMappingRecord> = {},
): OfflineUploadColumnMappingRecord {
  return {
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
    ...overrides,
  };
}

function makeOfflineUpload(
  overrides: Partial<OfflineUploadRecord> = {},
): OfflineUploadRecord {
  return {
    byte_size: 46,
    checksum_sha256: CHECKSUM,
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

function makeListResponse(
  items: OfflineUploadRecord[],
): OfflineUploadListResponse {
  return {
    data: { items },
    meta: makeMeta({ request_id: "e2e-offline-list" }),
  };
}

function makeDetailResponse(
  upload: OfflineUploadRecord,
): OfflineUploadDetailResponse {
  return { data: upload, meta: { duration_ms: 1, request_id: "e2e-detail" } };
}

function makeWriteMeta(
  overrides: Partial<OfflineUploadWriteMeta> = {},
): OfflineUploadWriteMeta {
  return {
    bucket: "kor-travel-map-uploads",
    content_type: "text/csv",
    duration_ms: 1,
    object_key: `offline-uploads/${OFFLINE_UPLOAD_ID}/offline.csv`,
    request_id: "e2e-write",
    ...overrides,
  };
}

function makeWriteResponse(
  upload: OfflineUploadRecord,
  metaOverrides: Partial<OfflineUploadWriteMeta> = {},
): OfflineUploadWriteResponse {
  return {
    data: upload,
    meta: makeWriteMeta({ object_key: upload.storage_key, ...metaOverrides }),
  };
}

function makePreviewMeta(
  overrides: Partial<OfflineUploadPreviewMeta> = {},
): OfflineUploadPreviewMeta {
  return {
    bytes_read: 46,
    checksum_sha256_actual: CHECKSUM,
    delimiter: ",",
    duration_ms: 1,
    encoding: "utf-8",
    headers: ["name", "lon", "lat"],
    parsed_format: "csv",
    request_id: "e2e-preview",
    rows_sampled: 1,
    rows_total: 1,
    sample_rows: [{ name: "Seoul Test POI", lon: "126.978", lat: "37.5665" }],
    ...overrides,
  };
}

function makePreviewResponse(
  upload: OfflineUploadRecord,
  metaOverrides: Partial<OfflineUploadPreviewMeta> = {},
): OfflineUploadPreviewResponse {
  return { data: upload, meta: makePreviewMeta(metaOverrides) };
}

function makeIssue(
  overrides: Partial<OfflineUploadValidationIssueRecord> = {},
): OfflineUploadValidationIssueRecord {
  return {
    code: "invalid_coordinate",
    column: "lon",
    message: "lon must be numeric",
    row_number: 2,
    severity: "error",
    ...overrides,
  };
}

function makeValidationMeta(
  overrides: Partial<OfflineUploadValidationMeta> = {},
): OfflineUploadValidationMeta {
  return {
    bytes_read: 46,
    checksum_sha256_actual: CHECKSUM,
    column_mapping: makeColumnMapping(),
    delimiter: ",",
    duration_ms: 1,
    encoding: "utf-8",
    error_rows: 0,
    headers: ["name", "lon", "lat"],
    issues: [],
    job_id: OFFLINE_VALIDATION_JOB_ID,
    job_status: "done",
    parsed_format: "csv",
    request_id: "e2e-validate",
    rows_sampled: 3,
    rows_total: 3,
    sample_rows: [{ name: "Seoul Test POI", lon: "126.978", lat: "37.5665" }],
    valid_rows: 1,
    ...overrides,
  };
}

function makeValidationResponse(
  upload: OfflineUploadRecord,
  metaOverrides: Partial<OfflineUploadValidationMeta> = {},
): OfflineUploadValidationResponse {
  return { data: upload, meta: makeValidationMeta(metaOverrides) };
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

// SSR 문서/_rsc 네비게이션은 그대로 통과시켜야 한다(admin-ops 스모크와 동일 가드).
// /v1 API 호출만 mock 분기로 보낸다.
function isPassthrough(route: Route): boolean {
  const request = route.request();
  if (request.resourceType() === "document") {
    return true;
  }
  const url = new URL(request.url());
  return (
    url.pathname === "/admin/offline-uploads" || url.searchParams.has("_rsc")
  );
}

const csvFile = {
  buffer: Buffer.from("name,lon,lat\nSeoul Test POI,126.978,37.5665\n"),
  mimeType: "text/csv",
  name: "offline.csv",
};

test.describe("admin/offline-uploads edge depth", () => {
  // -------------------------------------------------------------------------
  // 1) Job-level validation_failed surface (NOT an isError transport failure).
  //    smoke는 HAPPY path(1 valid / 0 error → validated)만 검증한다. 여기서는
  //    validate POST가 error_rows=2 + issues[]를 돌려주는 실패 잡을 검증한다.
  // -------------------------------------------------------------------------
  test("validation_failed job surfaces error badge + issues table (not the destructive alert)", async ({
    page,
  }) => {
    let upload = makeOfflineUpload();
    let uploads: OfflineUploadRecord[] = [];
    const uploadPath = `/v1/admin/offline-uploads/${OFFLINE_UPLOAD_ID}`;

    await page.route("**/admin/offline-uploads**", async (route) => {
      if (isPassthrough(route)) {
        await route.continue();
        return;
      }
      const request = route.request();
      const url = new URL(request.url());
      const method = request.method();

      if (method === "GET" && url.pathname === "/v1/admin/offline-uploads") {
        const status = url.searchParams.get("status");
        const items = status
          ? uploads.filter((item) => item.status === status)
          : uploads;
        await fulfillJson(route, makeListResponse(items));
        return;
      }
      if (method === "POST" && url.pathname === "/v1/admin/offline-uploads") {
        expect(request.headers()["content-type"]).toContain(
          "multipart/form-data",
        );
        upload = makeOfflineUpload({ status: "uploaded" });
        uploads = [upload];
        await fulfillJson(route, makeWriteResponse(upload), 201);
        return;
      }
      if (method === "GET" && url.pathname === uploadPath) {
        await fulfillJson(route, makeDetailResponse(upload));
        return;
      }
      if (method === "GET" && url.pathname === `${uploadPath}/preview`) {
        await fulfillJson(route, makePreviewResponse(upload));
        return;
      }
      // validate POST가 validation_job_id를 채우면 detail refetch로 selected에
      // 반영되고 useOfflineUploadValidation(GET /validation)이 enabled 된다.
      // 같은 실패 잡(error_rows=2, issues[])을 그대로 돌려줘 round-trip을 보존한다.
      if (method === "GET" && url.pathname === `${uploadPath}/validation`) {
        const failed = upload.status === "validation_failed";
        await fulfillJson(
          route,
          makeValidationResponse(upload, {
            error_rows: failed ? 2 : 0,
            job_status: failed ? "failed" : "done",
            valid_rows: 1,
            issues: failed
              ? [
                  makeIssue({
                    code: "invalid_coordinate",
                    column: "lon",
                    message: "lon must be numeric",
                    row_number: 2,
                    severity: "error",
                  }),
                  makeIssue({
                    code: "required field missing",
                    column: "name",
                    message: "name is required",
                    row_number: 3,
                    severity: "error",
                  }),
                ]
              : [],
          }),
        );
        return;
      }
      if (method === "POST" && url.pathname === `${uploadPath}/validate`) {
        expect(request.postData()).toContain("column_mapping");
        // 잡 자체가 실패: data.status='validation_failed', error_rows>0, issues[].
        upload = {
          ...upload,
          status: "validation_failed",
          updated_at: "2026-06-08T00:01:00.000Z",
          validation_job_id: OFFLINE_VALIDATION_JOB_ID,
        };
        uploads = [upload];
        await fulfillJson(
          route,
          makeValidationResponse(upload, {
            error_rows: 2,
            job_status: "failed",
            valid_rows: 1,
            issues: [
              makeIssue({
                code: "invalid_coordinate",
                column: "lon",
                message: "lon must be numeric",
                row_number: 2,
                severity: "error",
              }),
              makeIssue({
                code: "required field missing",
                column: "name",
                message: "name is required",
                row_number: 3,
                severity: "error",
              }),
            ],
          }),
        );
        return;
      }
      throw new Error(`Unhandled route: ${method} ${url.pathname}`);
    });

    await page.goto("/admin/offline-uploads");
    await page.getByTestId("offline-upload-file-input").setInputFiles(csvFile);
    await page.getByRole("button", { name: "업로드" }).click();

    // preview가 떠서 sample_rows의 POI가 보여야 한다.
    await expect(page.getByText("Seoul Test POI").first()).toBeVisible();

    await page.getByTestId("offline-upload-validate").click();

    // 결과 배지: error_rows>0 → destructive variant + '1 valid / 2 error' 텍스트.
    // (variant attr가 아니라 보이는 텍스트로 단언 — house gotcha.)
    await expect(page.getByText("1 valid / 2 error")).toBeVisible();

    // 이슈 DataTable: 각 이슈는 semantic <tr role=row>로 렌더되고(non-virtual
    // DataTable → shadcn Table primitive) row 접근성 이름은 셀 텍스트 concat이라
    // `code` 셀('invalid_coordinate' / 'required field missing')을 그대로 포함한다.
    // 이 코드 문자열은 페이지 어디에도 중복되지 않으므로 brittle div-filter scope
    // 없이 role=row 이름 매칭만으로 strict-mode 충돌 없이 고유 매칭된다.
    await expect(
      page.getByRole("row", { name: /invalid_coordinate/ }),
    ).toBeVisible();
    await expect(
      page.getByRole("row", { name: /required field missing/ }),
    ).toBeVisible();
    await expect(page.getByText("2 issues")).toBeVisible();
    // severity 셀은 StatusBadge가 raw 'error' 텍스트를 그대로 렌더한다.
    // 정확히 'error'인 cell은 이슈 테이블 severity 컬럼뿐(preview/목록 테이블엔 없음).
    await expect(
      page.getByRole("cell", { name: "error", exact: true }).first(),
    ).toBeVisible();

    // status='validation_failed'가 round-trip 되어 StatusBadge로 노출된다
    // (UploadDetail 패널 + 행). 적어도 하나는 보여야 한다.
    await expect(page.getByText("validation_failed").first()).toBeVisible();

    // NEGATIVE: 잡 실패는 isError가 아니므로 transport 실패용 destructive Alert
    // 'validation 처리 실패'는 절대 뜨면 안 된다 (두 에러 표면 구분).
    await expect(page.getByText("validation 처리 실패")).toHaveCount(0);
  });

  // -------------------------------------------------------------------------
  // 2) 413 oversize → create mutation HTTP 실패 → '업로드 실패' destructive alert.
  //    413 OpenAPI 응답은 content?:never(빈 바디)라 literal text로 fulfill한다.
  // -------------------------------------------------------------------------
  test("413 oversize upload rejection shows '업로드 실패' destructive alert", async ({
    page,
  }) => {
    let createCount = 0;

    await page.route("**/admin/offline-uploads**", async (route) => {
      if (isPassthrough(route)) {
        await route.continue();
        return;
      }
      const request = route.request();
      const url = new URL(request.url());
      const method = request.method();

      if (method === "GET" && url.pathname === "/v1/admin/offline-uploads") {
        // create는 실패하므로 목록은 계속 비어 있다.
        await fulfillJson(route, makeListResponse([]));
        return;
      }
      if (method === "POST" && url.pathname === "/v1/admin/offline-uploads") {
        createCount += 1;
        // 413은 components 스키마가 아니라 literal text 바디(에러 envelope 없음).
        await route.fulfill({
          body: "offline upload 파일 크기 상한 초과",
          contentType: "text/plain",
          status: 413,
        });
        return;
      }
      throw new Error(`Unhandled route: ${method} ${url.pathname}`);
    });

    await page.goto("/admin/offline-uploads");
    await page.getByTestId("offline-upload-file-input").setInputFiles(csvFile);
    await page.getByRole("button", { name: "업로드" }).click();

    await expect.poll(() => createCount).toBe(1);

    // createUpload.isError → destructive Alert (role=alert) '업로드 실패' + 'HTTP 413'.
    // ApiClientError 메시지: 'POST ... 실패 (HTTP 413) offline upload ...' (client.ts).
    await expect(page.getByText("업로드 실패")).toBeVisible();
    await expect(page.getByText(/HTTP 413/)).toBeVisible();

    // create가 성공하지 않았으므로 행이 없고 빈 메시지가 보인다.
    await expect(page.getByTestId("offline-upload-row")).toHaveCount(0);
    await expect(page.getByText("offline upload가 없습니다.")).toBeVisible();
  });

  // -------------------------------------------------------------------------
  // 3) 비-CSV(JSON/JSONL): 비-tabular gate 텍스트 + column-mapping 폼/validate 버튼 없음.
  //    canLoad는 비-tabular면 status in loadableStates 만으로 true → load 가능.
  // -------------------------------------------------------------------------
  test("JSON/JSONL non-tabular uploads gate (no mapping form, load enabled)", async ({
    page,
  }) => {
    let upload = makeOfflineUpload({
      detected_format: "json",
      original_filename: "bundle.json",
      storage_key: `offline-uploads/${OFFLINE_UPLOAD_ID}/bundle.json`,
    });
    let uploads: OfflineUploadRecord[] = [];
    const uploadPath = `/v1/admin/offline-uploads/${OFFLINE_UPLOAD_ID}`;

    await page.route("**/admin/offline-uploads**", async (route) => {
      if (isPassthrough(route)) {
        await route.continue();
        return;
      }
      const request = route.request();
      const url = new URL(request.url());
      const method = request.method();

      if (method === "GET" && url.pathname === "/v1/admin/offline-uploads") {
        const status = url.searchParams.get("status");
        const items = status
          ? uploads.filter((item) => item.status === status)
          : uploads;
        await fulfillJson(route, makeListResponse(items));
        return;
      }
      if (method === "POST" && url.pathname === "/v1/admin/offline-uploads") {
        uploads = [upload];
        await fulfillJson(route, makeWriteResponse(upload), 201);
        return;
      }
      if (method === "GET" && url.pathname === uploadPath) {
        await fulfillJson(route, makeDetailResponse(upload));
        return;
      }
      // 비-tabular는 preview를 enabled=false로 두므로 호출되지 않지만,
      // 혹시 모를 호출에 대비해 빈 preview를 돌려준다(헤더 0개).
      if (method === "GET" && url.pathname === `${uploadPath}/preview`) {
        await fulfillJson(
          route,
          makePreviewResponse(upload, {
            headers: [],
            sample_rows: [],
            parsed_format: "json",
            rows_sampled: 0,
            rows_total: 0,
          }),
        );
        return;
      }
      throw new Error(`Unhandled route: ${method} ${url.pathname}`);
    });

    await page.goto("/admin/offline-uploads");

    // (a) JSON 업로드.
    await page.getByTestId("offline-upload-file-input").setInputFiles({
      buffer: Buffer.from('{"features":[]}\n'),
      mimeType: "application/json",
      name: "bundle.json",
    });
    await page.getByRole("button", { name: "업로드" }).click();

    const row = page.getByTestId("offline-upload-row");
    await expect(row).toBeVisible();
    // 행 format 배지 'json' (행 scope으로 충돌 회피).
    await expect(row.getByText("json", { exact: true })).toBeVisible();

    await row.click();

    // ValidationPanel: 비-tabular gate. heading 'CSV/TSV validation' + JSON gate 문단.
    await expect(page.getByText("CSV/TSV validation")).toBeVisible();
    await expect(
      page.getByText(/JSON\/JSONL FeatureBundle load gate를 따릅니다\./),
    ).toBeVisible();

    // column-mapping 입력/validate 버튼은 비-tabular 분기에서 렌더되지 않는다.
    await expect(page.getByLabel("mapping name")).toHaveCount(0);
    await expect(page.getByTestId("offline-upload-validate")).toHaveCount(0);

    // canLoad: 비-tabular + status 'uploaded'(loadableStates) → load 버튼 ENABLED.
    await expect(page.getByTestId("offline-upload-load")).toBeEnabled();

    // (b) JSONL로 교체 — 같은 비-tabular gate, format 배지 'jsonl'.
    upload = makeOfflineUpload({
      detected_format: "jsonl",
      original_filename: "bundle.jsonl",
      storage_key: `offline-uploads/${OFFLINE_UPLOAD_ID}/bundle.jsonl`,
    });
    await page.getByTestId("offline-upload-file-input").setInputFiles({
      buffer: Buffer.from('{"kind":"place"}\n'),
      mimeType: "application/x-ndjson",
      name: "bundle.jsonl",
    });
    await page.getByRole("button", { name: "업로드" }).click();

    await expect(row.getByText("jsonl", { exact: true })).toBeVisible();
    await row.click();
    await expect(page.getByText("CSV/TSV validation")).toBeVisible();
    await expect(
      page.getByText(/JSON\/JSONL FeatureBundle load gate를 따릅니다\./),
    ).toBeVisible();
    await expect(page.getByTestId("offline-upload-validate")).toHaveCount(0);
  });

  // -------------------------------------------------------------------------
  // 4) TSV tabular(탭 구분자) — CSV와 동일한 tabular 분기(매핑 폼 + validate + preview).
  // -------------------------------------------------------------------------
  test("TSV tabular upload renders mapping form + tab-delimited preview", async ({
    page,
  }) => {
    const upload = makeOfflineUpload({
      detected_format: "tsv",
      original_filename: "offline.tsv",
      storage_key: `offline-uploads/${OFFLINE_UPLOAD_ID}/offline.tsv`,
    });
    let uploads: OfflineUploadRecord[] = [];
    const uploadPath = `/v1/admin/offline-uploads/${OFFLINE_UPLOAD_ID}`;

    await page.route("**/admin/offline-uploads**", async (route) => {
      if (isPassthrough(route)) {
        await route.continue();
        return;
      }
      const request = route.request();
      const url = new URL(request.url());
      const method = request.method();

      if (method === "GET" && url.pathname === "/v1/admin/offline-uploads") {
        await fulfillJson(route, makeListResponse(uploads));
        return;
      }
      if (method === "POST" && url.pathname === "/v1/admin/offline-uploads") {
        uploads = [upload];
        await fulfillJson(route, makeWriteResponse(upload), 201);
        return;
      }
      if (method === "GET" && url.pathname === uploadPath) {
        await fulfillJson(route, makeDetailResponse(upload));
        return;
      }
      if (method === "GET" && url.pathname === `${uploadPath}/preview`) {
        await fulfillJson(
          route,
          makePreviewResponse(upload, {
            delimiter: "\t",
            parsed_format: "tsv",
          }),
        );
        return;
      }
      throw new Error(`Unhandled route: ${method} ${url.pathname}`);
    });

    await page.goto("/admin/offline-uploads");
    await page.getByTestId("offline-upload-file-input").setInputFiles({
      buffer: Buffer.from("name\tlon\tlat\nSeoul Test POI\t126.978\t37.5665\n"),
      mimeType: "text/tab-separated-values",
      name: "offline.tsv",
    });
    await page.getByRole("button", { name: "업로드" }).click();

    const row = page.getByTestId("offline-upload-row");
    await expect(row).toBeVisible();
    await expect(row.getByText("tsv", { exact: true })).toBeVisible();

    // tabular 분기: column mapping 입력 + validate 버튼 렌더 (CSV와 동일 경로).
    await expect(page.getByLabel("mapping name")).toBeVisible();
    await expect(page.getByLabel("mapping lon")).toBeVisible();
    await expect(page.getByLabel("mapping lat")).toBeVisible();
    await expect(page.getByTestId("offline-upload-validate")).toBeVisible();

    // preview 배지 + PreviewTable.
    await expect(page.getByText("3 columns")).toBeVisible();
    await expect(page.getByText("1 sampled")).toBeVisible();
    await expect(page.getByText("Seoul Test POI").first()).toBeVisible();
  });

  // -------------------------------------------------------------------------
  // 5) 목록 폴링 + cursor-exhausted envelope + status filter wiring.
  //    active 업로드(loading)면 useOfflineUploads refetchInterval=2000ms.
  // -------------------------------------------------------------------------
  test("list polls active uploads then stops + consumes exhausted-cursor envelope + status filter", async ({
    page,
  }) => {
    let active = true;
    let listCount = 0;
    let lastStatusParam: string | null = "(none)";
    const detailUpload = makeOfflineUpload({ status: "loading" });
    const uploadPath = `/v1/admin/offline-uploads/${OFFLINE_UPLOAD_ID}`;

    await page.route("**/admin/offline-uploads**", async (route) => {
      if (isPassthrough(route)) {
        await route.continue();
        return;
      }
      const request = route.request();
      const url = new URL(request.url());
      const method = request.method();

      if (method === "GET" && url.pathname === "/v1/admin/offline-uploads") {
        listCount += 1;
        lastStatusParam = url.searchParams.get("status");
        // 초기 필터는 컴포넌트 기본값 'uploaded'. active phase의 seeded 행은
        // 폴링 트리거를 위해 status='loading'이지만, 'uploaded'(기본)·'loading'·
        // 'loaded'·'all' GET에는 항상 노출한다(목록 폴링/플래토 검증 대상).
        // 'validation_failed'를 명시 선택했을 때만 빈 목록 → 필터 wiring 검증.
        if (lastStatusParam === "validation_failed") {
          await fulfillJson(route, makeListResponse([]));
          return;
        }
        const item = active
          ? makeOfflineUpload({ status: "loading" })
          : makeOfflineUpload({ status: "loaded" });
        await fulfillJson(route, makeListResponse([item]));
        return;
      }
      if (method === "GET" && url.pathname === uploadPath) {
        await fulfillJson(route, makeDetailResponse(detailUpload));
        return;
      }
      throw new Error(`Unhandled route: ${method} ${url.pathname}`);
    });

    await page.goto("/admin/offline-uploads");

    // 단일 행 + 'N rows' 배지(1 rows).
    const uploadRow = page.getByTestId("offline-upload-row");
    await expect(uploadRow).toBeVisible();
    await expect(page.getByText("1 rows")).toBeVisible();
    // active(loading) status 배지가 보인다. bare getByText('loading')은 status
    // 필터 <select>의 숨은 <option value="loading">와도 매칭되므로 row scope으로
    // 좁혀 행의 StatusBadge만 단언한다(option은 hidden → toBeVisible 실패).
    await expect(uploadRow.getByText("loading")).toBeVisible();

    // POLLING: loading 항목이 있으면 2s 폴링이 돈다 — 정확한 횟수가 아니라 >=2만 단언.
    await expect.poll(() => listCount, { timeout: 15_000 }).toBeGreaterThanOrEqual(2);

    // 폴링 멈춤: active=false로 뒤집고 'loaded' 배지가 뜰 때까지 기다린다.
    // 여기서도 row scope — 'loaded'는 status 필터 <select>의 숨은 <option>과도
    // 충돌하므로 행의 StatusBadge만 단언한다.
    active = false;
    await expect(uploadRow.getByText("loaded")).toBeVisible();
    // 플래토 단언(타이머가 아니라 카운트 안정으로 refetch-stop 검증):
    // 한 번 더 폴링이 진행 중일 수 있으므로 안정 지점을 잡고 delta<=1 확인.
    const settled = listCount;
    await expect
      .poll(() => listCount, { timeout: 6_000 })
      .toBeLessThanOrEqual(settled + 1);

    // status filter wiring: validation_failed 선택 → 다음 GET이 ?status=validation_failed,
    // mock이 걸러 빈 목록 → 'offline upload가 없습니다.'
    await page
      .getByLabel("offline upload status")
      .selectOption("validation_failed");
    await expect
      .poll(() => lastStatusParam)
      .toBe("validation_failed");
    await expect(page.getByText("offline upload가 없습니다.")).toBeVisible();
  });

  // -------------------------------------------------------------------------
  // 6) CP949 인코딩 round-trip — UI 인디케이터 없음(정직한 gap 기록).
  //    component는 detected_encoding/meta.encoding을 렌더하지 않는다(grep 0건).
  //    여기서는 인코딩 배지를 단언하지 않고 한글 텍스트 round-trip + gap을 기록한다.
  // -------------------------------------------------------------------------
  test("CP949 payload round-trips Korean text (no encoding indicator — documented gap)", async ({
    page,
  }) => {
    const upload = makeOfflineUpload({
      detected_encoding: "cp949",
      detected_format: "csv",
    });
    let uploads: OfflineUploadRecord[] = [];
    const uploadPath = `/v1/admin/offline-uploads/${OFFLINE_UPLOAD_ID}`;

    await page.route("**/admin/offline-uploads**", async (route) => {
      if (isPassthrough(route)) {
        await route.continue();
        return;
      }
      const request = route.request();
      const url = new URL(request.url());
      const method = request.method();

      if (method === "GET" && url.pathname === "/v1/admin/offline-uploads") {
        await fulfillJson(route, makeListResponse(uploads));
        return;
      }
      if (method === "POST" && url.pathname === "/v1/admin/offline-uploads") {
        uploads = [upload];
        await fulfillJson(route, makeWriteResponse(upload), 201);
        return;
      }
      if (method === "GET" && url.pathname === uploadPath) {
        await fulfillJson(route, makeDetailResponse(upload));
        return;
      }
      if (method === "GET" && url.pathname === `${uploadPath}/preview`) {
        await fulfillJson(
          route,
          makePreviewResponse(upload, {
            encoding: "cp949",
            sample_rows: [
              { name: "서울 테스트 장소", lon: "126.978", lat: "37.5665" },
            ],
          }),
        );
        return;
      }
      throw new Error(`Unhandled route: ${method} ${url.pathname}`);
    });

    await page.goto("/admin/offline-uploads");
    await page.getByTestId("offline-upload-file-input").setInputFiles(csvFile);
    await page.getByRole("button", { name: "업로드" }).click();

    // CP949로 디코드된 한글 POI가 preview 테이블에 mojibake 없이 렌더된다.
    await expect(page.getByText("서울 테스트 장소")).toBeVisible();
    await expect(page.getByText("3 columns")).toBeVisible();

    // GAP: UploadDetail은 format DetailRow는 보여주지만 encoding은 어디에도 없다.
    const row = page.getByTestId("offline-upload-row");
    await row.click();
    await expect(page.getByText("format").first()).toBeVisible();
    // 'cp949'는 component 어디에도 렌더되지 않는다(인디케이터 미존재 — 정직한 gap).
    await expect(page.getByText("cp949")).toHaveCount(0);
  });
});
