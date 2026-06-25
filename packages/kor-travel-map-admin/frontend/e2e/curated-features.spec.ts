import { expect, test } from "@playwright/test";

/**
 * `/admin/curated-features` (1192줄 mutation 콘솔) — ZERO 커버 페이지 spec
 * (T-AUDIT-0616, `docs/reports/e2e-scenario-coverage-2026-06-16.md` §1.1).
 *
 * 이 콘솔은 select/unselect/patch/archive/source-rule-apply/detail-snapshot 등 6개
 * mutation을 갖지만, **mutation 흐름은 시드된 curated 후보가 필요**하다(빈 DB에선 후보 0).
 * 따라서 본 spec은 `features.spec.ts`와 같은 **라이브 smoke** 패턴으로 렌더·필터·페이지
 * 구조·필터 상호작용만 결정적으로 덮는다. 시드 후보 기반 mutation depth(select/archive/
 * source-rule apply 등)는 mocked-route 후속으로 분리한다(아래 NOTE).
 *
 * NOTE: Playwright는 Windows 호스트에서만 실행되고, debug UI backend(:12701)/frontend
 * (:12705)는 WSL에서 기동된다. 빈 DB에서도 통과하도록 후보 0/N 양쪽을 허용한다.
 */
test.describe("/admin/curated-features", () => {
  test("페이지 렌더 + 필터 + 후보 테이블 구조", async ({ page }) => {
    await page.goto("/admin/curated-features");

    await expect(
      page.getByRole("heading", { level: 1, name: "Curated features" }),
    ).toBeVisible();

    // 필터 컨트롤(aria-label로 접근 — data-testid 없음).
    await expect(page.getByLabel("curated feature search")).toBeVisible();
    await expect(page.getByLabel("theme filter")).toBeVisible();
    await expect(page.getByLabel("provider filter")).toBeVisible();
    await expect(page.getByLabel("dataset filter")).toBeVisible();
    await expect(page.getByLabel("curation status filter")).toBeVisible();
    await expect(page.getByLabel("page size")).toBeVisible();

    // 후보 목록 테이블 컬럼 헤더 — source rules 테이블과 겹치지 않는 고유 컬럼만 단언
    // (source/theme/updated는 두 테이블에 모두 있어 strict-mode 충돌).
    for (const col of ["status", "feature", "reuse", "actions"]) {
      await expect(
        page.getByRole("columnheader", { name: col, exact: true }),
      ).toBeVisible();
    }

    // 카운트 라인은 후보 0/N 무관하게 항상 렌더.
    await expect(page.getByText(/개 표시/).first()).toBeVisible();
  });

  test("status 필터 기본값 candidate + 전환", async ({ page }) => {
    await page.goto("/admin/curated-features");

    const status = page.getByLabel("curation status filter");
    await expect(status).toHaveValue("candidate");
    await status.selectOption("curated");
    await expect(status).toHaveValue("curated");
    await status.selectOption("archived");
    await expect(status).toHaveValue("archived");
  });

  test("page size 전환 25/50/100/200", async ({ page }) => {
    await page.goto("/admin/curated-features");

    const pageSize = page.getByLabel("page size");
    await expect(pageSize).toHaveValue("50");
    await pageSize.selectOption("200");
    await expect(pageSize).toHaveValue("200");
  });

  test("source rules 패널 + 빈/행 양립", async ({ page }) => {
    await page.goto("/admin/curated-features");

    await expect(page.getByText("Source rules", { exact: true })).toBeVisible();
    await expect(page.getByLabel("rule enabled filter")).toBeVisible();
    // 후보 미선택 시 상세/에디터 안내 문구.
    await expect(
      page.getByText("후보를 선택하면 상세를 확인할 수 있습니다."),
    ).toBeVisible();
  });
});
