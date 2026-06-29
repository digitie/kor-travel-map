import {
  expect,
  test,
  type Locator,
  type Page,
  type Request,
  type Response,
} from "@playwright/test";

import type { components } from "../../src/api/types";

// LIVE (non-mock) e2e against the real deployed stack. SELF-RESTORING write:
// pick a provider/dataset that already has a refresh policy, change ONE field
// (targeted_policy) through the /ops/providers PolicyEditor, confirm the PUT
// round-trips into the backend (API GET) AND the freshness list UI, then PUT
// the captured original policy back in finally{} so the run leaves zero drift.
//
// This EXTENDS providers-consistency.live.spec.ts (read-only smoke) and the
// route-mocked providers-refresh-policy.spec.ts (mock PUT) by exercising the
// real PUT /v1/admin/provider-refresh-policies/{provider}/{dataset_key} upsert
// and asserting eventual backend + UI reflection.
//
// We RECONSTRUCT every editor field from the captured original record before
// flipping targeted_policy, because PolicyEditor seeds its draft lazily at
// mount (useState(() => policyToDraft(policy))) and the dataset detail query
// resolves AFTER the editor mounts — so the editor is NOT pre-populated. Full
// reconstruction guarantees the upsert changes only targeted_policy.

type OpsProvidersResponse = components["schemas"]["OpsProvidersResponse"];
type ProviderRefreshPolicyRecord =
  components["schemas"]["ProviderRefreshPolicyRecord"];
type ProviderRefreshPolicyResponse =
  components["schemas"]["ProviderRefreshPolicyResponse"];
type ProviderRefreshPolicyUpsertRequest =
  components["schemas"]["ProviderRefreshPolicyUpsertRequest"];

type BrowserFetchResult<T> = {
  body: T | null;
  status: number;
  text: string;
};

const UI_TIMEOUT = 15_000;
const FLOW_TIMEOUT = 5 * 60 * 1000;
const T = { timeout: UI_TIMEOUT } as const;

