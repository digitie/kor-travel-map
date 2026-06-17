import { expect, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";

// 손으로 쓴 record shape 대신 **생성된 OpenAPI 스키마**에 바인딩한다(#308 리뷰).
// 백엔드 DTO가 바뀌면 mock factory가 타입 불일치로 컴파일 실패 → mock-실계약 drift 감지.
//
// 이 파일은 admin-ops.spec.ts의 `/v1/admin/backups` smoke(목록 렌더) +
// `operations (T-218c)` plan-only(execute 미체크) 경로를 **중복하지 않는다**.
// 추가 depth만 다룬다:
//   1. execute:true 가 3개 체크박스(백업/restore/swap)를 통해 payload에 흐르는지,
//   2. command_enabled=true 배지가 보여도 체크박스 미선택이면 execute:false 인지(가드 불변식),
//   3. 빈 목록(empty state)과 list GET 500 error alert.
// (PROMPT HINT 정정: backups-client.tsx에 window.confirm/dialog 가드는 존재하지 않으므로
//  page.once("dialog", ...)는 등록하지 않는다. 대신 execute opt-in 불변식으로 대체한다.)

type BackupRecord = components["schemas"]["BackupRecord"];
type BackupListResponse = components["schemas"]["BackupListResponse"];
type BackupOperationResponse = components["schemas"]["BackupOperationResponse"];
type BackupRunRequest = components["schemas"]["BackupRunRequest"];
type RestoreRunRequest = components["schemas"]["RestoreRunRequest"];
type RestoreSwapRequest = components["schemas"]["RestoreSwapRequest"];

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
    restore_url: `/v1/admin/restore/${MOCK_BACKUP_ID}`,
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

function makeBackupOp(
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
    meta: { duration_ms: 1, request_id: "e2e-backup-op" },
  };
}

