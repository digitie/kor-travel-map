import { expect, test } from "@playwright/test";

/**
 * codex PR #617(세션 UI 재반영) + #613 리뷰 fix(#618) 후속의 새/변경 UI live e2e.
 *
 * 기본은 read-only(페이지가 새 요소를 렌더하는지). 컨트롤 클릭이 필요한 시나리오는
 * `E2E_ADMIN_WRITE=1`로 게이트하되, 확인 다이얼로그를 dismiss(취소)해 실제 mutate는
 * 하지 않는다. 실행은 별도 에이전트가 n150 live에서 수행한다(여기선 작성만).
 */
const ADMIN_WRITE = process.env.E2E_ADMIN_WRITE === "1";

test.describe("PR #617/#613 후속 UI", () => {
  test("운영 로그 — system/API 두 canonical stream만 노출", async ({ page }) => {
    await page.goto("/ops/logs");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByRole("tab", { name: "System logs" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "API call logs" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Job events" })).toHaveCount(0);
  });

  test("중복 검토 — 다중 선택 combobox 필터(#617)", async ({ page }) => {
    await page.goto("/admin/features/dedup-reviews");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByRole("combobox").first()).toBeVisible();
  });

  test("보강 검토 — 다중 선택 combobox 필터(#617)", async ({ page }) => {
    await page.goto("/admin/features/enrichment-reviews");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByRole("combobox").first()).toBeVisible();
  });

  test("신규 Feature 작성 — 시군구 코드 자동검색 필드(#617)", async ({ page }) => {
    await page.goto("/admin/features/new");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByLabel(/시군구/).first()).toBeVisible();
  });

  test("파이프라인 — 실행 타임라인 렌더", async ({ page }) => {
    await page.goto("/ops/pipeline");
    await expect(page.getByRole("heading", { name: "실행 타임라인" })).toBeVisible();
  });

  test("파이프라인 — 스케줄 컨트롤 렌더", async ({ page }) => {
    await page.goto("/ops/pipeline?tab=schedules");
    await expect(page.getByRole("heading", { name: "스케줄" })).toBeVisible();
  });

  test.describe("쓰기 게이트(E2E_ADMIN_WRITE=1)", () => {
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
      if ((await control.count()) > 0 && (await control.isEnabled())) {
        await control.click();
        // #613 가드: 확인 단계(AlertDialog) 없이 바로 mutate되면 안 된다.
        const dialog = page.getByRole("alertdialog");
        await expect(dialog).toBeVisible();
        // 실제 실행하지 않도록 취소.
        await dialog.getByRole("button", { name: "취소" }).click();
      }
    });
  });
});
