import { expect, test, type Locator, type Page, type Response } from "@playwright/test";

import type { components } from "../../src/api/types";

// LIVE (non-mock) e2e for the /admin/dagster ops surface (runs + assets read,
// schedule controls, and opt-in real write commands).
//
// PART A (NOT gated): read round-trip for the Dagster ops summary. The page auto-
//   fetches GET /v1/ops/dagster/summary on mount and (when status==='ok') auto-POSTs
//   /v1/ops/dagster/nux-seen once. We assert the summary GET body, that its counts/
//   repositories reflect into the SummaryCards + Code locations card (assets list),
//   that the refresh button re-issues the GET, and — when recent_runs is non-empty —
//   that selecting a run drives GET /v1/ops/dagster/runs/{run_id} and the Run detail
//   card reflects it. The env may have Dagster up OR down, so every run/asset-
//   dependent assertion is branched on data.status / list length (no flake when the
//   Dagster webserver is unreachable -> status='unavailable', empty lists).
//
// PART B (GATED, DEFAULT-SKIP): change a real Dagster schedule override, restore its
// default, start/stop it, and trigger its "run now" command through the admin UI/API.
// The test records the original running state and restores cron/status in finally.
//
// PART C (GATED + HEAVY, DEFAULT-SKIP): trigger a REAL Dagster run/materialization of
//   an operator-nominated SAFE job/asset-job, then assert the new run shows up in the
//   admin summary (API) and the Recent runs table + Run detail (UI).
//
//   *** HEAVINESS / WHY EXTRA GATING ***
//   This launches an ACTUAL Dagster job: it consumes compute, may hit upstream public
//   APIs, write to Postgres/PostGIS/object storage, and cannot be cleanly undone (we
//   best-effort `terminateRun` in finally, but already-applied side effects persist).
//   It is therefore default-skip and needs BOTH the EXTRA flag E2E_DAGSTER_RUN=1 AND a
//   write gate (E2E_ADMIN_WRITE=1 or E2E_DAGSTER_WRITE=1), PLUS E2E_DAGSTER_JOB naming
//   the safe target. Only enable against a disposable/local stack with a known
//   config-free, side-effect-light job/asset-job.
//
//   PART C still launches via Dagster GraphQL directly. It intentionally remains
//   separate from the schedule "run now" UI/API command because it targets arbitrary
//   operator-selected jobs and may have larger side effects.

type DagsterSummaryResponse = components["schemas"]["DagsterSummaryResponse"];
type DagsterRunDetailResponse =
  components["schemas"]["DagsterRunDetailResponse"];
type DagsterNuxSeenResponse = components["schemas"]["DagsterNuxSeenResponse"];
type DagsterRunSummary = components["schemas"]["DagsterRunSummary"];
type DagsterSchedule = components["schemas"]["DagsterSchedule"];
type DagsterScheduleCommandResponse =
  components["schemas"]["DagsterScheduleCommandResponse"];

type BrowserFetchResult<T> = {
  body: T | null;
  status: number;
  text: string;
};

const UI_TIMEOUT = 15_000;
const FLOW_TIMEOUT = 5 * 60 * 1000;
const T = { timeout: UI_TIMEOUT } as const;

const SUMMARY_PATH = "/v1/ops/dagster/summary";
const NUX_SEEN_PATH = "/v1/ops/dagster/nux-seen";

// 상단 상태 배지는 dagster-client.tsx에서 statusLabel(data.status)로 한글화된다
// (status-badge.tsx). summary data.status enum("ok"|"unavailable"|"error")의 한글 매핑.
// 주의: 이는 UI 렌더 텍스트 단언에만 쓴다 — API/DTO enum은 여전히 영어다.
const SUMMARY_STATUS_LABEL: Record<string, string> = {
  ok: "정상",
  unavailable: "사용불가",
  error: "오류",
};

// PART B gating: heavy + hard-to-undo, default-skip. Requires the EXTRA flag
// E2E_DAGSTER_RUN=1 AND a write gate (E2E_ADMIN_WRITE=1 or E2E_DAGSTER_WRITE=1).
const EXECUTE_DAGSTER_WRITE =
  process.env.E2E_ADMIN_WRITE === "1" || process.env.E2E_DAGSTER_WRITE === "1";
