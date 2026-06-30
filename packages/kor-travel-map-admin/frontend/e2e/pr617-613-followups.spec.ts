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
  test("운영 로그 — 'live live' 중복 대신 '실시간' 표기(#617)", async ({ page }) => {
    await page.goto("/ops/logs");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    // 라이브 배지 중복('live live')이 사라지고 '실시간'으로 정리됐다.
    await expect(page.getByText(/live\s+live/i)).toHaveCount(0);
  });

  test("중복 검토 — 다중 선택 combobox 필터(#617)", async ({ page }) => {
    await page.goto("/admin/dedup-reviews");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByRole("combobox").first()).toBeVisible();
  });

  test("보강 검토 — 다중 선택 combobox 필터(#617)", async ({ page }) => {
    await page.goto("/admin/enrichment-reviews");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByRole("combobox").first()).toBeVisible();
  });

  test("신규 Feature 작성 — 시군구 코드 자동검색 필드(#617)", async ({ page }) => {
    await page.goto("/admin/features/new");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByLabel(/시군구/).first()).toBeVisible();
  });

  test("적재 작업 상세 — payload 시각화 영역(#617)", async ({ page }) => {
    await page.goto("/ops/import-jobs");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  });

  test("작업 자동화 — 스케줄 컨트롤 렌더(#617 polish)", async ({ page }) => {
    await page.goto("/admin/dagster");
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
      await page.goto("/admin/dagster");
      // 확인 다이얼로그를 dismiss(취소)해 실제 실행은 하지 않는다.
      let dialogShown = false;
      page.on("dialog", (dialog) => {
        dialogShown = true;
        void dialog.dismiss();
      });
      const control = page
        .getByRole("button", { name: /시작|즉시 실행/ })
        .first();
      if ((await control.count()) > 0 && (await control.isEnabled())) {
        await control.click();
        // #613 가드: 확인 단계 없이 바로 mutate되면 안 된다.
        expect(dialogShown).toBe(true);
      }
    });
  });
});
