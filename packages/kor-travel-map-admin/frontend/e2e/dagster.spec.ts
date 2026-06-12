import { expect, test } from "@playwright/test";

test.describe("admin dagster page (/admin/dagster)", () => {
  test("Dagster 자체 요약 UI와 embedded webserver를 렌더", async ({ page }) => {
    await page.goto("/admin/dagster");

    await expect(
      page.getByRole("heading", { level: 1, name: "Dagster 운영" }),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: /Dagster 열기/ })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Code locations" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Recent runs" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Run detail" })).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Dagster webserver" }),
    ).toBeVisible();
    await expect(page.getByTestId("dagster-embed")).toBeVisible();
  });
});
