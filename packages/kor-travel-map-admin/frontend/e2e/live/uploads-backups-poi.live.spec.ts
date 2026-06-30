import { test, expect } from "@playwright/test";
import * as F from "./_fixtures";

/**
 * LIVE (non-mock) read-only e2e — uploads / backups / poi-cache-targets.
 *
 * 세 페이지(/admin/offline-uploads, /admin/backups, /admin/poi-cache-targets)는
 * prod 실데이터에서 PRESENCE=0(rows 없음)이다. 본 spec은 **순수 조회/렌더**만 검증한다:
 * page.goto + 안정 heading(getByRole heading level 1) + empty-state/컨테이너 visible +
 * 안정 컨트롤(status 필터 select / 검색 input / pagination disabled) + 반응형 viewport.
 *
 * mutation(업로드/백업실행/restore/swap/생성/삭제/검증/적재) 클릭·폼 제출은 전혀 없다.
 * click은 [내비 링크]에만 사용한다. 검색/필터 input 타이핑과 status 필터 select는
 * GET-only 조회라 허용된다. pagination 버튼은 PRESENCE=0이라 disabled → 클릭하지 않고
 * disabled 상태만 단언한다. selector/heading 텍스트는 참조 spec에서 검증된 것만 재사용.
 */

const HEADINGS = {
  uploads: "Offline uploads",
  backups: "Backups",
  poi: "POI cache targets",
} as const;

async function expectHeading(
  page: import("@playwright/test").Page,
  name: string,
): Promise<void> {
  await expect(
    page.getByRole("heading", { level: 1, name }),
  ).toBeVisible({ timeout: 15000 });
}

