import { expect, test } from "@playwright/test";

const ADMIN_WRITE = process.env.E2E_ADMIN_WRITE === "1";

test.describe("PR #617/#613 스케줄 쓰기 확인", () => {
  test.skip(
    !ADMIN_WRITE,
    "E2E_ADMIN_WRITE=1일 때만 — 스케줄 컨트롤 확인 다이얼로그(#613 가드)",
  );

  test("스케줄 시작/즉시 실행은 확인 다이얼로그를 띄운다(즉시 mutate 금지)", async ({
    page,
  }) => {
    await page.goto("/ops/pipeline?tab=schedules");
    const control = page
      .getByRole("button", { name: /시작|즉시 실행/ })
      .first();
    await expect(control).toBeVisible();
    await expect(control).toBeEnabled();
    await control.click();
    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "취소" }).click();
  });
});
