import { test, expect, type Response } from "@playwright/test";

import type { AdminNavHref } from "../../src/lib/admin-nav";
import { adminNavLink, expectAdminPageLoaded, pagerButton } from "./_admin-nav";
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
 * disabled 상태만 단언한다.
 *
 * 화면 이름(h1·사이드바 링크)은 하드코딩하지 않고 nav 정본(`src/lib/admin-nav.ts`)에서
 * 읽는다(`_admin-nav.ts`). 2026-11-25 운영 e2e에서 h1 `Offline uploads`(현재
 * `오프라인 업로드`)·`POI cache targets`(현재 `POI 캐시 대상`) drift로 34건이 실패했다.
 */

const HEADINGS = {
  uploads: "/admin/offline-uploads",
  backups: "/admin/backups",
  poi: "/admin/poi-cache-targets",
} as const satisfies Record<string, AdminNavHref>;

async function expectHeading(
  page: import("@playwright/test").Page,
  href: AdminNavHref,
): Promise<void> {
  await expectAdminPageLoaded(page, href);
}

/** offline upload 목록 GET(`/v1/admin/offline-uploads`, BFF proxy 경유) 응답인지. */
function isOfflineUploadListResponse(response: Response): boolean {
  if (response.request().method() !== "GET") return false;
  const { pathname } = new URL(response.url());
  return pathname.replace(/^\/api\/proxy/, "") === "/v1/admin/offline-uploads";
}