test.describe("live/offline-uploads (read-only)", () => {

  test("uploads page loads with main heading", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
  });

  test("uploads empty-state or rows render (PRESENCE=0)", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    // PRESENCE=0 (빈) — 빈/행 추측 대신, 항상 렌더되는 업로드 폼 컨트롤로 page-ready 단언.
    await expect(page.getByTestId("offline-upload-file-input")).toBeVisible({
      timeout: 15000,
    });
  });

  test("uploads status filter select present", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    await expect(page.getByLabel("offline upload status")).toBeVisible({ timeout: 15000 });
  });

  test("uploads provider + dataset filter inputs present", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    await expect(page.getByLabel("provider filter")).toBeVisible({ timeout: 15000 });
    await expect(page.getByLabel("dataset filter")).toBeVisible({ timeout: 15000 });
  });

  test("uploads detail placeholder visible when nothing selected", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    await expect(
      page.getByText("목록에서 업로드를 선택하면", { exact: false }).first(),
    ).toBeVisible({ timeout: 15000 });
  });

  test("uploads status filter=uploaded keeps heading", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    await page.getByLabel("offline upload status").selectOption("uploaded");
    await expectHeading(page, HEADINGS.uploads);
  });

  test("uploads status filter=validating keeps heading", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    await page.getByLabel("offline upload status").selectOption("validating");
    await expectHeading(page, HEADINGS.uploads);
  });

  test("uploads status filter=validated keeps heading", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    await page.getByLabel("offline upload status").selectOption("validated");
    await expectHeading(page, HEADINGS.uploads);
  });

  test("uploads status filter=validation_failed keeps heading", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    await page.getByLabel("offline upload status").selectOption("validation_failed");
    await expectHeading(page, HEADINGS.uploads);
  });

  test("uploads status filter=loading keeps heading", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    await page.getByLabel("offline upload status").selectOption("loading");
    await expectHeading(page, HEADINGS.uploads);
  });

  test("uploads status filter=loaded keeps heading", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    await page.getByLabel("offline upload status").selectOption("loaded");
    await expectHeading(page, HEADINGS.uploads);
  });

  test("uploads status filter=load_failed keeps heading", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    await page.getByLabel("offline upload status").selectOption("load_failed");
    await expectHeading(page, HEADINGS.uploads);
  });

  test("uploads status filter=cancelled keeps heading", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    await page.getByLabel("offline upload status").selectOption("cancelled");
    await expectHeading(page, HEADINGS.uploads);
  });

  test("uploads status filter=all keeps heading", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    await page.getByLabel("offline upload status").selectOption("all");
    await expectHeading(page, HEADINGS.uploads);
  });

  test("uploads provider filter typing term[0]=공원", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    const term = F.SEARCH_TERMS[0];
    await page.getByLabel("provider filter").fill(term);
    await expect(page.getByLabel("provider filter")).toHaveValue(term, { timeout: 15000 });
    await expectHeading(page, HEADINGS.uploads);
  });

  test("uploads provider filter typing term[1]=공항", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    const term = F.SEARCH_TERMS[1];
    await page.getByLabel("provider filter").fill(term);
    await expect(page.getByLabel("provider filter")).toHaveValue(term, { timeout: 15000 });
    await expectHeading(page, HEADINGS.uploads);
  });

  test("uploads provider filter typing term[2]=도서관", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    const term = F.SEARCH_TERMS[2];
    await page.getByLabel("provider filter").fill(term);
    await expect(page.getByLabel("provider filter")).toHaveValue(term, { timeout: 15000 });
    await expectHeading(page, HEADINGS.uploads);
  });

  test("uploads provider filter typing term[3]=마트", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    const term = F.SEARCH_TERMS[3];
    await page.getByLabel("provider filter").fill(term);
    await expect(page.getByLabel("provider filter")).toHaveValue(term, { timeout: 15000 });
    await expectHeading(page, HEADINGS.uploads);
  });

  test("uploads provider filter typing term[4]=문화재", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    const term = F.SEARCH_TERMS[4];
    await page.getByLabel("provider filter").fill(term);
    await expect(page.getByLabel("provider filter")).toHaveValue(term, { timeout: 15000 });
    await expectHeading(page, HEADINGS.uploads);
  });

  test("uploads provider filter typing term[5]=미술관", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    const term = F.SEARCH_TERMS[5];
    await page.getByLabel("provider filter").fill(term);
    await expect(page.getByLabel("provider filter")).toHaveValue(term, { timeout: 15000 });
    await expectHeading(page, HEADINGS.uploads);
  });

  test("uploads provider filter typing term[6]=박물관", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    const term = F.SEARCH_TERMS[6];
    await page.getByLabel("provider filter").fill(term);
    await expect(page.getByLabel("provider filter")).toHaveValue(term, { timeout: 15000 });
    await expectHeading(page, HEADINGS.uploads);
  });

  test("uploads provider filter typing term[7]=서점", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    const term = F.SEARCH_TERMS[7];
    await page.getByLabel("provider filter").fill(term);
    await expect(page.getByLabel("provider filter")).toHaveValue(term, { timeout: 15000 });
    await expectHeading(page, HEADINGS.uploads);
  });

  test("uploads provider filter typing term[8]=수목원", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    const term = F.SEARCH_TERMS[8];
    await page.getByLabel("provider filter").fill(term);
    await expect(page.getByLabel("provider filter")).toHaveValue(term, { timeout: 15000 });
    await expectHeading(page, HEADINGS.uploads);
  });

  test("uploads provider filter typing term[9]=주유소", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    const term = F.SEARCH_TERMS[9];
    await page.getByLabel("provider filter").fill(term);
    await expect(page.getByLabel("provider filter")).toHaveValue(term, { timeout: 15000 });
    await expectHeading(page, HEADINGS.uploads);
  });

  test("uploads provider filter typing term[10]=주차장", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    const term = F.SEARCH_TERMS[10];
    await page.getByLabel("provider filter").fill(term);
    await expect(page.getByLabel("provider filter")).toHaveValue(term, { timeout: 15000 });
    await expectHeading(page, HEADINGS.uploads);
  });

  test("uploads provider filter typing term[11]=축제", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    const term = F.SEARCH_TERMS[11];
    await page.getByLabel("provider filter").fill(term);
    await expect(page.getByLabel("provider filter")).toHaveValue(term, { timeout: 15000 });
    await expectHeading(page, HEADINGS.uploads);
  });

  test("uploads provider filter typing term[12]=카페", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    const term = F.SEARCH_TERMS[12];
    await page.getByLabel("provider filter").fill(term);
    await expect(page.getByLabel("provider filter")).toHaveValue(term, { timeout: 15000 });
    await expectHeading(page, HEADINGS.uploads);
  });

  test("uploads provider filter typing term[13]=해수욕장", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    const term = F.SEARCH_TERMS[13];
    await page.getByLabel("provider filter").fill(term);
    await expect(page.getByLabel("provider filter")).toHaveValue(term, { timeout: 15000 });
    await expectHeading(page, HEADINGS.uploads);
  });

  test("uploads provider filter typing term[14]=휴게소", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    const term = F.SEARCH_TERMS[14];
    await page.getByLabel("provider filter").fill(term);
    await expect(page.getByLabel("provider filter")).toHaveValue(term, { timeout: 15000 });
    await expectHeading(page, HEADINGS.uploads);
  });

  test("uploads provider filter typing term[15]=휴양림", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    const term = F.SEARCH_TERMS[15];
    await page.getByLabel("provider filter").fill(term);
    await expect(page.getByLabel("provider filter")).toHaveValue(term, { timeout: 15000 });
    await expectHeading(page, HEADINGS.uploads);
  });

  test("uploads dataset filter typing code[0]=01000000", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    const code = F.CATEGORY_CODES[0];
    await page.getByLabel("dataset filter").fill(code);
    await expect(page.getByLabel("dataset filter")).toHaveValue(code, { timeout: 15000 });
  });

  test("uploads dataset filter typing code[1]=01010000", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    const code = F.CATEGORY_CODES[1];
    await page.getByLabel("dataset filter").fill(code);
    await expect(page.getByLabel("dataset filter")).toHaveValue(code, { timeout: 15000 });
  });

  test("uploads dataset filter typing code[2]=01010100", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    const code = F.CATEGORY_CODES[2];
    await page.getByLabel("dataset filter").fill(code);
    await expect(page.getByLabel("dataset filter")).toHaveValue(code, { timeout: 15000 });
  });

  test("uploads dataset filter typing code[3]=01010200", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    const code = F.CATEGORY_CODES[3];
    await page.getByLabel("dataset filter").fill(code);
    await expect(page.getByLabel("dataset filter")).toHaveValue(code, { timeout: 15000 });
  });

  test("uploads dataset filter typing code[4]=01010300", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    const code = F.CATEGORY_CODES[4];
    await page.getByLabel("dataset filter").fill(code);
    await expect(page.getByLabel("dataset filter")).toHaveValue(code, { timeout: 15000 });
  });

  test("uploads dataset filter typing code[5]=01010400", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    const code = F.CATEGORY_CODES[5];
    await page.getByLabel("dataset filter").fill(code);
    await expect(page.getByLabel("dataset filter")).toHaveValue(code, { timeout: 15000 });
  });

  test("uploads dataset filter typing code[6]=01020000", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    const code = F.CATEGORY_CODES[6];
    await page.getByLabel("dataset filter").fill(code);
    await expect(page.getByLabel("dataset filter")).toHaveValue(code, { timeout: 15000 });
  });

  test("uploads dataset filter typing code[7]=01020100", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    const code = F.CATEGORY_CODES[7];
    await page.getByLabel("dataset filter").fill(code);
    await expect(page.getByLabel("dataset filter")).toHaveValue(code, { timeout: 15000 });
  });

  test("uploads dataset filter typing code[8]=01020200", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    const code = F.CATEGORY_CODES[8];
    await page.getByLabel("dataset filter").fill(code);
    await expect(page.getByLabel("dataset filter")).toHaveValue(code, { timeout: 15000 });
  });

  test("uploads dataset filter typing code[9]=01020300", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    const code = F.CATEGORY_CODES[9];
    await page.getByLabel("dataset filter").fill(code);
    await expect(page.getByLabel("dataset filter")).toHaveValue(code, { timeout: 15000 });
  });

  test("uploads dataset filter typing code[10]=01020400", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    const code = F.CATEGORY_CODES[10];
    await page.getByLabel("dataset filter").fill(code);
    await expect(page.getByLabel("dataset filter")).toHaveValue(code, { timeout: 15000 });
  });

  test("uploads dataset filter typing code[11]=01030000", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    const code = F.CATEGORY_CODES[11];
    await page.getByLabel("dataset filter").fill(code);
    await expect(page.getByLabel("dataset filter")).toHaveValue(code, { timeout: 15000 });
  });

  test("uploads renders at desktop 1280x800", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    await expect(page.getByLabel("offline upload status")).toBeVisible({ timeout: 15000 });
  });

  test("uploads renders at tablet 768x1024", async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 1024 });
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    await expect(page.getByLabel("offline upload status")).toBeVisible({ timeout: 15000 });
  });

  test("uploads renders at mobile 390x844", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    await expect(page.getByLabel("offline upload status")).toBeVisible({ timeout: 15000 });
  });

});

