import { expect, test, type Locator, type Page, type Response } from "@playwright/test";

const UI_TIMEOUT = 15_000;
const COMMAND_TIMEOUT = 45 * 60 * 1000;
const T = { timeout: UI_TIMEOUT } as const;

const EXECUTE_BACKUP_RESTORE = process.env.E2E_BACKUP_RESTORE_EXECUTE === "1";
const EXECUTE_SWAP_COMMAND =
  process.env.E2E_BACKUP_RESTORE_EXECUTE_SWAP === "1";
const EXECUTE_SWAP_APPLY =
  process.env.E2E_BACKUP_RESTORE_EXECUTE_SWAP_APPLY === "1";

type OperationBody = {
  data: {
    artifact?: {
      backup_id: string;
      checksum_count: number;
      manifest_status: string;
    } | null;
    backup_id: string;
    command?: {
      enabled: boolean;
      env: Record<string, string>;
    } | null;
    message: string;
    operation: "backup" | "restore" | "swap";
    restore_targets?: {
      app_db: string;
      dagster_db: string;
      rustfs_volume: string;
    } | null;
    status: "planned" | "completed" | "failed" | "manual_required";
  };
};

let createdBackupId: string | null = null;

test.describe.configure({ mode: "serial" });

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function uniqueBackupId(prefix: string, workerIndex: number): string {
  const random = Math.random().toString(36).slice(2, 8);
  return `${prefix}-${random}-${Date.now()}-${workerIndex}`;
}

function apiPath(response: Response): string {
  const pathname = new URL(response.url()).pathname;
  return pathname.startsWith("/api/proxy/")
    ? pathname.slice("/api/proxy".length)
    : pathname;
}

function isBackupResponse(response: Response): boolean {
  return (
    response.request().method() === "POST" &&
    apiPath(response) === "/v1/admin/backups"
  );
}

function isRestoreResponse(response: Response): boolean {
  const path = apiPath(response);
  return (
    response.request().method() === "POST" &&
    path.startsWith("/v1/admin/restore/") &&
    !path.endsWith("/swap")
  );
}

function isRestoreSwapResponse(response: Response): boolean {
  const path = apiPath(response);
  return (
    response.request().method() === "POST" &&
    path.startsWith("/v1/admin/restore/") &&
    path.endsWith("/swap")
  );
}

async function expectBackupsReady(page: Page): Promise<void> {
  await expect(
    page.getByRole("heading", { level: 1, name: "Backups" }),
  ).toBeVisible(T);
  await expect(page.getByText("백업 목록")).toBeVisible(T);
  await expect(
    page.getByRole("heading", { name: "실행 옵션" }),
  ).toBeVisible(T);
}

async function gotoBackups(page: Page): Promise<void> {
  await page.goto("/admin/backups");
  await expectBackupsReady(page);
}

async function readOperation(response: Response): Promise<OperationBody> {
  expect(response.status()).toBe(200);
  return (await response.json()) as OperationBody;
}

async function waitForPost(
  page: Page,
  predicate: (response: Response) => boolean,
): Promise<Response> {
  return page.waitForResponse(predicate, { timeout: COMMAND_TIMEOUT });
}

async function firstRestoreButton(page: Page): Promise<Locator> {
  const restoreButtons = page.getByRole("button", { name: "Restore" });
  const count = await restoreButtons.count();
  test.skip(count === 0, "live 대상에 backup artifact가 없어 restore/swap을 실행할 수 없음");
  return restoreButtons.first();
}

async function createdBackupRow(page: Page): Promise<Locator> {
  test.skip(!createdBackupId, "실제 backup 실행이 선행되지 않아 restore 대상 artifact가 없음");
  const row = page.getByRole("row", {
    name: new RegExp(escapeRegExp(createdBackupId!.slice(0, 20))),
  });
  await expect(row).toBeVisible({ timeout: UI_TIMEOUT });
  return row;
}

