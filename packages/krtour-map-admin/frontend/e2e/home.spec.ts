import { expect, test } from "@playwright/test";

/**
 * 홈(`/`) — frontend skeleton smoke + 실 backend(/debug/health·/debug/version) 연동.
 * react-query가 backend에서 데이터를 받아 렌더링하므로 auto-retry expect로 대기한다.
 */
test.describe("home page (/)", () => {
  test("타이틀 + ETL 내비 링크 렌더", async ({ page }) => {
    await page.goto("/");
    await expect(
      page.getByRole("heading", { level: 1, name: "krtour-map admin" }),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: /Feature 지도/ })).toBeVisible();
    await expect(page.getByRole("link", { name: /Dagster 운영/ })).toBeVisible();
    await expect(page.getByRole("link", { name: /ETL preview/ })).toBeVisible();
  });

  test("Backend health 섹션이 live /debug/health 결과(status ok)를 표시", async ({
    page,
  }) => {
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "Backend health" }),
    ).toBeVisible();
    // 헬스 JSON <pre>에 service 이름 + status ok가 보여야 함.
    const healthPre = page.locator("pre").filter({ hasText: '"status"' });
    await expect(healthPre).toContainText('"ok"');
    await expect(healthPre).toContainText("krtour-map-admin");
  });

  test("Versions 섹션이 live /debug/version 결과를 표시", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Versions" })).toBeVisible();
    const versions = page.getByTestId("version-list");
    await expect(
      versions.locator("dt").filter({ hasText: /^admin$/ }),
    ).toBeVisible();
    await expect(
      versions.locator("dt").filter({ hasText: /^krtour\.map$/ }),
    ).toBeVisible();
  });

  test("Dagster 요약 카드가 ops summary 결과를 표시", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("dagster-summary-card")).toBeVisible();
    await expect(page.getByTestId("dagster-summary-card")).toContainText(
      /assets|Dagster summary 호출 실패/,
    );
  });

  test("Zustand viewport 데모 버튼 동작 (클라이언트 상태)", async ({ page }) => {
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: /Map viewport/ }),
    ).toBeVisible();
    await page.getByRole("button", { name: /미세 이동/ }).click();
    await page.getByRole("button", { name: /기본값으로 초기화/ }).click();
    // 크래시 없이 viewport pre가 계속 렌더되는지.
    await expect(page.getByRole("heading", { name: /Map viewport/ })).toBeVisible();
  });
});
