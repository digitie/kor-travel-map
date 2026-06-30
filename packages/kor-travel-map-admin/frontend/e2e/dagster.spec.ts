import { expect, test } from "@playwright/test";

test.describe("admin dagster page (/admin/dagster)", () => {
  test("작업 자동화 요약 UI를 렌더", async ({ page }) => {
    await page.goto("/admin/dagster");

    await expect(
      page.getByRole("heading", { level: 1, name: "작업 자동화" }),
    ).toBeVisible();
    await expect(page.getByRole("heading", { name: "스케줄" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "코드 위치" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "최근 실행" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "실행 상세" })).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "상세 엔진 화면" }),
    ).toHaveCount(0);
    await expect(page.getByTestId("dagster-embed")).toHaveCount(0);
  });
});