test.describe("/admin/backups live backup/restore operations", () => {
  test("실행 옵션 기본값 — 모든 host command opt-in이 꺼져 있다", async ({ page }) => {
    await gotoBackups(page);

    await expect(page.getByLabel("backup id")).toBeVisible(T);
    await expect(page.getByLabel("백업 command 실행")).not.toBeChecked();
    await expect(page.getByLabel("restore command 실행")).not.toBeChecked();
    await expect(page.getByLabel("staging 대상 재생성")).not.toBeChecked();
    await expect(page.getByLabel("swap command 실행")).not.toBeChecked();
    await expect(page.getByLabel("swap 즉시 적용")).not.toBeChecked();

    await expect(
      page.getByText(/plan only|execute enabled/).first(),
    ).toBeVisible(T);
  });

  test("잘못된 backup id — API 422과 UI 오류 alert를 표시한다", async ({ page }) => {
    await gotoBackups(page);
    await page.getByLabel("backup id").fill("invalid/backup-id");

    const responsePromise = waitForPost(page, isBackupResponse);
    await page.getByRole("button", { name: "백업" }).click();
    const response = await responsePromise;
    expect(response.status()).toBeGreaterThanOrEqual(400);

    const alert = page
      .getByRole("alert")
      .filter({ hasText: "backup/restore 요청 실패" });
    await expect(alert).toBeVisible(T);
    await expect(alert).toContainText(`HTTP ${response.status()}`);
  });

  test("backup plan — execute=false command env와 결과 live region을 확인한다", async ({
    page,
  }, testInfo) => {
    await gotoBackups(page);

    const backupId = uniqueBackupId("e2e-plan", testInfo.workerIndex);
    await page.getByLabel("backup id").fill(backupId);

    const responsePromise = waitForPost(page, isBackupResponse);
    await page.getByRole("button", { name: "백업" }).click();
    const body = await readOperation(await responsePromise);

    expect(body.data.operation).toBe("backup");
    expect(body.data.status).toBe("planned");
    expect(body.data.backup_id).toBe(backupId);
    expect(body.data.command?.env.KOR_TRAVEL_MAP_BACKUP_ID).toBe(backupId);
    expect(body.data.command?.env.KOR_TRAVEL_MAP_BACKUP_ALLOW_RUNNING).toBe("0");

    const result = page
      .getByRole("status")
      .filter({ hasText: "backup / planned" });
    await expect(result).toBeVisible(T);
    await expect(result).toContainText("백업 command plan을 생성했습니다.");
    await expect(result).toContainText(`KOR_TRAVEL_MAP_BACKUP_ID=${backupId}`);
  });

  test("backup execute — 실제 cold backup artifact를 생성하고 목록에 반영한다", async ({
    page,
  }, testInfo) => {
    test.skip(
      !EXECUTE_BACKUP_RESTORE,
      "E2E_BACKUP_RESTORE_EXECUTE=1일 때만 실제 backup command를 실행",
    );
    test.setTimeout(COMMAND_TIMEOUT);

    await gotoBackups(page);
    await expect(page.getByText("execute enabled")).toBeVisible(T);
    await expect(page.getByLabel("백업 command 실행")).not.toBeChecked();

    createdBackupId = uniqueBackupId("e2e-restore", testInfo.workerIndex);
    await page.getByLabel("backup id").fill(createdBackupId);
    await page.getByLabel("백업 command 실행").click();
    await expect(page.getByLabel("백업 command 실행")).toBeChecked();

    const responsePromise = waitForPost(page, isBackupResponse);
    await page.getByRole("button", { name: "백업" }).click();
    const body = await readOperation(await responsePromise);

    expect(body.data.operation).toBe("backup");
    expect(body.data.status).toBe("completed");
    expect(body.data.backup_id).toBe(createdBackupId);
    expect(body.data.artifact?.backup_id).toBe(createdBackupId);
    expect(body.data.artifact?.manifest_status).toBe("ok");
    expect(body.data.artifact?.checksum_count ?? 0).toBeGreaterThan(0);

    const result = page
      .getByRole("status")
      .filter({ hasText: "backup / completed" });
    await expect(result).toBeVisible(T);
    await expect(result).toContainText("백업 command 실행이 완료됐습니다.");

    await page.getByRole("button", { name: "새로고침" }).click();
    await createdBackupRow(page);
  });

  test("restore plan — artifact 기준 staging restore command plan을 확인한다", async ({
    page,
  }) => {
    await gotoBackups(page);

    const button =
      createdBackupId === null
        ? await firstRestoreButton(page)
        : (await createdBackupRow(page)).getByRole("button", { name: "Restore" });

    await expect(page.getByLabel("restore command 실행")).not.toBeChecked();
    await expect(page.getByLabel("staging 대상 재생성")).not.toBeChecked();

    const responsePromise = waitForPost(page, isRestoreResponse);
    await button.click();
    const body = await readOperation(await responsePromise);

    expect(body.data.operation).toBe("restore");
    expect(body.data.status).toBe("planned");
    expect(body.data.restore_targets?.app_db).toBeTruthy();
    expect(body.data.command?.env.KOR_TRAVEL_MAP_RESTORE_BACKUP_ID).toBe(
      body.data.backup_id,
    );
    expect(body.data.command?.env.KOR_TRAVEL_MAP_RESTORE_RECREATE).toBe("0");
    expect(body.data.command?.env.KOR_TRAVEL_MAP_RESTORE_SKIP_RUSTFS).toBe("0");

    const result = page
      .getByRole("status")
      .filter({ hasText: "restore / planned" });
    await expect(result).toBeVisible(T);
    await expect(result).toContainText(
      "staging restore command plan을 생성했습니다.",
    );
  });

  test("restore execute — 생성한 artifact를 staging DB/volume으로 실제 복구한다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_BACKUP_RESTORE,
      "E2E_BACKUP_RESTORE_EXECUTE=1일 때만 실제 restore command를 실행",
    );
    test.setTimeout(COMMAND_TIMEOUT);

    await gotoBackups(page);
    await expect(page.getByText("execute enabled")).toBeVisible(T);
    const row = await createdBackupRow(page);

    await page.getByLabel("restore command 실행").click();
    await expect(page.getByLabel("restore command 실행")).toBeChecked();
    await page.getByLabel("staging 대상 재생성").click();
    await expect(page.getByLabel("staging 대상 재생성")).toBeChecked();

    const responsePromise = waitForPost(page, isRestoreResponse);
    await row.getByRole("button", { name: "Restore" }).click();
    const body = await readOperation(await responsePromise);

    expect(body.data.operation).toBe("restore");
    expect(body.data.status).toBe("completed");
    expect(body.data.backup_id).toBe(createdBackupId);
    expect(body.data.command?.env.KOR_TRAVEL_MAP_RESTORE_RECREATE).toBe("1");
    expect(body.data.restore_targets?.app_db).toBeTruthy();
    expect(body.data.restore_targets?.dagster_db).toBeTruthy();
    expect(body.data.restore_targets?.rustfs_volume).toBeTruthy();

    const result = page
      .getByRole("status")
      .filter({ hasText: "restore / completed" });
    await expect(result).toBeVisible(T);
    await expect(result).toContainText("staging restore command 실행이 완료됐습니다.");
    await expect(result).toContainText(body.data.restore_targets!.app_db);
  });

  test("swap plan — 즉시 적용 없이 hot-swap command plan만 확인한다", async ({
    page,
  }) => {
    await gotoBackups(page);

    const button =
      createdBackupId === null
        ? page.getByRole("button", { name: "Swap" }).first()
        : (await createdBackupRow(page)).getByRole("button", { name: "Swap" });
    const swapButtons = page.getByRole("button", { name: "Swap" });
    test.skip(
      (await swapButtons.count()) === 0,
      "live 대상에 backup artifact가 없어 swap plan을 만들 수 없음",
    );

    await expect(page.getByLabel("swap command 실행")).not.toBeChecked();
    await expect(page.getByLabel("swap 즉시 적용")).not.toBeChecked();

    const responsePromise = waitForPost(page, isRestoreSwapResponse);
    await button.click();
    const body = await readOperation(await responsePromise);

    expect(body.data.operation).toBe("swap");
    expect(body.data.status).toBe("planned");
    expect(body.data.command?.env.KOR_TRAVEL_MAP_RESTORE_SWAP_APPLY).toBe("0");
    expect(body.data.command?.env.KOR_TRAVEL_MAP_RESTORE_SWAP_SKIP_VERIFY).toBe("0");

    const result = page
      .getByRole("status")
      .filter({ hasText: "swap / planned" });
    await expect(result).toBeVisible(T);
    await expect(result).toContainText(
      "restore hot-swap command plan을 생성했습니다.",
    );
  });

  test("swap execute — apply 옵션으로 hot-swap command를 실제 실행한다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_SWAP_COMMAND,
      "E2E_BACKUP_RESTORE_EXECUTE_SWAP=1일 때만 swap command를 실행",
    );
    test.setTimeout(COMMAND_TIMEOUT);

    await gotoBackups(page);
    await expect(page.getByText("execute enabled")).toBeVisible(T);
    const row = await createdBackupRow(page);

    await page.getByLabel("swap command 실행").click();
    await expect(page.getByLabel("swap command 실행")).toBeChecked();
    if (EXECUTE_SWAP_APPLY) {
      await page.getByLabel("swap 즉시 적용").click();
      await expect(page.getByLabel("swap 즉시 적용")).toBeChecked();
    } else {
      await expect(page.getByLabel("swap 즉시 적용")).not.toBeChecked();
    }

    const responsePromise = waitForPost(page, isRestoreSwapResponse);
    await row.getByRole("button", { name: "Swap" }).click();
    const body = await readOperation(await responsePromise);

    expect(body.data.operation).toBe("swap");
    expect(body.data.status).toBe("completed");
    expect(body.data.command?.env.KOR_TRAVEL_MAP_RESTORE_SWAP_APPLY).toBe(
      EXECUTE_SWAP_APPLY ? "1" : "0",
    );

    const result = page
      .getByRole("status")
      .filter({ hasText: "swap / completed" });
    await expect(result).toBeVisible(T);
    await expect(result).toContainText("restore hot-swap command 실행이 완료됐습니다.");
  });
});
