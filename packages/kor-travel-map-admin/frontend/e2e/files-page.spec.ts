import { expect, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";
import { bffApiPath } from "./bff-api-path";

/**
 * `/admin/files` 관리 파일 레지스트리 — route-mocked smoke spec (개편 D).
 *
 * 모든 mock body는 생성 OpenAPI 타입(components["schemas"][...])에 바인딩 →
 * 백엔드 DTO drift 시 컴파일 실패로 mock-실계약 drift를 잡는다.
 *
 * `**​/v1/admin/files**` glob으로 목록/요약/상세/이벤트/재스캔을 가로채고
 * normalized API path + method로 분기한다.
 *
 * NOTE: Playwright는 Windows 호스트에서만 실행된다(라이브 검증은 Windows/n150 런).
 */

type Meta = components["schemas"]["Meta"];
type ManagedFileModel = components["schemas"]["ManagedFileModel"];
type ManagedFileListResponse = components["schemas"]["ManagedFileListResponse"];
type ManagedFileSummaryResponse =
  components["schemas"]["ManagedFileSummaryResponse"];
type ManagedFileDetailResponse =
  components["schemas"]["ManagedFileDetailResponse"];
type ManagedFileRescanResponse =
  components["schemas"]["ManagedFileRescanResponse"];

const NOW = "2026-07-05T00:00:00.000Z";

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

function makeMeta(overrides: Partial<Meta> = {}): Meta {
  return {
    request_id: "e2e-files",
    duration_ms: 1,
    ...overrides,
  };
}

function makeFile(overrides: Partial<ManagedFileModel> = {}): ManagedFileModel {
  return {
    file_id: 1,
    storage_backend: "s3",
    location: "offline_uploads",
    path: "offline/uploads/festival-2026.csv",
    is_directory: false,
    kind: "upload",
    provider: "python-visitkorea-api",
    dataset_key: "festival",
    status: "active",
    orphan_reason: null,
    registered_by: "hook",
    byte_size: 20480,
    checksum_sha256: "abc123def456abc123def456abc123def456abc123def456",
    upload_id: "upload-77",
    origin_import_job_id: "job-a",
    origin_dagster_run_id: null,
    downloaded_at: NOW,
    last_loaded_at: NOW,
    last_seen_at: NOW,
    deleted_at: null,
    meta: { columns: 12, sync_scope: "default" },
    created_at: NOW,
    updated_at: NOW,
    ...overrides,
  };
}

function makeList(items: ManagedFileModel[]): ManagedFileListResponse {
  return {
    data: items,
    meta: makeMeta({
      page: { page_size: 50, total: items.length, next_cursor: null },
    }),
  };
}

function makeSummary(): ManagedFileSummaryResponse {
  return {
    data: {
      by_kind: [{ key: "upload", count: 1, byte_size: 20480, last_seen_at: NOW }],
      by_status: [{ key: "active", count: 1, byte_size: null, last_seen_at: NOW }],
      by_location: [
        { key: "offline_uploads", count: 1, byte_size: null, last_seen_at: NOW },
      ],
    },
    meta: makeMeta(),
  };
}

function makeDetail(file: ManagedFileModel): ManagedFileDetailResponse {
  return {
    data: {
      file,
      links: [
        { rel: "import-job", label: "적재 작업", href: "/ops/import-jobs/job-a" },
        {
          rel: "offline-upload",
          label: "오프라인 업로드",
          href: "/admin/offline-uploads/upload-77",
        },
      ],
      events: [
        {
          event_id: 10,
          file_id: file.file_id,
          event_kind: "downloaded",
          occurred_at: NOW,
          import_job_id: "job-a",
          dagster_run_id: null,
          actor: "hook:offline_upload",
          detail: {},
        },
        {
          event_id: 11,
          file_id: file.file_id,
          event_kind: "loaded",
          occurred_at: NOW,
          import_job_id: "job-a",
          dagster_run_id: null,
          actor: "hook:offline_upload",
          detail: {},
        },
      ],
    },
    meta: makeMeta(),
  };
}

function makeRescan(): ManagedFileRescanResponse {
  return {
    data: {
      results: [
        {
          location: "backup_root",
          scanned: 3,
          registered: 1,
          orphaned: 0,
          missing: 0,
          details: {},
        },
      ],
      deferred_locations: ["mois_source", "object_store"],
      note: "mois_source·S3 버킷 실체 스캔은 Dagster managed_file_scan job 소관입니다.",
    },
    meta: makeMeta(),
  };
}

async function installFilesMocks(
  page: import("@playwright/test").Page,
  file: ManagedFileModel,
) {
  await page.route("**/v1/admin/files**", async (route) => {
    const request = route.request();
    const path = bffApiPath(request.url());
    const method = request.method();

    if (method === "GET" && path === "/v1/admin/files/summary") {
      await fulfillJson(route, makeSummary());
      return;
    }
    if (path === "/v1/admin/files/rescan" && method === "POST") {
      await fulfillJson(route, makeRescan());
      return;
    }
    if (method === "GET" && path === "/v1/admin/files") {
      await fulfillJson(route, makeList([file]));
      return;
    }
    if (method === "GET" && path === `/v1/admin/files/${file.file_id}`) {
      await fulfillJson(route, makeDetail(file));
      return;
    }
    throw new Error(`Unhandled files route: ${method} ${path}`);
  });
}

test.describe("/admin/files — 파일 관리 (mocked)", () => {
  test("요약 칩·목록·상세 provenance가 렌더된다", async ({ page }) => {
    const file = makeFile();
    await installFilesMocks(page, file);

    await page.goto("/admin/files");

    await expect(
      page.getByRole("heading", { name: "파일 관리", exact: true }),
    ).toBeVisible();

    // 요약 카드
    await expect(page.getByText("레지스트리 요약")).toBeVisible();

    // 목록 행 — 파일명(basename) 렌더
    await expect(page.getByText("festival-2026.csv")).toBeVisible();

    // 행 클릭 → 상세 패널의 provenance 링크
    await page.getByRole("row", { name: /festival-2026\.csv/ }).click();
    await expect(
      page
        .getByRole("link", { name: "적재 작업", exact: true })
        .and(page.locator('a[href="/ops/import-jobs/job-a"]')),
    ).toHaveAttribute("href", "/ops/import-jobs/job-a");
    await expect(
      page
        .getByRole("link", { name: "오프라인 업로드", exact: true })
        .and(page.locator('a[href="/admin/offline-uploads/upload-77"]')),
    ).toHaveAttribute("href", "/admin/offline-uploads/upload-77");

    // 이력 타임라인
    await expect(
      page.getByRole("listitem").filter({ hasText: "다운로드" }),
    ).toBeVisible();
    await expect(
      page.getByRole("listitem").filter({ hasText: "적재" }),
    ).toBeVisible();
  });

  test("재스캔 버튼이 결과와 deferred 안내를 표시한다", async ({ page }) => {
    const file = makeFile();
    await installFilesMocks(page, file);

    let rescanPosted = false;
    page.on("request", (request) => {
      if (
        request.method() === "POST" &&
        bffApiPath(request.url()) === "/v1/admin/files/rescan"
      ) {
        rescanPosted = true;
      }
    });

    await page.goto("/admin/files");
    await page.getByRole("button", { name: "재스캔" }).click();

    await expect(page.getByText("재스캔 완료")).toBeVisible();
    await expect(
      page.getByText("Dagster managed_file_scan job 소관", { exact: false }),
    ).toBeVisible();
    expect(rescanPosted).toBe(true);
  });
});
