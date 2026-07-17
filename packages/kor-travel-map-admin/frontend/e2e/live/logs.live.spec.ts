import { expect, test, type Page, type Response } from "@playwright/test";

const TIMEOUT = 30_000;

function apiPath(response: Response): string {
  const pathname = new URL(response.url()).pathname;
  const path = pathname.startsWith("/api/proxy/")
    ? pathname.slice("/api/proxy".length)
    : pathname;
  return decodeURIComponent(path);
}

function waitForGet(page: Page, path: string): Promise<Response> {
  return page.waitForResponse(
    (response) =>
      response.request().method() === "GET" && apiPath(response) === path,
    { timeout: TIMEOUT },
  );
}

async function expectPanel(page: Page, emptyText: string) {
  await expect(
    page.getByRole("columnheader", { name: "생성" }).or(
      page.getByText(emptyText),
    ).first(),
  ).toBeVisible({ timeout: TIMEOUT });
}

test.describe("운영 로그 live canonical surface", () => {
  test("system/API 목록을 실제 REST 응답으로 렌더한다", async ({ page }) => {
    const systemResponse = waitForGet(page, "/v1/ops/system-logs");
    const apiResponse = waitForGet(page, "/v1/ops/api-call-logs");

    await page.goto("/ops/logs");

    expect((await systemResponse).ok()).toBeTruthy();
    expect((await apiResponse).ok()).toBeTruthy();
    await expect(
      page.getByRole("heading", { level: 1, name: "운영 로그" }),
    ).toBeVisible({ timeout: TIMEOUT });
    await expect(page.getByRole("tab", { name: "System logs" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "API call logs" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Job events" })).toHaveCount(0);
    await expectPanel(page, "system log가 없습니다.");

    await page.getByRole("tab", { name: "API call logs" }).click();
    await expectPanel(page, "API call log가 없습니다.");
  });

  test("필터와 페이지 크기를 GET-only 상태로 조작한다", async ({ page }) => {
    await page.goto("/ops/logs?tab=api");
    await expect(
      page.getByRole("heading", { level: 1, name: "운영 로그" }),
    ).toBeVisible({ timeout: TIMEOUT });
    await expect(page.getByRole("tab", { name: "API call logs" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    await page.getByLabel("log page size").selectOption("25");
    await expect(page.getByLabel("log page size")).toHaveValue("25");
    await page.getByLabel("api log method").fill("GET");
    await expect(page.getByLabel("api log method")).toHaveValue("GET");

    await page.getByRole("tab", { name: "System logs" }).click();
    await page.getByLabel("system log level").selectOption("error");
    await expect(page.getByLabel("system log level")).toHaveValue("error");
    await expectPanel(page, "system log가 없습니다.");
  });
});