const EXECUTE_DAGSTER_RUN =
  process.env.E2E_DAGSTER_RUN === "1" && EXECUTE_DAGSTER_WRITE;
const DAGSTER_SCHEDULE_NAME = process.env.E2E_DAGSTER_SCHEDULE ?? "";

// Dagster GraphQL endpoint for the PART B launch. Mirrors the project's existing
// E2E_DAGSTER_URL / NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL conventions; default local.
const DAGSTER_BASE_URL = (
  process.env.E2E_DAGSTER_URL ??
  process.env.NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL ??
  "http://127.0.0.1:12702"
).replace(/\/+$/, "");
const DAGSTER_GRAPHQL_URL =
  process.env.E2E_DAGSTER_GRAPHQL_URL ?? `${DAGSTER_BASE_URL}/graphql`;

// Acceptable statuses immediately after a launch. Normally QUEUED/NOT_STARTED, but a
// tiny asset-job can already be running/done by the time we re-read, so we accept the
// non-failure launch/terminal-success window.
const LAUNCHED_STATUSES = new Set([
  "QUEUED",
  "NOT_STARTED",
  "STARTING",
  "STARTED",
  "MANAGED",
  "SUCCESS",
]);

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

function isRunDetailResponse(response: Response): boolean {
  return (
    response.request().method() === "GET" &&
    apiPath(response).startsWith("/v1/ops/dagster/runs/")
  );
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

// shortRunId mirror of dagster-client.tsx: `runId.length > 12 ? runId.slice(0,12)+'...' : runId`.
function shortRunId(runId: string): string {
  return runId.length > 12 ? `${runId.slice(0, 12)}...` : runId;
}

function runDetailPath(runId: string): string {
  return `/v1/ops/dagster/runs/${runId}`;
}

function schedulePath(scheduleName: string, command?: string): string {
  const base = `/v1/ops/dagster/schedules/${encodeURIComponent(scheduleName)}`;
  return command ? `${base}/${command}` : base;
}

function allSchedules(summary: DagsterSummaryResponse): DagsterSchedule[] {
  return summary.data.repositories.flatMap((repository) => repository.schedules);
}

function scheduleRow(page: Page, scheduleName: string): Locator {
  return page.getByTestId(`dagster-schedule-row-${scheduleName}`);
}

async function clickScheduleButton(
  page: Page,
  scheduleName: string,
  buttonName: string,
): Promise<void> {
  await scheduleRow(page, scheduleName)
    .getByRole("button", { name: buttonName, exact: true })
    .click();
}

// dagster-client.tsx renders every section as a shadcn Card (`div[data-slot="card"]`)
// with a CardTitle that resolves to role=heading (proven by the passing mock specs).
function card(page: Page, headingName: string): Locator {
  return page
    .locator('div[data-slot="card"]')
    .filter({ has: page.getByRole("heading", { name: headingName }) });
}

async function expectDagsterShell(page: Page): Promise<void> {
  await expect(
    page.getByRole("heading", { level: 1, name: "작업 자동화" }),
  ).toBeVisible(T);
  await expect(page.getByRole("button", { name: "새로고침" })).toBeVisible(T);
  await expect(page.getByRole("heading", { name: "스케줄" })).toBeVisible(T);
  await expect(page.getByRole("heading", { name: "최근 실행" })).toBeVisible(T);
  await expect(page.getByRole("heading", { name: "실행 상세" })).toBeVisible(T);
  await expect(page.getByRole("heading", { name: "상세 엔진 화면" })).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "코드 위치" }).first(),
  ).toBeVisible(T);
  await expect(page.getByTestId("dagster-embed")).toHaveCount(0);
}

// fallbackRun mirror of DagsterAdminClient: first FAILURE run, else recent_runs[0].
function fallbackRun(runs: DagsterRunSummary[]): DagsterRunSummary | undefined {
  return runs.find((run) => run.status === "FAILURE") ?? runs[0];
}

interface DagsterLaunchOutcome {
  typename: string;
  runId: string;
  status: string;
  message: string;
}

