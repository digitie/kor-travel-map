import { expect, type Page } from "@playwright/test";

export async function expectDetailPanelAboveScaleControl(
  page: Page,
  detailTestId: string,
): Promise<void> {
  const detail = page.getByTestId(detailTestId);
  const scale = page.locator(".maplibregl-ctrl-scale");
  await expect(detail).toBeVisible();
  await expect(scale).toBeVisible();

  const [detailBox, scaleBox] = await Promise.all([
    detail.boundingBox(),
    scale.boundingBox(),
  ]);
  if (detailBox === null || scaleBox === null) {
    throw new Error(
      "지도 상세 패널 또는 축척 컨트롤의 경계를 측정할 수 없습니다.",
    );
  }

  expect(detailBox.y + detailBox.height).toBeLessThanOrEqual(scaleBox.y);
}