test.describe("admin/backups execute depth", () => {
  test("execute branch — backup/restore/swap send execute:true via the three checkboxes", async ({
    page,
  }) => {
    // 각 mutation의 마지막 요청 body를 캡처해 payload 단언에 사용한다.
    const captured: {
      backup: BackupRunRequest | null;
      restore: RestoreRunRequest | null;
      swap: RestoreSwapRequest | null;
    } = { backup: null, restore: null, swap: null };

    // '**/v1/admin/backups**' glob은 list GET + backup POST 둘 다 매칭(restore는 미매칭).
    await page.route("**/v1/admin/backups**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());

      if (request.method() === "GET" && url.pathname === "/v1/admin/backups") {
        // command_enabled:true → Badge가 'execute enabled'를 보인다.
        await fulfillJson(route, makeBackupList({ command_enabled: true }));
        return;
      }
      if (request.method() === "POST" && url.pathname === "/v1/admin/backups") {
        captured.backup = request.postDataJSON() as BackupRunRequest;
        await fulfillJson(
          route,
          makeBackupOp({
            message: "backup command executed",
            operation: "backup",
          }),
        );
        return;
      }
      throw new Error(`Unhandled backups route: ${request.method()} ${url}`);
    });

    // '**/v1/admin/restore/**' glob은 restore POST + /swap POST 둘 다 매칭.
    // admin-ops 처럼 pathname.endsWith('/swap')으로 분기한다.
    await page.route("**/v1/admin/restore/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());

      if (url.pathname.endsWith("/swap")) {
        captured.swap = request.postDataJSON() as RestoreSwapRequest;
        await fulfillJson(
          route,
          makeBackupOp({
            message: "swap command executed",
            operation: "swap",
          }),
        );
        return;
      }
      captured.restore = request.postDataJSON() as RestoreRunRequest;
      await fulfillJson(
        route,
        makeBackupOp({
          message: "restore command executed",
          operation: "restore",
          restore_targets: {
            app_db: "kor_travel_map_staging",
            dagster_db: "kor_travel_map_dagster_staging",
            rustfs_volume: "rustfs_staging",
          },
        }),
      );
    });

    await page.goto("/admin/backups");

    await expect(
      page.getByRole("heading", { level: 1, name: "Backups" }),
    ).toBeVisible();
    // command_enabled:true → Badge가 'plan only'가 아니라 'execute enabled'.
    await expect(page.getByText("execute enabled")).toBeVisible();
    await expect(page.getByText("plan only")).toHaveCount(0);

    // 첫 행이 렌더되어야 row-scoped 액션이 안전하다(strict mode: detail CardTitle과 동명 충돌 회피).
    const backupRow = page.getByRole("row", {
      name: new RegExp(MOCK_BACKUP_ID.slice(0, 12)),
    });
    await expect(backupRow).toBeVisible();

    // --- 1) 백업 execute:true ---
    // controlled native <input type=checkbox>는 .check()가 React onChange와 race할 수 있어
    // (DOM checked는 set되지만 setState 반영 전 submit하면 execute:false로 굳음) .click()로
    // onChange를 명시 발화시키고, DOM checked 반영(toBeChecked)을 readiness gate로 둔 뒤 submit한다.
    const executeBackupCheckbox = page.getByLabel("백업 command 실행");
    await expect(executeBackupCheckbox).toBeVisible();
    await executeBackupCheckbox.click();
    await expect(executeBackupCheckbox).toBeChecked();
    await page.getByRole("button", { name: "백업" }).click();

    await expect.poll(() => captured.backup).not.toBeNull();
    // backup_id는 input 미입력이므로 backupId.trim() || null → null.
    expect(captured.backup).toEqual({
      allow_running: false,
      backup_id: null,
      execute: true,
    });
    // 성공 결과는 polite live region(role=status)으로 안내된다(T-218e).
    await expect(
      page.getByRole("status").filter({ hasText: "backup command executed" }),
    ).toBeVisible();
    // 'completed' status(plan-only smoke의 'planned'와 구분)로 execute 경로임을 못박는다.
    await expect(page.getByText("backup / completed")).toBeVisible();

    // --- 2) restore execute:true ---
    const executeRestoreCheckbox = page.getByLabel("restore command 실행");
    await expect(executeRestoreCheckbox).toBeVisible();
    await executeRestoreCheckbox.click();
    await expect(executeRestoreCheckbox).toBeChecked();
    await backupRow.getByRole("button", { name: "Restore" }).click();

    await expect.poll(() => captured.restore).not.toBeNull();
    expect(captured.restore).toEqual({
      app_db: null,
      dagster_db: null,
      execute: true,
      recreate: false,
      rustfs_volume: null,
      skip_checksum: false,
      skip_rustfs: false,
    });
    await expect(
      page.getByRole("status").filter({ hasText: "restore command executed" }),
    ).toBeVisible();

    // --- 3) swap execute:true ---
    const executeSwapCheckbox = page.getByLabel("swap command 실행");
    await expect(executeSwapCheckbox).toBeVisible();
    await executeSwapCheckbox.click();
    await expect(executeSwapCheckbox).toBeChecked();
    await backupRow.getByRole("button", { name: "Swap" }).click();

    await expect.poll(() => captured.swap).not.toBeNull();
    expect(captured.swap).toEqual({
      app_db: null,
      apply: false,
      dagster_db: null,
      env_file: null,
      execute: true,
      note: null,
      operator: null,
      rustfs_volume: null,
      skip_verify: false,
    });
    await expect(
      page.getByRole("status").filter({ hasText: "swap command executed" }),
    ).toBeVisible();
  });

  test("plan-only default — execute:false when checkboxes untouched even with command_enabled=true", async ({
    page,
  }) => {
    let getCount = 0;
    let backupBody: BackupRunRequest | null = null;

    await page.route("**/v1/admin/backups**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());

      if (request.method() === "GET" && url.pathname === "/v1/admin/backups") {
        getCount += 1;
        await fulfillJson(route, makeBackupList({ command_enabled: true }));
        return;
      }
      if (request.method() === "POST" && url.pathname === "/v1/admin/backups") {
        backupBody = request.postDataJSON() as BackupRunRequest;
        await fulfillJson(
          route,
          makeBackupOp({ message: "backup command planned", status: "planned" }),
        );
        return;
      }
      throw new Error(`Unhandled backups route: ${request.method()} ${url}`);
    });

    await page.goto("/admin/backups");

    // command_enabled:true 배지가 보이지만 체크박스는 건드리지 않는다.
    await expect(page.getByText("execute enabled")).toBeVisible();
    await expect(
      page.getByRole("row", { name: new RegExp(MOCK_BACKUP_ID.slice(0, 12)) }),
    ).toBeVisible();

    // 유일한 비-체크박스 입력(backup id)을 채워 payload 흐름을 확인한다.
    await page.getByLabel("backup id").fill("manual-backup-001");
    await page.getByRole("button", { name: "백업" }).click();

    await expect.poll(() => backupBody).not.toBeNull();
    // 불변식: execute는 순수 클라이언트 체크박스 상태이며 server command_enabled가
    // 자동으로 켜지 않는다 → execute:false. backup_id는 trim된 입력값.
    expect(backupBody).toEqual({
      allow_running: false,
      backup_id: "manual-backup-001",
      execute: false,
    });

    // onSuccess가 ['admin','backups'] 무효화 → 활성 observer가 재조회한다.
    // staleTime:10s + react-query coalescing 때문에 정확한 카운트는 불안정 → >=2 만 단언.
    await expect.poll(() => getCount).toBeGreaterThanOrEqual(2);
  });

  test("empty state — no artifacts renders empty message + plan only badge", async ({
    page,
  }) => {
    await page.route("**/v1/admin/backups**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());

      if (request.method() === "GET" && url.pathname === "/v1/admin/backups") {
        await fulfillJson(
          route,
          makeBackupList({ command_enabled: false, items: [] }),
        );
        return;
      }
      throw new Error(`Unhandled backups route: ${request.method()} ${url}`);
    });

    await page.goto("/admin/backups");

    await expect(
      page.getByRole("heading", { level: 1, name: "Backups" }),
    ).toBeVisible();
    // items.length=0 → DataTable emptyMessage.
    await expect(page.getByText("백업이 없습니다.")).toBeVisible();
    // backups.data는 있고 items.length=0 → '0 artifacts'.
    await expect(page.getByText("0 artifacts")).toBeVisible();
    // command_enabled:false → 'plan only' 배지.
    await expect(page.getByText("plan only")).toBeVisible();
    await expect(page.getByText("execute enabled")).toHaveCount(0);

    // selected = items.find ?? items[0] ?? null → null → BackupDetail 빈 카드.
    // (admin-ops smoke는 첫 행 auto-select 상세를 보므로 이 빈 분기는 미커버.)
    await expect(
      page.getByRole("heading", { name: "선택 없음" }),
    ).toBeVisible();
    await expect(
      page.getByText(
        "백업 행을 선택하면 manifest와 restore target을 확인합니다.",
      ),
    ).toBeVisible();
  });

  test("error alert — list GET 500 surfaces destructive role=alert", async ({
    page,
  }) => {
    // useBackups retry:1 → 500 list GET은 두 번 요청된다. 매 호출 500을 돌려 결정성 확보.
    await page.route("**/v1/admin/backups**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());

      if (request.method() === "GET" && url.pathname === "/v1/admin/backups") {
        await fulfillJson(route, { detail: "backup root unavailable" }, 500);
        return;
      }
      throw new Error(`Unhandled backups route: ${request.method()} ${url}`);
    });

    await page.goto("/admin/backups");

    await expect(
      page.getByRole("heading", { level: 1, name: "Backups" }),
    ).toBeVisible();

    // activeError = backups.error → destructive Alert(role=alert, assertive).
    const errorAlert = page.getByRole("alert");
    await expect(errorAlert).toBeVisible();
    await expect(page.getByText("backup/restore 요청 실패")).toBeVisible();
    // ApiClientError 메시지는 한국어 prefix + body 추가:
    // 'GET /v1/admin/backups 실패 (HTTP 500) <body>' → substring만 단언.
    await expect(page.getByText(/실패 \(HTTP 500\)/)).toBeVisible();

    // backups.data undefined → items=[] → DataTable이 빈 메시지를 alert와 공존 렌더.
    await expect(page.getByText("백업이 없습니다.")).toBeVisible();
  });
});
