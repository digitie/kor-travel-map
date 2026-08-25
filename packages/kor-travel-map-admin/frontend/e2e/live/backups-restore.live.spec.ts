import { expect, test, type Page, type Response } from "@playwright/test";

const UI_TIMEOUT = 15_000;
const T = { timeout: UI_TIMEOUT } as const;

type BackupOperationBody = {
  data: {
    backup_id: string;
    message: string;
    operation: "backup";
    status: "planned" | "completed" | "failed" | "manual_required";
  };
};

function uniqueBackupId(workerIndex: number): string {
  const random = Math.random().toString(36).slice(2, 8);
  return `e2e-plan-${random}-${Date.now()}-${workerIndex}`;
}

function apiPath(response: Response): string {
  const pathname = new URL(response.url()).pathname;
  return pathname.startsWith("/api/proxy/")
    ? pathname.slice("/api/proxy".length)
    : pathname;
}

async function expectBackupsReady(page: Page): Promise<void> {
  await expect(page.getByRole("heading", { level: 1, name: "백업" })).toBeVisible(T);
  await expect(page.getByText("백업 목록")).toBeVisible(T);
  await expect(page.getByRole("heading", { name: "실행 옵션" })).toBeVisible(T);
}

async function gotoBackups(page: Page): Promise<void> {
  await page.goto("/admin/backups");
  await expectBackupsReady(page);
}

function isBackupResponse(response: Response): boolean {
  return response.request().method() === "POST" && apiPath(response) === "/v1/admin/backups";
}

test.describe("/admin/backups live backup-only operations", () => {
  test("300 baseline 정책 — backup만 opt-in 가능하고 restore/hot swap은 UI에 없다", async ({
    page,
  }) => {
    await gotoBackups(page);

    await expect(page.getByLabel("backup id")).toBeVisible(T);
    await expect(page.getByLabel("백업 command 실행")).not.toBeChecked();
    await expect(page.getByRole("button", { name: "Restore" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Swap" })).toHaveCount(0);
    await expect(page.getByLabel("restore command 실행")).toHaveCount(0);
    await expect(page.getByLabel("swap command 실행")).toHaveCount(0);
    await expect(
      page.getByText("restore와 hot swap은 300 recovery 형식이 정의될 때까지 지원하지 않습니다."),
    ).toBeVisible(T);
    await expect(page.getByText(/plan only|execute enabled/).first()).toBeVisible(T);
  });

  test("backup plan — live API의 execute=false 결과와 UI live region을 확인한다", async ({
    page,
  }, testInfo) => {
    await gotoBackups(page);
    const backupId = uniqueBackupId(testInfo.workerIndex);
    await page.getByLabel("backup id").fill(backupId);

    const responsePromise = page.waitForResponse(isBackupResponse, T);
    await page.getByRole("button", { name: "백업", exact: true }).click();
    const response = await responsePromise;
    expect(response.status()).toBe(200);
    const body = (await response.json()) as BackupOperationBody;
    expect(body.data.operation).toBe("backup");
    expect(body.data.status).toBe("planned");
    expect(body.data.backup_id).toBe(backupId);

    const result = page.getByRole("status").filter({ hasText: "backup / 예정됨" });
    await expect(result).toBeVisible(T);
    await expect(result).toContainText("백업 command plan을 생성했습니다.");
    await expect(result).toContainText(`KOR_TRAVEL_MAP_BACKUP_ID=${backupId}`);
  });
});
