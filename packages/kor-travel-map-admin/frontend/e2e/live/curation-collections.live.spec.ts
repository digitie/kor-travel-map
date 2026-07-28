import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

import { expectDetailPanelAboveScaleControl } from "../map-control-assertions";

type Collection = {
  collection_id: string;
  collection_key: string;
  item_count: number;
};

type Curation = {
  edition_key: string;
  provider: string | null;
  title: string;
};

type AdminCurationItem = {
  external_component_id: string;
  external_item_id: string;
  feature_id: string | null;
};

type CurationGroup = {
  feature: { feature_id: string; name: string };
  curations: Curation[];
};

type Observation = {
  provider: string;
  source_entity_key: string;
};

type Envelope<T> = { data: T; meta?: Record<string, unknown> };

const FLOW_TIMEOUT = 120_000;
const EXECUTE_IMPORT = process.env.E2E_CURATION_IMPORT_WRITE === "1";
const EXPECTED_OFFICIAL_PUBLIC_MEMBERSHIPS = expectedLiveCount(
  "E2E_EXPECTED_OFFICIAL_PUBLIC_MEMBERSHIPS",
  486,
);
const EXPECTED_UNLINKED_BEAUTIFUL_LIGHTHOUSES = expectedLiveCount(
  "E2E_EXPECTED_UNLINKED_BEAUTIFUL_LIGHTHOUSES",
  15,
  15,
);
const EXPECTED_BEAUTIFUL_LIGHTHOUSE_MATCHES = expectedLiveMatches(
  "E2E_EXPECTED_BEAUTIFUL_LIGHTHOUSE_MATCHES",
  15 - EXPECTED_UNLINKED_BEAUTIFUL_LIGHTHOUSES,
);
const MULTI_OBSERVATION_FEATURE_ID = "f_4127310100_e_227e045425edb459";
const RESOURCE_ROOT =
  process.env.E2E_CURATION_RESOURCE_ROOT ??
  path.resolve(process.cwd(), "../../../resources/curations");

const OFFICIAL_FILES = [
  ["korean-tourism-100-2023-2024.csv", 110],
  ["korean-tourism-100-2025-2026.csv", 114],
  ["heritage-visit-campaign.csv", 85],
  ["arboretum-garden-stamp-tour-2026.csv", 72],
  ["lighthouse-stamp-tour.csv", 105],
] as const;

const OFFICIAL_COLLECTION_KEYS = [
  "arboretum-garden-stamp-tour:2026",
  "heritage-visit-campaign:baekje-ancient-capitals-route:current",
  "heritage-visit-campaign:gaya-civilization-route:current",
  "heritage-visit-campaign:gwandong-pungnyu-route:current",
  "heritage-visit-campaign:mountain-temples-route:current",
  "heritage-visit-campaign:myth-and-nature-route:current",
  "heritage-visit-campaign:prehistoric-geology-route:current",
  "heritage-visit-campaign:royal-family-route:current",
  "heritage-visit-campaign:seowon-route:current",
  "heritage-visit-campaign:sound-route:current",
  "heritage-visit-campaign:thousand-year-spirit-route:current",
  "korean-tourism-100:2023-2024",
  "korean-tourism-100:2025-2026",
  "lighthouse-stamp-tour:abundant-lighthouses:season-4",
  "lighthouse-stamp-tour:beautiful-lighthouses:season-1",
  "lighthouse-stamp-tour:fun-lighthouses:season-3",
  "lighthouse-stamp-tour:healing-lighthouses:season-5",
  "lighthouse-stamp-tour:historic-lighthouses:season-2",
  "lighthouse-stamp-tour:sunrise-lighthouses:season-6",
] as const;

test.describe.configure({ mode: "serial" });

function expectedLiveCount(name: string, fallback: number, maximum?: number): number {
  const raw = process.env[name];
  if (raw !== undefined && !/^(0|[1-9]\d*)$/.test(raw)) {
    throw new Error(
      `${name} must be a non-empty decimal integer; received ${JSON.stringify(raw)}`,
    );
  }
  const value = raw === undefined ? fallback : Number(raw);
  if (
    !Number.isSafeInteger(value) ||
    value < 0 ||
    (maximum !== undefined && value > maximum)
  ) {
    const range = maximum === undefined ? "non-negative" : `between 0 and ${maximum}`;
    throw new Error(
      `${name} must be a ${range} safe integer; received ${JSON.stringify(raw)}`,
    );
  }
  return value;
}

