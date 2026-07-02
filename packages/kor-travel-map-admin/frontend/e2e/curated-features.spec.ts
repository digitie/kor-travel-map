import { expect, test } from "@playwright/test";

/**
 * `/admin/features/curated` (큐레이션 관리 콘솔) — 라이브 smoke spec
 * (T-AUDIT-0616, `docs/reports/e2e-scenario-coverage-2026-06-16.md` §1.1).
 *
 * 큐레이션 UX 개편 이후 구조: 라이프사이클 스트립(상태 칩=필터) + '후보 검토'/'소스
 * 규칙' 탭. 이 콘솔은 select/unselect/patch/archive/source-rule-apply 등 mutation을
 * 갖지만 **mutation 흐름은 시드된 curated 후보가 필요**하다(빈 DB에선 후보 0).
 * 본 spec은 렌더·필터·탭·페이지 구조만 결정적으로 덮고, mutation depth는
 * `curated-features-mutations.spec.ts`(route-mocked)가 덮는다.
 *
 * NOTE: Playwright는 Windows 호스트에서만 실행되고, debug UI backend(:12701)/frontend
 * (:12705)는 WSL에서 기동된다. 빈 DB에서도 통과하도록 후보 0/N 양쪽을 허용한다.
 */
test.describe("/admin/features/curated", () => {
  test("페이지 렌더 + 스트립 + 탭 + 필터 + 후보 테이블 구조", async ({ page }) => {
    await page.goto("/admin/features/curated");

    await expect(
      page.getByRole("heading", { level: 1, name: "큐레이션 관리" }),
    ).toBeVisible();

    // 라이프사이클 스트립 — 상태 칩은 필터 버튼을 겸한다(기본 candidate 활성).
    const strip = page.getByTestId("curated-lifecycle-strip");
    await expect(strip).toBeVisible();
    await expect(
      strip.getByRole("button", { name: "후보", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");

    // 탭 — 후보 검토가 기본 선택, 소스 규칙 탭 존재.
    await expect(
      page.getByRole("tab", { name: "후보 검토", selected: true }),
    ).toBeVisible();
    await expect(page.getByRole("tab", { name: "소스 규칙" })).toBeVisible();

    // 필터 컨트롤(aria-label로 접근 — 영문 유지, locator 안정성).
    await expect(page.getByLabel("curated feature search")).toBeVisible();
    await expect(page.getByLabel("theme filter")).toBeVisible();
    await expect(page.getByLabel("provider filter")).toBeVisible();
    await expect(page.getByLabel("dataset filter")).toBeVisible();
    await expect(page.getByLabel("curation status filter")).toBeVisible();
    await expect(page.getByLabel("page size")).toBeVisible();

    // 후보 목록 테이블 컬럼 헤더(고유 컬럼만 단언).
    for (const col of ["상태", "feature", "정책·관계", "작업"]) {
      await expect(
        page.getByRole("columnheader", { name: col, exact: true }),
      ).toBeVisible();
    }

    // 카운트 라인은 후보 0/N 무관하게 항상 렌더.
    await expect(page.getByText(/페이지 크기/).first()).toBeVisible();
  });

  test("status 필터 기본값 candidate + 전환 (option value는 raw enum 유지)", async ({
    page,
  }) => {
    await page.goto("/admin/features/curated");

    const status = page.getByLabel("curation status filter");
    await expect(status).toHaveValue("candidate");
    await status.selectOption("curated");
    await expect(status).toHaveValue("curated");
    await status.selectOption("archived");
    await expect(status).toHaveValue("archived");
  });

  test("라이프사이클 칩 클릭 → 상태 필터 동기화", async ({ page }) => {
    await page.goto("/admin/features/curated");

    const strip = page.getByTestId("curated-lifecycle-strip");
    const curatedChip = strip.getByRole("button", {
      name: "큐레이션됨",
      exact: true,
    });
    await curatedChip.click();
    await expect(curatedChip).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByLabel("curation status filter")).toHaveValue(
      "curated",
    );
  });

  test("page size 전환 25/50/100/200", async ({ page }) => {
    await page.goto("/admin/features/curated");

    const pageSize = page.getByLabel("page size");
    await expect(pageSize).toHaveValue("50");
    await pageSize.selectOption("200");
    await expect(pageSize).toHaveValue("200");
  });

  test("소스 규칙 탭 + 빈/행 양립", async ({ page }) => {
    await page.goto("/admin/features/curated");

    await page.getByRole("tab", { name: "소스 규칙" }).click();
    // 탭 트리거도 "소스 규칙" 텍스트라 strict-mode 충돌 — 패널 부제로 단언.
    await expect(
      page.getByText(/provider source를 curated 후보로 끌어올리는 규칙/),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: "관련 job 실행" }),
    ).toHaveAttribute(
      "href",
      "/admin/dagster?schedule=curated_features_refresh_daily_schedule",
    );
    await expect(page.getByLabel("rule enabled filter")).toBeVisible();

    // 후보 검토 탭으로 돌아오면 미선택 안내 문구.
    await page.getByRole("tab", { name: "후보 검토" }).click();
    await expect(
      page.getByText("후보를 선택하면 상세를 확인할 수 있습니다."),
    ).toBeVisible();
  });
});
