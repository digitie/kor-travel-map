import { expect, test } from "@playwright/test";

/**
 * 신규 admin/ops 화면 smoke.
 * API 결과 행 수보다 운영자가 사용할 표면(제목, 필터, 폼, 표)을 우선 검증한다.
 */
test.describe("admin/ops pages", () => {
  test("/ops/import-jobs", async ({ page }) => {
    await page.goto("/ops/import-jobs");

    await expect(
      page.getByRole("heading", { level: 1, name: "Import jobs" }),
    ).toBeVisible();
    await expect(page.getByLabel("state")).toBeVisible();
    await expect(page.getByPlaceholder("kind filter")).toBeVisible();
    for (const column of ["job", "kind", "state", "progress", "stage"]) {
      await expect(page.getByRole("columnheader", { name: column })).toBeVisible();
    }
  });

  test("/ops/consistency", async ({ page }) => {
    await page.goto("/ops/consistency");

    await expect(
      page.getByRole("heading", { level: 1, name: "Consistency" }),
    ).toBeVisible();
    await expect(page.getByText("Open issues")).toBeVisible();
    await expect(page.getByText("Reports")).toBeVisible();
    await expect(page.getByText("Integrity issues")).toBeVisible();
    await expect(page.getByLabel("issue status")).toBeVisible();
  });

  test("/admin/dedup-review", async ({ page }) => {
    await page.goto("/admin/dedup-review");

    await expect(
      page.getByRole("heading", { level: 1, name: "Dedup review" }),
    ).toBeVisible();
    await expect(page.getByLabel("dedup status")).toBeVisible();
    for (const column of ["review", "score", "feature A", "feature B", "actions"]) {
      await expect(page.getByRole("columnheader", { name: column })).toBeVisible();
    }
  });

  test("/admin/feature-update-requests", async ({ page }) => {
    await page.goto("/admin/feature-update-requests");

    await expect(
      page.getByRole("heading", { level: 1, name: "Feature update requests" }),
    ).toBeVisible();
    await expect(page.getByText("새 요청")).toBeVisible();
    for (const label of ["lon", "lat", "radius km", "providers", "dataset keys"]) {
      await expect(page.getByLabel(label)).toBeVisible();
    }
    await expect(page.getByLabel("run mode")).toBeVisible();
    await expect(page.getByLabel("dry-run")).toBeChecked();
    await expect(page.getByLabel("request state")).toBeVisible();
  });

  test("/admin/poi-cache-targets", async ({ page }) => {
    await page.goto("/admin/poi-cache-targets");

    await expect(
      page.getByRole("heading", { level: 1, name: "POI cache targets" }),
    ).toBeVisible();
    await expect(page.getByText("Target upsert")).toBeVisible();
    for (const label of [
      "external system",
      "target key",
      "target name",
      "lon",
      "lat",
      "radius km",
    ]) {
      await expect(page.getByLabel(label)).toBeVisible();
    }
    await expect(page.getByLabel("scope mode")).toBeVisible();
    await expect(page.getByText("Nearby features")).toBeVisible();
  });
});