interface DagsterLaunchGraphqlResponse {
  data?: {
    launchPipelineExecution?: {
      __typename?: string;
      run?: { runId?: string; status?: string } | null;
      message?: string | null;
      errors?: Array<{ message?: string }> | null;
    } | null;
  } | null;
  errors?: Array<{ message?: string }> | null;
}

async function launchDagsterRun(
  page: Page,
  graphqlUrl: string,
  selector: { location: string; repoName: string; jobName: string },
): Promise<DagsterLaunchOutcome> {
  const query = `mutation KtmE2eLaunch($executionParams: ExecutionParams!) {
    launchPipelineExecution(executionParams: $executionParams) {
      __typename
      ... on LaunchRunSuccess { run { runId status } }
      ... on PipelineNotFoundError { message }
      ... on InvalidSubsetError { message }
      ... on RunConfigValidationInvalid { errors { message } }
      ... on PythonError { message }
    }
  }`;
  const variables = {
    executionParams: {
      selector: {
        repositoryLocationName: selector.location,
        repositoryName: selector.repoName,
        pipelineName: selector.jobName,
      },
      mode: "default",
    },
  };
  const response = await page.request.post(graphqlUrl, {
    data: { query, variables },
    headers: { "Content-Type": "application/json" },
  });
  expect(
    response.ok(),
    `Dagster GraphQL launch HTTP ${response.status()} @ ${graphqlUrl}`,
  ).toBe(true);
  const json = (await response.json()) as DagsterLaunchGraphqlResponse;
  expect(
    json.errors ?? null,
    `Dagster GraphQL launch errors: ${JSON.stringify(json.errors)}`,
  ).toBeNull();
  const result = json.data?.launchPipelineExecution ?? null;
  return {
    typename: result?.__typename ?? "",
    runId: result?.run?.runId ?? "",
    status: result?.run?.status ?? "",
    message:
      result?.message ??
      (result?.errors ?? []).map((entry) => entry.message ?? "").join("; "),
  };
}