test.describe("live/backups (read-only)", () => {

  test("backups page loads with main heading", async ({ page }) => {
    await page.goto("/admin/backups");
    await expectHeading(page, HEADINGS.backups);
  });

  test("backups empty-state or list container (PRESENCE=0)", async ({ page }) => {
    await page.goto("/admin/backups");
    await expectHeading(page, HEADINGS.backups);
    const empty = page.getByText("백업이 없습니다.");
    const emptyVisible = await empty.isVisible({ timeout: 15000 }).catch(() => false);
    if (emptyVisible) {
      await expect(empty).toBeVisible({ timeout: 15000 });
    } else {
      await expect(page.getByText("백업 목록")).toBeVisible({ timeout: 15000 });
    }
  });

  test("backups 백업 목록 card container visible", async ({ page }) => {
    await page.goto("/admin/backups");
    await expectHeading(page, HEADINGS.backups);
    await expect(page.getByText("백업 목록")).toBeVisible({ timeout: 15000 });
  });

  test("backups command-enabled badge visible", async ({ page }) => {
    await page.goto("/admin/backups");
    await expectHeading(page, HEADINGS.backups);
    const planOnly = page.getByText("plan only");
    const planVisible = await planOnly.isVisible({ timeout: 15000 }).catch(() => false);
    if (planVisible) {
      await expect(planOnly).toBeVisible({ timeout: 15000 });
    } else {
      await expect(page.getByText("execute enabled")).toBeVisible({ timeout: 15000 });
    }
  });

  test("backups 실행 옵션 card heading visible", async ({ page }) => {
    await page.goto("/admin/backups");
    await expectHeading(page, HEADINGS.backups);
    await expect(page.getByRole("heading", { name: "실행 옵션" })).toBeVisible({ timeout: 15000 });
  });

  test("backups detail placeholder or detail card present", async ({ page }) => {
    await page.goto("/admin/backups");
    await expectHeading(page, HEADINGS.backups);
    const none = page.getByRole("heading", { name: "선택 없음" });
    const noneVisible = await none.isVisible({ timeout: 15000 }).catch(() => false);
    if (noneVisible) {
      await expect(none).toBeVisible({ timeout: 15000 });
    } else {
      await expect(page.getByRole("heading", { name: "실행 옵션" })).toBeVisible({ timeout: 15000 });
    }
  });

  test("backups deep-link ?job_kind=consistency_check loads heading", async ({ page }) => {
    await page.goto(`/admin/backups?job_kind=${F.IMPORT_JOB_KINDS[0]}`);
    await expectHeading(page, HEADINGS.backups);
  });

  test("backups deep-link ?job_kind=full_load_batch loads heading", async ({ page }) => {
    await page.goto(`/admin/backups?job_kind=${F.IMPORT_JOB_KINDS[1]}`);
    await expectHeading(page, HEADINGS.backups);
  });

  test("backups deep-link ?job_kind=mv_refresh loads heading", async ({ page }) => {
    await page.goto(`/admin/backups?job_kind=${F.IMPORT_JOB_KINDS[2]}`);
    await expectHeading(page, HEADINGS.backups);
  });

  test("backups deep-link ?ref=jobid[0] loads heading", async ({ page }) => {
    await page.goto(`/admin/backups?ref=${F.IMPORT_JOB_IDS[0]}`);
    await expectHeading(page, HEADINGS.backups);
  });

  test("backups deep-link ?ref=jobid[1] loads heading", async ({ page }) => {
    await page.goto(`/admin/backups?ref=${F.IMPORT_JOB_IDS[1]}`);
    await expectHeading(page, HEADINGS.backups);
  });

  test("backups deep-link ?ref=jobid[2] loads heading", async ({ page }) => {
    await page.goto(`/admin/backups?ref=${F.IMPORT_JOB_IDS[2]}`);
    await expectHeading(page, HEADINGS.backups);
  });

  test("backups deep-link ?page_size=25 loads heading", async ({ page }) => {
    await page.goto(`/admin/backups?page_size=${F.PAGE_SIZES[0]}`);
    await expectHeading(page, HEADINGS.backups);
  });

  test("backups deep-link ?page_size=50 loads heading", async ({ page }) => {
    await page.goto(`/admin/backups?page_size=${F.PAGE_SIZES[1]}`);
    await expectHeading(page, HEADINGS.backups);
  });

  test("backups deep-link ?page_size=100 loads heading", async ({ page }) => {
    await page.goto(`/admin/backups?page_size=${F.PAGE_SIZES[2]}`);
    await expectHeading(page, HEADINGS.backups);
  });

  test("backups deep-link ?page_size=200 loads heading", async ({ page }) => {
    await page.goto(`/admin/backups?page_size=${F.PAGE_SIZES[3]}`);
    await expectHeading(page, HEADINGS.backups);
  });

  test("backups renders at desktop 1280x800", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/admin/backups");
    await expectHeading(page, HEADINGS.backups);
    await expect(page.getByText("백업 목록")).toBeVisible({ timeout: 15000 });
  });

  test("backups renders at tablet 768x1024", async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 1024 });
    await page.goto("/admin/backups");
    await expectHeading(page, HEADINGS.backups);
    await expect(page.getByText("백업 목록")).toBeVisible({ timeout: 15000 });
  });

  test("backups renders at mobile 390x844", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/admin/backups");
    await expectHeading(page, HEADINGS.backups);
    await expect(page.getByText("백업 목록")).toBeVisible({ timeout: 15000 });
  });

});

