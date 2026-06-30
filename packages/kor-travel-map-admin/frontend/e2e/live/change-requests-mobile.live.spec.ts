import { expect, test, type Locator, type Page } from "@playwright/test";

const T = { timeout: 30_000 };

async function longPressAtCenter(page: Page, locator: Locator): Promise<void> {
  const box = await locator.boundingBox();
  expect(box).not.toBeNull();
  if (!box) return;

  const point = {
    x: box.x + box.width / 2,
    y: box.y + box.height / 2,
  };

  await page.evaluate(({ x, y }) => {
    const node = document.querySelector<HTMLElement>(
      '[data-testid="feature-change-location-map"]',
    );
    if (!node) throw new Error("feature change location map not found");

    node.dispatchEvent(
      new PointerEvent("pointerdown", {
        bubbles: true,
        cancelable: true,
        clientX: x,
        clientY: y,
        isPrimary: true,
        pointerId: 1,
        pointerType: "touch",
      }),
    );
  }, point);
  await page.waitForTimeout(700);
  await page.evaluate(({ x, y }) => {
    const node = document.querySelector<HTMLElement>(
      '[data-testid="feature-change-location-map"]',
    );
    if (!node) throw new Error("feature change location map not found");

    node.dispatchEvent(
      new PointerEvent("pointerup", {
        bubbles: true,
        cancelable: true,
        clientX: x,
        clientY: y,
        isPrimary: true,
        pointerId: 1,
        pointerType: "touch",
      }),
    );
  }, point);
}

test.describe("/admin/features/change-requests mobile LIVE", () => {
  test("위치 편집 다이얼로그 지도와 액션이 모바일 화면 안에서 동작한다", async ({
    page,
  }) => {
    test.setTimeout(90_000);
    await page.setViewportSize({ width: 390, height: 844 });

    await page.goto("/admin/features/change-requests");
    await expect(
      page.getByRole("heading", { level: 1, name: "Feature 변경" }),
    ).toBeVisible(T);

    await page.getByLabel("change name", { exact: true }).fill("mobile layout");
    await page.getByLabel("change lon", { exact: true }).fill("126.978000");
    await page.getByLabel("change lat", { exact: true }).fill("37.566500");
    await page.getByRole("button", { name: "위치 편집" }).click();

    const dialog = page.getByRole("dialog", { name: "위치/마커 편집" });
    const map = page.getByTestId("feature-change-location-map");
    await expect(dialog).toBeVisible(T);
    await expect(map).toBeVisible(T);
    await map.locator("canvas").first().waitFor({ state: "visible" });

    const viewport = page.viewportSize();
    const dialogBox = await dialog.boundingBox();
    const mapBox = await map.boundingBox();
    const cancelBox = await dialog.getByRole("button", { name: "취소" }).boundingBox();
    const applyBox = await dialog.getByRole("button", { name: "적용" }).boundingBox();

    expect(viewport).not.toBeNull();
    expect(dialogBox).not.toBeNull();
    expect(mapBox).not.toBeNull();
    expect(cancelBox).not.toBeNull();
    expect(applyBox).not.toBeNull();
    if (!viewport || !dialogBox || !mapBox || !cancelBox || !applyBox) return;

    expect(dialogBox.x).toBeGreaterThanOrEqual(0);
    expect(dialogBox.y).toBeGreaterThanOrEqual(0);
    expect(dialogBox.x + dialogBox.width).toBeLessThanOrEqual(viewport.width);
    expect(dialogBox.y + dialogBox.height).toBeLessThanOrEqual(viewport.height);
    expect(mapBox.width).toBeGreaterThan(300);
    expect(mapBox.height).toBeGreaterThan(200);
    expect(cancelBox.y + cancelBox.height).toBeLessThanOrEqual(viewport.height);
    expect(applyBox.y + applyBox.height).toBeLessThanOrEqual(viewport.height);

    await longPressAtCenter(page, map);
    await expect
      .poll(
        async () => dialog.getByLabel("sigungu_code", { exact: true }).inputValue(),
        T,
      )
      .toMatch(/^\d{5}$/);
    await expect(dialog.getByText(/· \d{5}/).first()).toBeVisible(T);
  });
});
