import { expect, test, type Locator, type Page, type Response } from "@playwright/test";

import type { components } from "../../src/api/types";

// LIVE (non-mock) e2e for /etl (ETL preview, admin-internal debug surface). USER-INPUT →
// client-derived cascade / API param → response → UI round-trip. READ-ONLY: the page only
// reads the ETL catalog (GET /v1/debug/etl/providers) and runs the fixture preview transform
// (POST /v1/debug/etl/{provider}/{dataset}/preview?source=fixture), which performs NO DB
// write — the router module docstring states "적재(DB write)는 아직 없음 — 변환 결과만 JSON으로
// 응답" and the post_preview description states "DB write 없음". Therefore BOTH scenarios are
// UNGATED (always runnable; nothing is created → no cleanup/finally needed).
//
// This DEEPENS the route-mocked e2e/etl.spec.ts (issue #574). That spec only drives a couple
// of hard-coded provider/dataset picks against fixed selectors. Here we:
//   A) drive the provider→dataset cascade off the LIVE catalog payload and assert the
//      reset-on-provider-change contract (issue #553 area), and
//   B) run the fixture preview and assert the transform result reflects in the UI AND matches
//      a direct backend re-read of the same preview endpoint.
//
// Surface + selectors are read VERBATIM from src/app/etl/etl-client.tsx:
//   route                /etl
//   h1 heading           "ETL preview"
//     <h1 ...>ETL preview</h1>                                                  (line 118)
//   provider select      getByLabel("provider")
//     <FieldLabel htmlFor="provider">provider</FieldLabel>                      (line 160)
//     <NativeSelect id="provider" ... {...providerField} onChange={...
//        form.setValue("dataset", "", { shouldDirty, shouldValidate }) }>       (lines 161-172)
//     provider <option> label: `{entry.provider} ({entry.datasets.length})`     (lines 176-181)
//   dataset select       getByLabel("dataset")
//     <FieldLabel htmlFor="dataset">dataset</FieldLabel>                        (line 190)
//     <NativeSelect id="dataset" disabled={!provider} {...datasetField}>        (lines 191-196)
//     dataset <option> label: `{entry.dataset} [{entry.variant}] · {previewSuffix(...)}` (204-205)
//     selected-dataset metadata badge: <Badge ...>{selectedDataset.feature_kind}</Badge> (216)
//   source select        getByLabel("source")  (default "fixture")
//     <FieldLabel htmlFor="source">source</FieldLabel>                          (line 238)
//     <NativeSelect id="source" {...sourceField}> fixture/live options          (lines 239-251)
//   submit button        getByRole("button", { name: "Preview 실행" })
//     <Button type="submit">...{isPending ? "실행 중" : "Preview 실행"}</Button>  (lines 256-263)
//   preview count        getByTestId("preview-count")  → `{items.length}건`      (lines 298-303)
//   result summary       badges {provider}/{dataset}/{variant} + count span      (lines 290-304)
//   result JSON          <pre> (JsonBlock = JSON.stringify(items, null, 2))      (lines 43-49, 305)
//
// API + router (packages/kor-travel-map-api/.../routers/etl.py, prefix /debug/etl mounted at /v1):
//   GET  /v1/debug/etl/providers                                @router.get("/providers")   (line 207)
//   POST /v1/debug/etl/{provider}/{dataset}/preview?source=...  @router.post(".../preview")  (line 249)
//        → source=fixture: run_fixture_preview (offline transform, no external call, no DB write)
//
// NOTE: source=live is intentionally NOT exercised — it calls the real provider client
// (external API, quota, may 501/502/503 when unwired) and would be flaky/non-deterministic.

type ProvidersResponse = components["schemas"]["ProvidersResponse"];
type EtlPreviewResponse = components["schemas"]["EtlPreviewResponse"];

type BrowserFetchResult<T> = {
  body: T | null;
  status: number;
  text: string;
};

type FixtureTarget = {
  provider: string;
  dataset: string;
  featureKind: string;
  variant: string;
  datasetCount: number;
};

const ROUTE = "/etl";
const HEADING = "ETL preview";
const PROVIDERS_PATH = "/v1/debug/etl/providers";

const UI_TIMEOUT = 15_000;
const FLOW_TIMEOUT = 5 * 60 * 1000;
const T = { timeout: UI_TIMEOUT } as const;