// 2026-11 offline-uploads 필터는 provider 문자열·dataset key 두 칸에서 정수
// `provider_dataset_id` 한 칸(`provider dataset ID filter`, type=number)으로 바뀌었다
// (#966 계열). 존재 여부와 무관하게 양의 정수는 유효한 GET 필터다.
const PROVIDER_DATASET_ID_SAMPLES = [1, 2, 7, 42, 101, 401, 999, 123456] as const;

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

  test("uploads provider dataset ID filter input present", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expectHeading(page, HEADINGS.uploads);
    await expect(
      page.getByLabel("provider dataset ID filter", { exact: true }),
    ).toBeVisible({ timeout: 15000 });
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

  for (const datasetId of PROVIDER_DATASET_ID_SAMPLES) {
    test(`uploads provider dataset ID filter ${datasetId} → GET provider_dataset_id`, async ({
      page,
    }) => {
      await page.goto("/admin/offline-uploads");
      await expectHeading(page, HEADINGS.uploads);
      const input = page.getByLabel("provider dataset ID filter", { exact: true });
      await expect(input).toBeVisible({ timeout: 15000 });
      // 입력 → 목록 GET에 provider_dataset_id가 실린다(읽기 전용 필터 라운드트립).
      const listResponse = page.waitForResponse(
        (response) =>
          isOfflineUploadListResponse(response) &&
          new URL(response.url()).searchParams.get("provider_dataset_id") ===
            String(datasetId),
        { timeout: 15000 },
      );
      await input.fill(String(datasetId));
      expect((await listResponse).status()).toBe(200);
      await expect(input).toHaveValue(String(datasetId), { timeout: 15000 });
      await expectHeading(page, HEADINGS.uploads);
    });
  }

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
    // `isVisible`은 기다리지 않는다(timeout 옵션 무시) — 데이터 도착 전 분기가 갈려 flaky했다.
    // 둘 중 하나가 보일 때까지 기다린다.
    await expect(
      page.getByText("백업이 없습니다.").or(page.getByText("백업 목록")).first(),
    ).toBeVisible({ timeout: 15000 });
  });

  test("backups 백업 목록 card container visible", async ({ page }) => {
    await page.goto("/admin/backups");
    await expectHeading(page, HEADINGS.backups);
    await expect(page.getByText("백업 목록")).toBeVisible({ timeout: 15000 });
  });

  test("backups command-enabled badge visible", async ({ page }) => {
    await page.goto("/admin/backups");
    await expectHeading(page, HEADINGS.backups);
    // badge는 목록 응답(`command_enabled`)이 온 뒤에만 그려진다 — `isVisible`(대기 없음)로
    // 분기하면 응답 전에 "execute enabled" 쪽으로 갈려 실패했다(2026-11-25 운영 재실행).
    await expect(
      page.getByText("plan only", { exact: true }).or(
        page.getByText("execute enabled", { exact: true }),
      ),
    ).toBeVisible({ timeout: 15000 });
  });

  test("backups 실행 옵션 card heading visible", async ({ page }) => {
    await page.goto("/admin/backups");
    await expectHeading(page, HEADINGS.backups);
    await expect(page.getByRole("heading", { name: "실행 옵션" })).toBeVisible({ timeout: 15000 });
  });

  test("backups detail placeholder or detail card present", async ({ page }) => {
    await page.goto("/admin/backups");
    await expectHeading(page, HEADINGS.backups);
    await expect(
      page
        .getByRole("heading", { name: "선택 없음" })
        .or(page.getByRole("heading", { name: "실행 옵션" }))
        .first(),
    ).toBeVisible({ timeout: 15000 });
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
    await expect(
      page.getByText("데이터가 없습니다.").or(page.getByText("Nearby features")).first(),
    ).toBeVisible({ timeout: 15000 });
  });

  test("poi page 1 indicator visible", async ({ page }) => {
    await page.goto("/admin/poi-cache-targets");
    await expectHeading(page, HEADINGS.poi);
    await expect(page.getByText("page 1 ·")).toBeVisible({ timeout: 15000 });
  });

  // 손으로 만들던 targets pager가 공용 CursorPager(+`previous`)로 바뀌면서 버튼 접근성
  // 이름이 다른 목록과 같아졌다(보이는 라벨은 그대로 `이전`/`다음`). 첫 로드는 cursor
  // 스택이 비어 있어 데이터 유무와 무관하게 `이전`·`첫 페이지`가 비활성이다.
  test("poi pagination 이전 button disabled on first page", async ({ page }) => {
    await page.goto("/admin/poi-cache-targets");
    await expectHeading(page, HEADINGS.poi);
    await expect(pagerButton(page, "이전 페이지").first()).toBeDisabled({
      timeout: 15000,
    });
    await expect(pagerButton(page, "첫 페이지").first()).toBeDisabled({
      timeout: 15000,
    });
  });

  test("poi pagination 다음 enabled iff the targets response has next_cursor", async ({
    page,
  }) => {
    // 실데이터 행 수에 기대지 않는다: `다음`의 활성 여부는 첫 목록 응답의 next_cursor와
    // 정확히 같아야 한다(빈 목록이면 비활성).
    const listResponse = page.waitForResponse(
      (response) =>
        response.status() === 200 &&
        response.request().method() === "GET" &&
        new URL(response.url()).pathname.replace(/^\/api\/proxy/, "") ===
          "/v1/admin/poi-cache-targets",
      { timeout: 15000 },
    );
    await page.goto("/admin/poi-cache-targets");
    await expectHeading(page, HEADINGS.poi);
    const response = await listResponse;
    expect(response.status()).toBe(200);
    const body = (await response.json()) as {
      meta?: { page?: { next_cursor?: string | null } | null };
    };
    const next = pagerButton(page, "다음 페이지").first();
    if (body.meta?.page?.next_cursor) {
      await expect(next).toBeEnabled({ timeout: 15000 });
    } else {
      await expect(next).toBeDisabled({ timeout: 15000 });
    }
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

  test("poi deep-link ?target=item[0] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATION_ITEM_IDS[0]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=item[1] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATION_ITEM_IDS[1]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=item[2] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATION_ITEM_IDS[2]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=item[3] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATION_ITEM_IDS[3]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=item[4] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATION_ITEM_IDS[4]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=item[5] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATION_ITEM_IDS[5]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=item[6] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATION_ITEM_IDS[6]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=item[7] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATION_ITEM_IDS[7]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=item[8] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATION_ITEM_IDS[8]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=item[9] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATION_ITEM_IDS[9]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=item[10] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATION_ITEM_IDS[10]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=item[11] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATION_ITEM_IDS[11]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=item[12] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATION_ITEM_IDS[12]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=item[13] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATION_ITEM_IDS[13]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=item[14] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATION_ITEM_IDS[14]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=item[15] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATION_ITEM_IDS[15]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=item[16] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATION_ITEM_IDS[16]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=item[17] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATION_ITEM_IDS[17]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=item[18] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATION_ITEM_IDS[18]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=item[19] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATION_ITEM_IDS[19]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=item[20] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATION_ITEM_IDS[20]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=item[21] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATION_ITEM_IDS[21]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=item[22] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATION_ITEM_IDS[22]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=item[23] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATION_ITEM_IDS[23]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?target=item[24] loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?target=${F.CURATION_ITEM_IDS[24]}`);
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
    await adminNavLink(page, HEADINGS.uploads).first().click();
    await expect(page).toHaveURL(new RegExp("\\/admin\\/offline-uploads(\\?|$|\\/)"), { timeout: 15000 });
    await expectHeading(page, HEADINGS.uploads);
  });

  test("nav /admin/offline-uploads click Backups to /admin/backups", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible({ timeout: 15000 });
    await adminNavLink(page, HEADINGS.backups).first().click();
    await expect(page).toHaveURL(new RegExp("\\/admin\\/backups(\\?|$|\\/)"), { timeout: 15000 });
    await expectHeading(page, HEADINGS.backups);
  });

  test("nav /admin/backups click POI targets to /admin/poi-cache-targets", async ({ page }) => {
    await page.goto("/admin/backups");
    await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible({ timeout: 15000 });
    await adminNavLink(page, HEADINGS.poi).first().click();
    await expect(page).toHaveURL(new RegExp("\\/admin\\/poi-cache-targets(\\?|$|\\/)"), { timeout: 15000 });
    await expectHeading(page, HEADINGS.poi);
  });

  test("nav /admin/poi-cache-targets click Offline uploads to /admin/offline-uploads", async ({ page }) => {
    await page.goto("/admin/poi-cache-targets");
    await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible({ timeout: 15000 });
    await adminNavLink(page, HEADINGS.uploads).first().click();
    await expect(page).toHaveURL(new RegExp("\\/admin\\/offline-uploads(\\?|$|\\/)"), { timeout: 15000 });
    await expectHeading(page, HEADINGS.uploads);
  });

  test("nav /admin/offline-uploads click POI targets to /admin/poi-cache-targets", async ({ page }) => {
    await page.goto("/admin/offline-uploads");
    await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible({ timeout: 15000 });
    await adminNavLink(page, HEADINGS.poi).first().click();
    await expect(page).toHaveURL(new RegExp("\\/admin\\/poi-cache-targets(\\?|$|\\/)"), { timeout: 15000 });
    await expectHeading(page, HEADINGS.poi);
  });

  test("nav /admin/poi-cache-targets click Backups to /admin/backups", async ({ page }) => {
    await page.goto("/admin/poi-cache-targets");
    await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible({ timeout: 15000 });
    await adminNavLink(page, HEADINGS.backups).first().click();
    await expect(page).toHaveURL(new RegExp("\\/admin\\/backups(\\?|$|\\/)"), { timeout: 15000 });
    await expectHeading(page, HEADINGS.backups);
  });

});