const RUN_ID = `live-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

const TARGETED_POLICIES = [
  "follow_system",
  "allow_targeted",
  "disabled",
] as const;
type TargetedPolicy = (typeof TARGETED_POLICIES)[number];

const EXECUTE_PROVIDER_POLICY_WRITE =
  process.env.E2E_ADMIN_WRITE === "1" ||
  process.env.E2E_PROVIDER_POLICY_WRITE === "1";

test.describe.configure({ mode: "serial" });

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function numberText(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

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
  options: {
    body?: unknown;
    method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  } = {},
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

// /admin/provider-refresh-policies router segments are encodeURIComponent'd by
// the app client (providerRefreshPolicies.ts). The proxied path mirrors that;
// the raw path matches apiPath() (which decodeURIComponent's). For the plain
// provider/dataset ids in this repo the two strings are identical, but we keep
// both so an exotic id never silently breaks the waitForResponse match.
function proxiedPolicyPath(provider: string, datasetKey: string): string {
  return `/v1/admin/provider-refresh-policies/${encodeURIComponent(
    provider,
  )}/${encodeURIComponent(datasetKey)}`;
}

function rawPolicyPath(provider: string, datasetKey: string): string {
  return `/v1/admin/provider-refresh-policies/${provider}/${datasetKey}`;
}

function pickNextTargeted(current: string): TargetedPolicy {
  return TARGETED_POLICIES.find((value) => value !== current) ?? "follow_system";
}

function recordToUpsert(
  record: ProviderRefreshPolicyRecord,
): ProviderRefreshPolicyUpsertRequest {
  return {
    source_kind:
      record.source_kind as ProviderRefreshPolicyUpsertRequest["source_kind"],
    targeted_policy:
      record.targeted_policy as ProviderRefreshPolicyUpsertRequest["targeted_policy"],
    system_interval_seconds: record.system_interval_seconds ?? null,
    optimal_interval_seconds: record.optimal_interval_seconds ?? null,
    min_interval_seconds: record.min_interval_seconds ?? null,
    max_requests_per_minute: record.max_requests_per_minute ?? null,
    max_requests_per_hour: record.max_requests_per_hour ?? null,
    max_requests_per_day: record.max_requests_per_day ?? null,
    max_concurrent: record.max_concurrent,
    burst_size: record.burst_size ?? null,
    rate_limit_source: record.rate_limit_source,
    config_source: record.config_source,
    enabled: record.enabled,
  };
}

async function fetchOpsProviders(
  page: Page,
): Promise<BrowserFetchResult<OpsProvidersResponse>> {
  return browserFetch<OpsProvidersResponse>(page, "/v1/ops/providers");
}

async function fetchPolicy(
  page: Page,
  provider: string,
  datasetKey: string,
): Promise<BrowserFetchResult<ProviderRefreshPolicyResponse>> {
  return browserFetch<ProviderRefreshPolicyResponse>(
    page,
    proxiedPolicyPath(provider, datasetKey),
  );
}

// First ops dataset that already carries a refresh policy — the only kind we
// can self-restore (the router exposes GET/PUT only; there is no DELETE, so a
// never-set policy could not be removed after creation).
async function findPolicyCandidate(
  page: Page,
): Promise<{ provider: string; datasetKey: string } | null> {
  const response = await fetchOpsProviders(page);
  if (response.status !== 200 || !response.body) {
    return null;
  }
  const item = response.body.data.items.find(
    (entry) => entry.refresh_policy != null,
  );
  return item
    ? { provider: item.provider, datasetKey: item.dataset_key }
    : null;
}

async function expectProvidersReady(page: Page): Promise<void> {
  await expect(
    page.getByRole("heading", { level: 1, name: "Providers" }),
  ).toBeVisible(T);
  await expect(page.getByRole("table").first()).toBeVisible(T);
}

function providerRow(page: Page, provider: string, datasetKey: string): Locator {
  return page
    .getByRole("row", {
      name: new RegExp(`${escapeRegExp(provider)}.*${escapeRegExp(datasetKey)}`),
    })
    .first();
}

// Drive the PolicyEditor draft to exactly `record`, overriding targeted_policy.
// Mirrors policyToDraft(): null numbers become empty inputs, max_concurrent is
// stringified, rate_limit_source is pretty-printed JSON. buildPolicyBody coerces
// these back, so the resulting upsert changes only targeted_policy.
async function applyPolicyToEditor(
  page: Page,
  record: ProviderRefreshPolicyRecord,
  targetedPolicy: TargetedPolicy,
): Promise<void> {
  await page.getByLabel("source kind").selectOption(record.source_kind);
  await page.getByLabel("targeted policy").selectOption(targetedPolicy);
  await page
    .getByLabel("system interval sec")
    .fill(numberText(record.system_interval_seconds));
  await page
    .getByLabel("optimal interval sec")
    .fill(numberText(record.optimal_interval_seconds));
  await page
    .getByLabel("min interval sec")
    .fill(numberText(record.min_interval_seconds));
  await page
    .getByLabel("requests / min")
    .fill(numberText(record.max_requests_per_minute));
  await page
    .getByLabel("requests / hour")
    .fill(numberText(record.max_requests_per_hour));
  await page
    .getByLabel("requests / day")
    .fill(numberText(record.max_requests_per_day));
  await page.getByLabel("max concurrent").fill(numberText(record.max_concurrent));
  await page.getByLabel("burst size").fill(numberText(record.burst_size));
  await page.getByLabel("config source").fill(record.config_source);
  await page.getByLabel("enabled", { exact: true }).setChecked(record.enabled);
  await page
    .getByLabel("rate limit source")
    .fill(JSON.stringify(record.rate_limit_source ?? {}, null, 2));
}

// Coerce a backend `targeted_policy` (typed as plain string in the schema) to
// the editor's literal union without flipping it — used when a scenario keeps
// the original policy and changes a *different* field.
function currentTargeted(value: string): TargetedPolicy {
  return (TARGETED_POLICIES as readonly string[]).includes(value)
    ? (value as TargetedPolicy)
    : "follow_system";
}

// Up to `max` DISTINCT provider/dataset pairs that already carry a refresh
// policy (deduped — the same policy can surface under multiple sync_scopes).
// Only existing policies are self-restorable (router has no DELETE).
async function findPolicyCandidates(
  page: Page,
  max: number,
): Promise<{ provider: string; datasetKey: string }[]> {
  const response = await fetchOpsProviders(page);
  if (response.status !== 200 || !response.body) {
    return [];
  }
  const seen = new Set<string>();
  const candidates: { provider: string; datasetKey: string }[] = [];
  for (const entry of response.body.data.items) {
    if (entry.refresh_policy == null) {
      continue;
    }
    const key = `${entry.provider} ${entry.dataset_key}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    candidates.push({ provider: entry.provider, datasetKey: entry.dataset_key });
    if (candidates.length >= max) {
      break;
    }
  }
  return candidates;
}