// read-only spec — nothing is created, so RUN_ID is only a per-run trace tag (no entity
// collisions / no cleanup possible). kept per repo convention for parallel re-run hygiene.
const RUN_ID = `live-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

test.describe.configure({ mode: "serial" });

function apiPath(response: Response): string {
  const pathname = new URL(response.url()).pathname;
  const path = pathname.startsWith("/api/proxy/")
    ? pathname.slice("/api/proxy".length)
    : pathname;
  return decodeURIComponent(path);
}

function isApiResponse(
  response: Response,
  method: string,
  path: string,
): boolean {
  return response.request().method() === method && apiPath(response) === path;
}

async function waitForApiResponse(
  page: Page,
  method: string,
  path: string,
): Promise<Response> {
  return page.waitForResponse(
    (response) => isApiResponse(response, method, decodeURIComponent(path)),
    { timeout: FLOW_TIMEOUT },
  );
}

async function browserFetch<T>(
  page: Page,
  path: string,
  options: { body?: unknown; method?: "GET" | "POST" | "PATCH" | "DELETE" } = {},
): Promise<BrowserFetchResult<T>> {
  return page.evaluate(
    async ({ body, method, path }) => {
      const response = await fetch(`/api/proxy${path}`, {
        method,
        headers: {
          Accept: "application/json",
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        credentials: "same-origin",
        cache: "no-store",
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      const text = await response.text();
      let parsed: unknown = null;
      try {
        parsed = text.length > 0 ? JSON.parse(text) : null;
      } catch {
        parsed = null;
      }
      return { body: parsed as T | null, status: response.status, text };
    },
    {
      body: options.body,
      method: options.method ?? "GET",
      path,
    },
  );
}

function previewPath(provider: string, dataset: string): string {
  return `/v1/debug/etl/${provider}/${dataset}/preview`;
}

// /etl로 이동하고 providers 카탈로그가 로드돼 form(provider select)이 렌더될 때까지 대기.
async function gotoEtl(page: Page): Promise<void> {
  await page.goto(ROUTE);
  await expect(
    page.getByRole("heading", { level: 1, name: HEADING }),
  ).toBeVisible(T);
  // form은 providersQuery.data가 있을 때만 렌더된다 → provider select 가시성 = 카탈로그 로드 완료.
  await expect(page.getByLabel("provider", { exact: true })).toBeVisible(T);
}

// dataset Field(role=group) — selected-dataset 메타데이터 badge가 들어있는 가장 안쪽 group.
// 바깥 admin-shell group이 dataset select를 감쌀 수 있으므로 .last()로 innermost를 고른다.
function datasetGroup(page: Page): Locator {
  return page
    .getByRole("group")
    .filter({ has: page.getByLabel("dataset", { exact: true }) })
    .last();
}

// 라이브 카탈로그에서 fixture preview 가능한 첫 (provider, dataset)을 고른다.
function findFixtureTarget(data: ProvidersResponse): FixtureTarget | null {
  for (const entry of data.data.providers) {
    for (const ds of entry.datasets) {
      if (ds.preview === "fixture") {
        return {
          provider: entry.provider,
          dataset: ds.dataset,
          featureKind: ds.feature_kind,
          variant: ds.variant,
          datasetCount: entry.datasets.length,
        };
      }
    }
  }
  return null;
}

// fixtureTarget과 다른 provider(초기화 검증용). 없으면 null.
function findOtherProvider(data: ProvidersResponse, exclude: string): string | null {
  const other = data.data.providers.find((p) => p.provider !== exclude);
  return other ? other.provider : null;
}

async function fetchProviders(
  page: Page,
): Promise<BrowserFetchResult<ProvidersResponse>> {
  return browserFetch<ProvidersResponse>(page, PROVIDERS_PATH);
}

test.describe("/etl ETL preview live read round-trip", () => {
  test("provider→dataset cascade: provider 선택 시 dataset 옵션이 카탈로그대로 채워지고 메타데이터가 반영되며 provider 변경 시 dataset이 초기화된다(#553)", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    test.info().annotations.push({ type: "run_id", description: RUN_ID });

    await gotoEtl(page);

    // ── backend 카탈로그 ground-truth (GET /v1/debug/etl/providers) ──
    const providers = await fetchProviders(page);
    expect(providers.status).toBe(200);
    expect(providers.body).not.toBeNull();
    const catalog = providers.body as ProvidersResponse;
    expect(catalog.data.providers.length).toBeGreaterThan(0);

    const target = findFixtureTarget(catalog);
    expect(
      target,
      "라이브 카탈로그에 preview=fixture dataset이 최소 1개 있어야 한다(etl_fixtures.FIXTURE_REGISTRY)",
    ).not.toBeNull();
    const { provider, dataset, featureKind, datasetCount } =
      target as FixtureTarget;

    const otherProvider = findOtherProvider(catalog, provider);
    expect(otherProvider).not.toBeNull();

    const providerSelect = page.getByLabel("provider", { exact: true });
    const datasetSelect = page.getByLabel("dataset", { exact: true });

    await test.step("초기 상태: provider 미선택이면 dataset select는 비활성이다", async () => {
      await expect(providerSelect).toHaveValue("");
      await expect(datasetSelect).toBeDisabled();
    });

    await test.step("provider option label이 backend dataset 수를 반영한다", async () => {
      // option label = `${provider} (${datasets.length})` — client-derived dataset 목록의 길이.
      const providerOption = providerSelect.locator(`option[value="${provider}"]`);
      await expect(providerOption).toHaveCount(1);
      await expect(providerOption).toHaveText(`${provider} (${datasetCount})`);
    });

    await test.step("provider 선택 → dataset select 활성화 + 카탈로그 dataset 옵션이 채워진다", async () => {
      await providerSelect.selectOption(provider);
      await expect(datasetSelect).toBeEnabled();
      // dataset 옵션은 클라이언트가 providers payload에서 파생(별도 API 호출 없음).
      await expect(
        datasetSelect.locator(`option[value="${dataset}"]`),
      ).toHaveCount(1);
    });

    await test.step("dataset 선택 → 값/메타데이터(feature_kind badge)가 반영된다", async () => {
      await datasetSelect.selectOption(dataset);
      await expect(datasetSelect).toHaveValue(dataset);
      // 선택된 dataset의 feature_kind badge는 dataset group 안에서만 나타난다(옵션 텍스트엔 없음).
      await expect(
        datasetGroup(page).getByText(featureKind, { exact: true }),
      ).toBeVisible(T);
      // 안내 문구도 표면에 있다.
      await expect(
        page.getByText("provider를 바꾸면 dataset 선택은 초기화됩니다.", {
          exact: false,
        }),
      ).toBeVisible(T);
    });

    await test.step("provider 변경 → dataset 선택이 초기화되고 메타데이터 badge가 사라진다(#553)", async () => {
      await providerSelect.selectOption(otherProvider as string);
      // onChange 핸들러가 form.setValue("dataset", "")로 초기화.
      await expect(datasetSelect).toHaveValue("");
      // selectedDataset == null → feature_kind badge 미렌더.
      await expect(
        datasetGroup(page).getByText(featureKind, { exact: true }),
      ).toHaveCount(0);
    });
  });

  test("fixture preview POST가 읽기 전용으로 변환 결과를 UI에 반영하고 backend 재조회와 일치한다", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    test.info().annotations.push({ type: "run_id", description: RUN_ID });

    await gotoEtl(page);

    const providers = await fetchProviders(page);
    expect(providers.status).toBe(200);
    const catalog = providers.body as ProvidersResponse;
    const target = findFixtureTarget(catalog);
    expect(target).not.toBeNull();
    const { provider, dataset } = target as FixtureTarget;

    const providerSelect = page.getByLabel("provider", { exact: true });
    const datasetSelect = page.getByLabel("dataset", { exact: true });
    const sourceSelect = page.getByLabel("source", { exact: true });

    await test.step("provider/dataset 선택 + source는 fixture 기본값", async () => {
      await providerSelect.selectOption(provider);
      await datasetSelect.selectOption(dataset);
      await expect(datasetSelect).toHaveValue(dataset);
      // defaultValues.source === "fixture" — read-only 변환 모드.
      await expect(sourceSelect).toHaveValue("fixture");
    });

    let uiItemCount = 0;
    let uiVariant = "";

    await test.step("Preview 실행 → POST preview 응답이 fixture 변환 결과를 돌려준다", async () => {
      const responsePromise = waitForApiResponse(
        page,
        "POST",
        previewPath(provider, dataset),
      );
      await page.getByRole("button", { name: "Preview 실행" }).click();
      const response = await responsePromise;

      expect(response.status()).toBe(200);
      const body = (await response.json()) as EtlPreviewResponse;
      expect(body.data.provider).toBe(provider);
      expect(body.data.dataset).toBe(dataset);
      expect(body.data.source).toBe("fixture");
      expect(body.data.items.length).toBeGreaterThan(0);
      uiItemCount = body.data.items.length;
      uiVariant = body.data.variant;

      // ── UI 반영: 요약 badge(provider/dataset/variant) + count + JSON ──
      const summary = page.getByTestId("preview-count").locator("xpath=..");
      await expect(summary).toContainText(`${uiItemCount}건`, T);
      await expect(summary).toContainText(provider, T);
      await expect(summary).toContainText(dataset, T);
      await expect(summary).toContainText(uiVariant, T);

      // 변환 결과 JSON(pre)에 첫 item의 top-level key가 들어있다(데이터 주도 검증).
      const firstKey = Object.keys(body.data.items[0] ?? {})[0];
      expect(firstKey, "fixture 변환 item에 최소 1개 key가 있어야 한다").toBeTruthy();
      const resultPre = page.locator("pre").last();
      await expect(resultPre).toContainText(firstKey as string, T);
    });

    await test.step("backend 재조회(POST preview)가 UI가 표시한 결과와 동일하다", async () => {
      const direct = await browserFetch<EtlPreviewResponse>(
        page,
        `${previewPath(provider, dataset)}?source=fixture`,
        { method: "POST" },
      );
      expect(direct.status).toBe(200);
      expect(direct.body).not.toBeNull();
      const directBody = direct.body as EtlPreviewResponse;
      expect(directBody.data.provider).toBe(provider);
      expect(directBody.data.dataset).toBe(dataset);
      expect(directBody.data.source).toBe("fixture");
      expect(directBody.data.variant).toBe(uiVariant);
      // fixture 변환은 결정적 → UI가 보여준 item 수와 동일.
      expect(directBody.data.items.length).toBe(uiItemCount);
    });
  });
});