function expectedLiveMatches(name: string, expectedCount: number): string[] {
  const raw = process.env[name];
  if (raw === undefined && expectedCount === 0) return [];
  if (raw === undefined || raw.length === 0 || raw.trim() !== raw) {
    throw new Error(`${name} must declare ${expectedCount} source=feature pair(s)`);
  }
  const pairs = raw.split(",");
  if (
    pairs.length !== expectedCount ||
    pairs.some((pair) => !/^[^=,\s]+=[^=,\s]+$/.test(pair))
  ) {
    throw new Error(
      `${name} must contain ${expectedCount} comma-separated source=feature pair(s)`,
    );
  }
  if (new Set(pairs).size !== pairs.length) {
    throw new Error(`${name} must not contain duplicate source=feature pairs`);
  }
  const sourceKeys = pairs.map((pair) => pair.slice(0, pair.indexOf("=")));
  const featureIds = pairs.map((pair) => pair.slice(pair.indexOf("=") + 1));
  if (
    new Set(sourceKeys).size !== pairs.length ||
    new Set(featureIds).size !== pairs.length
  ) {
    throw new Error(`${name} must contain unique source keys and feature IDs`);
  }
  return pairs.sort();
}

async function browserJson<T>(page: Page, pathName: string): Promise<T> {
  return page.evaluate(async (pathValue) => {
    const response = await fetch(`/api/proxy${pathValue}`, {
      cache: "no-store",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    const text = await response.text();
    if (!response.ok) {
      throw new Error(`${pathValue}: ${response.status} ${text.slice(0, 500)}`);
    }
    return JSON.parse(text) as T;
  }, pathName);
}

async function allTourismGroups(page: Page): Promise<CurationGroup[]> {
  const groups: CurationGroup[] = [];
  let cursor: string | null = null;
  for (;;) {
    const query = new URLSearchParams({
      page_size: "500",
      theme_slug: "korean-tourism-100",
    });
    if (cursor) query.set("cursor", cursor);
    const response = await browserJson<
      Envelope<{ items: CurationGroup[] }> & {
        meta: { page?: { next_cursor?: string | null } };
      }
    >(page, `/v1/curations?${query.toString()}`);
    groups.push(...response.data.items);
    cursor = response.meta.page?.next_cursor ?? null;
    if (!cursor) return groups;
  }
}

test.describe("공식 큐레이션 collection live", () => {
  test("관리자 UI에서 공식 CSV를 preview 후 원자적으로 반영한다", async ({ page }) => {
    test.skip(
      !EXECUTE_IMPORT,
      "prod 공식 데이터 반영은 E2E_CURATION_IMPORT_WRITE=1 명시 opt-in이 필요합니다.",
    );
    test.setTimeout(10 * 60_000);

    await page.goto("/admin/features/curated");
    await expect(
      page.getByRole("heading", { level: 1, name: "큐레이션 관리" }),
    ).toBeVisible({ timeout: FLOW_TIMEOUT });

    for (const [fileName, rows] of OFFICIAL_FILES) {
      await page.getByLabel("CSV 파일").setInputFiles(path.join(RESOURCE_ROOT, fileName));

      const previewResponse = page.waitForResponse(
        (response) =>
          response.url().includes("/api/proxy/v1/admin/curations/import") &&
          response.url().includes("dry_run=true") &&
          response.request().method() === "POST",
        { timeout: FLOW_TIMEOUT },
      );
      await page.getByRole("button", { name: "매칭 미리보기" }).click();
      expect((await previewResponse).status()).toBe(200);

      const report = page.getByTestId("curation-import-report");
      await expect(report.getByText("미리보기", { exact: true })).toBeVisible();
      await expect(report.getByText(`전체 ${rows}`, { exact: true })).toBeVisible();
      await expect(report.getByText("오류 0", { exact: true })).toBeVisible();

      const commitResponse = page.waitForResponse(
        (response) =>
          response.url().includes("/api/proxy/v1/admin/curations/import") &&
          response.url().includes("dry_run=false") &&
          response.request().method() === "POST",
        { timeout: FLOW_TIMEOUT },
      );
      page.once("dialog", async (dialog) => dialog.accept());
      await page.getByRole("button", { name: "전체 반영" }).click();
      expect((await commitResponse).status()).toBe(200);
      await expect(report.getByText("반영 결과", { exact: true })).toBeVisible();
      await expect(report.getByText(`전체 ${rows}`, { exact: true })).toBeVisible();
      await expect(report.getByText("오류 0", { exact: true })).toBeVisible();
      await expect(report.getByText(/^제거 \d+$/)).toBeVisible();
    }
  });

  test("REST와 관리자 상세에 19개 공식 collection·membership·미연결 등대를 보존한다", async ({
    page,
  }) => {
    await page.goto("/admin/features/curated");

    const categories = await browserJson<
      Envelope<{ items: Array<{ code: string; label: string }> }>
    >(page, "/v1/categories");
    expect(categories.data.items).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          code: "01050400",
          label: "관광 > 자연명소 > 등대",
        }),
      ]),
    );

    const response = await browserJson<Envelope<{ items: Collection[] }>>(
      page,
      "/v1/curations/collections?page_size=500",
    );
    const byKey = new Map(
      response.data.items.map((collection) => [collection.collection_key, collection]),
    );
    for (const key of OFFICIAL_COLLECTION_KEYS) expect(byKey.has(key), key).toBe(true);
    expect(
      OFFICIAL_COLLECTION_KEYS.reduce(
        (total, key) => total + (byKey.get(key)?.item_count ?? 0),
        0,
      ),
    ).toBe(EXPECTED_OFFICIAL_PUBLIC_MEMBERSHIPS);

    const template = await page.evaluate(async () => {
      const response = await fetch("/api/proxy/v1/admin/curations/import-template.csv", {
        cache: "no-store",
        credentials: "same-origin",
      });
      return {
        disposition: response.headers.get("content-disposition"),
        status: response.status,
        text: await response.text(),
      };
    });
    expect(template.status).toBe(200);
    expect(template.disposition).toMatch(/attachment;.*\.csv/i);
    expect(template.text.split(/\r?\n/, 1)[0]).toContain(
      "source_item_key,source_component_key",
    );

    const tourismCollection = byKey.get("korean-tourism-100:2023-2024");
    expect(tourismCollection).toBeDefined();
    const tourismDetail = await browserJson<
      Envelope<{ collection: Collection; items: AdminCurationItem[] }>
    >(
      page,
      `/v1/admin/curations/${encodeURIComponent(
        (tourismCollection as Collection).collection_id,
      )}`,
    );
    const palaceComponents = tourismDetail.data.items
      .filter((item) => item.external_item_id === "kt100-2023-2024-001")
      .map((item) => item.external_component_id)
      .sort();
    expect(palaceComponents).toEqual(["component-01", "component-02"]);

    const list = page.getByTestId("curation-collection-list");
    const lighthouseButton = list.getByRole("button", {
      name: /아름다운 등대 · 등대 스탬프투어/,
    });
    await lighthouseButton.click();
    const lighthouseCollection = byKey.get(
      "lighthouse-stamp-tour:beautiful-lighthouses:season-1",
    );
    expect(lighthouseCollection).toBeDefined();
    const lighthouseDetail = await browserJson<
      Envelope<{ collection: Collection; items: AdminCurationItem[] }>
    >(
      page,
      `/v1/admin/curations/${encodeURIComponent(
        (lighthouseCollection as Collection).collection_id,
      )}`,
    );
    const linkedLighthouses = lighthouseDetail.data.items.filter(
      (item) => item.feature_id !== null,
    );
    expect(lighthouseDetail.data.items).toHaveLength(15);
    expect(linkedLighthouses).toHaveLength(
      15 - EXPECTED_UNLINKED_BEAUTIFUL_LIGHTHOUSES,
    );
    expect(
      linkedLighthouses
        .map((item) => `${item.external_item_id}=${item.feature_id}`)
        .sort(),
    ).toEqual(EXPECTED_BEAUTIFUL_LIGHTHOUSE_MATCHES);
    const detail = page.getByTestId("curation-collection-detail");
    await expect(detail.getByText("Feature 미연결", { exact: true })).toHaveCount(
      EXPECTED_UNLINKED_BEAUTIFUL_LIGHTHOUSES,
    );
  });

  test("지도 marker·목록·Feature 상세·REST가 두 회차와 복수 관측을 모두 표시한다", async ({
    page,
  }) => {
    test.setTimeout(3 * 60_000);
    await page.goto("/curated-features");

    const groups = await allTourismGroups(page);
    const multiEdition = groups.find((group) => {
      const editions = new Set(group.curations.map((item) => item.edition_key));
      return editions.has("2023-2024") && editions.has("2025-2026");
    });
    expect(multiEdition, "두 회차에 모두 연결된 실 Feature가 필요합니다.").toBeDefined();
    const group = multiEdition as CurationGroup;

    const feature = await browserJson<
      Envelope<{ curations: Curation[]; observations: Observation[] }>
    >(page, `/v1/features/${encodeURIComponent(group.feature.feature_id)}`);
    expect(feature.data.curations.map((item) => item.edition_key)).toEqual(
      expect.arrayContaining(["2023-2024", "2025-2026"]),
    );

    await page.getByLabel("테마 필터").selectOption("korean-tourism-100");
    await page
      .getByLabel("POI명 또는 큐레이션 제목 필터")
      .fill(group.feature.name);
    const marker = page.getByRole("button", {
      name: `${group.feature.name} (place)`,
      exact: true,
    });
    await expect(marker).toBeVisible({ timeout: FLOW_TIMEOUT });
    await marker.click();
    if (!(await page.getByTestId("curation-group-detail").isVisible())) {
      await page
        .getByRole("button", { name: `장소 ${group.feature.name}`, exact: true })
        .click();
    }
    const mapDetail = page.getByTestId("curation-group-detail");
    await expect(mapDetail.getByText("2023-2024", { exact: true })).toBeVisible();
    await expect(mapDetail.getByText("2025-2026", { exact: true })).toBeVisible();
    await expectDetailPanelAboveScaleControl(page, "curation-group-detail");

    await page.getByRole("tab", { name: "테이블" }).click();
    const table = page.getByRole("table", { name: "큐레이션 Feature 그룹" });
    await table
      .getByRole("row")
      .filter({ hasText: group.feature.name })
      .first()
      .click();
    await expect(page.getByTestId("curation-group-detail")).toContainText("큐레이션 소속");

    await page.goto(`/features/${encodeURIComponent(group.feature.feature_id)}`);
    const featureDetail = page.getByTestId("feature-detail-view");
    await expect(featureDetail.getByText("2023-2024", { exact: true })).toBeVisible();
    await expect(featureDetail.getByText("2025-2026", { exact: true })).toBeVisible();

    // T-VN-05: raw observation lineage는 공개 detail에서 제거돼 operator 표면
    // (GET /v1/features/{id}/sources)으로 이동했다. browserJson은 admin BFF
    // (/api/proxy)를 통해 호출하므로 operator로 인증된다.
    const observed = await browserJson<
      Envelope<{ observations: Observation[] }>
    >(page, `/v1/features/${encodeURIComponent(MULTI_OBSERVATION_FEATURE_ID)}/sources`);
    expect(observed.data.observations.length).toBeGreaterThanOrEqual(2);
    expect(observed.data.observations.map((item) => item.provider)).toEqual(
      expect.arrayContaining(["data.go.kr-standard", "python-visitkorea-api"]),
    );
    for (const observation of observed.data.observations) {
      // observation history도 operator-gated — 동일하게 인증된 BFF proxy 경유.
      const history = await browserJson<Envelope<{ items: unknown[] }>>(
        page,
        `/v1/features/${encodeURIComponent(
          MULTI_OBSERVATION_FEATURE_ID,
        )}/observations/${encodeURIComponent(observation.source_entity_key)}/history?page_size=1`,
      );
      expect(history.data.items.length).toBe(1);
    }
  });
});