test.describe("live/uploads-backups-poi kind deep-links (read-only)", () => {

  test("uploads deep-link ?kind=place loads heading", async ({ page }) => {
    await page.goto(`/admin/offline-uploads?kind=${F.KINDS[0]}`);
    await expectHeading(page, HEADINGS.uploads);
  });

  test("uploads deep-link ?kind=event loads heading", async ({ page }) => {
    await page.goto(`/admin/offline-uploads?kind=${F.KINDS[1]}`);
    await expectHeading(page, HEADINGS.uploads);
  });

  test("uploads deep-link ?kind=notice loads heading", async ({ page }) => {
    await page.goto(`/admin/offline-uploads?kind=${F.KINDS[2]}`);
    await expectHeading(page, HEADINGS.uploads);
  });

  test("uploads deep-link ?kind=price loads heading", async ({ page }) => {
    await page.goto(`/admin/offline-uploads?kind=${F.KINDS[3]}`);
    await expectHeading(page, HEADINGS.uploads);
  });

  test("uploads deep-link ?kind=route loads heading", async ({ page }) => {
    await page.goto(`/admin/offline-uploads?kind=${F.KINDS[5]}`);
    await expectHeading(page, HEADINGS.uploads);
  });

  test("uploads deep-link ?kind=area loads heading", async ({ page }) => {
    await page.goto(`/admin/offline-uploads?kind=${F.KINDS[6]}`);
    await expectHeading(page, HEADINGS.uploads);
  });

  test("backups deep-link ?kind=place loads heading", async ({ page }) => {
    await page.goto(`/admin/backups?kind=${F.KINDS[0]}`);
    await expectHeading(page, HEADINGS.backups);
  });

  test("backups deep-link ?kind=event loads heading", async ({ page }) => {
    await page.goto(`/admin/backups?kind=${F.KINDS[1]}`);
    await expectHeading(page, HEADINGS.backups);
  });

  test("backups deep-link ?kind=notice loads heading", async ({ page }) => {
    await page.goto(`/admin/backups?kind=${F.KINDS[2]}`);
    await expectHeading(page, HEADINGS.backups);
  });

  test("backups deep-link ?kind=price loads heading", async ({ page }) => {
    await page.goto(`/admin/backups?kind=${F.KINDS[3]}`);
    await expectHeading(page, HEADINGS.backups);
  });

  test("backups deep-link ?kind=route loads heading", async ({ page }) => {
    await page.goto(`/admin/backups?kind=${F.KINDS[5]}`);
    await expectHeading(page, HEADINGS.backups);
  });

  test("backups deep-link ?kind=area loads heading", async ({ page }) => {
    await page.goto(`/admin/backups?kind=${F.KINDS[6]}`);
    await expectHeading(page, HEADINGS.backups);
  });

  test("poi deep-link ?kind=place loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?kind=${F.KINDS[0]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?kind=event loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?kind=${F.KINDS[1]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?kind=notice loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?kind=${F.KINDS[2]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?kind=price loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?kind=${F.KINDS[3]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?kind=route loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?kind=${F.KINDS[5]}`);
    await expectHeading(page, HEADINGS.poi);
  });

  test("poi deep-link ?kind=area loads heading", async ({ page }) => {
    await page.goto(`/admin/poi-cache-targets?kind=${F.KINDS[6]}`);
    await expectHeading(page, HEADINGS.poi);
  });

});
