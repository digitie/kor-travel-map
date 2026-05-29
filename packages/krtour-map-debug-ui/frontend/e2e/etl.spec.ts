import { expect, test } from "@playwright/test";

/**
 * `/etl` — ETL preview. 실 backend(/debug/etl/providers + .../preview?source=fixture)
 * 연동을 검증한다: provider 목록 로드 → provider/dataset 선택 → "Preview 실행" →
 * 변환 결과(FeatureBundle JSON) 렌더.
 *
 * 페이지에 native <select> 3개가 고정 순서(provider/dataset/source)로 있다.
 * 래핑 <label>의 accessible-name이 option 텍스트와 합쳐져 모호하므로 순서(nth)로
 * 지정한다 (skeleton UI — 순서 안정적).
 */
test.describe("/etl preview", () => {
  test("provider 목록 로드 + krex_rest_areas fixture preview 실행", async ({
    page,
  }) => {
    await page.goto("/etl");
    await expect(
      page.getByRole("heading", { level: 1, name: "ETL preview" }),
    ).toBeVisible();

    const selects = page.locator("main select");
    const providerSelect = selects.nth(0);
    const datasetSelect = selects.nth(1);

    // providers가 backend에서 로드돼 옵션이 채워졌는지.
    await expect(
      providerSelect.locator("option", { hasText: "python-krex-api" }),
    ).toBeAttached();

    await providerSelect.selectOption("python-krex-api");
    await datasetSelect.selectOption("krex_rest_areas");
    await page.getByRole("button", { name: "Preview 실행" }).click();

    // 변환 결과 요약 + JSON.
    await expect(page.getByText(/count\s*\d+/)).toBeVisible();
    const resultPre = page.locator("pre").last();
    await expect(resultPre).toContainText("feature_id");
    await expect(resultPre).toContainText('"kind": "place"');
  });

  test("provider 드롭다운에 4개 provider가 모두 있음", async ({ page }) => {
    await page.goto("/etl");
    const providerSelect = page.locator("main select").nth(0);
    for (const name of [
      "data.go.kr-standard",
      "python-kma-api",
      "python-krex-api",
      "python-opinet-api",
    ]) {
      await expect(
        providerSelect.locator("option", { hasText: name }),
      ).toBeAttached();
    }
  });

  test("datagokr 축제 fixture preview → event FeatureBundle", async ({ page }) => {
    await page.goto("/etl");
    const selects = page.locator("main select");
    await selects.nth(0).selectOption("data.go.kr-standard");
    await selects.nth(1).selectOption("datagokr_cultural_festivals");
    await page.getByRole("button", { name: "Preview 실행" }).click();

    const resultPre = page.locator("pre").last();
    await expect(resultPre).toContainText("feature_id");
    await expect(resultPre).toContainText('"kind": "event"');
  });
});
