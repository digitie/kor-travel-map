import { expect, test } from "@playwright/test";

const T = { timeout: 15_000 } as const;

async function expectUpdateRequestsReady(
  page: import("@playwright/test").Page,
) {
  await expect(
    page.getByRole("heading", { level: 1, name: "Feature update requests" }),
  ).toBeVisible(T);
  await expect(page.getByLabel("lon")).toBeVisible(T);
  await expect(page.getByLabel("lat")).toBeVisible(T);
  await expect(page.getByLabel("radius km")).toBeVisible(T);
  await expect(page.getByRole("button", { name: "요청 생성" })).toBeVisible(T);
}

test.describe("/admin/features/update-requests live", () => {
  test("페이지 로드 — form controls + status filter", async ({ page }) => {
    await page.goto("/admin/features/update-requests");

    await expectUpdateRequestsReady(page);
    await expect(page.getByLabel("request status")).toBeVisible(T);
    await expect(page.getByLabel("dry-run")).toBeChecked();
    await expect(page.getByLabel("run mode")).toHaveValue("queued");
  });

  test("validation errors — lon required + lat range + radius min", async ({
    page,
  }) => {
    await page.goto("/admin/features/update-requests");
    await expectUpdateRequestsReady(page);

    await page.getByLabel("lon").fill("");
    await page.getByLabel("lat").fill("44");
    await page.getByLabel("radius km").fill("0.01");
    await page.getByRole("button", { name: "요청 생성" }).click();

    await expect(page.getByText("경도(lon)는 필수입니다.")).toBeVisible(T);
    await expect(page.getByText("위도는 33~43 범위여야 합니다.")).toBeVisible(T);
    await expect(page.getByText("반경은 0.1 이상이어야 합니다.")).toBeVisible(T);
  });

  test("dry-run 생성 — 실제 API preview 응답을 성공 alert로 표시", async ({
    page,
  }) => {
    await page.goto("/admin/features/update-requests");
    await expectUpdateRequestsReady(page);

    await expect(page.getByLabel("dry-run")).toBeChecked();
    await page.getByRole("button", { name: "요청 생성" }).click();

    const successAlert = page
      .getByRole("status")
      .filter({ hasText: "요청 처리 완료" });
    await expect(successAlert).toBeVisible(T);
    await expect(successAlert).toContainText("dry-run");
    await expect(successAlert).toContainText("dry_run");
  });

  test("/features 지도 Update 링크 → feature update requests 화면", async ({
    page,
  }) => {
    await page.goto("/features");

    await expect(
      page.getByRole("heading", { level: 1, name: "Feature 지도" }),
    ).toBeVisible(T);
    await page.getByRole("link", { name: "Update", exact: true }).click();

    await expect(page).toHaveURL(/\/admin\/feature-update-requests$/, T);
    await expectUpdateRequestsReady(page);
  });
});
