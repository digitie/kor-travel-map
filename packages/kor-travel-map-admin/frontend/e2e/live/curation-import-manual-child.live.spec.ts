import { expect, test } from "@playwright/test";

/**
 * T-VN-M03 — manual Feature child 발급의 격리 live acceptance (사상 첫 harness).
 *
 * manual_feature_* typed 열이 든 1행 CSV를 admin UI 업로드 → preview → commit으로
 * 완주시키고, commit 응답의 ordered `manual_children`(transaction 확정값)과 생성된
 * Feature/item이 admin REST에서 관측되는 것까지 확인한다. linkage 표 자체는 command
 * owner 전용이라 API 표면이 없다 — DB 결박은 통합 테스트
 * (tests/integration/test_m03_import_child_issuance.py)가 소유하고, 여기서는
 * 부모 응답 summary와 읽기 표면의 정합만 판정한다.
 *
 * 쓰기 스펙이므로 명시 opt-in: E2E_MANUAL_IMPORT_WRITE=1 (격리 스택 전용 —
 * 만든 collection/Feature를 지우지 않는다).
 */

type Envelope<T> = { data: T };

const FLOW_TIMEOUT = 120_000;
const EXECUTE = process.env.E2E_MANUAL_IMPORT_WRITE === "1";
// 격리 스택의 seed catalog에 실재하는 pair여야 preview가 422로 끊지 않는다.
const PROVIDER = process.env.E2E_MANUAL_IMPORT_PROVIDER ?? "data.go.kr-standard";
const DATASET_KEY =
  process.env.E2E_MANUAL_IMPORT_DATASET_KEY ?? "datagokr_museums";

function manualCsv(suffix: string): string {
  const headers = [
    "collection_key",
    "theme_slug",
    "theme_name",
    "theme_group",
    "title",
    "edition_key",
    "subcourse",
    "provider",
    "dataset_key",
    "source_name",
    "source_url",
    "source_item_key",
    "source_component_key",
    "official_ordinal",
    "place_name",
    "address_hint",
    "feature_id",
    "sort_order",
    "item_title",
    "item_summary",
    "metadata_json",
    "manual_feature_kind",
    "manual_feature_category",
    "manual_feature_lon",
    "manual_feature_lat",
  ];
  const row = [
    `m03-live-${suffix}:2026`,
    `m03-live-${suffix}`,
    "M03 live 수동 생성",
    "test",
    "M03 live 수동 생성 acceptance",
    "2026",
    "",
    PROVIDER,
    DATASET_KEY,
    "M03 live acceptance",
    "",
    `manual-${suffix}`,
    "primary",
    "",
    `수동 생성 장소 ${suffix}`,
    "",
    "",
    "1",
    "",
    "",
    "",
    "place",
    "12010000",
    "126.99100",
    "37.57960",
  ];
  return `﻿${headers.join(",")}\n${row.join(",")}\n`;
}

test.describe("M03 manual child 격리 live acceptance", () => {
  test("manual 행 CSV가 child 발급까지 완주하고 읽기 표면과 정합한다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE,
      "쓰기 스펙 — 격리 스택에서 E2E_MANUAL_IMPORT_WRITE=1 명시 opt-in이 필요합니다.",
    );
    test.setTimeout(5 * 60_000);
    const suffix = `${Date.now().toString(36)}`;

    await page.goto("/admin/features/curated");
    await expect(
      page.getByRole("heading", { level: 1, name: "큐레이션 관리" }),
    ).toBeVisible({ timeout: FLOW_TIMEOUT });

    await page.getByLabel("CSV 파일").setInputFiles({
      name: `m03-manual-${suffix}.csv`,
      mimeType: "text/csv",
      buffer: Buffer.from(manualCsv(suffix), "utf-8"),
    });

    const previewResponse = page.waitForResponse(
      (response) =>
        response.url().includes("/api/proxy/v1/admin/curations/imports/preview") &&
        response.request().method() === "POST",
      { timeout: FLOW_TIMEOUT },
    );
    await page.getByRole("button", { name: "매칭 미리보기" }).click();
    const preview = await previewResponse;
    expect(preview.status()).toBe(201);
    const previewBody = (await preview.json()) as Envelope<{
      rows_total: number;
      invalid_rows: number;
    }>;
    expect(previewBody.data.rows_total).toBe(1);
    expect(previewBody.data.invalid_rows).toBe(0);

    const commitResponse = page.waitForResponse(
      (response) =>
        response.url().includes("/api/proxy/v1/admin/curations/import-plans/") &&
        response.url().endsWith("/commit") &&
        response.request().method() === "POST",
      { timeout: FLOW_TIMEOUT },
    );
    page.once("dialog", (dialog) => void dialog.accept());
    await page.getByRole("button", { name: "전체 반영" }).click();
    const commit = await commitResponse;
    expect(commit.status()).toBe(200);
    const commitBody = (await commit.json()) as Envelope<{
      inserted: number;
      manual_children: Array<{
        row_number: number;
        child_command_id: number;
        feature_id: string;
        feature_uuid: string;
        curation_item_id: string;
      }>;
    }>;

    // ── 부모 summary는 transaction 확정값이다(설계 §6.3) ────────────────
    expect(commitBody.data.manual_children).toHaveLength(1);
    const child = commitBody.data.manual_children[0];
    expect(child.row_number).toBe(2);
    expect(child.child_command_id).toBeGreaterThan(0);
    expect(child.feature_id).toMatch(/^f_/);

    // ── 생성된 Feature가 admin 읽기 표면에서 관측된다 ───────────────────
    const feature = await page.request.get(
      `/api/proxy/v1/admin/features/${child.feature_uuid}`,
    );
    expect(feature.status()).toBe(200);
    const featureBody = (await feature.json()) as Envelope<{
      feature: { name: string; category: string };
    }>;
    expect(featureBody.data.feature.name).toBe(`수동 생성 장소 ${suffix}`);
    expect(featureBody.data.feature.category).toBe("12010000");
  });
});
