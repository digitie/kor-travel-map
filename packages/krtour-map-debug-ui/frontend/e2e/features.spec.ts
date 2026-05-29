import { expect, test } from "@playwright/test";

/**
 * `/features` — 지도 페이지 smoke. backend `/features` 호출은 DB가 비어 있어도
 * (count=0) 정상 200을 반환하므로 페이지 렌더 + 캔버스 + 헤더 상태가 보이는지만
 * 검증한다. 실 마커 렌더는 DB에 feature가 적재된 환경에서 별도 검증.
 */
test.describe("/features", () => {
  test("페이지 렌더 + 지도 컨테이너 + 헤더 상태", async ({ page }) => {
    await page.goto("/features");
    await expect(
      page.getByRole("heading", { level: 1, name: "Feature 지도" }),
    ).toBeVisible();
    await expect(page.getByTestId("map-canvas-container")).toBeVisible();
    await expect(page.getByRole("link", { name: /홈/ })).toBeVisible();
    // 로딩→데이터 또는 에러 어느 쪽이든 상태 텍스트가 렌더돼야 함.
    await expect(
      page.locator(
        "text=/지도 로딩 중|feature 로딩 중|건 표시|feature 호출 실패/",
      ),
    ).toBeVisible();
  });

  test("홈에서 → Feature 지도 링크로 이동", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: /Feature 지도/ }).click();
    await expect(page).toHaveURL(/\/features$/);
    await expect(
      page.getByRole("heading", { level: 1, name: "Feature 지도" }),
    ).toBeVisible();
  });
});