async function terminateDagsterRun(
  page: Page,
  graphqlUrl: string,
  runId: string,
): Promise<void> {
  // Best-effort cleanup (cannot undo already-applied work). Swallow everything.
  const query = `mutation KtmE2eTerminate($runId: String!) {
    terminateRun(runId: $runId) {
      __typename
      ... on TerminateRunSuccess { run { runId status } }
      ... on TerminateRunFailure { message }
      ... on RunNotFoundError { message }
      ... on PythonError { message }
    }
  }`;
  try {
    await page.request.post(graphqlUrl, {
      data: { query, variables: { runId } },
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    // ignore — terminate is courtesy cleanup only.
  }
}

test.describe("/admin/dagster live ops 읽기 + 실행 round-trip", () => {
  test("summary/runs/assets 읽기와 새로고침, run 상세 선택이 실제 서비스에 반영된다", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);

    // nux-seen은 status==='ok'일 때 effect로 자동 1회 POST된다(라우트보다 먼저 등록해 race 회피).
    const nuxSeenPromise = page
      .waitForResponse(
        (response) => isApiResponse(response, "POST", NUX_SEEN_PATH),
        { timeout: FLOW_TIMEOUT },
      )
      .catch(() => null);
    const summaryPromise = waitForApiResponse(page, "GET", SUMMARY_PATH);
    // 첫 run 상세 자동 fetch(fallbackRun 자동선택)도 goto 전에 잡아 둔다.
    const autoRunDetailPromise = page
      .waitForResponse(isRunDetailResponse, { timeout: FLOW_TIMEOUT })
      .catch(() => null);

    await test.step("/admin/dagster 진입 — 운영 표면과 summary GET 계약을 확인한다", async () => {
      await page.goto("/admin/dagster");
      await expectDagsterShell(page);

      const summaryResponse = await summaryPromise;
      expect(summaryResponse.status()).toBe(200);
      const summary =
        (await summaryResponse.json()) as DagsterSummaryResponse;
      expect(summary.data.status).toMatch(/^(ok|unavailable|error)$/);
      expect(typeof summary.data.repository_count).toBe("number");
      expect(Array.isArray(summary.data.recent_runs)).toBe(true);
      expect(summary.data.graphql_url).toContain("graphql");
      expect(summary.data.dagster_url.length).toBeGreaterThan(0);
      expect(summary.meta.request_id.length).toBeGreaterThan(0);
    });

    await test.step("summary 수치/리포지토리(assets)가 SummaryCard·코드 위치에 반영된다", async () => {
      const fetched = await browserFetch<DagsterSummaryResponse>(
        page,
        SUMMARY_PATH,
      );
      expect(fetched.status).toBe(200);
      expect(fetched.body).not.toBeNull();
      const data = (fetched.body as DagsterSummaryResponse).data;

      // 상단 상태 배지 = statusLabel(data.status) 한글 텍스트 (Badge 텍스트, exact).
      await expect(
        page
          .getByText(SUMMARY_STATUS_LABEL[data.status] ?? data.status, {
            exact: true,
          })
          .first(),
      ).toBeVisible(T);

      // SummaryCard value(text-2xl div) = repository_count / asset_count. 카드로 scope해
      // 설명 문구의 동일 숫자와의 strict-mode 충돌을 피한다.
      await expect(
        card(page, "코드 위치")
          .getByText(String(data.repository_count), { exact: true })
          .first(),
      ).toBeVisible(T);
      await expect(
        card(page, "에셋")
          .getByText(String(data.asset_count), { exact: true })
          .first(),
      ).toBeVisible(T);

      // assets list 읽기: repository가 있으면 location_name과 첫 asset group이 코드 위치에 보인다.
      const codeLocations = card(page, "코드 위치").filter({
        hasText: "에셋 그룹과 코드 레벨 이름",
      });
      if (data.repositories.length > 0) {
        const repo = data.repositories[0];
        await expect(codeLocations.getByText(repo.location_name).first()).toBeVisible(T);
        if (repo.asset_groups.length > 0) {
          await expect(
            codeLocations.getByText(repo.asset_groups[0].group_name).first(),
          ).toBeVisible(T);
        }
      } else {
        await expect(
          codeLocations.getByText("등록된 코드 위치가 없습니다."),
        ).toBeVisible(T);
      }
    });

    await test.step("새로고침 버튼이 summary GET을 재발행하고 UI가 유지된다", async () => {
      const refreshResponse = waitForApiResponse(page, "GET", SUMMARY_PATH);
      await page.getByRole("button", { name: "새로고침" }).click();
      expect((await refreshResponse).status()).toBe(200);
      await expect(page.getByRole("heading", { name: "최근 실행" })).toBeVisible(T);
    });

    await test.step("recent runs 유무에 따라 run 상세 round-trip 또는 empty-state를 확인한다", async () => {
      const fetched = await browserFetch<DagsterSummaryResponse>(
        page,
        SUMMARY_PATH,
      );
      const data = (fetched.body as DagsterSummaryResponse).data;
      const runs = data.recent_runs;
      const recentRunsCard = card(page, "최근 실행");
      const runDetailCard = card(page, "실행 상세");

      if (data.status !== "ok" || runs.length === 0) {
        // Dagster down 또는 run 없음 — empty-state/placeholder만 단언(no flake).
        await expect(
          recentRunsCard.getByText("최근 실행이 없습니다."),
        ).toBeVisible(T);
        await expect(
          runDetailCard.getByText(
            "최근 실행을 선택하면 이벤트와 실패 원인이 표시됩니다.",
          ),
        ).toBeVisible(T);
        return;
      }

      // status==='ok' → nux-seen 자동 POST가 정확히 발사됐다(부수 mutation round-trip).
      const nux = await nuxSeenPromise;
      expect(nux, "status=ok인데 nux-seen POST가 관측되지 않음").not.toBeNull();
      expect((nux as Response).status()).toBe(200);
      const nuxBody =
        (await (nux as Response).json()) as DagsterNuxSeenResponse;
      expect(nuxBody.data.seen).toBe(true);

      // fallbackRun(첫 FAILURE 또는 recent_runs[0])이 자동선택돼 run 상세 GET이 한 번 발사된다.
      const fallback = fallbackRun(runs);
      expect(fallback).toBeDefined();
      const fallbackId = (fallback as DagsterRunSummary).run_id;

      const autoDetail = await autoRunDetailPromise;
      expect(autoDetail, "fallback run 자동 상세 GET 미관측").not.toBeNull();
      expect((autoDetail as Response).status()).toBe(200);
      const autoDetailBody =
        (await (autoDetail as Response).json()) as DagsterRunDetailResponse;
      // 자동 선택 run의 상세 본문이 같은 run을 가리킨다(ok일 때) — backend 반영 확인.
      if (autoDetailBody.data.status === "ok" && autoDetailBody.data.run) {
        expect(autoDetailBody.data.run.run_id).toBe(fallbackId);
        await expect(runDetailCard.getByText(fallbackId).first()).toBeVisible(T);
      } else {
        // not_found/unavailable여도 실행 상세 카드는 상태 배지/안내를 렌더한다.
        await expect(
          runDetailCard.getByRole("heading", { name: "실행 상세" }),
        ).toBeVisible(T);
      }

      // run이 2개 이상이면 사용자 클릭으로 다른 run을 선택해 새 상세 GET을 유발(navigation round-trip).
      const target = runs.find((run) => run.run_id !== fallbackId);
      if (target) {
        const targetButton = recentRunsCard.getByRole("button", {
          name: shortRunId(target.run_id),
          exact: true,
        });
        await expect(targetButton).toBeVisible(T);
        const targetDetail = waitForApiResponse(
          page,
          "GET",
          runDetailPath(target.run_id),
        );
        await targetButton.click();
        const targetDetailResponse = await targetDetail;
        expect(targetDetailResponse.status()).toBe(200);
        const targetBody =
          (await targetDetailResponse.json()) as DagsterRunDetailResponse;
        if (targetBody.data.status === "ok" && targetBody.data.run) {
          expect(targetBody.data.run.run_id).toBe(target.run_id);
          await expect(runDetailCard.getByText(target.run_id).first()).toBeVisible(T);
        }
      }
    });
  });

  test("스케줄의 제공자 상태 버튼은 해당 제공자를 선택한 상태로 이동한다", async ({
    page,
  }) => {
    await page.goto("/admin/dagster");
    await expectDagsterShell(page);

    const providerLink = page.getByRole("link", { name: "제공자 상태" }).first();
    await expect(providerLink).toBeVisible(T);
    const href = await providerLink.getAttribute("href");
    expect(href).toMatch(/\/ops\/providers\?provider=/);

    const expectedProvider = new URL(href ?? "", page.url()).searchParams.get(
      "provider",
    );
    expect(expectedProvider).toBeTruthy();

    await providerLink.click();
    await expect(page).toHaveURL(/\/ops\/providers\?provider=/, T);
    await expect(
      page.getByRole("heading", { level: 1, name: "제공자" }),
    ).toBeVisible(T);
    await expect(page.getByText(expectedProvider ?? "").first()).toBeVisible(T);
  });

  test("스케줄 수정/기본값/시작/중지/즉시 실행 명령이 live UI에서 동작한다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_DAGSTER_WRITE,
      "E2E_DAGSTER_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 스케줄 write e2e 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    let target: DagsterSchedule | null = null;
    let originalRunning = false;

    try {
      await page.goto("/admin/dagster");
      await expectDagsterShell(page);

      const summaryFetch = await browserFetch<DagsterSummaryResponse>(
        page,
        SUMMARY_PATH,
      );
      expect(summaryFetch.status).toBe(200);
      const summary = summaryFetch.body as DagsterSummaryResponse;
      test.skip(
        summary.data.status !== "ok",
        `Dagster summary status=${summary.data.status} → 스케줄 명령 불가(skip)`,
      );
      const schedules = allSchedules(summary);
      target =
        schedules.find((schedule) => schedule.name === DAGSTER_SCHEDULE_NAME) ??
        schedules.find((schedule) =>
          schedule.name.includes("curated_features_refresh_daily_schedule"),
        ) ??
        schedules[0] ??
        null;
      test.skip(!target, "summary에 조작 가능한 스케줄이 없음(skip)");
      if (!target) return;

      originalRunning = target.status === "RUNNING";
      await expect(scheduleRow(page, target.name)).toBeVisible(T);

      await test.step("사람이 읽는 반복 주기와 실행 시각으로 수정한다", async () => {
        const patchResponse = waitForApiResponse(
          page,
          "PATCH",
          schedulePath(target!.name),
        );
        await clickScheduleButton(page, target!.name, "스케줄 수정");
        const dialog = page.getByRole("dialog", { name: "스케줄 수정" });
        await expect(dialog).toBeVisible(T);
        await dialog.getByLabel(`${target!.name} frequency`).selectOption("daily");
        await dialog.getByLabel(`${target!.name} time`).fill("04:11");
        await dialog
          .getByLabel(`${target!.name} reason`)
          .fill("live e2e 스케줄 변경");
        await dialog.getByRole("button", { name: "저장" }).click();

        const response = await patchResponse;
        expect(response.status()).toBe(200);
        const body =
          (await response.json()) as DagsterScheduleCommandResponse;
        expect(body.data.command).toBe("update");
        expect(body.data.status).toBe("ok");
        await expect(page.getByText("스케줄 명령 결과")).toBeVisible(T);
        await expect(page.getByText("매일 04:11에 실행")).toBeVisible(T);
      });

      await test.step("기본값 버튼으로 스케줄 override를 되돌린다", async () => {
        const defaultResponse = waitForApiResponse(
          page,
          "POST",
          schedulePath(target!.name, "default"),
        );
        await clickScheduleButton(page, target!.name, "기본값으로 되돌리기");
        const response = await defaultResponse;
        expect(response.status()).toBe(200);
        const body =
          (await response.json()) as DagsterScheduleCommandResponse;
        expect(body.data.command).toBe("default");
        expect(body.data.status).toBe("ok");
        await expect(page.getByText("기본값으로 되돌리기 ·")).toBeVisible(T);
      });

      await test.step("시작/중지 버튼을 눌러 상태 명령을 확인하고 원래 상태로 복귀한다", async () => {
        const firstCommand = originalRunning ? "stop" : "start";
        const firstButton = originalRunning ? "스케줄 중지" : "스케줄 시작";
        const firstResponse = waitForApiResponse(
          page,
          "POST",
          schedulePath(target!.name, firstCommand),
        );
        await clickScheduleButton(page, target!.name, firstButton);
        expect((await firstResponse).status()).toBe(200);
        await expect(
          page.getByText(`${originalRunning ? "스케줄 중지" : "스케줄 시작"} ·`),
        ).toBeVisible(T);

        const refreshAfterFirst = waitForApiResponse(page, "GET", SUMMARY_PATH);
        await page.getByRole("button", { name: "새로고침" }).click();
        await refreshAfterFirst;

        const restoreCommand = originalRunning ? "start" : "stop";
        const restoreButton = originalRunning ? "스케줄 시작" : "스케줄 중지";
        const restoreResponse = waitForApiResponse(
          page,
          "POST",
          schedulePath(target!.name, restoreCommand),
        );
        await clickScheduleButton(page, target!.name, restoreButton);
        expect((await restoreResponse).status()).toBe(200);
        await expect(
          page.getByText(`${originalRunning ? "스케줄 시작" : "스케줄 중지"} ·`),
        ).toBeVisible(T);
      });

      await test.step("즉시 실행 버튼이 run 명령을 만들고 run id를 노출한다", async () => {
        const runResponse = waitForApiResponse(
          page,
          "POST",
          schedulePath(target!.name, "run"),
        );
        await clickScheduleButton(page, target!.name, "즉시 실행");
        const response = await runResponse;
        expect(response.status()).toBe(200);
        const body =
          (await response.json()) as DagsterScheduleCommandResponse;
        expect(body.data.command).toBe("run");
        expect(body.data.status).toBe("ok");
        expect(body.data.run_id?.length ?? 0).toBeGreaterThan(0);
        await expect(page.getByText("즉시 실행 ·")).toBeVisible(T);
      });
    } finally {
      if (target) {
        await browserFetch<DagsterScheduleCommandResponse>(
          page,
          schedulePath(target.name, "default"),
          { method: "POST", body: { reason: "live e2e cleanup" } },
        ).catch(() => null);
        await browserFetch<DagsterScheduleCommandResponse>(
          page,
          schedulePath(target.name, originalRunning ? "start" : "stop"),
          { method: "POST", body: { reason: "live e2e cleanup" } },
        ).catch(() => null);
      }
    }
  });

  test("안전한 job을 실제로 트리거하면 새 run이 summary(API)와 Recent runs(UI)에 나타난다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_DAGSTER_RUN,
      "E2E_DAGSTER_RUN=1 + (E2E_ADMIN_WRITE=1|E2E_DAGSTER_WRITE=1)일 때만 실제 heavy run을 트리거",
    );
    const jobName = process.env.E2E_DAGSTER_JOB ?? "";
    test.skip(
      jobName === "",
      "E2E_DAGSTER_JOB(안전한 config-free job/asset-job 이름)이 없으면 트리거 대상 미정 → skip",
    );
    test.setTimeout(FLOW_TIMEOUT);

    let launchedRunId: string | null = null;

    try {
      const summaryPromise = waitForApiResponse(page, "GET", SUMMARY_PATH);
      await page.goto("/admin/dagster");
      await expectDagsterShell(page);

      const summary =
        (await (await summaryPromise).json()) as DagsterSummaryResponse;
      test.skip(
        summary.data.status !== "ok",
        `Dagster summary status=${summary.data.status} → 안전 트리거 불가(skip)`,
      );

      const repo = summary.data.repositories.find((repository) =>
        repository.jobs.some((job) => job.name === jobName),
      );
      if (!repo) {
        test.skip(true, `summary에서 job '${jobName}' 보유 repository 미발견 → skip`);
        return;
      }
      const location = process.env.E2E_DAGSTER_LOCATION ?? repo.location_name;
      const repoName = process.env.E2E_DAGSTER_REPO ?? repo.name;

      await test.step("Dagster GraphQL로 안전한 job을 launch한다 (관리 경계 ADR-045)", async () => {
        const launch = await launchDagsterRun(page, DAGSTER_GRAPHQL_URL, {
          location,
          repoName,
          jobName,
        });
        expect(
          launch.typename,
          `launch 결과=${launch.typename} msg=${launch.message}`,
        ).toBe("LaunchRunSuccess");
        expect(launch.runId.length).toBeGreaterThan(0);
        expect(
          LAUNCHED_STATUSES.has(launch.status),
          `예상 밖 launch status=${launch.status}`,
        ).toBe(true);
        launchedRunId = launch.runId;
      });

      await test.step("새 run이 admin summary(API)에 큐/시작 상태로 나타난다", async () => {
        const runId = launchedRunId as string;
        await expect
          .poll(
            async () => {
              const res = await browserFetch<DagsterSummaryResponse>(
                page,
                SUMMARY_PATH,
              );
              const found = res.body?.data.recent_runs.find(
                (run) => run.run_id === runId,
              );
              return found?.status ?? null;
            },
            { intervals: [1000, 2000, 3000, 5000], timeout: FLOW_TIMEOUT },
          )
          .not.toBeNull();

        const res = await browserFetch<DagsterSummaryResponse>(
          page,
          SUMMARY_PATH,
        );
        const found = res.body?.data.recent_runs.find(
          (run) => run.run_id === runId,
        );
        expect(found).toBeDefined();
        expect(found?.status.length).toBeGreaterThan(0);
      });

      await test.step("Recent runs 목록과 실행 상세 UI가 새 run을 반영한다", async () => {
        const runId = launchedRunId as string;
        const refreshResponse = waitForApiResponse(page, "GET", SUMMARY_PATH);
        await page.getByRole("button", { name: "새로고침" }).click();
        await refreshResponse;

        const recentRunsCard = card(page, "최근 실행");
        const runButton = recentRunsCard.getByRole("button", {
          name: shortRunId(runId),
          exact: true,
        });
        await expect(runButton).toBeVisible(T);

        const detailResponse = waitForApiResponse(
          page,
          "GET",
          runDetailPath(runId),
        );
        await runButton.click();
        expect((await detailResponse).status()).toBe(200);
        await expect(card(page, "실행 상세").getByText(runId)).toBeVisible(T);
      });
    } finally {
      if (launchedRunId) {
        await terminateDagsterRun(page, DAGSTER_GRAPHQL_URL, launchedRunId);
      }
    }
  });
});