// Select a dataset row → its PolicyEditor mounts. Clicks the mono dataset cell
// (no stopPropagation) so the row onClick fires; the leading icon button stops
// propagation, so we must NOT click that.
async function selectDatasetRow(
  page: Page,
  provider: string,
  datasetKey: string,
): Promise<void> {
  const row = providerRow(page, provider, datasetKey);
  await expect(row).toBeVisible(T);
  await row.getByText(datasetKey, { exact: true }).click();
  await expect(
    page.getByText(`${provider}/${datasetKey}`).first(),
  ).toBeVisible(T);
  await expect(page.getByText("Refresh policy")).toBeVisible(T);
}

async function saveAndAwaitPut(
  page: Page,
  provider: string,
  datasetKey: string,
): Promise<Response> {
  const putPromise = waitForApiResponse(
    page,
    "PUT",
    rawPolicyPath(provider, datasetKey),
  );
  await page.getByRole("button", { name: "저장" }).click();
  return putPromise;
}

async function readPolicyResponse(
  response: Response,
): Promise<ProviderRefreshPolicyResponse> {
  return (await response.json()) as ProviderRefreshPolicyResponse;
}

// Self-restore: PUT the captured original back and confirm via API GET. PUTs the
// full record so every field (not just targeted_policy) is reverted.
async function restorePolicy(
  page: Page,
  provider: string,
  datasetKey: string,
  original: ProviderRefreshPolicyRecord,
): Promise<void> {
  await browserFetch<ProviderRefreshPolicyResponse>(
    page,
    proxiedPolicyPath(provider, datasetKey),
    { body: recordToUpsert(original), method: "PUT" },
  );
  await expect
    .poll(async () => {
      const response = await fetchPolicy(page, provider, datasetKey);
      return response.body?.data.targeted_policy ?? `http:${response.status}`;
    }, T)
    .toBe(original.targeted_policy);
}