test.describe("live/poi-cache-targets (read-only)", () => {

  test("poi page loads with main heading", async ({ page }) => {
    await page.goto("/admin/poi-cache-targets");
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi empty placeholder or targets container (PRESENCE=0)", async ({ page }) => {
    await page.goto("/admin/poi-cache-targets");
    await expectHeading(page, HEADINGS.poi);
    const empty = page.getByText("데이터가 없습니다.");
    const emptyVisible = await empty.first().isVisible({ timeout: 15000 }).catch(() => false);
    if (emptyVisible) {
      await expect(empty.first()).toBeVisible({ timeout: 15000 });
    } else {
      await expect(page.getByText("Nearby features")).toBeVisible({ timeout: 15000 });
    }
  });

  test("poi page 1 indicator visible", async ({ page }) => {
    await page.goto("/admin/poi-cache-targets");
    await expectHeading(page, HEADINGS.poi);
    await expect(page.getByText("page 1 ·")).toBeVisible({ timeout: 15000 });
  });

  test("poi pagination 이전 button disabled (PRESENCE=0)", async ({ page }) => {
    await page.goto("/admin/poi-cache-targets");
    await expectHeading(page, HEADINGS.poi);
    await expect(page.getByRole("button", { name: "이전" })).toBeDisabled({ timeout: 15000 });
  });

  test("poi pagination 다음 button disabled (PRESENCE=0)", async ({ page }) => {
    await page.goto("/admin/poi-cache-targets");
    await expectHeading(page, HEADINGS.poi);
    await expect(page.getByRole("button", { name: "다음" })).toBeDisabled({ timeout: 15000 });
  });

  test("poi Nearby features card present", async ({ page }) => {
    await page.goto("/admin/poi-cache-targets");
    await expectHeading(page, HEADINGS.poi);
    await expect(page.getByText("Nearby features")).toBeVisible({ timeout: 15000 });
  });

  test("poi nearby placeholder target select prompt visible", async ({ page }) => {
    await page.goto("/admin/poi-cache-targets");
    await expectHeading(page, HEADINGS.poi);
    await expect(page.getByText("target을 선택하세요")).toBeVisible({ timeout: 15000 });
  });

  test("poi deep-link ?target=curated[0] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATED_IDS[0]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=curated[1] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATED_IDS[1]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=curated[2] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATED_IDS[2]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=curated[3] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATED_IDS[3]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=curated[4] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATED_IDS[4]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=curated[5] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATED_IDS[5]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=curated[6] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATED_IDS[6]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=curated[7] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATED_IDS[7]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=curated[8] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATED_IDS[8]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=curated[9] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATED_IDS[9]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=curated[10] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATED_IDS[10]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=curated[11] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATED_IDS[11]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=curated[12] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATED_IDS[12]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=curated[13] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATED_IDS[13]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=curated[14] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATED_IDS[14]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=curated[15] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATED_IDS[15]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=curated[16] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATED_IDS[16]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=curated[17] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATED_IDS[17]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=curated[18] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATED_IDS[18]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=curated[19] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATED_IDS[19]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=curated[20] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATED_IDS[20]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=curated[21] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATED_IDS[21]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=curated[22] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATED_IDS[22]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=curated[23] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATED_IDS[23]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=curated[24] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATED_IDS[24]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?ref=feature[0] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?ref=${F.FEATURE_IDS[0]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?ref=feature[1] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?ref=${F.FEATURE_IDS[1]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?ref=feature[2] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?ref=${F.FEATURE_IDS[2]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?ref=feature[3] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?ref=${F.FEATURE_IDS[3]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?ref=feature[4] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?ref=${F.FEATURE_IDS[4]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?ref=feature[5] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?ref=${F.FEATURE_IDS[5]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?ref=feature[6] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?ref=${F.FEATURE_IDS[6]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?ref=feature[7] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?ref=${F.FEATURE_IDS[7]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?ref=feature[8] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?ref=${F.FEATURE_IDS[8]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?ref=feature[9] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?ref=${F.FEATURE_IDS[9]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?page_size=25 loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?page_size=${F.PAGE_SIZES[0]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?page_size=50 loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?page_size=${F.PAGE_SIZES[1]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?page_size=100 loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?page_size=${F.PAGE_SIZES[2]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?page_size=200 loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?page_size=${F.PAGE_SIZES[3]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi renders at desktop 1280x800", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/admin/poi-cache-targets");
    await expectHeading(page, HEADINGS.poi);
    await expect(page.getByText("Nearby features")).toBeVisible({ timeout: 15000 });
  });

  test("poi renders at tablet 768x1024", async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 1024 });
    await page.goto("/admin/poi-cache-targets");
    await expectHeading(page, HEADINGS.poi);
    await expect(page.getByText("Nearby features")).toBeVisible({ timeout: 15000 });
  });

  test("poi renders at mobile 390x844", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/admin/poi-cache-targets");
    await expectHeading(page, HEADINGS.poi);
    await expect(page.getByText("Nearby features")).toBeVisible({ timeout: 15000 });
  });

});

