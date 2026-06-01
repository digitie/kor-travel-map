import { expect, test } from "@playwright/test";

/**
 * `/geocoding` — kraddr-geo 디버그 페이지. backend `/debug/geocoding/health` 응답에
 * 따라 두 가지 경로:
 *   - kraddr-geo 도달 (KRTOUR_MAP_ADMIN_KRADDR_GEO_BASE_URL 설정 + upstream OK):
 *     health 카드 "reachable" + form 사용 가능.
 *   - 도달 불가/base_url 미설정: health 카드 "unreachable" + 실행 버튼 비활성.
 *
 * 두 시나리오 모두 페이지 렌더 + form 구조 + health 카드 노출은 동일.
 */
test.describe("/geocoding", () => {
  test("페이지 렌더 + health 카드 + 세 form", async ({ page }) => {
    await page.goto("/geocoding");
    await expect(
      page.getByRole("heading", { level: 1, name: /kraddr-geo 디버그/ }),
    ).toBeVisible();
    await expect(page.getByTestId("geocoding-health")).toBeVisible();
    await expect(page.getByTestId("reverse-form")).toBeVisible();
    await expect(page.getByTestId("geocode-form")).toBeVisible();
    await expect(page.getByTestId("regions-form")).toBeVisible();
    // 세 실행 버튼 노출(상태에 따라 disabled 가능).
    await expect(
      page.getByRole("button", { name: /Reverse 실행/ }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /Geocode 실행/ }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /Regions 실행/ }),
    ).toBeVisible();
  });

  test("홈에서 → kraddr-geo 디버그 링크로 이동", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: /kraddr-geo 디버그/ }).click();
    await expect(page).toHaveURL(/\/geocoding$/);
    await expect(
      page.getByRole("heading", { level: 1, name: /kraddr-geo 디버그/ }),
    ).toBeVisible();
  });

  test("reverse form 입력값이 보존됨", async ({ page }) => {
    await page.goto("/geocoding");
    const form = page.getByTestId("reverse-form");
    const lonInput = form.locator('input[type="text"]').first();
    await lonInput.fill("129.0756");
    await expect(lonInput).toHaveValue("129.0756");
    // type 셀렉트 변경.
    const typeSelect = form.getByRole("combobox").first();
    await typeSelect.selectOption("road");
    await expect(typeSelect).toHaveValue("road");
  });

  test("regions form 입력값과 level 토글이 보존됨", async ({ page }) => {
    await page.goto("/geocoding");
    const form = page.getByTestId("regions-form");
    const lonInput = form.locator('input[type="text"]').first();
    await lonInput.fill("127.0276");
    await expect(lonInput).toHaveValue("127.0276");

    const radius = form.locator('input[type="number"]').first();
    await radius.fill("5");
    await expect(radius).toHaveValue("5");

    const sido = form.getByLabel("sido");
    const sigungu = form.getByLabel("sigungu");
    const emd = form.getByLabel("emd");
    await expect(sido).not.toBeChecked();
    await expect(sigungu).toBeChecked();
    await expect(emd).toBeChecked();
    await sido.check();
    await expect(sido).toBeChecked();
  });
});