test.describe("/ops/providers refresh policy live write round-trip", () => {
  test("기존 refresh policy의 targeted_policy를 UI에서 바꾸면 백엔드와 목록 UI에 반영되고 원복된다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_PROVIDER_POLICY_WRITE,
      "E2E_PROVIDER_POLICY_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 provider refresh policy write flow를 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    await page.goto("/ops/providers");
    await expectProvidersReady(page);

    const candidate = await findPolicyCandidate(page);
    test.skip(
      candidate === null,
      "기존 refresh policy를 가진 provider/dataset이 없어 self-restoring write를 건너뜀 " +
        `(run ${RUN_ID})`,
    );
    const { provider, datasetKey } = candidate as {
      provider: string;
      datasetKey: string;
    };

    const originalResponse = await fetchPolicy(page, provider, datasetKey);
    expect(originalResponse.status).toBe(200);
    expect(originalResponse.body).not.toBeNull();
    const original = (originalResponse.body as ProviderRefreshPolicyResponse)
      .data;
    const nextTargeted = pickNextTargeted(original.targeted_policy);

    try {
      await test.step("freshness 목록에서 대상 provider/dataset 행을 선택한다", async () => {
        const row = providerRow(page, provider, datasetKey);
        await expect(row).toBeVisible(T);
        // Plain (non-virtualized) DataTable row → onRowClick selects the dataset.
        // Click the mono dataset cell text (no stopPropagation) so the row's
        // onClick fires (the leading detail icon button stops propagation).
        await row.getByText(datasetKey, { exact: true }).click();

        // Selection drives both panel sub-headings to "{provider}/{datasetKey}".
        await expect(
          page.getByText(`${provider}/${datasetKey}`).first(),
        ).toBeVisible(T);
        await expect(page.getByText("Refresh policy")).toBeVisible(T);
      });

      await test.step("정책 폼을 원본값으로 채우고 targeted_policy만 바꿔 저장한다", async () => {
        await applyPolicyToEditor(page, original, nextTargeted);
        await expect(page.getByLabel("targeted policy")).toHaveValue(
          nextTargeted,
          T,
        );

        const putPromise = waitForApiResponse(
          page,
          "PUT",
          rawPolicyPath(provider, datasetKey),
        );
        await page.getByRole("button", { name: "저장" }).click();
        const putResponse = await putPromise;
        expect(putResponse.status()).toBe(200);

        const putBody =
          (await putResponse.json()) as ProviderRefreshPolicyResponse;
        // Only targeted_policy changed; every other field matches the original.
        expect(putBody.data).toMatchObject({
          provider,
          dataset_key: datasetKey,
          targeted_policy: nextTargeted,
          source_kind: original.source_kind,
          config_source: original.config_source,
          enabled: original.enabled,
          max_concurrent: original.max_concurrent,
        });
        expect(putBody.data.system_interval_seconds ?? null).toBe(
          original.system_interval_seconds ?? null,
        );
        expect(putBody.data.max_requests_per_minute ?? null).toBe(
          original.max_requests_per_minute ?? null,
        );
      });

      await test.step("API GET이 변경된 targeted_policy를 반영한다", async () => {
        await expect
          .poll(async () => {
            const response = await fetchPolicy(page, provider, datasetKey);
            return response.body?.data.targeted_policy ?? `http:${response.status}`;
          }, T)
          .toBe(nextTargeted);

        // The rest of the policy must remain untouched in the backend.
        const reread = await fetchPolicy(page, provider, datasetKey);
        expect(reread.body?.data).toMatchObject({
          enabled: original.enabled,
          source_kind: original.source_kind,
          max_concurrent: original.max_concurrent,
        });
      });

      await test.step("freshness 목록 UI(policy 배지)와 편집기가 변경값을 보여준다", async () => {
        // mutation onSuccess invalidates ops-providers → list refetches → the
        // row's policy column Badge (refresh_policy.targeted_policy) re-renders.
        await expect
          .poll(async () => {
            const row = providerRow(page, provider, datasetKey);
            return (await row.textContent()) ?? "";
          }, T)
          .toContain(nextTargeted);

        // Editor key (provider/dataset) is unchanged → no remount → the select
        // keeps the saved value, and the success Badge confirms the 200.
        await expect(page.getByLabel("targeted policy")).toHaveValue(
          nextTargeted,
          T,
        );
        await expect(page.getByText(/^saved /)).toBeVisible(T);
      });
    } finally {
      // Self-restore: PUT the captured original back and confirm via API GET,
      // even if an assertion above failed mid-flow.
      await browserFetch<ProviderRefreshPolicyResponse>(
        page,
        proxiedPolicyPath(provider, datasetKey),
        { body: recordToUpsert(original), method: "PUT" },
      );
      await expect
        .poll(async () => {
          const response = await fetchPolicy(page, provider, datasetKey);
          return response.body?.data.targeted_policy ?? `http:${response.status}`;
        }, T)
        .toBe(original.targeted_policy);
    }
  });

  test("refresh policy enabled을 enable→disable→enable로 토글하면 각 단계가 백엔드와 편집기 UI에 반영되고 원복된다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_PROVIDER_POLICY_WRITE,
      "E2E_PROVIDER_POLICY_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 provider refresh policy write flow를 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    await page.goto("/ops/providers");
    await expectProvidersReady(page);

    const candidate = await findPolicyCandidate(page);
    test.skip(
      candidate === null,
      "기존 refresh policy를 가진 provider/dataset이 없어 enabled 토글을 건너뜀 " +
        `(run ${RUN_ID})`,
    );
    const { provider, datasetKey } = candidate as {
      provider: string;
      datasetKey: string;
    };

    const originalResponse = await fetchPolicy(page, provider, datasetKey);
    expect(originalResponse.status).toBe(200);
    const original = (originalResponse.body as ProviderRefreshPolicyResponse)
      .data;
    const targeted = currentTargeted(original.targeted_policy);

    try {
      await selectDatasetRow(page, provider, datasetKey);

      const transitions: { enabled: boolean; label: string }[] = [
        { enabled: true, label: "enable" },
        { enabled: false, label: "disable" },
        { enabled: true, label: "enable" },
      ];

      for (const transition of transitions) {
        await test.step(`enabled=${transition.enabled}(${transition.label})로 저장하고 API+UI를 확인한다`, async () => {
          await applyPolicyToEditor(
            page,
            { ...original, enabled: transition.enabled },
            targeted,
          );
          const checkbox = page.getByLabel("enabled", { exact: true });
          if (transition.enabled) {
            await expect(checkbox).toBeChecked(T);
          } else {
            await expect(checkbox).not.toBeChecked(T);
          }

          const putResponse = await saveAndAwaitPut(page, provider, datasetKey);
          expect(putResponse.status()).toBe(200);
          const putBody = await readPolicyResponse(putResponse);
          expect(putBody.data.enabled).toBe(transition.enabled);
          // Only enabled changes; the rest of the policy stays put.
          expect(putBody.data).toMatchObject({
            provider,
            dataset_key: datasetKey,
            targeted_policy: targeted,
            source_kind: original.source_kind,
            config_source: original.config_source,
            max_concurrent: original.max_concurrent,
          });

          // Backend read confirms the enabled flip landed.
          await expect
            .poll(async () => {
              const response = await fetchPolicy(page, provider, datasetKey);
              return response.body?.data.enabled ?? `http:${response.status}`;
            }, T)
            .toBe(transition.enabled);

          // UI reflect: success badge + the checkbox keeps the saved state
          // (editor key unchanged → no remount → draft retained).
          await expect(page.getByText(/^saved /)).toBeVisible(T);
          if (transition.enabled) {
            await expect(checkbox).toBeChecked(T);
          } else {
            await expect(checkbox).not.toBeChecked(T);
          }
        });
      }
    } finally {
      await restorePolicy(page, provider, datasetKey, original);
    }
  });

  test("refresh policy의 interval/cadence 값을 UI에서 바꾸면 PUT 본문과 백엔드 재조회에 반영되고 원복된다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_PROVIDER_POLICY_WRITE,
      "E2E_PROVIDER_POLICY_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 provider refresh policy write flow를 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    await page.goto("/ops/providers");
    await expectProvidersReady(page);

    const candidate = await findPolicyCandidate(page);
    test.skip(
      candidate === null,
      "기존 refresh policy를 가진 provider/dataset이 없어 cadence 변경을 건너뜀 " +
        `(run ${RUN_ID})`,
    );
    const { provider, datasetKey } = candidate as {
      provider: string;
      datasetKey: string;
    };

    const originalResponse = await fetchPolicy(page, provider, datasetKey);
    expect(originalResponse.status).toBe(200);
    const original = (originalResponse.body as ProviderRefreshPolicyResponse)
      .data;
    const targeted = currentTargeted(original.targeted_policy);

    // Rate limits cleared → server interval-floor = min_interval_seconds(600);
    // system/optimal stay above it so the upsert validator accepts the body.
    const cadence = {
      system_interval_seconds: 3600,
      optimal_interval_seconds: 1800,
      min_interval_seconds: 600,
      max_requests_per_minute: null,
      max_requests_per_hour: null,
      max_requests_per_day: null,
      burst_size: 5,
    } as const;

    try {
      await selectDatasetRow(page, provider, datasetKey);

      await test.step("interval/cadence 폼을 채우고 저장하면 PUT 본문에 반영된다", async () => {
        await applyPolicyToEditor(page, { ...original, ...cadence }, targeted);
        const putResponse = await saveAndAwaitPut(page, provider, datasetKey);
        expect(putResponse.status()).toBe(200);
        const putBody = await readPolicyResponse(putResponse);
        expect(putBody.data).toMatchObject({
          provider,
          dataset_key: datasetKey,
          targeted_policy: targeted,
          system_interval_seconds: 3600,
          optimal_interval_seconds: 1800,
          min_interval_seconds: 600,
          burst_size: 5,
        });
        expect(putBody.data.max_requests_per_minute ?? null).toBeNull();
        expect(putBody.data.max_requests_per_hour ?? null).toBeNull();
        expect(putBody.data.max_requests_per_day ?? null).toBeNull();
      });

      await test.step("API 재조회가 변경된 cadence를 반영한다", async () => {
        await expect
          .poll(async () => {
            const response = await fetchPolicy(page, provider, datasetKey);
            return (
              response.body?.data.system_interval_seconds ??
              `http:${response.status}`
            );
          }, T)
          .toBe(3600);

        const reread = await fetchPolicy(page, provider, datasetKey);
        expect(reread.body?.data).toMatchObject({
          optimal_interval_seconds: 1800,
          min_interval_seconds: 600,
          burst_size: 5,
          enabled: original.enabled,
          max_concurrent: original.max_concurrent,
        });
      });

      await test.step("편집기 UI가 저장된 cadence 값과 saved 배지를 유지한다", async () => {
        await expect(page.getByText(/^saved /)).toBeVisible(T);
        await expect(page.getByLabel("system interval sec")).toHaveValue(
          "3600",
          T,
        );
        await expect(page.getByLabel("optimal interval sec")).toHaveValue(
          "1800",
          T,
        );
        await expect(page.getByLabel("min interval sec")).toHaveValue("600", T);
        await expect(page.getByLabel("burst size")).toHaveValue("5", T);
      });
    } finally {
      await restorePolicy(page, provider, datasetKey, original);
    }
  });

  test("잘못된 refresh policy는 client JSON 검증과 서버 422로 차단되고 백엔드 값은 그대로다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_PROVIDER_POLICY_WRITE,
      "E2E_PROVIDER_POLICY_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 provider refresh policy write flow를 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    await page.goto("/ops/providers");
    await expectProvidersReady(page);

    const candidate = await findPolicyCandidate(page);
    test.skip(
      candidate === null,
      "기존 refresh policy를 가진 provider/dataset이 없어 invalid policy 검증을 건너뜀 " +
        `(run ${RUN_ID})`,
    );
    const { provider, datasetKey } = candidate as {
      provider: string;
      datasetKey: string;
    };

    const originalResponse = await fetchPolicy(page, provider, datasetKey);
    expect(originalResponse.status).toBe(200);
    const original = (originalResponse.body as ProviderRefreshPolicyResponse)
      .data;
    const targeted = currentTargeted(original.targeted_policy);

    try {
      await selectDatasetRow(page, provider, datasetKey);

      await test.step("rate_limit_source에 잘못된 JSON을 넣으면 PUT 없이 client 오류가 뜬다", async () => {
        let putCount = 0;
        const onRequest = (request: Request) => {
          if (request.method() !== "PUT") {
            return;
          }
          if (
            new URL(request.url()).pathname.startsWith(
              "/api/proxy/v1/admin/provider-refresh-policies/",
            )
          ) {
            putCount += 1;
          }
        };
        page.on("request", onRequest);
        try {
          await page.getByLabel("rate limit source").fill("{ not-valid-json ");
          await page.getByRole("button", { name: "저장" }).click();
          await expect(page.getByText("policy 저장 실패")).toBeVisible(T);
          await expect(page.getByText(/^saved /)).toHaveCount(0);
          // No network PUT was ever issued — blocked client-side.
          expect(putCount).toBe(0);
        } finally {
          page.off("request", onRequest);
        }
      });

      await test.step("rate-limit floor보다 낮은 interval은 서버가 422로 거부하고 값은 안 바뀐다", async () => {
        // max_requests_per_minute=2 → effective floor=30s; system_interval=10 < 30
        // → upsert validator rejects with 422 (client validation passes first).
        await applyPolicyToEditor(
          page,
          {
            ...original,
            system_interval_seconds: 10,
            optimal_interval_seconds: null,
            min_interval_seconds: null,
            max_requests_per_minute: 2,
            max_requests_per_hour: null,
            max_requests_per_day: null,
          },
          targeted,
        );
        const putResponse = await saveAndAwaitPut(page, provider, datasetKey);
        expect(putResponse.status()).toBe(422);
        await expect(page.getByText("policy 저장 실패")).toBeVisible(T);

        // Backend stayed on the captured original (rejected upsert = no commit).
        const reread = await fetchPolicy(page, provider, datasetKey);
        expect(reread.status).toBe(200);
        expect(reread.body?.data.system_interval_seconds ?? null).toBe(
          original.system_interval_seconds ?? null,
        );
        expect(reread.body?.data.targeted_policy).toBe(original.targeted_policy);
      });
    } finally {
      await restorePolicy(page, provider, datasetKey, original);
    }
  });

  test("여러 provider/dataset의 targeted_policy를 바꾸면 전체 reload 후에도 목록 UI에 유지되고 모두 원복된다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_PROVIDER_POLICY_WRITE,
      "E2E_PROVIDER_POLICY_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 provider refresh policy write flow를 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    await page.goto("/ops/providers");
    await expectProvidersReady(page);

    const candidates = await findPolicyCandidates(page, 3);
    test.skip(
      candidates.length === 0,
      "기존 refresh policy를 가진 provider/dataset이 없어 multi-dataset 영속성 검증을 건너뜀 " +
        `(run ${RUN_ID})`,
    );

    const restorePlan: {
      provider: string;
      datasetKey: string;
      original: ProviderRefreshPolicyRecord;
      next: TargetedPolicy;
    }[] = [];

    try {
      for (const { provider, datasetKey } of candidates) {
        const originalResponse = await fetchPolicy(page, provider, datasetKey);
        expect(originalResponse.status).toBe(200);
        const original = (originalResponse.body as ProviderRefreshPolicyResponse)
          .data;
        const next = pickNextTargeted(original.targeted_policy);
        restorePlan.push({ provider, datasetKey, original, next });

        await test.step(`${provider}/${datasetKey} targeted_policy를 ${next}로 바꿔 저장한다`, async () => {
          await selectDatasetRow(page, provider, datasetKey);
          await applyPolicyToEditor(page, original, next);
          const putResponse = await saveAndAwaitPut(page, provider, datasetKey);
          expect(putResponse.status()).toBe(200);
          const putBody = await readPolicyResponse(putResponse);
          expect(putBody.data.targeted_policy).toBe(next);

          await expect
            .poll(async () => {
              const response = await fetchPolicy(page, provider, datasetKey);
              return (
                response.body?.data.targeted_policy ?? `http:${response.status}`
              );
            }, T)
            .toBe(next);
        });
      }

      await test.step("전체 페이지 reload 후에도 모든 변경된 targeted_policy가 목록 배지에 유지된다", async () => {
        await page.reload();
        await expectProvidersReady(page);
        for (const { provider, datasetKey, next } of restorePlan) {
          await expect
            .poll(async () => {
              const row = providerRow(page, provider, datasetKey);
              return (await row.textContent()) ?? "";
            }, T)
            .toContain(next);
        }
      });
    } finally {
      for (const { provider, datasetKey, original } of restorePlan) {
        await restorePolicy(page, provider, datasetKey, original);
      }
    }
  });
});