test.describe("live/uploads-backups-poi nav (read-only)", () => {

  test("nav /admin/backups click Offline uploads to /admin/offline-uploads", async ({ page }) => {
    await page.goto("/admin/backups");
    await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible({ timeout: 15000 });
    await page.getByRole("link", { name: "오프라인 업로드", exact: true }).first().click();
    await expect(page).toHaveURL(new RegExp("\\/admin\\/offline-uploads(\\?|$|\\/)"), { timeout: 15000 });
    await expectHeading(page, "Offline uploads");
  });

  test("nav /admin/offline-uploads click Backups to /admin/backups", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible({ timeout: 15000 });
    await page.getByRole("link", { name: "백업", exact: true }).first().click();
    await expect(page).toHaveURL(new RegExp("\\/admin\\/backups(\\?|$|\\/)"), { timeout: 15000 });
    await expectHeading(page, "Backups");
  });

  test("nav /admin/backups click POI targets to /admin/poi-cache-targets", async ({ page }) => {
    await page.goto("/admin/backups");
    await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible({ timeout: 15000 });
    await page.getByRole("link", { name: "POI 캐시 대상", exact: true }).first().click();
    await expect(page).toHaveURL(new RegExp("\\/admin\\/poi-cache-targets(\\?|$|\\/)"), { timeout: 15000 });
    await expectHeading(page, "POI cache targets");
  });

  test("nav /admin/poi-cache-targets click Offline uploads to /admin/offline-uploads", async ({ page }) => {
    await page.goto("/admin/poi-cache-targets");
    await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible({ timeout: 15000 });
    await page.getByRole("link", { name: "오프라인 업로드", exact: true }).first().click();
    await expect(page).toHaveURL(new RegExp("\\/admin\\/offline-uploads(\\?|$|\\/)"), { timeout: 15000 });
    await expectHeading(page, "Offline uploads");
  });

  test("nav /admin/offline-uploads click POI targets to /admin/poi-cache-targets", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible({ timeout: 15000 });
    await page.getByRole("link", { name: "POI 캐시 대상", exact: true }).first().click();
    await expect(page).toHaveURL(new RegExp("\\/admin\\/poi-cache-targets(\\?|$|\\/)"), { timeout: 15000 });
    await expectHeading(page, "POI cache targets");
  });

  test("nav /admin/poi-cache-targets click Backups to /admin/backups", async ({ page }) => {
    await page.goto("/admin/poi-cache-targets");
    await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible({ timeout: 15000 });
    await page.getByRole("link", { name: "백업", exact: true }).first().click();
    await expect(page).toHaveURL(new RegExp("\\/admin\\/backups(\\?|$|\\/)"), { timeout: 15000 });
    await expectHeading(page, "Backups");
  });

});

