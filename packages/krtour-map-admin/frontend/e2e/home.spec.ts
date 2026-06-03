import { expect, test } from "@playwright/test";

/**
 * 홈(`/`) — 운영 홈 대시보드 smoke.
 * 실 API 데이터가 비어 있거나 일시 실패해도 shell, 주요 metric, 운영 내비게이션은
 * 렌더되어야 한다.
 */
test.describe("home page (/)", () => {
  test("운영 홈 shell + 주요 운영 내비 링크 렌더", async ({ page }) => {
    await page.goto("/");

    await expect(
      page.getByRole("heading", { level: 1, name: "운영 홈" }),
    ).toBeVisible();
    const navigation = page.getByRole("navigation");
    for (const linkName of [
      "Features",
      "Import jobs",
      "Consistency",
      "Dedup review",
      "Update requests",
      "POI targets",
      "Dagster",
      "ETL preview",
    ]) {
      await expect(
        navigation.getByRole("link", { name: linkName, exact: true }),
      ).toBeVisible();
    }
  });

  test("운영 metric 카드와 상태 카드가 렌더", async ({ page }) => {
    await page.goto("/");

    for (const heading of [
      "Features",
      "Import jobs",
      "Dedup queue",
      "Issues",
      "Backend",
      "Dagster",
      "Dedup pending",
    ]) {
      await expect(
        page.getByRole("heading", { name: heading, exact: true }),
      ).toBeVisible();
    }
    await expect(
      page.getByRole("heading", { name: "최근 import jobs" }),
    ).toBeVisible();
  });

  test("홈에서 새 운영 화면으로 이동", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: "Import jobs" }).click();
    await expect(page).toHaveURL(/\/ops\/import-jobs$/);
    await expect(
      page.getByRole("heading", { level: 1, name: "Import jobs" }),
    ).toBeVisible();

    await page.getByRole("link", { name: "Update requests" }).click();
    await expect(page).toHaveURL(/\/admin\/feature-update-requests$/);
    await expect(
      page.getByRole("heading", { level: 1, name: "Feature update requests" }),
    ).toBeVisible();
  });
});
