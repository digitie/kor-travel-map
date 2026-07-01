import { expect, test, type Locator, type Page, type Response } from "@playwright/test";

import type { components } from "../../src/api/types";
import { CURATED_IDS } from "./_fixtures";

type CuratedFeatureView = components["schemas"]["CuratedFeatureView"];
type CuratedFeatureResponse = components["schemas"]["CuratedFeatureResponse"];
type CuratedFeaturePatchRequest =
  components["schemas"]["CuratedFeaturePatchRequest"];

type BrowserFetchResult<T> = {
  body: T | null;
  status: number;
  text: string;
};

const UI_TIMEOUT = 15_000;
const FLOW_TIMEOUT = 5 * 60 * 1000;
const T = { timeout: UI_TIMEOUT } as const;

const RUN_ID = `live-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
const MARKER = `[e2e ${RUN_ID}]`;

// reuse_policy enum mirrors CuratedFeaturePatchRequest.reuse_policy (curated.py
// `ReusePolicy = Literal["allowed", "blocked", "manual_review"]`).
const REUSE_POLICIES = ["allowed", "blocked", "manual_review"] as const;
type ReusePolicy = (typeof REUSE_POLICIES)[number];

const LIST_ROUTE = "/admin/features/curated";

const EXECUTE_CURATED_WRITE =
  process.env.E2E_ADMIN_WRITE === "1" || process.env.E2E_CURATED_WRITE === "1";

test.describe.configure({ mode: "serial" });

// --- API-path helpers (verbatim from admin-features-change-requests-write) ---

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

// --- curated-feature specific helpers ---

function curatedPath(curatedFeatureId: string): string {
  return `/v1/admin/features/curated/${encodeURIComponent(curatedFeatureId)}`;
}

function detailRoute(curatedFeatureId: string): string {
  return `/admin/features/curated/${encodeURIComponent(curatedFeatureId)}`;
}

async function fetchCuratedFeature(
  page: Page,
  curatedFeatureId: string,
): Promise<BrowserFetchResult<CuratedFeatureResponse>> {
  return browserFetch<CuratedFeatureResponse>(page, curatedPath(curatedFeatureId));
}

async function patchCuratedFeature(
  page: Page,
  curatedFeatureId: string,
  body: CuratedFeaturePatchRequest,
): Promise<BrowserFetchResult<CuratedFeatureResponse>> {
  return browserFetch<CuratedFeatureResponse>(page, curatedPath(curatedFeatureId), {
    body,
    method: "PATCH",
  });
}

async function readCuratedResponse(
  response: Response,
): Promise<CuratedFeatureView> {
  expect(response.status()).toBe(200);
  const json = (await response.json()) as CuratedFeatureResponse;
  return json.data;
}

/**
 * Pick the first CURATED_ID that GET admin returns 200 for. Prefer a
 * non-archived row (the list status filter + editor flow are simplest for
 * candidate/curated/rejected), but fall back to an archived one if that is all
 * the snapshot offers. Returns null when none of the probed ids resolve.
 */
async function pickCuratedTarget(
  page: Page,
): Promise<CuratedFeatureView | null> {
  let archivedFallback: CuratedFeatureView | null = null;
  for (const id of CURATED_IDS.slice(0, 12)) {
    const res = await fetchCuratedFeature(page, id);
    if (res.status === 200 && res.body?.data) {
      const view = res.body.data;
      if (view.curation_status !== "archived") {
        return view;
      }
      archivedFallback ??= view;
    }
  }
  return archivedFallback;
}

async function expectListConsoleLoaded(page: Page): Promise<void> {
  await expect(
    page.getByRole("heading", { level: 1, name: "Curated features" }),
  ).toBeVisible(T);
  await expect(page.getByLabel("curated feature search")).toBeVisible(T);
}

/**
 * Probe CURATED_IDS and return up to `count` rows the admin GET resolves (200).
 * Prefer non-archived rows (their list status partition is selectable in the
 * filter); fall back to archived ones only to reach `count`. Multi-row variant
 * of pickCuratedTarget so loops aren't single-row (issue #574 vanity guard).
 */
async function collectCuratedTargets(
  page: Page,
  count: number,
): Promise<CuratedFeatureView[]> {
  const targets: CuratedFeatureView[] = [];
  const archivedFallback: CuratedFeatureView[] = [];
  for (const id of CURATED_IDS.slice(0, 20)) {
    if (targets.length >= count) break;
    const res = await fetchCuratedFeature(page, id);
    if (res.status === 200 && res.body?.data) {
      const view = res.body.data;
      if (view.curation_status === "archived") {
        archivedFallback.push(view);
      } else {
        targets.push(view);
      }
    }
  }
  while (targets.length < count && archivedFallback.length > 0) {
    targets.push(archivedFallback.shift() as CuratedFeatureView);
  }
  return targets;
}

/**
 * Navigate the list console and narrow it to exactly the row for `curatedId`.
 * Relies on the just-mutated row having the freshest updated_at so it sorts to
 * the top of its status partition (ORDER BY cf.updated_at DESC) and lands inside
 * the widened page; the client text filter (which matches curated_feature_id —
 * curated-features-client.tsx line 986 `item.curated_feature_id`) then isolates
 * it. Verified selectors: `aria-label="curation status filter"` (line 1453),
 * `aria-label="page size"` (line 1469), `archived 포함` checkbox label (line 1493),
 * `aria-label="curated feature search"` (line 1371), `rowTestId(() =>
 * "curated-feature-row")` (line 1589).
 */
async function gotoListSingleRow(
  page: Page,
  status: string,
  curatedId: string,
): Promise<Locator> {
  await page.goto(LIST_ROUTE);
  await expectListConsoleLoaded(page);
  await page.getByLabel("curation status filter").selectOption(status);
  await page.getByLabel("page size").selectOption("200");
  if (status === "archived") {
    await page.getByLabel("archived 포함").check();
  }
  await page.getByLabel("curated feature search").fill(curatedId);
  const row = page.getByTestId("curated-feature-row");
  await expect(row).toHaveCount(1, T);
  return row;
}

test.describe("/admin/features/curated edit round-trip (self-restoring)", () => {
  test("기존 curated 후보의 display_title/reuse_policy를 편집하면 백엔드와 상세/목록 UI에 반영되고 원복된다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_CURATED_WRITE,
      "E2E_CURATED_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 curated edit round-trip을 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    // browserFetch needs the admin origin + session cookie, so land on the list
    // first; this also exercises the read surface before mutating.
    await page.goto(LIST_ROUTE);
    await expectListConsoleLoaded(page);

    const target = await pickCuratedTarget(page);
    test.skip(
      target === null,
      "CURATED_IDS 중 조회 가능한 curated feature가 없어 edit round-trip을 건너뜀",
    );
    if (target === null) return;

    const curatedId = target.curated_feature_id;
    const originalDisplayTitle = target.display_title ?? null;
    const originalReusePolicy = target.reuse_policy as ReusePolicy;
    const originalStatus = target.curation_status;
    // The 저장 button re-sends the full editor payload (display_summary /
    // rank_score / curation_relation seeded from the server, plus the edited
    // display_title / reuse_policy). display_summary is `.trim()`-ed on save, so
    // capture every field the save mutates to guarantee the finally fully reverts
    // the row (only the server-managed content_version is left bumped).
    const originalDisplaySummary = target.display_summary ?? null;
    const originalRankScore = target.rank_score;
    const originalCurationRelation =
      target.curation_relation as CuratedFeaturePatchRequest["curation_relation"];

    const baseTitle = (
      originalDisplayTitle ??
      target.feature_name ??
      "curated"
    ).trim();
    const newTitle = `${baseTitle} ${MARKER}`;
    const newPolicy: ReusePolicy =
      REUSE_POLICIES.find((policy) => policy !== originalReusePolicy) ??
      "manual_review";

    try {
      await test.step("curated feature 상세 화면을 열고 editor가 현재 값으로 시드되어 있음을 확인한다", async () => {
        await page.goto(detailRoute(curatedId));
        await expect(
          page.getByRole("heading", { level: 1, name: "Curated feature detail" }),
        ).toBeVisible(T);
        // FeatureEditor header renders the full curated_feature_id, confirming we
        // opened the right row: `<div ...>{feature.curated_feature_id}</div>`.
        await expect(page.getByText(curatedId, { exact: true }).first()).toBeVisible(
          T,
        );
        // Editor inputs are seeded from the server feature (label-wrapped controls).
        await expect(page.getByLabel("display title", { exact: true })).toHaveValue(
          originalDisplayTitle ?? "",
          T,
        );
        await expect(page.getByLabel("reuse policy", { exact: true })).toHaveValue(
          originalReusePolicy,
          T,
        );
      });

      await test.step("editor에서 display_title을 수정하고 reuse_policy를 토글한 뒤 저장하면 PATCH가 반영된다", async () => {
        await page.getByLabel("display title", { exact: true }).fill(newTitle);
        await page
          .getByLabel("reuse policy", { exact: true })
          .selectOption(newPolicy);

        const responsePromise = waitForApiResponse(
          page,
          "PATCH",
          curatedPath(curatedId),
        );
        await page.getByRole("button", { name: "저장" }).click();
        const patched = await readCuratedResponse(await responsePromise);

        expect(patched.curated_feature_id).toBe(curatedId);
        expect(patched.display_title).toBe(newTitle);
        expect(patched.reuse_policy).toBe(newPolicy);
      });

      await test.step("admin API GET로 새 display_title/reuse_policy가 영속화되었는지 확인한다", async () => {
        await expect
          .poll(async () => {
            const res = await fetchCuratedFeature(page, curatedId);
            return res.body?.data.display_title ?? `http:${res.status}`;
          }, T)
          .toBe(newTitle);

        const current = await fetchCuratedFeature(page, curatedId);
        expect(current.status).toBe(200);
        expect(current.body?.data.reuse_policy).toBe(newPolicy);
      });

      await test.step("상세 화면 제목이 refetch된 서버 display_title로 다시 렌더된다", async () => {
        // The h2 title (`{item.display_title ?? item.feature_name}`) is driven by
        // the refetched server feature, not editor input state, so this proves
        // the backend change re-rendered the UI.
        await expect(
          page.getByRole("heading", { level: 2, name: newTitle }),
        ).toBeVisible(T);
      });

      await test.step("목록 화면에서 해당 후보 행이 새 display_title/reuse_policy를 보여준다", async () => {
        await page.goto(LIST_ROUTE);
        await expectListConsoleLoaded(page);

        // The just-edited row has the freshest updated_at, so with the matching
        // status filter it sorts to the top of page 1 (ORDER BY cf.updated_at
        // DESC). Match the status partition and widen the page for margin.
        await page
          .getByLabel("curation status filter")
          .selectOption(originalStatus);
        await page.getByLabel("page size").selectOption("200");
        if (originalStatus === "archived") {
          await page.getByLabel("archived 포함").check();
        }
        await page.getByLabel("curated feature search").fill(RUN_ID);

        const row = page
          .getByTestId("curated-feature-row")
          .filter({ hasText: RUN_ID });
        await expect(row).toHaveCount(1, T);
        await expect(row).toContainText(MARKER);
        await expect(row).toContainText(newPolicy);
      });
    } finally {
      // Restore the captured originals (display_title + reuse_policy) regardless
      // of assertion outcome — idempotent even if nothing was edited — then
      // poll-confirm the revert landed.
      await patchCuratedFeature(page, curatedId, {
        display_title: originalDisplayTitle,
        display_summary: originalDisplaySummary,
        rank_score: originalRankScore,
        reuse_policy: originalReusePolicy,
        curation_relation: originalCurationRelation,
      });
      await expect
        .poll(async () => {
          const res = await fetchCuratedFeature(page, curatedId);
          return {
            display_title: res.body?.data.display_title ?? null,
            reuse_policy: res.body?.data.reuse_policy ?? null,
          };
        }, T)
        .toEqual({
          display_title: originalDisplayTitle,
          reuse_policy: originalReusePolicy,
        });
    }
  });

  test("기존 curated 후보의 rank_score를 editor에서 수정하면 백엔드와 상세 UI(rank/editor)에 반영되고 원복된다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_CURATED_WRITE,
      "E2E_CURATED_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 rank_score round-trip을 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    await page.goto(LIST_ROUTE);
    await expectListConsoleLoaded(page);

    const target = await pickCuratedTarget(page);
    test.skip(
      target === null,
      "CURATED_IDS 중 조회 가능한 curated feature가 없어 rank_score round-trip을 건너뜀",
    );
    if (target === null) return;

    const curatedId = target.curated_feature_id;
    // The 저장 button re-sends the full editor payload, so capture every field it
    // touches to guarantee a complete revert (content_version is server-managed
    // and intentionally left bumped).
    const originalRankScore = target.rank_score;
    const originalDisplayTitle = target.display_title ?? null;
    const originalDisplaySummary = target.display_summary ?? null;
    const originalReusePolicy = target.reuse_policy as ReusePolicy;
    const originalCurationRelation =
      target.curation_relation as CuratedFeaturePatchRequest["curation_relation"];
    // editor rank input is type=number seeded from `String(feature.rank_score)`
    // (curated-features-client.tsx line 453); a clean 2-decimal delta round-trips
    // exactly through JSON and re-seeds the remounted editor.
    const newRank = Number((originalRankScore + 1.25).toFixed(2));

    try {
      await test.step("상세 editor가 현재 rank_score로 시드되어 있음을 확인한다", async () => {
        await page.goto(detailRoute(curatedId));
        await expect(
          page.getByRole("heading", { level: 1, name: "Curated feature detail" }),
        ).toBeVisible(T);
        // FeatureEditor header renders the full curated_feature_id:
        // `<div ...>{feature.curated_feature_id}</div>` (line 513).
        await expect(page.getByText(curatedId, { exact: true }).first()).toBeVisible(
          T,
        );
        // `<label><span>rank score</span><Input type="number" .../></label>`
        // (lines 530-538) → label-addressable.
        await expect(page.getByLabel("rank score", { exact: true })).toHaveValue(
          String(originalRankScore),
          T,
        );
      });

      await test.step("rank score 입력을 바꾸고 저장하면 PATCH 응답 rank_score가 새 값이다", async () => {
        await page.getByLabel("rank score", { exact: true }).fill(String(newRank));

        const responsePromise = waitForApiResponse(
          page,
          "PATCH",
          curatedPath(curatedId),
        );
        await page.getByRole("button", { name: "저장" }).click();
        const patched = await readCuratedResponse(await responsePromise);

        expect(patched.curated_feature_id).toBe(curatedId);
        expect(patched.rank_score).toBe(newRank);
      });

      await test.step("admin API GET로 새 rank_score가 영속화되었는지 확인한다", async () => {
        await expect
          .poll(async () => {
            const res = await fetchCuratedFeature(page, curatedId);
            return res.body?.data.rank_score ?? `http:${res.status}`;
          }, T)
          .toBe(newRank);
      });

      await test.step("상세 화면 rank 요약과 editor 입력이 refetch된 새 rank_score로 다시 렌더된다", async () => {
        // detail header dl renders `<dt>rank</dt><dd>{item.rank_score.toFixed(2)}</dd>`
        // (curated-feature-detail-client.tsx lines 114-115); driven by the
        // refetched server feature, not editor state.
        await expect(page.locator('dt:has-text("rank") + dd').first()).toHaveText(
          newRank.toFixed(2),
          T,
        );
        // editor remounts on the new updated_at (key on detail line 137) and
        // re-seeds from the server value, proving persistence.
        await expect(page.getByLabel("rank score", { exact: true })).toHaveValue(
          String(newRank),
          T,
        );
      });
    } finally {
      await patchCuratedFeature(page, curatedId, {
        rank_score: originalRankScore,
        display_title: originalDisplayTitle,
        display_summary: originalDisplaySummary,
        reuse_policy: originalReusePolicy,
        curation_relation: originalCurationRelation,
      });
      await expect
        .poll(async () => {
          const res = await fetchCuratedFeature(page, curatedId);
          return res.body?.data.rank_score ?? null;
        }, T)
        .toBe(originalRankScore);
    }
  });

  test("reuse_policy를 allowed→blocked→manual_review로 전이하면 각 단계가 API와 목록 배지에 반영되고 원복된다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_CURATED_WRITE,
      "E2E_CURATED_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 reuse_policy 전이를 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    await page.goto(LIST_ROUTE);
    await expectListConsoleLoaded(page);

    const target = await pickCuratedTarget(page);
    test.skip(
      target === null,
      "CURATED_IDS 중 조회 가능한 curated feature가 없어 reuse_policy 전이를 건너뜀",
    );
    if (target === null) return;

    const curatedId = target.curated_feature_id;
    const originalReusePolicy = target.reuse_policy as ReusePolicy;
    const originalStatus = target.curation_status;
    // explicit allowed→blocked→manual_review chain (distinct from the seeded
    // value so every step is a real mutation that bumps updated_at).
    const transitions: ReusePolicy[] = ["allowed", "blocked", "manual_review"];

    try {
      for (const policy of transitions) {
        await test.step(`reuse_policy를 ${policy}로 PATCH하면 응답과 API GET이 ${policy}가 된다`, async () => {
          const res = await patchCuratedFeature(page, curatedId, {
            reuse_policy: policy,
          });
          expect(res.status).toBe(200);
          expect(res.body?.data.reuse_policy).toBe(policy);

          await expect
            .poll(async () => {
              const current = await fetchCuratedFeature(page, curatedId);
              return current.body?.data.reuse_policy ?? `http:${current.status}`;
            }, T)
            .toBe(policy);
        });

        await test.step(`목록 행 reuse 배지가 ${policy}로 갱신된다`, async () => {
          // reuse column renders `<Badge>{feature.reuse_policy}</Badge>` (line
          // 1145); the just-patched row is freshest so it tops its partition.
          const row = await gotoListSingleRow(page, originalStatus, curatedId);
          await expect(row).toContainText(policy);
        });
      }
    } finally {
      await patchCuratedFeature(page, curatedId, {
        reuse_policy: originalReusePolicy,
      });
      await expect
        .poll(async () => {
          const res = await fetchCuratedFeature(page, curatedId);
          return res.body?.data.reuse_policy ?? null;
        }, T)
        .toBe(originalReusePolicy);
    }
  });

  test("여러 curated 후보에 연속 PATCH를 가하면 content_version이 매번 단조 증가하고 목록 패널/순위에 반영된 뒤 원복된다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_CURATED_WRITE,
      "E2E_CURATED_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 content_version round-trip을 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    await page.goto(LIST_ROUTE);
    await expectListConsoleLoaded(page);

    const targets = await collectCuratedTargets(page, 3);
    test.skip(
      targets.length === 0,
      "CURATED_IDS 중 조회 가능한 curated feature가 없어 content_version round-trip을 건너뜀",
    );
    if (targets.length === 0) return;

    try {
      for (const original of targets) {
        const curatedId = original.curated_feature_id;
        const base = original.rank_score;
        const finalRank = Number((base + 3).toFixed(2));
        let previousVersion = original.content_version;
        let finalVersion = original.content_version;

        await test.step(`${curatedId}에 3회 PATCH하면 content_version이 매번 증가한다`, async () => {
          // update_curated_feature bumps content_version by exactly 1 per
          // non-empty update (curated_repo.py line 1436), so each distinct
          // rank_score PATCH must produce a strictly greater version.
          for (let step = 1; step <= 3; step += 1) {
            const nextRank = Number((base + step).toFixed(2));
            const res = await patchCuratedFeature(page, curatedId, {
              rank_score: nextRank,
            });
            expect(res.status).toBe(200);
            expect(res.body?.data.rank_score).toBe(nextRank);
            const version = res.body?.data.content_version ?? -1;
            expect(version).toBeGreaterThan(previousVersion);
            previousVersion = version;
            finalVersion = version;
          }
        });

        await test.step(`${curatedId} API GET이 마지막 PATCH의 content_version/rank_score와 일치한다`, async () => {
          const current = await fetchCuratedFeature(page, curatedId);
          expect(current.status).toBe(200);
          expect(current.body?.data.content_version).toBe(finalVersion);
          expect(current.body?.data.rank_score).toBe(finalRank);
        });

        await test.step(`${curatedId} 목록 선택 패널이 새 content_version/rank를 보여준다`, async () => {
          await gotoListSingleRow(page, original.curation_status, curatedId);
          // single filtered row auto-selects (selectedFeature = filteredItems[0]);
          // panel renders the full id (line 1608) and the dl `<dt>content version</dt>
          // <dd>{content_version}</dd>` / `<dt>rank</dt><dd>{rank_score.toFixed(2)}</dd>`
          // (lines 1644-1647).
          await expect(
            page.getByText(curatedId, { exact: true }).first(),
          ).toBeVisible(T);
          await expect(
            page.locator('dt:has-text("content version") + dd'),
          ).toHaveText(String(finalVersion), T);
          await expect(page.locator('dt:has-text("rank") + dd')).toHaveText(
            finalRank.toFixed(2),
            T,
          );
        });
      }
    } finally {
      for (const original of targets) {
        await patchCuratedFeature(page, original.curated_feature_id, {
          rank_score: original.rank_score,
          display_title: original.display_title ?? null,
          display_summary: original.display_summary ?? null,
          reuse_policy: original.reuse_policy as ReusePolicy,
          curation_relation:
            original.curation_relation as CuratedFeaturePatchRequest["curation_relation"],
        });
      }
    }
  });

  test("잘못된 reuse_policy PATCH는 422로 거부되고 빈 본문 PATCH는 200 no-op이라 값/콘텐츠버전이 그대로다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_CURATED_WRITE,
      "E2E_CURATED_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 PATCH 에러 경로를 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    await page.goto(LIST_ROUTE);
    await expectListConsoleLoaded(page);

    const target = await pickCuratedTarget(page);
    test.skip(
      target === null,
      "CURATED_IDS 중 조회 가능한 curated feature가 없어 PATCH 에러 경로를 건너뜀",
    );
    if (target === null) return;

    const curatedId = target.curated_feature_id;
    const before = await fetchCuratedFeature(page, curatedId);
    expect(before.status).toBe(200);
    const originalReusePolicy = before.body?.data.reuse_policy as ReusePolicy;
    const originalRankScore = before.body?.data.rank_score as number;
    const originalContentVersion = before.body?.data.content_version as number;

    await test.step("허용되지 않은 reuse_policy 값은 422를 반환하고 아무것도 바꾸지 않는다", async () => {
      // CuratedFeaturePatchRequest.reuse_policy is Literal-typed (curated.py line
      // 463) + model_config extra="forbid"; a bogus enum is rejected at request
      // validation. browserFetch body is `unknown`, so the off-schema value is
      // deliberate, not a type hole.
      const invalid = await browserFetch<unknown>(page, curatedPath(curatedId), {
        method: "PATCH",
        body: { reuse_policy: "definitely-not-a-policy" },
      });
      expect(invalid.status).toBe(422);

      const after = await fetchCuratedFeature(page, curatedId);
      expect(after.status).toBe(200);
      expect(after.body?.data.reuse_policy).toBe(originalReusePolicy);
      expect(after.body?.data.content_version).toBe(originalContentVersion);
    });

    await test.step("빈 본문 PATCH는 200이지만 content_version/필드를 그대로 둔다", async () => {
      // model_dump(exclude_unset=True) yields {} → update_curated_feature returns
      // the row WITHOUT an UPDATE (curated_repo.py lines 1430-1435), so no
      // content_version bump.
      const noop = await patchCuratedFeature(page, curatedId, {});
      expect(noop.status).toBe(200);
      expect(noop.body?.data.reuse_policy).toBe(originalReusePolicy);
      expect(noop.body?.data.rank_score).toBe(originalRankScore);
      expect(noop.body?.data.content_version).toBe(originalContentVersion);
    });

    await test.step("상세 editor가 여전히 원래 reuse_policy/rank_score로 시드된다", async () => {
      // detail GET-by-id is pagination-free, so reflection is robust even though
      // the no-op left updated_at unchanged (row may sit deep in its partition).
      await page.goto(detailRoute(curatedId));
      await expect(
        page.getByRole("heading", { level: 1, name: "Curated feature detail" }),
      ).toBeVisible(T);
      await expect(page.getByLabel("reuse policy", { exact: true })).toHaveValue(
        originalReusePolicy,
        T,
      );
      await expect(page.getByLabel("rank score", { exact: true })).toHaveValue(
        String(originalRankScore),
        T,
      );
    });
  });
});