test.describe("live/uploads-backups-poi kind deep-links (read-only)", () => {

  test("uploads deep-link ?kind=place loads heading", async ({ page }) => {
    await page.goto(`/admin/offline-uploads?kind=${F.KINDS[0]}`);
    await expectHeading(page, "Offline uploads");
  });

  test("uploads deep-link ?kind=event loads heading", async ({ page }) => {
    await page.goto(`/admin/offline-uploads?kind=${F.KINDS[1]}`);
    await expectHeading(page, "Offline uploads");
  });

  test("uploads deep-link ?kind=notice loads heading", async ({ page }) => {
    await page.goto(`/admin/offline-uploads?kind=${F.KINDS[2]}`);
    await expectHeading(page, "Offline uploads");
  });

  test("uploads deep-link ?kind=price loads heading", async ({ page }) => {
    await page.goto(`/admin/offline-uploads?kind=${F.KINDS[3]}`);
    await expectHeading(page, "Offline uploads");
  });

  test("uploads deep-link ?kind=weather loads heading", async ({ page }) => {
    await page.goto(`/admin/offline-uploads?kind=${F.KINDS[4]}`);
    await expectHeading(page, "Offline uploads");
  });

  test("uploads deep-link ?kind=route loads heading", async ({ page }) => {
    await page.goto(`/admin/offline-uploads?kind=${F.KINDS[5]}`);
    await expectHeading(page, "Offline uploads");
  });

  test("uploads deep-link ?kind=area loads heading", async ({ page }) => {
    await page.goto(`/admin/offline-uploads?kind=${F.KINDS[6]}`);
    await expectHeading(page, "Offline uploads");
  });

  test("backups deep-link ?kind=place loads heading", async ({ page }) => {
    await page.goto(`/admin/backups?kind=${F.KINDS[0]}`);
    await expectHeading(page, "Backups");
  });

  test("backups deep-link ?kind=event loads heading", async ({ page }) => {
    await page.goto(`/admin/backups?kind=${F.KINDS[1]}`);
    await expectHeading(page, "Backups");
  });

  test("backups deep-link ?kind=notice loads heading", async ({ page }) => {
    await page.goto(`/admin/backups?kind=${F.KINDS[2]}`);
    await expectHeading(page, "Backups");
  });

  test("backups deep-link ?kind=price loads heading", async ({ page }) => {
    await page.goto(`/admin/backups?kind=${F.KINDS[3]}`);
    await expectHeading(page, "Backups");
  });

  test("backups deep-link ?kind=weather loads heading", async ({ page }) => {
    await page.goto(`/admin/backups?kind=${F.KINDS[4]}`);
    await expectHeading(page, "Backups");
  });

  test("backups deep-link ?kind=route loads heading", async ({ page }) => {
    await page.goto(`/admin/backups?kind=${F.KINDS[5]}`);
    await expectHeading(page, "Backups");
  });

  test("backups deep-link ?kind=area loads heading", async ({ page }) => {
    await page.goto(`/admin/backups?kind=${F.KINDS[6]}`);
    await expectHeading(page, "Backups");
  });

  test("poi deep-link ?kind=place loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?kind=${F.KINDS[0]}`);
    await expectHeading(page, "POI cache targets");
  });

  test("poi deep-link ?kind=event loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?kind=${F.KINDS[1]}`);
    await expectHeading(page, "POI cache targets");
  });

  test("poi deep-link ?kind=notice loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?kind=${F.KINDS[2]}`);
    await expectHeading(page, "POI cache targets");
  });

  test("poi deep-link ?kind=price loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?kind=${F.KINDS[3]}`);
    await expectHeading(page, "POI cache targets");
  });

  test("poi deep-link ?kind=weather loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?kind=${F.KINDS[4]}`);
    await expectHeading(page, "POI cache targets");
  });

  test("poi deep-link ?kind=route loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?kind=${F.KINDS[5]}`);
    await expectHeading(page, "POI cache targets");
  });

  test("poi deep-link ?kind=area loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?kind=${F.KINDS[6]}`);
    await expectHeading(page, "POI cache targets");
  });

});
