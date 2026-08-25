import { expect, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";
import { bffApiPath } from "./bff-api-path";

// 생성된 OpenAPI schema에 mock을 묶어 backup 계약 drift를 컴파일 단계에서 잡는다.
type BackupRecord = components["schemas"]["BackupRecord"];
type BackupListResponse = components["schemas"]["BackupListResponse"];
type BackupOperationResponse = components["schemas"]["BackupOperationResponse"];
type BackupRunRequest = components["schemas"]["BackupRunRequest"];

const MOCK_NOW = "2026-06-08T00:00:00.000Z";
const MOCK_BACKUP_ID = "backup-20260608-000000";

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

function makeBackup(overrides: Partial<BackupRecord> = {}): BackupRecord {
  return {
    backup_id: MOCK_BACKUP_ID,
    byte_size: 1024,
    checksum_count: 3,
    components: { app_db: "ok", dagster_db: "ok" },
    created_at_utc: MOCK_NOW,
    databases: { app: "kor_travel_map", dagster: "kor_travel_map_dagster" },
    detail_url: `/v1/admin/backups/${MOCK_BACKUP_ID}`,
    manifest_status: "complete",
    mode: "cold",
    object_storage: {},
    path: `/var/backups/${MOCK_BACKUP_ID}`,
    ...overrides,
  };
}

function makeBackupList(
  overrides: Partial<BackupListResponse["data"]> = {},
): BackupListResponse {
  return {
    data: {
      backup_root: "/var/backups",
      command_enabled: true,
      items: [makeBackup()],
      ...overrides,
    },
    meta: { duration_ms: 1, request_id: "e2e-backup-list" },
  };
}

function makeBackupOperation(
  overrides: Partial<BackupOperationResponse["data"]> = {},
): BackupOperationResponse {
  return {
    data: {
      backup_id: MOCK_BACKUP_ID,
      message: "backup command executed",
      operation: "backup",
      status: "completed",
      ...overrides,
    },
    meta: { duration_ms: 1, request_id: "e2e-backup-operation" },
  };
}

test.describe("admin/backups backup-only execution", () => {
  test("명시 opt-in만 execute:true로 전송하고 restore/swap control은 노출하지 않는다", async ({
    page,
  }) => {
    let backupBody: BackupRunRequest | null = null;
    await page.route("**/v1/admin/backups**", async (route) => {
      const request = route.request();
      const apiPath = bffApiPath(request.url());
      if (request.method() === "GET" && apiPath === "/v1/admin/backups") {
        await fulfillJson(route, makeBackupList());
        return;
      }
      if (request.method() === "POST" && apiPath === "/v1/admin/backups") {
        backupBody = request.postDataJSON() as BackupRunRequest;
        await fulfillJson(route, makeBackupOperation());
        return;
      }
      throw new Error(`Unhandled backups route: ${request.method()} ${apiPath}`);
    });

    await page.goto("/admin/backups");
    await expect(page.getByText("execute enabled")).toBeVisible();
    const executeBackup = page.getByLabel("백업 command 실행");
    await executeBackup.click();
    await expect(executeBackup).toBeChecked();
    await page.getByRole("button", { name: "백업", exact: true }).click();

    await expect.poll(() => backupBody).not.toBeNull();
    expect(backupBody).toEqual({
      allow_running: false,
      backup_id: null,
      execute: true,
    });
    await expect(
      page.getByRole("status").filter({ hasText: "backup command executed" }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Restore" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Swap" })).toHaveCount(0);
    await expect(page.getByLabel("restore command 실행")).toHaveCount(0);
    await expect(page.getByLabel("swap command 실행")).toHaveCount(0);
    await expect(
      page.getByText("restore와 hot swap은 300 recovery 형식이 정의될 때까지 지원하지 않습니다."),
    ).toBeVisible();
  });

  test("기본 plan은 execute:false를 유지한다", async ({ page }) => {
    let getCount = 0;
    let backupBody: BackupRunRequest | null = null;
    await page.route("**/v1/admin/backups**", async (route) => {
      const request = route.request();
      const apiPath = bffApiPath(request.url());
      if (request.method() === "GET" && apiPath === "/v1/admin/backups") {
        getCount += 1;
        await fulfillJson(route, makeBackupList({ command_enabled: true }));
        return;
      }
      if (request.method() === "POST" && apiPath === "/v1/admin/backups") {
        backupBody = request.postDataJSON() as BackupRunRequest;
        await fulfillJson(route, makeBackupOperation({ message: "backup command planned", status: "planned" }));
        return;
      }
      throw new Error(`Unhandled backups route: ${request.method()} ${apiPath}`);
    });

    await page.goto("/admin/backups");
    await page.getByLabel("backup id").fill("manual-backup-001");
    await page.getByRole("button", { name: "백업", exact: true }).click();

    await expect.poll(() => backupBody).not.toBeNull();
    expect(backupBody).toEqual({
      allow_running: false,
      backup_id: "manual-backup-001",
      execute: false,
    });
    await expect.poll(() => getCount).toBeGreaterThanOrEqual(2);
  });

  test("빈 목록과 목록 오류를 안전하게 표시한다", async ({ page }) => {
    await page.route("**/v1/admin/backups**", async (route) => {
      const request = route.request();
      const apiPath = bffApiPath(request.url());
      if (request.method() === "GET" && apiPath === "/v1/admin/backups") {
        await fulfillJson(route, makeBackupList({ command_enabled: false, items: [] }));
        return;
      }
      throw new Error(`Unhandled backups route: ${request.method()} ${apiPath}`);
    });

    await page.goto("/admin/backups");
    await expect(page.getByText("백업이 없습니다.")).toBeVisible();
    await expect(page.getByText("plan only")).toBeVisible();
    await expect(page.getByRole("heading", { name: "선택 없음" })).toBeVisible();
    await expect(
      page.getByText("백업 행을 선택하면 manifest와 보존 범위를 확인합니다."),
    ).toBeVisible();
  });
});
