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

  test("/admin/features", async ({ page }) => {
    await page.goto("/admin/features");

    await expect(
      page.getByRole("heading", { level: 1, name: "Admin features" }),
    ).toBeVisible();
    await expect(page.getByLabel("feature search")).toBeVisible();
    await expect(page.getByLabel("feature kind")).toBeVisible();
    await expect(page.getByLabel("feature status")).toBeVisible();
    await expect(page.getByLabel("has issue")).toBeVisible();
    await expect(page.getByLabel("feature sort")).toBeVisible();
    await expect(page.getByLabel("feature page size")).toBeVisible();
    for (const column of [
      "feature",
      "kind/status",
      "provider",
      "issues",
      "coord/address",
      "updated",
      "actions",
    ]) {
      await expect(page.getByRole("columnheader", { name: column })).toBeVisible();
    }
    await expect(page.getByText("table에서 feature를 선택하면")).toBeVisible();
  });

  test("/admin/issues", async ({ page }) => {
    await page.goto("/admin/issues");

    await expect(
      page.getByRole("heading", { level: 1, name: "Admin issues" }),
    ).toBeVisible();
    await expect(page.getByLabel("issue search")).toBeVisible();
    await expect(page.getByLabel("issue status")).toBeVisible();
    await expect(page.getByLabel("issue severity")).toBeVisible();
    await expect(page.getByLabel("issue page size")).toBeVisible();
    await expect(page.getByLabel("issue type")).toBeVisible();
    await expect(page.getByLabel("issue provider")).toBeVisible();
    await expect(page.getByLabel("issue dataset")).toBeVisible();
    await expect(page.getByLabel("bbox")).toBeVisible();
    for (const column of [
      "issue",
      "severity",
      "status",
      "provider",
      "message",
      "feature",
      "detected",
      "actions",
    ]) {
      await expect(page.getByRole("columnheader", { name: column })).toBeVisible();
    }
    const firstIssue = page.getByRole("row").nth(1);
    if (await firstIssue.isVisible()) {
      await firstIssue.click();
      await expect(page.getByLabel("address JSON")).toBeVisible();
      await expect(page.getByLabel("manual lon")).toBeVisible();
      await expect(page.getByLabel("manual lat")).toBeVisible();
    } else {
      await expect(page.getByText("table에서 issue를 선택하면")).toBeVisible();
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

  test("/ops/logs", async ({ page }) => {
    await page.goto("/ops/logs");

    await expect(page.getByRole("heading", { level: 1, name: "Logs" })).toBeVisible();
    await expect(page.getByLabel("log page size")).toBeVisible();
    await expect(page.getByRole("tab", { name: "System logs" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "API call logs" })).toBeVisible();
    await expect(page.getByLabel("system log search")).toBeVisible();
    await expect(page.getByLabel("system log level")).toBeVisible();
    await expect(page.getByLabel("system log source")).toBeVisible();
    for (const column of [
      "created",
      "level",
      "source",
      "event",
      "message",
      "request",
    ]) {
      await expect(page.getByRole("columnheader", { name: column })).toBeVisible();
    }
    await page.getByRole("tab", { name: "API call logs" }).click();
    await expect(page.getByRole("tab", { name: "API call logs" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(page.getByLabel("api log method")).toBeVisible();
    await expect(page.getByLabel("api log path")).toBeVisible();
    await expect(page.getByLabel("api log min status")).toBeVisible();
    for (const column of [
      "created",
      "method",
      "status",
      "duration",
      "path",
      "request",
      "error",
    ]) {
      await expect(page.getByRole("columnheader", { name: column })).toBeVisible();
    }
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

  test("/admin/enrichment-review", async ({ page }) => {
    await page.goto("/admin/enrichment-review");

    await expect(
      page.getByRole("heading", { level: 1, name: "Enrichment review" }),
    ).toBeVisible();
    await expect(page.getByLabel("enrichment status")).toBeVisible();
    for (const column of [
      "review",
      "score",
      "1차 (datagokr)",
      "2차 (visitkorea)",
      "actions",
    ]) {
      await expect(page.getByRole("columnheader", { name: column })).toBeVisible();
    }
    // cursor 페이지네이션 컨트롤(#299).
    await expect(page.getByLabel("이전 페이지")).toBeVisible();
    await expect(page.getByLabel("다음 페이지")).toBeVisible();
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

  test("/admin/offline-uploads", async ({ page }) => {
    await page.goto("/admin/offline-uploads");

    await expect(
      page.getByRole("heading", { level: 1, name: "Offline uploads" }),
    ).toBeVisible();
    await expect(page.getByText("파일 업로드")).toBeVisible();
    await expect(page.getByTestId("offline-upload-file-input")).toBeVisible();
    for (const label of ["provider", "dataset key", "sync scope", "created by"]) {
      await expect(page.getByLabel(label, { exact: true })).toBeVisible();
    }
    await expect(page.getByRole("button", { name: "업로드" })).toBeDisabled();
    await expect(page.getByText("CSV/TSV 업로드를 선택하면")).toBeVisible();
    await expect(page.getByLabel("offline upload state")).toBeVisible();
    await expect(page.getByLabel("provider filter")).toBeVisible();
    await expect(page.getByLabel("dataset filter")).toBeVisible();
    for (const column of [
      "upload",
      "state",
      "format",
      "provider/dataset",
      "file",
      "size",
      "updated",
      "actions",
    ]) {
      await expect(page.getByRole("columnheader", { name: column })).toBeVisible();
    }
  });
});
