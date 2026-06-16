import { expect, test } from "@playwright/test";

/**
 * `/admin/features/new` (1097줄 수동 생성 폼) — ZERO 커버 페이지 spec
 * (T-AUDIT-0616, `docs/reports/e2e-scenario-coverage-2026-06-16.md` §1.2).
 *
 * 생성 submit은 백엔드 `POST /v1/admin/features`가 필요하지만, **클라이언트측 검증**
 * (필수 필드 / 한국 본토 좌표 범위)은 네트워크 없이 동기적으로 throw된다. 따라서 본 spec은
 * 라이브 smoke 렌더 + 결정적인 클라이언트 검증 경로를 덮는다. 실제 생성→change request
 * 결과/422·409/중복후보(nearby)/지오코딩 흐름은 mocked-route 후속으로 분리한다.
 *
 * 실제 폼은 kind가 place/event 2종뿐이고 provider 필드가 없다(감사 보고서의
 * Place/Event/Notice/Route/Area·provider=manual 가정은 컴포넌트와 불일치 — 본 spec이 정합).
 *
 * NOTE: Playwright는 Windows 호스트에서만 실행된다. 라이브 실행 검증은 Windows 런 필요.
 */
test.describe("/admin/features/new", () => {
  test("폼 렌더 — 섹션 + 핵심 필드 + 제출 버튼", async ({ page }) => {
    await page.goto("/admin/features/new");

    await expect(
      page.getByRole("heading", { level: 1, name: "New feature" }),
    ).toBeVisible();

    for (const section of ["좌표", "kor-travel-geo", "중복 후보", "기본 정보", "주소", "상세"]) {
      await expect(
        page.getByRole("heading", { level: 2, name: section }),
      ).toBeVisible();
    }

    await expect(page.getByLabel("name", { exact: true })).toBeVisible();
    await expect(page.getByLabel("category", { exact: true })).toHaveValue(
      "01070300",
    );
    await expect(page.getByLabel("lon", { exact: true })).toBeVisible();
    await expect(page.getByLabel("lat", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "요청 생성" })).toBeVisible();
  });

  test("kind 옵션은 place/event 2종", async ({ page }) => {
    await page.goto("/admin/features/new");

    const kind = page.getByLabel("kind", { exact: true });
    await expect(kind).toHaveValue("place");
    await kind.selectOption("event");
    await expect(kind).toHaveValue("event");
    // event 전환 시 detail 폼에 starts_at 노출.
    await expect(page.getByLabel("starts_at", { exact: true })).toBeVisible();
  });

  test("검증 — name 비우고 제출하면 필수 에러", async ({ page }) => {
    await page.goto("/admin/features/new");

    // 기본값: name 빈값, reason 빈값. 그대로 제출 → name 필수에서 throw.
    await page.getByRole("button", { name: "요청 생성" }).click();

    await expect(page.getByText("feature 작성 실패")).toBeVisible();
    await expect(page.getByText("name은 필수입니다.").first()).toBeVisible();
  });

  test("검증 — 한국 본토 밖 좌표는 범위 에러", async ({ page }) => {
    await page.goto("/admin/features/new");

    await page.getByLabel("name", { exact: true }).fill("범위밖 테스트");
    await page.getByLabel("reason", { exact: true }).fill("e2e");
    await page.getByLabel("lon", { exact: true }).fill("200");
    await page.getByLabel("lat", { exact: true }).fill("10");
    await page.getByRole("button", { name: "요청 생성" }).click();

    await expect(
      page.getByText("좌표는 한국 본토 기준 범위 안이어야 합니다.").first(),
    ).toBeVisible();
  });
});
